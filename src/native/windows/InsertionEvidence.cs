using System.Globalization;
using System.Text;
using System.Windows.Automation;
using System.Windows.Automation.Text;

namespace OpenASRInput;

// Optional verification capabilities are independent. A broken value provider
// must not hide working text/selection evidence, before OR after an insertion.
// Snapshots stay local and bounded; this class never writes or logs field text.
internal sealed class InsertionEvidence
{
    private const int TextLimit = 65536;
    private ValuePattern? valuePattern;
    private TextPattern? textPattern;
    private string? beforeValue, beforeText;
    private int beforeCount = -1;
    private bool beforeCollapsed = true;
    internal bool Available => beforeValue != null || beforeText != null || beforeCount >= 0;
    internal string LastStatus { get; private set; } = "provider-unavailable";

    internal static string Normalize(string text) => text.Replace("\r\n", "\n").Replace('\r', '\n');

    private static int Count(TextPattern pattern)
    {
        var document = pattern.DocumentRange;
        var range = document.Clone();
        int count = range.MoveEndpointByUnit(TextPatternRangeEndpoint.Start, TextUnit.Character, int.MaxValue);
        return range.CompareEndpoints(TextPatternRangeEndpoint.Start, document, TextPatternRangeEndpoint.End) == 0 ? count : -1;
    }

    internal static InsertionEvidence Read(Target target)
    {
        var evidence = new InsertionEvidence();
        AutomationElement? element;
        try
        {
            element = AutomationElement.FocusedElement;
            if (element == null || string.Join(".", element.GetRuntimeId()) != target.Identity ||
                !target.InsertionFocusCurrent())
                return evidence;
        }
        catch { return evidence; }
        try
        {
            if (element.TryGetCurrentPattern(ValuePattern.Pattern, out var value))
            {
                var pattern = (ValuePattern)value;
                string snapshot = pattern.Current.Value;
                if (snapshot.Length <= TextLimit)
                {
                    evidence.valuePattern = pattern;
                    evidence.beforeValue = snapshot;
                }
            }
        }
        catch (Exception error) { evidence.LastStatus = "value-provider-" + error.GetType().Name; }
        try
        {
            if (element.TryGetCurrentPattern(TextPattern.Pattern, out var value))
                evidence.textPattern = (TextPattern)value;
        }
        catch (Exception error) { evidence.LastStatus = "text-provider-" + error.GetType().Name; }
        if (evidence.textPattern != null)
        {
            try
            {
                string snapshot = evidence.textPattern.DocumentRange.GetText(TextLimit + 1);
                if (snapshot.Length <= TextLimit)
                    evidence.beforeText = snapshot;
            }
            catch (Exception error) { evidence.LastStatus = "text-snapshot-" + error.GetType().Name; }
            try
            {
                var selection = evidence.textPattern.GetSelection();
                if (selection.Length == 1)
                {
                    evidence.beforeCollapsed = selection[0].CompareEndpoints(TextPatternRangeEndpoint.Start,
                        selection[0], TextPatternRangeEndpoint.End) == 0;
                    evidence.beforeCount = Count(evidence.textPattern);
                }
            }
            catch (Exception error) { evidence.LastStatus = "text-count-" + error.GetType().Name; }
        }
        // Any of the preceding provider calls can pump a focus-change callback.
        if (!target.InsertionFocusCurrent())
            return new InsertionEvidence { LastStatus = "focus-changed-during-snapshot" };
        return evidence;
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

    internal string? Confirm(string text)
    {
        string normalized = Normalize(text);
        if (valuePattern != null && beforeValue != null)
        {
            try
            {
                string after = valuePattern.Current.Value;
                if (after.Length <= TextLimit && ChangedBy(beforeValue, after, normalized))
                    return "value-change-confirmed";
            }
            catch (Exception error) { LastStatus = "value-confirmation-" + error.GetType().Name; }
        }
        if (textPattern != null && beforeText != null)
        {
            try
            {
                string after = textPattern.DocumentRange.GetText(TextLimit + 1);
                if (after.Length <= TextLimit && ChangedBy(beforeText, after, normalized))
                    return "text-change-confirmed";
            }
            catch (Exception error) { LastStatus = "text-confirmation-" + error.GetType().Name; }
        }
        // A missing baseline count is not evidence that the count increased.
        if (textPattern != null && beforeCount >= 0)
        {
            try
            {
                var selection = textPattern.GetSelection();
                if (selection.Length == 1 && selection[0].CompareEndpoints(TextPatternRangeEndpoint.Start,
                    selection[0], TextPatternRangeEndpoint.End) == 0 && (!beforeCollapsed || Count(textPattern) > beforeCount))
                {
                    int[] units = { StringInfo.ParseCombiningCharacters(normalized).Length,
                        normalized.EnumerateRunes().Count(), normalized.Length };
                    foreach (int count in units.Distinct())
                    {
                        var inserted = selection[0].Clone();
                        inserted.MoveEndpointByUnit(TextPatternRangeEndpoint.Start, TextUnit.Character, -count);
                        if (Normalize(inserted.GetText(normalized.Length * 2 + 2)) == normalized)
                            return "caret-text-confirmed";
                    }
                }
            }
            catch (Exception error) { LastStatus = "caret-confirmation-" + error.GetType().Name; }
        }
        return null;
    }
}
