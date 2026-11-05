using System.Diagnostics;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Automation;
using System.Windows.Automation.Text;

namespace OpenASRInput;

internal static class TextInsertion
{
    internal static string LastMethod = "";
    internal static string LastVerification = "";
    private const uint GetSelection = 0x00b0, ReplaceSelection = 0x00c2;
    private const uint MessageFlags = 0x23, Timeout = 300;
    private const int VerificationTextLimit = 65536;
    [DllImport("user32.dll", EntryPoint = "SendMessageTimeoutW", SetLastError = true)]
    private static extern nint Character(nint window, uint message, nuint character, nint data,
        uint flags, uint timeout, out nuint result);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetClassNameW(nint window, StringBuilder name, int capacity);
    [DllImport("user32.dll")]
    private static extern bool IsWindowUnicode(nint window);
    [DllImport("user32.dll", EntryPoint = "SendMessageTimeoutW", SetLastError = true)]
    private static extern nint ReadSelection(nint window, uint message, out uint start, out uint end,
        uint flags, uint timeout, out nuint result);
    [DllImport("user32.dll", EntryPoint = "SendMessageTimeoutW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern nint Replace(nint window, uint message, nuint undo, string text,
        uint flags, uint timeout, out nuint result);

    internal static void Validate(string text)
    {
        if (text.Length > 32768 || text.Any(character => char.IsControl(character) && character is not '\r' and not '\n' and not '\t'))
            throw new ArgumentException("Invalid final text");
    }

    internal static bool NativeEdit(Target target)
    {
        var name = new StringBuilder(256);
        GetClassNameW(target.Focus, name, name.Capacity);
        string type = name.ToString();
        return IsWindowUnicode(target.Focus) && (type.Equals("Edit", StringComparison.OrdinalIgnoreCase) ||
            type.StartsWith("WindowsForms10.EDIT.", StringComparison.OrdinalIgnoreCase) ||
            type.StartsWith("RichEdit", StringComparison.OrdinalIgnoreCase) ||
            type.StartsWith("WindowsForms10.RichEdit", StringComparison.OrdinalIgnoreCase));
    }

    internal static string Commit(Target target, string text, Func<bool> current)
    {
        LastVerification = "not-confirmed";
        Validate(text);
        if (text.Length == 0)
        {
            LastMethod = "none";
            LastVerification = "empty-no-op";
            return current() ? "accepted" : "stale";
        }
        if (OfficeInsertion.Supports(target))
        {
            string office = OfficeInsertion.Replace(target, text, current);
            if (office != "unsupported")
            {
                LastMethod = "office-selection";
                LastVerification = office == "accepted" ? "office-range-confirmed" : "not-confirmed";
                return office;
            }
            return "failed";
        }
        var name = new StringBuilder(256);
        GetClassNameW(target.Focus, name, name.Capacity);
        string type = name.ToString();
        bool rich = type.StartsWith("RichEdit", StringComparison.OrdinalIgnoreCase) ||
            type.StartsWith("WindowsForms10.RichEdit", StringComparison.OrdinalIgnoreCase);
        bool edit = type.Equals("Edit", StringComparison.OrdinalIgnoreCase) ||
            type.StartsWith("WindowsForms10.EDIT.", StringComparison.OrdinalIgnoreCase) ||
            rich;
        if (!edit || !IsWindowUnicode(target.Focus))
        {
            return CommitCharacters(target, text, current);
        }

        LastMethod = "native-edit";
        // Standard Edit controls expose a cursor/selection insertion API. It
        // preserves undo and avoids VK_PACKET being consumed by an IME or hook.
        // No whole-field replacement, clipboard operation or input-method change.
        if (ReadSelection(target.Focus, GetSelection, out uint start, out _,
            MessageFlags, Timeout, out _) == 0)
            return "unknown";
        if (!current())
            return "stale";
        string normalized = rich ? Normalize(text) : Normalize(text).Replace("\n", "\r\n");
        if (Replace(target.Focus, ReplaceSelection, 1, normalized, MessageFlags, Timeout, out _) == 0)
            return "unknown"; // A timeout can mean the insertion already happened.
        if (!current() || ReadSelection(target.Focus, GetSelection, out uint afterStart, out uint afterEnd,
            MessageFlags, Timeout, out _) == 0)
            return "unknown";
        // Verify cursor advancement without reading or retaining document text.
        bool accepted = afterStart == afterEnd && afterEnd == start + normalized.Length;
        if (accepted)
            LastVerification = "caret-position-confirmed";
        return accepted ? "accepted" : "unknown";
    }

    internal static string Normalize(string text) => text.Replace("\r\n", "\n").Replace('\r', '\n');

    internal static string DeleteSelected(Target target, Func<bool> current)
    {
        if (!current())
            return "stale";
        if (OfficeInsertion.Supports(target))
            return OfficeInsertion.Replace(target, "", current);
        if (NativeEdit(target))
            return Replace(target.Focus, ReplaceSelection, 1, "", MessageFlags, Timeout, out _) != 0 && current()
                ? "accepted" : "unknown";
        // Chromium handles selection deletion as a key command, not WM_CHAR.
        // Deliver to the already verified HWND, never to global keyboard focus.
        bool down = Character(target.Focus, 0x0100, 8, 0x000e0001, MessageFlags, Timeout, out _) != 0;
        bool up = Character(target.Focus, 0x0101, 8, unchecked((int)0xc00e0001), MessageFlags, Timeout, out _) != 0;
        return down && up && current() ? "accepted" : "unknown";
    }

    private static int Count(TextPattern pattern)
    {
        var document = pattern.DocumentRange;
        var range = document.Clone();
        int count = range.MoveEndpointByUnit(TextPatternRangeEndpoint.Start, TextUnit.Character, int.MaxValue);
        return range.CompareEndpoints(TextPatternRangeEndpoint.Start, document, TextPatternRangeEndpoint.End) == 0 ? count : -1;
    }

    private static bool ChangedBy(string before, string after, string text)
    {
        before = Normalize(before);
        after = Normalize(after);
        if (before == after || after.Length - before.Length > text.Length)
            return false;
        int prefix = 0, suffix = 0;
        while (prefix < Math.Min(before.Length, after.Length) && before[prefix] == after[prefix])
            prefix++;
        while (suffix < Math.Min(before.Length, after.Length) && before[^(suffix + 1)] == after[^(suffix + 1)])
            suffix++;
        int start = Math.Max(0, after.Length - text.Length - suffix);
        int end = Math.Min(prefix, after.Length - text.Length);
        if (start > end)
            return false;
        int match = after.IndexOf(text, start, StringComparison.Ordinal);
        return match >= start && match <= end;
    }

    private static string CommitCharacters(Target target, string text, Func<bool> current)
    {
        LastMethod = "native-char";
        LastVerification = "not-confirmed";
        if (!current())
            return "stale";
        if (!IsWindowUnicode(target.Focus))
            return "failed";
        TextPattern? pattern = null;
        ValuePattern? valuePattern = null;
        string? beforeValue = null;
        string? beforeText = null;
        int beforeCount = -1;
        bool beforeCollapsed = true;
        try
        {
            var element = AutomationElement.FocusedElement;
            if (element != null && string.Join(".", element.GetRuntimeId()) == target.Identity &&
                element.TryGetCurrentPattern(ValuePattern.Pattern, out var editableValue))
            {
                valuePattern = (ValuePattern)editableValue;
                // This local snapshot belongs only to the validated editable
                // field. It is never logged, persisted or sent to the Portal,
                // and never used to replace the whole field.
                beforeValue = valuePattern.Current.Value;
            }
            if (element != null && string.Join(".", element.GetRuntimeId()) == target.Identity &&
                element.TryGetCurrentPattern(TextPattern.Pattern, out var value))
            {
                pattern = (TextPattern)value;
                var selection = pattern.GetSelection();
                if (selection.Length == 1)
                {
                    beforeCollapsed = selection[0].CompareEndpoints(TextPatternRangeEndpoint.Start,
                        selection[0], TextPatternRangeEndpoint.End) == 0;
                    beforeCount = Count(pattern);
                    // Replacement need not increase provider character counts.
                    // Keep bounded local evidence even when counting is supported;
                    // Chromium contenteditable can publish caret/count separately.
                    string snapshot = pattern.DocumentRange.GetText(VerificationTextLimit + 1);
                    if (snapshot.Length <= VerificationTextLimit)
                        beforeText = snapshot;
                }
            }
        }
        catch (Exception error) { LastVerification = "provider-" + error.GetType().Name; }

        string normalized = Normalize(text);
        var budget = Stopwatch.StartNew();
        int consumed = 0;
        Span<char> scalar = stackalloc char[2];
        foreach (var rune in normalized.EnumerateRunes())
        {
            // Host checks modifiers before each bounded batch. A stop chord
            // arriving midway must not truncate that batch; WM_CHAR does not
            // depend on the modifier state. Real cancellation/focus/IME loss
            // still stops immediately and remains non-replayable.
            if (budget.ElapsedMilliseconds >= 1800 || !current() || Native.Composing(target.Focus))
            {
                LastVerification = "interrupted-before-character";
                return consumed == 0 ? "stale" : "unknown";
            }
            int count = rune.EncodeToUtf16(scalar);
            for (int index = 0; index < count; index++)
                if (Character(target.Focus, 0x0102, scalar[index], 1, MessageFlags, Timeout, out _) == 0)
                {
                    LastVerification = "character-send-timeout";
                    return "unknown";
                }
            consumed += count; // Never pause between a surrogate pair's units.
        }
        // WM_CHAR delivers text to the validated native focus, without relying
        // on VK_PACKET translation by IMEs/hooks. A delivered message alone is
        // not proof of insertion: confirm the caret suffix and metadata change.
        if ((pattern == null || beforeCount < 0) && valuePattern == null && beforeText == null)
        {
            LastVerification = "provider-unavailable";
            return "unknown";
        }
        int[] units = { StringInfo.ParseCombiningCharacters(normalized).Length,
            normalized.EnumerateRunes().Count(), normalized.Length };
        while (budget.ElapsedMilliseconds < 2400)
        {
            if (!current())
            {
                LastVerification = "focus-lost-during-confirmation";
                return "unknown";
            }
            try
            {
                if (valuePattern != null && beforeValue != null && ChangedBy(beforeValue, valuePattern.Current.Value, normalized))
                {
                    LastVerification = "value-change-confirmed";
                    return "accepted";
                }
                if (pattern != null && beforeText != null)
                {
                    string afterText = pattern.DocumentRange.GetText(VerificationTextLimit + 1);
                    if (afterText.Length <= VerificationTextLimit && ChangedBy(beforeText, afterText, normalized))
                    {
                        LastVerification = "text-change-confirmed";
                        return "accepted";
                    }
                }
                var selection = pattern?.GetSelection() ?? Array.Empty<TextPatternRange>();
                if (selection.Length == 1 && selection[0].CompareEndpoints(TextPatternRangeEndpoint.Start,
                    selection[0], TextPatternRangeEndpoint.End) == 0 && (!beforeCollapsed || Count(pattern!) > beforeCount))
                {
                    foreach (int count in units.Distinct())
                    {
                        var inserted = selection[0].Clone();
                        inserted.MoveEndpointByUnit(TextPatternRangeEndpoint.Start, TextUnit.Character, -count);
                        if (Normalize(inserted.GetText(normalized.Length * 2 + 2)) == normalized)
                        {
                            LastVerification = "caret-text-confirmed";
                            return "accepted";
                        }
                    }
                }
            }
            catch (Exception error) { LastVerification = "confirmation-" + error.GetType().Name; return "unknown"; }
            Thread.Sleep(10); // Chromium renderer confirmation is asynchronous.
        }
        LastVerification = "confirmation-timeout";
        return "unknown";
    }
}
