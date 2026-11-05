using System.Windows.Automation;
using System.Windows.Automation.Text;

namespace OpenASRInput;

// Local-only continuation evidence. Never log/persist this text or use it to
// replace the field. Recheck both contents and caret before resuming a batch.
internal sealed record InsertionCheckpoint(string Text, TextPatternRange Range)
{
    internal static InsertionCheckpoint? Read(Target target)
    {
        try
        {
            var element = AutomationElement.FocusedElement;
            if (element == null || string.Join(".", element.GetRuntimeId()) != target.Identity ||
                !element.TryGetCurrentPattern(TextPattern.Pattern, out var value))
                return null;
            var pattern = (TextPattern)value;
            var ranges = pattern.GetSelection();
            string text = pattern.DocumentRange.GetText(65537);
            return ranges.Length == 1 && text.Length <= 65536
                ? new(text, ranges[0].Clone()) : null;
        }
        catch { return null; }
    }

    internal bool Matches(InsertionCheckpoint? other)
    {
        try
        {
            return other != null && Text == other.Text &&
                Range.CompareEndpoints(TextPatternRangeEndpoint.Start, other.Range, TextPatternRangeEndpoint.Start) == 0 &&
                Range.CompareEndpoints(TextPatternRangeEndpoint.End, other.Range, TextPatternRangeEndpoint.End) == 0;
        }
        catch { return false; }
    }
}
