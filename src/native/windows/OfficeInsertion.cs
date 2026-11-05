using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Windows.Automation;
using System.Windows.Automation.Text;

namespace OpenASRInput;

// Office exposes an actual selection insertion API. Bind to an EXISTING instance
// and its active text selection; never create Office, open a file or replace a slide.
internal static class OfficeInsertion
{
    internal static string LastStatus = "";
    [DllImport("oleacc.dll")]
    private static extern int AccessibleObjectFromWindow(nint hwnd, uint objectId, ref Guid iid,
        [MarshalAs(UnmanagedType.IDispatch)] out object value);
    internal static bool Supports(Target target)
    {
        try
        {
            return Process.GetProcessById((int)target.Process).ProcessName.Equals("POWERPNT", StringComparison.OrdinalIgnoreCase);
        }
        catch { return false; }
    }

    internal static string Replace(Target target, string text, Func<bool> current)
    {
        bool writing = false;
        string stage = "native-object";
        try
        {
            Guid dispatch = new("00020400-0000-0000-C000-000000000046");
            if (AccessibleObjectFromWindow(target.Focus, 0xfffffff0, ref dispatch, out object native) != 0)
                return "unsupported";
            dynamic app = ((dynamic)native).Application;
            stage = "selection";
            dynamic window = app.ActiveWindow;
            stage = "selection-type";
            // Native object came from the validated focused HWND, so no global
            // ROT lookup can accidentally bind another PowerPoint instance.
            if ((int)window.Selection.Type != 3 || !current())
                return "stale";
            dynamic range = window.Selection.TextRange;
            var pattern = (TextPattern)AutomationElement.FocusedElement.GetCurrentPattern(TextPattern.Pattern);
            var selections = pattern.GetSelection();
            if (selections.Length != 1)
                return "unsupported";
            var before = pattern.DocumentRange;
            var prefix = before.Clone();
            prefix.MoveEndpointByRange(TextPatternRangeEndpoint.End, selections[0], TextPatternRangeEndpoint.Start);
            var suffix = before.Clone();
            suffix.MoveEndpointByRange(TextPatternRangeEndpoint.Start, selections[0], TextPatternRangeEndpoint.End);
            string left = prefix.GetText(65537), right = suffix.GetText(65537);
            if (left.Length + right.Length > 65536)
                return "unsupported";
            string expected = TextInsertion.Normalize(left + text + right);
            // TextRange is the selected text/caret, NOT the owning TextFrame.
            string normalized = TextInsertion.Normalize(text).Replace('\n', '\r');
            if (!current())
                return "stale";
            writing = true;
            stage = "write";
            range.Text = normalized;
            // Office may leave the replaced range selected. Collapse it at the
            // inserted end so consecutive results append rather than overwrite.
            var after = pattern.GetSelection();
            if (!current() || after.Length != 1 ||
                TextInsertion.Normalize(pattern.DocumentRange.GetText(98305)) != expected)
                return "unknown";
            var caret = after[0].Clone();
            caret.MoveEndpointByRange(TextPatternRangeEndpoint.Start, caret, TextPatternRangeEndpoint.End);
            caret.Select();
            LastStatus = "confirmed";
            return current() ? "accepted" : "unknown";
        }
        catch (Exception error) { LastStatus = stage + ":" + error.GetType().Name + ":" + error.HResult; return writing ? "unknown" : "unsupported"; }
    }
}
