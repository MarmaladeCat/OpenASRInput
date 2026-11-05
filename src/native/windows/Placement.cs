using System.Drawing;

namespace OpenASRInput;

public static class Placement
{
    public static (int Width, int Height, double Scale) Fit(Rectangle area, int logicalWidth, double requestedScale)
    {
        int margin = Math.Min(12, Math.Max(0, (Math.Min(area.Width, area.Height) - 1) / 4));
        int availableWidth = Math.Max(1, area.Width - margin * 2);
        int availableHeight = Math.Max(1, area.Height - margin * 2);
        double scale = Math.Min(requestedScale, Math.Min(availableWidth / 320.0, availableHeight / 156.0));
        return (Math.Max(1, (int)Math.Min(logicalWidth * scale, availableWidth)), Math.Max(1, (int)(156 * scale)), scale);
    }

    public static Rectangle Position(Rectangle area, Rectangle caret, int width, int height,
        Rectangle editor = default, int gap = 8, bool followCaret = false, string position = "cursor")
    {
        int margin = Math.Min(12, Math.Max(0, (Math.Min(area.Width, area.Height) - 1) / 4));
        width = Math.Clamp(width, 1, Math.Max(1, area.Width - margin * 2));
        height = Math.Clamp(height, 1, Math.Max(1, area.Height - margin * 2));
        Rectangle At(int x, int y) => new(
            Math.Clamp(x, area.Left + margin, area.Right - width - margin),
            Math.Clamp(y, area.Top + margin, area.Bottom - height - margin), width, height);
        if (position != "cursor")
        {
            int x = area.Left + (area.Width - width) / 2;
            if (position.EndsWith("left"))
                x = area.Left + margin;
            if (position.EndsWith("right"))
                x = area.Right - width - margin;
            return At(x, position.StartsWith("top") ? area.Top + margin : area.Bottom - height - margin);
        }
        var candidates = new List<Rectangle>();
        if (!editor.IsEmpty)
        {
            candidates.Add(At(caret.Left, editor.Bottom + gap));
            candidates.Add(At(caret.Left, editor.Top - height - gap));
            candidates.Add(At(editor.Right + gap, caret.Top));
            candidates.Add(At(editor.Left - width - gap, caret.Top));
        }
        candidates.Add(At(caret.Left, caret.Bottom + gap));
        candidates.Add(At(caret.Left, caret.Top - height - gap));
        candidates.Add(At(caret.Right + gap, caret.Top));
        candidates.Add(At(caret.Left - width - gap, caret.Top));
        candidates.Add(At(area.Left + margin, area.Top + margin));
        candidates.Add(At(area.Right - width - margin, area.Bottom - height - margin));
        long Overlap(Rectangle panel, Rectangle obstacle)
        {
            if (obstacle.IsEmpty)
                return 0;
            obstacle.Inflate(gap, gap);
            var overlap = Rectangle.Intersect(panel, obstacle);
            return (long)Math.Max(0, overlap.Width) * Math.Max(0, overlap.Height);
        }
        long Distance(Rectangle panel)
        {
            long dx = Math.Max(0L, Math.Max((long)panel.Left - caret.Right, (long)caret.Left - panel.Right));
            long dy = Math.Max(0L, Math.Max((long)panel.Top - caret.Bottom, (long)caret.Top - panel.Bottom));
            return dx * dx + dy * dy;
        }
        // A reliable caret should not be displaced to a large slide/notes box's
        // outer edge. Keep the active line visible, then choose the nearest spot.
        // Without caret evidence retain the editor-edge avoidance fallback.
        var ranked = candidates.OrderBy(panel => Overlap(panel, caret));
        return followCaret
            ? ranked.ThenBy(Distance).ThenBy(panel => Overlap(panel, editor)).First()
            : ranked.ThenBy(panel => Overlap(panel, editor)).First();
    }
}
