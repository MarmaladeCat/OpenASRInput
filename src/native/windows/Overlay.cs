using System.Drawing;
using System.Drawing.Drawing2D;
using Forms = System.Windows.Forms;

namespace OpenASRInput;

internal sealed class Overlay : Forms.Form
{
    private string text = "", wave = "", state = "";
    private PreviewBuffer buffer = PreviewBuffer.From("");
    private float scale = 1;
    internal double UserScale = 1;
    internal string PanelPosition = "cursor";
    internal int Transparency = 0;
    private Target? lastTarget;
    private bool active;
    public new void Hide()
    {
        active = false;
        lastTarget = null;
        base.Hide();
    }
    internal void Reconfigure()
    {
        if (active)
            Present(lastTarget, text, wave, state);
    }
    internal int LogicalWidth = 760, TextSize = 15, Radius = 18;
    internal string BufferStatus = "";
    internal Rectangle CaretAnchor
    {
        get; private set;
    }
    internal bool CaretKnown
    {
        get; private set;
    }
    internal int[] Colors = { 0xffffff, 0xf8fafc, 0xdbe4ee, 0x1e293b, 0x64748b, 0x475569,
        0x38b8ab, 0x6366f1, 0xeef2ff, 0xecfdf5, 0x15803d };
    internal Overlay()
    {
        FormBorderStyle = Forms.FormBorderStyle.None;
        ShowInTaskbar = false;
        TopMost = true;
        DoubleBuffered = true;
        AutoScaleMode = Forms.AutoScaleMode.None;
        Text = "OpenASRInput 语音预览";
    }
    protected override bool ShowWithoutActivation => true;
    protected override Forms.CreateParams CreateParams
    {
        get
        {
            var value = base.CreateParams;
            value.ExStyle |= 0x08000000 | 0x80 | 0x20;
            return value;
        }
    }
    protected override void WndProc(ref Forms.Message message)
    {
        if (message.Msg == 0x21)
        {
            message.Result = 3;
            return;
        } // MA_NOACTIVATE
        if (message.Msg == 0x84)
        {
            message.Result = -1;
            return;
        } // HTTRANSPARENT
        base.WndProc(ref message);
    }
    internal void Present(Target? target, string preview, string energy, string phase)
    {
        active = true;
        lastTarget = target;
        if (PanelPosition == "hidden" || Transparency == 100)
        {
            text = preview;
            wave = energy;
            state = phase;
            buffer = PreviewBuffer.From(preview);
            base.Hide();
            return;
        }
        Opacity = 1 - Transparency / 100.0;
        var anchor = target != null && !target.Caret.IsEmpty ? target.Caret :
            new Rectangle(Forms.Cursor.Position, new Size(1, 24));
        CaretAnchor = anchor;
        CaretKnown = target?.CaretKnown == true;
        var screen = Forms.Screen.FromPoint(new Point(anchor.Left, anchor.Top));
        var area = screen.WorkingArea;
        var monitor = Native.MonitorFromPoint(new Native.Point { X = anchor.Left, Y = anchor.Top }, 2);
        double dpi = Native.GetDpiForMonitor(monitor, 0, out uint dpiX, out _) == 0
            ? Math.Clamp(dpiX / 96.0, .75, 4) : 1;
        var size = Placement.Fit(area, LogicalWidth, UserScale * dpi);
        scale = (float)size.Scale;
        Bounds = Placement.Position(area, anchor, size.Width, size.Height,
            target?.Editor ?? Rectangle.Empty, Math.Max(8, (int)(8 * scale)), target?.CaretKnown == true, PanelPosition);
        if (text != preview)
            buffer = PreviewBuffer.From(preview);
        text = preview;
        wave = energy;
        state = phase;
        using var shape = new GraphicsPath();
        int radius = Math.Max(1, Math.Min((int)(Radius * scale), Math.Min(Width, Height) / 2));
        int diameter = radius * 2;
        shape.AddArc(0, 0, diameter, diameter, 180, 90);
        shape.AddArc(Width - diameter, 0, diameter, diameter, 270, 90);
        shape.AddArc(Width - diameter, Height - diameter, diameter, diameter, 0, 90);
        shape.AddArc(0, Height - diameter, diameter, diameter, 90, 90);
        shape.CloseFigure();
        var old = Region;
        Region = new Region(shape);
        old?.Dispose();
        if (!Visible)
            Show();
        Invalidate();
    }
    private Color Palette(int index) => Color.FromArgb(255, Color.FromArgb(Colors[index]));
    protected override void OnPaint(Forms.PaintEventArgs e)
    {
        e.Graphics.Clear(Palette(0));
        e.Graphics.ScaleTransform(scale, scale);
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        e.Graphics.TextRenderingHint = System.Drawing.Text.TextRenderingHint.ClearTypeGridFit;
        var names = new Dictionary<string, string>
        {
            ["connecting"] = "录音缓存",
            ["edit-connecting"] = "指令缓存",
            ["edit-listening"] = "听取指令",
            ["edit-pausing"] = "识别指令",
            ["edit-processing"] = "修改中",
            ["listening"] = "录音中",
            ["pausing"] = "收尾中",
            ["needs-config"] = "需设置"
        };
        GraphicsPath Rounded(float x, float y, float width, float height, float radius)
        {
            var path = new GraphicsPath();
            float diameter = Math.Max(1, Math.Min(radius * 2, Math.Min(width, height)));
            path.AddArc(x, y, diameter, diameter, 180, 90);
            path.AddArc(x + width - diameter, y, diameter, diameter, 270, 90);
            path.AddArc(x + width - diameter, y + height - diameter, diameter, diameter, 0, 90);
            path.AddArc(x, y + height - diameter, diameter, diameter, 90, 90);
            path.CloseFigure();
            return path;
        }
        void Fill(float x, float y, float width, float height, float radius, int color)
        {
            using var path = Rounded(x, y, width, height, radius);
            using var brush = new SolidBrush(Palette(color));
            e.Graphics.FillPath(brush, path);
        }
        void Label(string value, float x, float y, float width, int size, int color, bool tail = false)
        {
            using var font = new Font("Microsoft YaHei UI", size, GraphicsUnit.Pixel);
            using var brush = new SolidBrush(Palette(color));
            using var format = new StringFormat(StringFormat.GenericTypographic) { FormatFlags = StringFormatFlags.NoWrap };
            if (tail && e.Graphics.MeasureString(value, font, int.MaxValue, format).Width > width)
            {
                // Ellipsize the oldest content; keep the newest graphemes intact.
                var offsets = System.Globalization.StringInfo.ParseCombiningCharacters(value);
                int low = 0, high = offsets.Length;
                while (low < high)
                {
                    int middle = (low + high) / 2;
                    string candidate = "…" + value[offsets[middle]..];
                    if (e.Graphics.MeasureString(candidate, font, int.MaxValue, format).Width > width)
                        low = middle + 1;
                    else
                        high = middle;
                }
                value = low < offsets.Length ? "…" + value[offsets[low]..] : "…";
            }
            format.Trimming = StringTrimming.EllipsisCharacter;
            e.Graphics.DrawString(value, font, brush, new RectangleF(x, y, Math.Max(1, width), 30), format);
        }
        float w = Width / scale;
        using (var outline = Rounded(1, 1, w - 2, 154, Radius - 1))
        using (var border = new Pen(Palette(2)))
            e.Graphics.DrawPath(border, outline);

        // Same three rows and palette as the Linux panel: energy, buffer, keys.
        Fill(20, 16, 32, 32, 10, 8);
        Fill(32, 22, 8, 13, 4, 7);
        using (var pen = new Pen(Palette(7), 1.7f))
        {
            e.Graphics.DrawArc(pen, 29, 23, 14, 14, 0, 180);
            e.Graphics.DrawLine(pen, 36, 37, 36, 41);
            e.Graphics.DrawLine(pen, 32, 41, 40, 41);
        }
        var levels = wave.Where(c => c >= '▁' && c <= '█').Select(c => (c - '▁') / 7f).ToArray();
        if (levels.Length == 0)
            levels = new[] { 0f };
        using (var gradient = new LinearGradientBrush(new PointF(68, 0), new PointF(w - 126, 0), Palette(6), Palette(7)))
            for (int i = 0; i < 56; i++)
            {
                float position = i * (levels.Length - 1) / 55f;
                int index = (int)position;
                float fraction = position - index;
                float height = 3 + 25 * (levels[index] * (1 - fraction) + levels[Math.Min(index + 1, levels.Length - 1)] * fraction);
                using var bar = Rounded(70 + i * (w - 198) / 55, 32 - height / 2, 3.5f, height, 1.75f);
                e.Graphics.FillPath(gradient, bar);
            }
        bool listening = state == "listening";
        Fill(w - 102, 20, 80, 25, 12.5f, listening ? 9 : 8);
        Label(names.GetValueOrDefault(state, state), w - 85, 23, 65, 13, listening ? 10 : 7);
        Fill(20, 58, w - 40, 43, 9, 1);
        Label(buffer.Text.Length == 0 ? (BufferStatus.Length == 0 ? "等待语音识别…" : BufferStatus) : buffer.Text, 34, 68, w - 138, TextSize,
            buffer.Text.Length == 0 ? 4 : 3, true);
        Label(buffer.Words.HasValue ? $"{buffer.Words} / 20" : "预览", w - 82, 71, 60, 12, 4);

        bool compact = w < 620;
        float x = 24;
        void Key(string name, string hint, int keyWidth, int hintWidth)
        {
            Fill(x, 117, keyWidth, 22, 5, 1);
            Label(name, x + 7, 120, keyWidth - 12, 11, 5);
            Label(hint, x + keyWidth + 8, 119, hintWidth, 12, 4);
            x += keyWidth + hintWidth + (compact ? 16 : 28);
        }
        Key(compact ? "⇧ Space" : "Shift + Space", state == "needs-config" ? "重试" : compact ? "启停" : "暂停 / 恢复",
            compact ? 62 : 96, compact ? 30 : 70);
        if (state == "needs-config")
            Label("请打开设置检查连接与输入目标", x, 119, w - x - 24, 12, 4);
        else
        {
            Key("Enter", "收尾", compact ? 42 : 46, 30);
            Key("Esc", "取消", compact ? 32 : 34, 30);
            if (w >= 720)
                Label("Alt + X 也可启停", x, 119, w - x - 24, 11, 4);
        }
    }
}
