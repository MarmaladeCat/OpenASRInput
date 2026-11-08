// In-memory UIA/user32 doubles. This executable has no desktop API references,
// windows, hooks, keyboard events or microphone access; it runs actual Target.cs.
using System.Drawing;

namespace OpenASRInput
{
    internal static class Scene
    {
        internal static int Start, End = 3, GeometryReads;
        internal static bool NativeCaret, ThrowCollapsed, NoGeometry, ReadOnly, Rtl;
        internal static bool ThrowBounds, EmptyBounds, ThrowValue, Password, Disabled, MoveFocus;
        internal static bool MissingText, ThrowText, UnknownReadOnly, NoSelection, OfficeEditing, ValueReadOnly;
        internal static bool HasValue, ThrowValueRead, ThrowTextRead, ThrowCount, ThrowSelection, KeyboardFocus = true;
        internal static string Document = "abc";
        internal static nint Foreground = 1;
        internal static Action? OnIdentity, OnTextRead, OnValueRead;
        internal static int OfficeQueries;
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
            ThrowBounds = EmptyBounds = ThrowValue = Password = Disabled = MoveFocus = false;
            MissingText = ThrowText = UnknownReadOnly = NoSelection = OfficeEditing = ValueReadOnly = false;
            HasValue = ThrowValueRead = ThrowTextRead = ThrowCount = ThrowSelection = false;
            KeyboardFocus = true;
            Document = "abc";
            Foreground = 1;
            OnIdentity = OnTextRead = OnValueRead = null;
            OfficeQueries = 0;
            NativeBounds = default;
        }
    }
    internal static class OfficeInsertion
    {
        internal static bool Editing(Target target)
        {
            Scene.OfficeQueries++;
            return Scene.OfficeEditing && target.InsertionFocusCurrent();
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
        internal static nint GetForegroundWindow() => Scene.Foreground;
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
        internal int CompareEndpoints(TextPatternRangeEndpoint endpoint, TextPatternRange range, TextPatternRangeEndpoint other)
            => (endpoint == TextPatternRangeEndpoint.Start ? start : end) -
                (other == TextPatternRangeEndpoint.Start ? range.start : range.end);
        internal string GetText(int maximum)
        {
            if (Scene.ThrowTextRead)
                throw new NotSupportedException("Text content unavailable");
            string text = Scene.Document[start..end];
            var callback = Scene.OnTextRead;
            Scene.OnTextRead = null;
            callback?.Invoke();
            return maximum < 0 ? text : text[..Math.Min(text.Length, maximum)];
        }
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
            if (Scene.ThrowCount && count == int.MaxValue)
                throw new NotSupportedException("Character counting unavailable");
            int original = endpoint == TextPatternRangeEndpoint.Start ? start : end;
            int value = (int)Math.Clamp((long)original + count, 0, Scene.Document.Length);
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
            ? Scene.UnknownReadOnly ? new object() : Scene.ReadOnly
            : Scene.Rtl ? FlowDirections.RightToLeft : FlowDirections.Default;
    }
}

namespace System.Windows.Automation
{
    using OpenASRInput;
    using System.Windows.Automation.Text;
    internal sealed class ElementProperties
    {
        internal bool IsPassword => Scene.Password;
        internal bool IsEnabled => !Scene.Disabled;
        internal bool HasKeyboardFocus => Scene.KeyboardFocus;
        internal long ProcessId => uint.MaxValue;
        internal Rect BoundingRectangle
        {
            get
            {
                Scene.GeometryReads++;
                if (Scene.ThrowBounds)
                    throw new NotSupportedException("Provider has no bounds");
                if (Scene.EmptyBounds)
                    return new(0, 0, 0, 0);
                var r = Scene.Editor;
                return new(r.X, r.Y, r.Width, r.Height);
            }
        }
    }
    internal sealed class AutomationElement
    {
        internal static AutomationElement FocusedElement => new();
        internal ElementProperties Current => new();
        private readonly int identity = Scene.MoveFocus && Scene.GeometryReads > 0 ? 8 : 7;
        internal int[] GetRuntimeId()
        {
            var callback = Scene.OnIdentity;
            Scene.OnIdentity = null;
            callback?.Invoke();
            return new[] { identity };
        }
        internal bool TryGetCurrentPattern(object pattern, out object value)
        {
            if (pattern == ValuePattern.Pattern && Scene.ThrowValue)
                throw new NotSupportedException("Provider does not implement ValuePattern");
            if (pattern == ValuePattern.Pattern && (Scene.ValueReadOnly || Scene.HasValue))
            {
                value = new ValuePattern();
                return true;
            }
            if (pattern == TextPattern.Pattern && Scene.ThrowText)
                throw new NotSupportedException("Provider does not implement TextPattern");
            value = new TextPattern();
            return pattern == TextPattern.Pattern && !Scene.MissingText;
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
        internal bool IsReadOnly => Scene.ValueReadOnly;
        internal string Value
        {
            get
            {
                if (Scene.ThrowValueRead)
                    throw new NotSupportedException("Value content unavailable");
                string value = Scene.Document;
                var callback = Scene.OnValueRead;
                Scene.OnValueRead = null;
                callback?.Invoke();
                return value;
            }
        }
    }
    internal sealed class TextPattern
    {
        internal static object Pattern = new(), IsReadOnlyAttribute = new(), TextFlowDirectionsAttribute = new();
        internal TextPatternRange DocumentRange => new(0, Scene.Document.Length);
        internal TextPatternRange[] GetSelection()
        {
            if (Scene.ThrowSelection)
                throw new NotSupportedException("Text selection unavailable");
            return Scene.NoSelection ? Array.Empty<TextPatternRange>() :
                new[] { new TextPatternRange(Scene.Start, Scene.End) };
        }
    }
}
