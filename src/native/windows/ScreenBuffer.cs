using System.Globalization;
using System.Text;
using System.Windows.Automation;
using System.Windows.Automation.Text;

namespace OpenASRInput;

// Reversible application-owned text range. This is NOT a TSF composition: only
// touch the exact range while content, selection and target still match evidence.
internal sealed class ScreenBuffer
{
    internal string Text { get; private set; } = "";
    internal string Desired { get; private set; } = "";
    internal string FinalId { get; private set; } = "";
    internal string FinalText { get; private set; } = "";
    internal string LastFailure { get; private set; } = "";
    internal bool Active => checkpoint != null;
    internal bool Failed
    {
        get; private set;
    }
    private string original = "";
    private InsertionCheckpoint? checkpoint;

    private static int Prefix(string a, string b)
    {
        int count = 0;
        while (count < Math.Min(a.Length, b.Length) && a[count] == b[count])
            count++;
        var left = StringInfo.ParseCombiningCharacters(a).Append(a.Length).ToHashSet();
        var right = StringInfo.ParseCombiningCharacters(b).Append(b.Length).ToHashSet();
        while (count > 0 && (!left.Contains(count) || !right.Contains(count)))
            count--;
        return count;
    }
    internal string PanelText => Desired[Prefix(Text, Desired)..];

    private static TextPatternRange? Suffix(TextPatternRange caret, string text)
    {
        if (text.Length == 0)
            return caret.Clone();
        foreach (int units in new[] { text.Length, text.EnumerateRunes().Count(),
            StringInfo.ParseCombiningCharacters(text).Length }.Distinct())
        {
            var range = caret.Clone();
            range.MoveEndpointByUnit(TextPatternRangeEndpoint.Start, TextUnit.Character, -units);
            string actual = range.GetText(65537);
            if (TextInsertion.Normalize(actual) == text)
                // Chromium can mix a leaf start with a contenteditable-container
                // end when moving a caret range. FindText normalizes both ends
                // to text nodes, so Blink can apply the selection.
                return range.FindText(actual, false, false) ?? range;
        }
        return null;
    }

