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
    private static nint Pane(Target target)
    {
        try
        {
            using var process = Process.GetProcessById((int)target.Process);
            if (!process.ProcessName.Equals("POWERPNT", StringComparison.OrdinalIgnoreCase) ||
                TextInsertion.NativeEdit(target))
                return 0;
            // OBJID_NATIVEOM belongs to paneClassDC, not every control in the
            // POWERPNT process. Dialog/ribbon edits keep their normal backend.
            // Some versions focus a child HWND: walk only its same-process
            // ancestors inside this foreground window, never sibling panes.
            nint window = target.Focus;
            for (int depth = 0; window != 0 && depth < 32; depth++)
            {
                Native.GetWindowThreadProcessId(window, out uint pid);
                if (pid != target.Process || Native.GetAncestor(window, 2) != target.Window)
                    break;
                if (Native.WindowClass(window).Equals("paneClassDC", StringComparison.OrdinalIgnoreCase))
                    return window;
                if (window == target.Window)
                    break;
                window = Native.GetAncestor(window, 1);
            }
        }
        catch { }
        return 0;
    }

    internal static bool Supports(Target target) => Pane(target) != 0;

    internal static bool Editing(Target target)
    {
        object? native = null, selection = null;
        try
        {
            nint pane = Pane(target);
            Guid dispatch = new("00020400-0000-0000-C000-000000000046");
            if (pane == 0 || !target.InsertionFocusCurrent() ||
                AccessibleObjectFromWindow(pane, 0xfffffff0, ref dispatch, out native) != 0)
                return false;
            selection = ((dynamic)native).Selection;
            return (int)((dynamic)selection).Type == 3 && target.InsertionFocusCurrent();
        }
        catch { return false; }
        finally
        {
            if (selection != null && Marshal.IsComObject(selection))
                Marshal.ReleaseComObject(selection);
            if (native != null && Marshal.IsComObject(native))
                Marshal.ReleaseComObject(native);
        }
    }

    private static string ReplaceNative(object window, string text, Func<bool> current)
    {
        string result = OfficeTextRange.Replace(window, TextInsertion.Normalize(text).Replace('\n', '\r'), current);
        LastStatus = OfficeTextRange.LastStatus;
        return result;
    }

    internal static string Replace(Target target, string text, Func<bool> current)
    {
        bool writing = false;
        string stage = "native-object";
        LastStatus = stage;
        object? native = null;
        try
        {
            if (!current())
                return "stale";
            nint pane = Pane(target);
            Guid dispatch = new("00020400-0000-0000-C000-000000000046");
            if (pane == 0 || AccessibleObjectFromWindow(pane, 0xfffffff0, ref dispatch, out native) != 0)
            {
                LastStatus = "native-object-unavailable";
                return "unsupported";
            }
            stage = "selection";
            // The native object IS the DocumentWindow. Following Application's
            // ActiveWindow can switch to another presentation during a COM call.
            dynamic window = native;
            stage = "selection-type";
            // Native object came from the validated focused HWND, so no global
            // ROT lookup can accidentally bind another PowerPoint instance.
            if ((int)window.Selection.Type != 3 || !current())
            {
                LastStatus = "text-selection-unavailable";
                return "stale";
            }
            dynamic range = window.Selection.TextRange;
            var pattern = (TextPattern)AutomationElement.FocusedElement.GetCurrentPattern(TextPattern.Pattern);
            var selections = pattern.GetSelection();
            if (selections.Length != 1)
                return ReplaceNative(native, text, current);
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
            if (!current())
                return "unknown"; // UIA range queries can dispatch a focus change.
            caret.Select();
            LastStatus = "confirmed";
            return current() ? "accepted" : "unknown";
        }
        catch (Exception error)
        {
            LastStatus = stage + ":" + error.GetType().Name + ":" + error.HResult;
            // Only a pre-write UIA/provider failure may switch backends. Once a
            // setter was attempted its result is ambiguous and must not replay.
            return !writing && native != null ? ReplaceNative(native, text, current) : writing ? "unknown" : "unsupported";
        }
        finally
        {
            if (native != null && Marshal.IsComObject(native))
                Marshal.ReleaseComObject(native);
        }
    }
}
