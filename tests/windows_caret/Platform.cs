// In-memory UIA/user32 doubles. This executable has no desktop API references,
// windows, hooks, keyboard events or microphone access; it runs actual Target.cs.
using System.Drawing;

namespace OpenASRInput
{
    internal static class Scene
    {
        internal static int Start, End = 3, GeometryReads;
        internal static bool NativeCaret, ThrowCollapsed, NoGeometry, ReadOnly, Rtl;
        internal static Native.Rect NativeBounds;
        internal static readonly Rectangle Editor = new(150, 150, 700, 500);
        internal static readonly System.Windows.Rect[] Glyphs = {
            new(200, 200, 20, 28), new(220, 200, 20, 28), new(300, 260, 20, 28)
        };
        internal static void Reset()
        {
            Start = GeometryReads = 0;
            End = 3;
            NativeCaret = ThrowCollapsed = NoGeometry = ReadOnly = Rtl = false;
            NativeBounds = default;
        }
    }
    internal static class Native
    {
        internal struct Point
        {
            internal int X, Y;
        }
        internal struct Rect
        {
            internal int Left, Top, Right, Bottom;
        }
        internal struct GuiThreadInfo
        {
            internal uint Size;
            internal nint Focus, Caret;
            internal Rect CaretRect;
        }
        internal static nint GetForegroundWindow() => 1;
        internal static uint GetWindowThreadProcessId(nint window, out uint process)
        {
            process = uint.MaxValue;
            return 1;
        }
        internal static nint GetAncestor(nint window, uint flags) => 1;
        internal static bool GetGUIThreadInfo(uint thread, ref GuiThreadInfo info)
        {
            info.Focus = 2;
            info.Caret = Scene.NativeCaret ? 3 : 0;
            info.CaretRect = Scene.NativeBounds;
            return true;
        }
        internal static bool ClientToScreen(nint window, ref Point point)
        {
            point.X += 100;
            point.Y += 100;
            return true;
        }
    }
}

namespace System.Windows
{
    internal readonly record struct Rect(double X, double Y, double Width, double Height)
    {
        internal bool IsEmpty => Width < 0 || Height < 0;
    }
}

namespace System.Windows.Automation.Text
{
    using OpenASRInput;
    internal enum TextPatternRangeEndpoint
    {
        Start, End
    }
    internal enum TextUnit
    {
        Character
    }
    [Flags]
    internal enum FlowDirections
    {
        Default = 0, RightToLeft = 1, BottomToTop = 2, Vertical = 4
    }
    internal sealed class TextPatternRange
    {
        private int start, end;
        internal TextPatternRange(int start, int end)
        {
            this.start = start;
            this.end = end;
        }
        internal TextPatternRange Clone() => new(start, end);
        internal void MoveEndpointByRange(TextPatternRangeEndpoint endpoint, TextPatternRange range, TextPatternRangeEndpoint other)
        {
            int value = other == TextPatternRangeEndpoint.Start ? range.start : range.end;
            if (endpoint == TextPatternRangeEndpoint.Start)
            {
                start = value;
                end = Math.Max(end, start);
            }
            else
            {
                end = value;
                start = Math.Min(start, end);
            }
        }
        internal int MoveEndpointByUnit(TextPatternRangeEndpoint endpoint, TextUnit unit, int count)
        {
            int original = endpoint == TextPatternRangeEndpoint.Start ? start : end;
            int value = (int)Math.Clamp((long)original + count, 0, Scene.Glyphs.Length);
            if (endpoint == TextPatternRangeEndpoint.Start)
            {
                start = value;
                end = Math.Max(end, start);
            }
            else
            {
                end = value;
                start = Math.Min(start, end);
            }
            return value - original;
        }
        internal Rect[] GetBoundingRectangles()
        {
            Scene.GeometryReads++;
            if (Scene.ThrowCollapsed && start == end)
                throw new NotSupportedException();
            return Scene.NoGeometry ? Array.Empty<Rect>() : Scene.Glyphs[start..end];
        }
        internal object GetAttributeValue(object attribute) => attribute == TextPattern.IsReadOnlyAttribute
            ? Scene.ReadOnly : Scene.Rtl ? FlowDirections.RightToLeft : FlowDirections.Default;
    }
}

namespace System.Windows.Automation
{
    using OpenASRInput;
    using System.Windows.Automation.Text;
    internal sealed class ElementProperties
    {
        internal bool IsPassword => false;
        internal bool IsEnabled => true;
        internal bool HasKeyboardFocus => true;
        internal long ProcessId => uint.MaxValue;
        internal Rect BoundingRectangle
        {
            get
            {
                Scene.GeometryReads++;
                var r = Scene.Editor;
                return new(r.X, r.Y, r.Width, r.Height);
            }
        }
    }
    internal sealed class AutomationElement
    {
        internal static AutomationElement FocusedElement => new();
        internal ElementProperties Current => new();
        internal int[] GetRuntimeId() => new[] { 7 };
        internal bool TryGetCurrentPattern(object pattern, out object value)
        {
            value = new TextPattern();
            return pattern == TextPattern.Pattern;
        }
    }
    internal sealed class TreeWalker
    {
        internal static TreeWalker RawViewWalker => new();
        internal AutomationElement? GetParent(AutomationElement element) => null;
    }
    internal sealed class ValuePattern
    {
        internal static object Pattern = new();
        internal ValuePattern Current => this;
        internal bool IsReadOnly => true;
    }
    internal sealed class TextPattern
    {
        internal static object Pattern = new(), IsReadOnlyAttribute = new(), TextFlowDirectionsAttribute = new();
        internal TextPatternRange DocumentRange => new(0, Scene.Glyphs.Length);
        internal TextPatternRange[] GetSelection() => new[] { new TextPatternRange(Scene.Start, Scene.End) };
    }
}