    internal string Update(Target target, string requested, Func<bool> current, bool restore = false)
    {
        bool selecting = false;
        try
        {
            TextInsertion.Validate(requested);
            Desired = TextInsertion.Normalize(requested);
            if (Failed)
                return "stale";
            if (!current())
                return "stale";
            if (Active && !checkpoint!.Matches(InsertionCheckpoint.Read(target)))
            {
                Failed = true;
                return "stale";
            }
            if (Active && Text == Desired)
                return "accepted";
            if (!Active && Desired.Length == 0)
                return "accepted";
            var element = AutomationElement.FocusedElement;
            if (!element.TryGetCurrentPattern(TextPattern.Pattern, out var value))
                return "unsupported";
            var pattern = (TextPattern)value;
            var selection = pattern.GetSelection();
            if (selection.Length != 1)
                return "unsupported";
            var before = InsertionCheckpoint.Read(target);
            if (before == null)
                return "unsupported";
            if (!Active)
            {
                original = TextInsertion.Normalize(selection[0].GetText(65537));
                if (original.Length > 32768)
                    return "unsupported";
                // Do not temporarily remove content we cannot restore through
                // this insertion API (e.g. Office soft-break control characters).
                try
                {
                    TextInsertion.Validate(original);
                }
                catch (ArgumentException) { return "unsupported"; }
            }
            int common = Active && !restore ? Prefix(Text, Desired) : 0;
            bool fast = TextInsertion.NativeEdit(target) || OfficeInsertion.Supports(target);
            if (!Active && !fast && original.Length > 16)
                return "unsupported";
            string replacement = Desired[common..];
            // Providers without a whole-range native API yield small confirmed
            // increments. Each new SHOW supersedes the pending preview tail.
            if (!fast && !restore && replacement.Length > 16)
            {
                var boundaries = StringInfo.ParseCombiningCharacters(replacement);
                int length = boundaries.Where(n => n > 0 && n <= 16).DefaultIfEmpty(0).Max();
                // A single large grapheme is indivisible (e.g. a long ZWJ run).
                if (length == 0)
                    return "unsupported";
                replacement = replacement[..length];
            }
            string next = Desired[..common] + replacement;
            TextPatternRange replace;
            if (Active)
            {
                // Chromium can invalidate retained ranges after renderer updates.
                // Reconstruct from the freshly verified caret and exact owned suffix.
                var end = before.Range.Clone();
                end.MoveEndpointByRange(TextPatternRangeEndpoint.Start, end, TextPatternRangeEndpoint.End);
                replace = Suffix(end, Text[common..]) ?? throw new InvalidOperationException("owned range unavailable");
            }
            else
                replace = selection[0].Clone();
            var document = pattern.DocumentRange;
            var prefix = document.Clone();
            prefix.MoveEndpointByRange(TextPatternRangeEndpoint.End, replace, TextPatternRangeEndpoint.Start);
            var suffix = document.Clone();
            suffix.MoveEndpointByRange(TextPatternRangeEndpoint.Start, replace, TextPatternRangeEndpoint.End);
            string prefixText = prefix.GetText(65537), suffixText = suffix.GetText(65537);
            string selectedText = TextInsertion.Normalize(replace.GetText(65537));
            string expected = TextInsertion.Normalize(prefixText + replacement + suffixText);
            if (!before.Matches(InsertionCheckpoint.Read(target)) || !current())
            {
                Failed = true;
                return "stale";
            }
            selecting = true;
            replace.Select();
            // Chromium applies UIA selection asynchronously. Confirm the exact
            // range before sending characters; never race selection with input.
            long selectionDeadline = Environment.TickCount64 + 500;
            bool selected = false;
            while (current() && Environment.TickCount64 < selectionDeadline)
            {
                var ranges = pattern.GetSelection();
                if (ranges.Length == 1)
                {
                    // Leaf/container endpoints can compare unequal at the same
                    // Chromium text offset. Verify the selected text and both
                    // surrounding ranges instead of trusting raw endpoint IDs.
                    var selectedPrefix = pattern.DocumentRange.Clone();
                    selectedPrefix.MoveEndpointByRange(TextPatternRangeEndpoint.End, ranges[0], TextPatternRangeEndpoint.Start);
                    var selectedSuffix = pattern.DocumentRange.Clone();
                    selectedSuffix.MoveEndpointByRange(TextPatternRangeEndpoint.Start, ranges[0], TextPatternRangeEndpoint.End);
                    if (TextInsertion.Normalize(ranges[0].GetText(65537)) == selectedText &&
                        TextInsertion.Normalize(selectedPrefix.GetText(65537)) == TextInsertion.Normalize(prefixText) &&
                        TextInsertion.Normalize(selectedSuffix.GetText(65537)) == TextInsertion.Normalize(suffixText))
                    {
                        selected = true;
                        break;
                    }
                }
                Thread.Sleep(10);
            }
            if (!selected)
            {
                LastFailure = "selection-unconfirmed";
                Failed = true;
                return "unknown";
            }
            if (!current())
            {
                Failed = true;
                return "stale";
            }
            string result = replacement.Length == 0
                ? TextInsertion.DeleteSelected(target, current) : TextInsertion.Commit(target, replacement, current);
            var after = InsertionCheckpoint.Read(target);
            if (result == "accepted" && replacement.Length == 0)
            {
                // Renderer-backed deletion is asynchronous. Observe only; never
                // resend a deletion whose effect may already be in flight.
                long deadline = Environment.TickCount64 + 500;
                while (after != null && TextInsertion.Normalize(after.Text) != expected &&
                    Environment.TickCount64 < deadline && current())
                {
                    Thread.Sleep(10);
                    after = InsertionCheckpoint.Read(target);
                }
            }
            if (result != "accepted" || after == null || TextInsertion.Normalize(after.Text) != expected)
            {
                LastFailure = result != "accepted" ? "insertion-" + result :
                    after == null ? "checkpoint-unavailable" : "document-mismatch";
                Failed = true;
                return "unknown";
            }
            var range = Suffix(after.Range, next);
            if (range == null)
            {
                LastFailure = "caret-range-unavailable";
                Failed = true;
                return "unknown";
            }
            Text = next;
            checkpoint = after;
            return Text == Desired ? "accepted" : "deferred";
        }
        catch (Exception error)
        {
            LastFailure = error.GetType().Name;
            // Native Office dictation can work without UIA TextPattern. Before
            // touching any selection/text, a missing optional preview provider
            // means panel-only preview, not a failed recording round.
            if (!selecting && !Active)
                return "unsupported";
            Failed = true;
            return "unknown";
        }
    }

    internal string Finish(Target target, string id, string text, Func<bool> current)
    {
        if (FinalId.Length != 0 && FinalId != id)
            return "deferred";
        if (FinalId.Length != 0 && FinalText != text)
            return "failed";
        FinalId = id;
        FinalText = text;
        string result = text.Length == 0 ? Cancel(target, current) : Update(target, text, current);
        if (result == "accepted")
            Reset(); // Promote owned screen text; no second insertion.
        return result;
    }

    internal string Cancel(Target target, Func<bool> current)
    {
        if (!Active)
        {
            Reset();
            return "accepted";
        }
        string result = Update(target, original, current, restore: true);
        if (result == "accepted")
            Reset();
        return result;
    }

    internal void Reset()
    {
        Text = Desired = FinalId = FinalText = original = "";
        checkpoint = null;
        Failed = false;
        LastFailure = "";
    }
}
