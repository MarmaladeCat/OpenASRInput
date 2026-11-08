using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;

namespace OpenASRInput;

internal static class TextInsertion
{
    internal static string LastMethod = "";
    internal static string LastVerification = "";
    private const uint GetSelection = 0x00b0, ReplaceSelection = 0x00c2;
    private const uint MessageFlags = 0x23, Timeout = 300;
    [DllImport("user32.dll", EntryPoint = "SendMessageTimeoutW", SetLastError = true)]
    private static extern nint Character(nint window, uint message, nuint character, nint data,
        uint flags, uint timeout, out nuint result);

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
        string type = Native.WindowClass(target.Focus);
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
            LastMethod = "office-selection";
            string office = OfficeInsertion.Replace(target, text, current);
            if (office != "unsupported")
            {
                LastVerification = office == "accepted" ? "office-range-confirmed" : "not-confirmed";
                return office;
            }
            return "failed";
        }
        string type = Native.WindowClass(target.Focus);
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

    internal static string Normalize(string text) => InsertionEvidence.Normalize(text);

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

    private static string CommitCharacters(Target target, string text, Func<bool> current)
    {
        LastMethod = "native-char";
        LastVerification = "not-confirmed";
        if (!current())
            return "stale";
        if (!IsWindowUnicode(target.Focus))
            return "failed";
        var evidence = InsertionEvidence.Read(target);
        if (!current())
            return "stale";
        if (!evidence.Available)
        {
            LastVerification = evidence.LastStatus;
            return "failed"; // No write without a usable confirmation baseline.
        }

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
        while (budget.ElapsedMilliseconds < 2400)
        {
            if (!current())
            {
                LastVerification = "focus-lost-during-confirmation";
                return "unknown";
            }
            string? verification = evidence.Confirm(normalized);
            if (!current())
            {
                LastVerification = "focus-lost-during-confirmation";
                return "unknown";
            }
            if (verification != null)
            {
                LastVerification = verification;
                return "accepted";
            }
            Thread.Sleep(10); // Chromium renderer confirmation is asynchronous.
        }
        LastVerification = "confirmation-timeout";
        return "unknown";
    }
}
