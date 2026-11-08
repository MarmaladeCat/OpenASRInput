using System.Drawing;
using System.Runtime.InteropServices;
using System.Windows.Automation;
using System.Windows.Automation.Text;

namespace OpenASRInput;

internal sealed record Target(nint Window, nint Focus, uint Process, string Identity, Rectangle Caret,
    Rectangle Editor = default, bool CaretKnown = false)
{
    internal static string LastFailure = "";
    private static Target? Reject(string reason)
    {
        LastFailure = reason;
        return null;
    }

    internal bool FocusAncestor(string identity)
    {
        try
        {
            var element = AutomationElement.FocusedElement;
            if (element == null || string.Join(".", element.GetRuntimeId()) != Identity)
                return false;
            for (int depth = 0; element != null && depth < 64; depth++)
            {
                if (string.Join(".", element.GetRuntimeId()) == identity)
                    return true;
                element = TreeWalker.RawViewWalker.GetParent(element);
            }
        }
        catch { }
        return false;
    }

    internal bool Same(Target? other) => other != null && Window == other.Window && Focus == other.Focus &&
        Process == other.Process && Identity == other.Identity;

    internal bool InsertionFocusCurrent()
    {
        if (!NativeFocusCurrent())
            return false;
        try
        {
            // Keep sibling controls/shapes isolated for EVERY character, without
            // re-reading optional text patterns, selection and layout each time.
            var element = AutomationElement.FocusedElement;
            Native.GetWindowThreadProcessId(Focus, out uint focusProcess);
            return element != null && element.Current.ProcessId == focusProcess &&
                element.Current.IsEnabled && !element.Current.IsPassword && element.Current.HasKeyboardFocus &&
                string.Join(".", element.GetRuntimeId()) == Identity && NativeFocusCurrent();
        }
        catch { return false; }
    }

    // Safe inside WH_KEYBOARD_LL: no UI Automation/COM calls, which can pump
    // nested key messages before SessionKeys has consumed the original down.
    internal bool NativeFocusCurrent()
    {
        if (Native.GetForegroundWindow() != Window)
            return false;
        uint thread = Native.GetWindowThreadProcessId(Window, out uint process);
        var info = new Native.GuiThreadInfo { Size = (uint)Marshal.SizeOf<Native.GuiThreadInfo>() };
        return process == Process && Native.GetGUIThreadInfo(thread, ref info) && info.Focus == Focus;
    }

    private static Rectangle TextCaret(AutomationElement element, Rectangle editor)
    {
        try
        {
            if (!element.TryGetCurrentPattern(TextPattern.Pattern, out var value))
                return Rectangle.Empty;
            var selection = ((TextPattern)value).GetSelection();
            if (selection.Length != 1)
                return Rectangle.Empty;
            // GetBoundingRectangles on a noncollapsed selection describes whole
            // selected lines, not its insertion point. Work only on cloned ranges;
            // never Select()/move the user's real selection to obtain geometry.
            var point = selection[0].Clone();
            point.MoveEndpointByRange(TextPatternRangeEndpoint.Start, point, TextPatternRangeEndpoint.End);
            Rectangle Bounds(System.Windows.Rect rect) => rect.IsEmpty ? Rectangle.Empty :
                CaretGeometry.Bounds(rect.X, rect.Y, rect.Width, rect.Height);
            System.Windows.Rect[] Rectangles(TextPatternRange range)
            {
                try
                {
                    return range.GetBoundingRectangles();
                }
                catch { return Array.Empty<System.Windows.Rect>(); }
            }
            var direct = Rectangles(point);
            if (direct.Length == 1)
            {
                var caret = Bounds(direct[0]);
                if (CaretGeometry.WithinEditor(caret, editor))
                    return caret;
            }
            // Degenerate ranges often have no rectangle (Office, Chromium). The
            // next character's leading edge represents the caret; at document end
            // use the previous character's trailing edge, not its top-left.
            foreach (bool previous in new[] { false, true })
            {
                var adjacent = point.Clone();
                int moved = adjacent.MoveEndpointByUnit(previous ? TextPatternRangeEndpoint.Start :
                    TextPatternRangeEndpoint.End, TextUnit.Character, previous ? -1 : 1);
                if (moved == 0)
                    continue;
                var rectangles = Rectangles(adjacent);
                if (rectangles.Length == 0)
                    continue;
                var character = Bounds(previous ? rectangles[^1] : rectangles[0]);
                FlowDirections flow = FlowDirections.Default;
                try
                {
                    var direction = adjacent.GetAttributeValue(TextPattern.TextFlowDirectionsAttribute);
                    if (direction is FlowDirections typed)
                        flow = typed;
                    else if (direction is int flags)
                        flow = (FlowDirections)flags;
                }
                catch { /* Direction is optional; geometry still has a safe LTR fallback. */ }
                var caret = CaretGeometry.Edge(character, previous,
                    flow.HasFlag(FlowDirections.RightToLeft), flow.HasFlag(FlowDirections.Vertical),
                    flow.HasFlag(FlowDirections.BottomToTop));
                if (CaretGeometry.WithinEditor(caret, editor))
                    return caret;
            }
        }
        catch { /* Missing/inaccessible geometry does not make the target uneditable. */ }
        return Rectangle.Empty;
    }

    private static bool? Editable(AutomationElement element)
    {
        try
        {
            if (element.TryGetCurrentPattern(ValuePattern.Pattern, out var value))
                return !((ValuePattern)value).Current.IsReadOnly;
        }
        catch { /* An optional ValuePattern failure must not hide TextPattern. */ }
        try
        {
            // Office exposes edited slide shapes as Image, not Edit/Document.
            // Require an actual selection/caret, not just a writable text frame.
            if (element.TryGetCurrentPattern(TextPattern.Pattern, out var value))
            {
                var text = (TextPattern)value;
                var readOnly = text.DocumentRange.GetAttributeValue(TextPattern.IsReadOnlyAttribute);
                if (readOnly is true)
                    return false;
                if (readOnly is false && text.GetSelection().Length == 1)
                    return true;
            }
        }
        catch { }
        return null;
    }

    internal static Target? Read(bool includeGeometry = true)
    {
        LastFailure = "";
        try
        {
            nint window = Native.GetForegroundWindow();
            uint thread = Native.GetWindowThreadProcessId(window, out uint pid);
            if (window == 0 || pid == Environment.ProcessId)
                return Reject("foreground-unavailable");
            var info = new Native.GuiThreadInfo { Size = (uint)Marshal.SizeOf<Native.GuiThreadInfo>() };
            if (!Native.GetGUIThreadInfo(thread, ref info) || info.Focus == 0 ||
                Native.GetAncestor(info.Focus, 2) != window)
                return Reject("native-focus-unavailable");
            Native.GetWindowThreadProcessId(info.Focus, out uint focusPid);
            var element = AutomationElement.FocusedElement;
            if (element == null || element.Current.IsPassword || !element.Current.IsEnabled ||
                !element.Current.HasKeyboardFocus || element.Current.ProcessId != focusPid)
                return Reject("uia-focus-unavailable-or-protected");
            string identity = string.Join(".", element.GetRuntimeId());
            if (identity.Length == 0)
                return Reject("uia-identity-unavailable");
            bool? editable = Editable(element);
            if (editable == false)
                return Reject("read-only");
            // Older Office providers can omit TextPattern/IsReadOnly/selection
            // even while an actual text caret exists. The native object model
            // may authorize only a text selection in this exact focused pane.
            if (editable == null && !OfficeInsertion.Editing(new Target(window, info.Focus, pid, identity, Rectangle.Empty)))
                return Reject("editable-selection-unavailable");
            Rectangle editor = Rectangle.Empty, caret = Rectangle.Empty;
            bool caretKnown = false;
            if (includeGeometry)
            {
                try
                {
                    var bounds = element.Current.BoundingRectangle;
                    editor = !bounds.IsEmpty && bounds.Width > 0
                        ? CaretGeometry.Bounds(bounds.X, bounds.Y, bounds.Width, bounds.Height) : Rectangle.Empty;
                }
                catch { /* Optional layout is independent of editability. */ }
                if (info.Caret != 0 && Native.GetAncestor(info.Caret, 2) == window)
                {
                    Native.GetWindowThreadProcessId(info.Caret, out uint caretPid);
                    var point = new Native.Point { X = info.CaretRect.Left, Y = info.CaretRect.Top };
                    if (caretPid == focusPid && Native.ClientToScreen(info.Caret, ref point))
                    {
                        var nativeCaret = CaretGeometry.Bounds(point.X, point.Y,
                            (double)info.CaretRect.Right - info.CaretRect.Left,
                            (double)info.CaretRect.Bottom - info.CaretRect.Top);
                        if (CaretGeometry.WithinEditor(nativeCaret, editor))
                            caret = nativeCaret;
                    }
                }
                if (caret.IsEmpty)
                    caret = TextCaret(element, editor);
                caretKnown = !caret.IsEmpty;
                if (!caretKnown && !editor.IsEmpty)
                {
                    // Explicitly mark the fallback as editor geometry, not a caret.
                    caret = new Rectangle(editor.Left, editor.Bottom - 1, 1, 1);
                }
            }
            // UI Automation can yield while another shape/control in the SAME
            // HWND takes focus. Recheck UIA identity as well as native focus.
            var focused = AutomationElement.FocusedElement;
            if (focused == null || string.Join(".", focused.GetRuntimeId()) != identity)
                return Reject("uia-focus-changed");
            var latest = new Native.GuiThreadInfo { Size = info.Size };
            if (Native.GetForegroundWindow() != window ||
                !Native.GetGUIThreadInfo(thread, ref latest) || latest.Focus != info.Focus)
                return Reject("native-focus-changed");
            return new Target(window, info.Focus, pid, identity, caret, editor, caretKnown);
        }
        catch (Exception error) { return Reject("provider-" + error.GetType().Name); }
    }
}
