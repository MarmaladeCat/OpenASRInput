using System.Drawing;
using System.Runtime.InteropServices;
using System.Windows.Automation;
using System.Windows.Automation.Text;

namespace OpenASRInput;

internal sealed record Target(nint Window, nint Focus, uint Process, string Identity, Rectangle Caret,
    Rectangle Editor = default, bool CaretKnown = false)
{
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
                string.Join(".", element.GetRuntimeId()) == Identity;
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

    internal static Target? Read(bool includeGeometry = true)
    {
        try
        {
            nint window = Native.GetForegroundWindow();
            uint thread = Native.GetWindowThreadProcessId(window, out uint pid);
            if (window == 0 || pid == Environment.ProcessId)
                return null;
            var info = new Native.GuiThreadInfo { Size = (uint)Marshal.SizeOf<Native.GuiThreadInfo>() };
            if (!Native.GetGUIThreadInfo(thread, ref info) || info.Focus == 0 ||
                Native.GetAncestor(info.Focus, 2) != window)
                return null;
            Native.GetWindowThreadProcessId(info.Focus, out uint focusPid);
            var element = AutomationElement.FocusedElement;
            if (element == null || element.Current.IsPassword || !element.Current.IsEnabled ||
                !element.Current.HasKeyboardFocus || element.Current.ProcessId != focusPid)
                return null;
            bool editable = false;
            if (element.TryGetCurrentPattern(ValuePattern.Pattern, out var value))
                editable = !((ValuePattern)value).Current.IsReadOnly;
            // Office reports an actively edited slide text box as Image, not
            // Document/Edit. Use its actual text capabilities, but require a
            // caret/selection: a merely selected shape also advertises writable
            // TextPattern and must not authorize dictation into the canvas.
            if (!editable && element.TryGetCurrentPattern(TextPattern.Pattern, out var pattern))
            {
                var text = (TextPattern)pattern;
                editable = text.DocumentRange.GetAttributeValue(TextPattern.IsReadOnlyAttribute) is false &&
                    text.GetSelection().Length == 1;
            }
            if (!editable)
                return null;
            string identity = string.Join(".", element.GetRuntimeId());
            if (identity.Length == 0)
                return null;
            Rectangle editor = Rectangle.Empty, caret = Rectangle.Empty;
            bool caretKnown = false;
            if (includeGeometry)
            {
                var bounds = element.Current.BoundingRectangle;
                editor = !bounds.IsEmpty && bounds.Width > 0
                    ? CaretGeometry.Bounds(bounds.X, bounds.Y, bounds.Width, bounds.Height) : Rectangle.Empty;
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
                if (!caretKnown)
                {
                    if (editor.IsEmpty)
                        return null;
                    // Explicitly mark the fallback as editor geometry, not a caret.
                    caret = new Rectangle(editor.Left, editor.Bottom - 1, 1, 1);
                }
            }
            // UI Automation can yield while another application takes focus.
            var latest = new Native.GuiThreadInfo { Size = info.Size };
            if (Native.GetForegroundWindow() != window ||
                !Native.GetGUIThreadInfo(thread, ref latest) || latest.Focus != info.Focus)
                return null;
            return new Target(window, info.Focus, pid, identity, caret, editor, caretKnown);
        }
        catch { return null; } // Inaccessible/elevated/secure targets never authorize input.
    }
}
