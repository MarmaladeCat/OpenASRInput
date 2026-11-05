using System.Drawing;

namespace OpenASRInput;

// Physical screen coordinates throughout: UIA already returns screen pixels.
// Keep this independent of desktop APIs so malformed/provider geometry is testable.
internal static class CaretGeometry
{
    internal static Rectangle Bounds(double x, double y, double width, double height)
    {
        if (!double.IsFinite(x) || !double.IsFinite(y) || !double.IsFinite(width) ||
            !double.IsFinite(height) || width < 0 || height <= 0)
            return Rectangle.Empty;
        double left = Math.Floor(x), top = Math.Floor(y);
        double right = Math.Max(left + 1, Math.Ceiling(x + width));
        double bottom = Math.Ceiling(y + height);
        if (left < int.MinValue || top < int.MinValue || right > int.MaxValue || bottom > int.MaxValue ||
            right - left > int.MaxValue || bottom - top > int.MaxValue)
            return Rectangle.Empty;
        return Rectangle.FromLTRB((int)left, (int)top, (int)right, (int)bottom);
    }

    internal static bool WithinEditor(Rectangle caret, Rectangle editor)
    {
        if (caret.Width <= 0 || caret.Height <= 0)
            return false;
        if (editor.IsEmpty)
            return true;
        // Permit an insertion bar at the exact text-box edge, including rounding.
        return (long)caret.Left >= (long)editor.Left - 2 && (long)caret.Right <= (long)editor.Right + 2 &&
            (long)caret.Top >= (long)editor.Top - 2 && (long)caret.Bottom <= (long)editor.Bottom + 2;
    }

    internal static Rectangle Edge(Rectangle character, bool trailing, bool rightToLeft = false,
        bool vertical = false, bool bottomToTop = false)
    {
        if (character.IsEmpty)
            return Rectangle.Empty;
        if (vertical)
            return new Rectangle(character.Left, trailing != bottomToTop ? character.Bottom : character.Top,
                character.Width, 1);
        return new Rectangle(trailing != rightToLeft ? character.Right : character.Left,
            character.Top, 1, character.Height);
    }
}
