using System.Drawing;
using System.Runtime.InteropServices;
using OpenASRInput;

void Check(bool value, string message) { if (!value) throw new Exception(message); }
var monitor = new Rectangle(-2560, -400, 2560, 1440);
var fitted = Placement.Fit(new Rectangle(0, 0, 800, 600), 760, 1.5);
Check(fitted.Scale == 1.5 && fitted.Width == 776 && fitted.Height == 234, "compact width preserves requested DPI/font scale");
fitted = Placement.Fit(new Rectangle(-10, -10, 10, 8), 760, 1.5);
Check(fitted.Scale > 0 && fitted.Width > 0 && fitted.Width <= 10 && fitted.Height <= 8, "tiny monitor bounds");
var panel = Placement.Position(monitor, new Rectangle(-20, 1000, 1, 24), 1520, 312);
Check(panel.Left >= monitor.Left && panel.Right <= monitor.Right, "negative monitor origin");
Check(panel.Top >= monitor.Top && panel.Bottom <= monitor.Bottom, "monitor vertical bounds");
panel = Placement.Position(new Rectangle(1920, 0, 800, 600), new Rectangle(2700, 580, 1, 20), 1800, 1200);
Check(panel.Left >= 1920 && panel.Right <= 2720 && panel.Height <= 600, "oversized DPI panel");
var work = new Rectangle(0, 0, 1920, 1040);
var editor = new Rectangle(320, 220, 900, 280);
var caret = new Rectangle(360, 240, 1, 24);
panel = Placement.Position(work, caret, 760, 156, editor);
Check(!panel.IntersectsWith(editor) && panel.Top >= editor.Bottom + 8, "avoid whole multiline editor below");
editor = new Rectangle(320, 800, 900, 230);
caret = new Rectangle(360, 880, 1, 24);
panel = Placement.Position(work, caret, 760, 156, editor);
Check(!panel.IntersectsWith(editor) && panel.Bottom <= editor.Top - 8, "avoid bottom editor above");
editor = new Rectangle(700, 0, 400, 1040);
caret = new Rectangle(720, 300, 1, 24);
panel = Placement.Position(work, caret, 480, 156, editor);
Check(!panel.IntersectsWith(editor), "use side when vertical space unavailable");
caret = new Rectangle(600, 1000, 1, 24);
panel = Placement.Position(work, caret, 760, 156, work);
Check(!panel.IntersectsWith(caret) && work.Contains(panel), "full-screen editor keeps caret visible");
foreach (var screen in new[] { work, monitor, new Rectangle(1920, -600, 1280, 1024) })
    for (int y = screen.Top; y < screen.Bottom; y += 71)
        for (int x = screen.Left; x < screen.Right; x += 173)
        {
            caret = new Rectangle(x, y, 1, 24);
            panel = Placement.Position(screen, caret, 760, 156, screen);
            Check(screen.Contains(panel), "all candidate positions stay in work area");
            Check(!panel.IntersectsWith(caret), "edge clamping never covers caret");
        }
var keys = new SessionKeys();
foreach (var screen in new[] { work, monitor, new Rectangle(1920, -600, 1280, 1024) })
    foreach (string position in new[] { "top-left", "top-center", "top-right", "bottom-left", "bottom-center", "bottom-right" })
    {
        var first = Placement.Position(screen, screen, 480, 156, position: position);
        var second = Placement.Position(screen, new Rectangle(screen.Right - 2, screen.Bottom - 30, 2, 28),
            480, 156, screen, followCaret: true, position: position);
        Check(first == second && screen.Contains(first), "fixed position is independent of caret within the active monitor");
        Check(position.StartsWith("top") ? first.Top == screen.Top + 12 : first.Bottom == screen.Bottom - 12,
            "fixed vertical edge respects monitor origin and work area");
        Check(position.EndsWith("left") ? first.Left == screen.Left + 12 :
            position.EndsWith("right") ? first.Right == screen.Right - 12 :
            first.Left == screen.Left + (screen.Width - first.Width) / 2, "fixed horizontal alignment");
    }
// Large slide/notes editors must follow the actual caret, not their outer edge.
editor = new Rectangle(100, 100, 1600, 700);
caret = new Rectangle(400, 300, 2, 28);
panel = Placement.Position(work, caret, 480, 156, editor, followCaret: true);
Check(panel.Left == caret.Left && panel.Top == caret.Bottom + 8,
    "known caret anchors nearby in a large PowerPoint-style text box");
var movedCaret = new Rectangle(620, 500, 2, 28);
var movedPanel = Placement.Position(work, movedCaret, 480, 156, editor, followCaret: true);
Check(movedPanel.Left == movedCaret.Left && movedPanel.Top == movedCaret.Bottom + 8,
    "moving insertion point follows both coordinates within the same editor");
Check(!panel.IntersectsWith(caret) && !movedPanel.IntersectsWith(movedCaret), "active text line stays visible");
var unknownPanel = Placement.Position(work, caret, 480, 156, editor);
Check(!unknownPanel.IntersectsWith(editor), "unknown caret retains editor avoidance");
foreach (var screen in new[] { work, monitor, new Rectangle(1920, -600, 1280, 1024) })
    foreach (var point in new[] { screen.Location, new Point(screen.Right - 2, screen.Bottom - 30),
        new Point(screen.Left + screen.Width / 2, screen.Top + screen.Height / 2) })
    {
        var current = new Rectangle(point.X, point.Y, 2, 28);
        panel = Placement.Position(screen, current, 760, 234, screen, gap: 12, followCaret: true);
        Check(screen.Contains(panel) && !panel.IntersectsWith(current), "caret-following stays on monitor and avoids caret");
    }
var glyph = CaretGeometry.Bounds(-1200.5, -100.25, 18.5, 30.5);
Check(glyph == Rectangle.FromLTRB(-1201, -101, -1182, -69), "fractional UIA physical pixels round outward on negative monitor");
Check(CaretGeometry.Bounds(50, 60, 0, 24) == new Rectangle(50, 60, 1, 24), "zero-width UIA caret remains usable");
foreach (var invalid in new[] { CaretGeometry.Bounds(0, 0, 0, 0), CaretGeometry.Bounds(double.NaN, 0, 1, 20),
    CaretGeometry.Bounds(0, 0, double.PositiveInfinity, 20), CaretGeometry.Bounds(0, 0, -1, 20),
    CaretGeometry.Bounds(int.MaxValue, 0, 1, 20) })
    Check(invalid.IsEmpty, "invalid/overflowed geometry cannot become a screen anchor");
glyph = new Rectangle(400, 300, 20, 28);
Check(CaretGeometry.Edge(glyph, false) == new Rectangle(400, 300, 1, 28), "next character leading edge");
Check(CaretGeometry.Edge(glyph, true) == new Rectangle(420, 300, 1, 28), "end-of-document caret is AFTER last character");
Check(CaretGeometry.Edge(glyph, true, rightToLeft: true).Left == 400, "RTL trailing edge");
Check(CaretGeometry.Edge(glyph, false, rightToLeft: true).Left == 420, "RTL leading edge");
Check(CaretGeometry.Edge(glyph, true, vertical: true) == new Rectangle(400, 328, 20, 1), "vertical caret endpoint");
Check(CaretGeometry.Edge(glyph, true, vertical: true, bottomToTop: true).Top == 300, "bottom-to-top endpoint");
Check(!CaretGeometry.WithinEditor(new Rectangle(0, 0, 1, 1), editor), "reject stale native caret outside focused slide text box");
Check(CaretGeometry.WithinEditor(new Rectangle(editor.Right, editor.Top, 1, 28), editor), "allow caret exactly on editor boundary");
Check(!CaretGeometry.WithinEditor(Rectangle.Empty, editor), "missing native geometry falls through to UIA");
Check(keys.Handle(0x0d, true, false) == (false, null), "idle Enter passes through");
Check(keys.Handle(0x0d, true, true) == (false, null), "held-before-session Enter is not stolen");
keys.Handle(0x0d, false, false);
Check(keys.Handle(0x0d, true, true) == (true, "pause"), "active Enter finalizes");
Check(keys.Handle(0x0d, true, true) == (true, null), "repeat Enter does not resume/finalize again");
Check(keys.Handle(0x0d, false, false) == (true, null), "paired release consumed after clear");
Check(keys.Handle(0x1b, true, true) == (true, "cancel"), "active Escape cancels");
Check(keys.Handle(0x1b, false, false) == (true, null), "Escape release remains consumed after cancellation");
Check(keys.Handle(0x1b, true, false) == (false, null), "foreign focus / modifier / IME Escape passes");
keys.Handle(0x1b, false, false);
Check(keys.Handle(0xe7, true, true) == (false, null), "Unicode text packets do not operate voice session");
Check(keys.Handle(0x41, true, true) == (false, null), "ordinary typing passes through");
var preview = PreviewBuffer.From(string.Join(" ", Enumerable.Range(1, 25).Select(i => $"word{i}")));
if (OperatingSystem.IsWindows())
    Check(preview.Words == 20 && preview.Clipped && preview.Text.StartsWith("word6 ") && preview.Text.EndsWith("word25"),
        "20-word preview retains newest words");
preview = PreviewBuffer.From("今天我们一起测试语音输入的新面板。🙂\nHello world");
Check(!preview.Clipped && preview.Text.EndsWith("🙂 Hello world"), "Unicode preview");
if (OperatingSystem.IsWindows())
    Check(preview.Words > 2, "ICU Chinese word segmentation");
preview = PreviewBuffer.From("   \n\t");
Check(preview.Text.Length == 0, "empty whitespace preview");
Check(Marshal.SizeOf<Native.Input>() == 40, "Windows x64 INPUT ABI layout");
var input = Native.EncodeUnicode("中🙂");
Check(input.Length == 6, "UTF-16 surrogate pair preservation");
Check(input[0].Data.Keyboard.Scan == '中' && input[2].Data.Keyboard.Scan == '\ud83d' &&
    input[4].Data.Keyboard.Scan == '\ude42', "Unicode scan ordering");
for (int i = 0; i < input.Length; i += 2)
    Check(input[i].Type == 1 && input[i].Data.Keyboard.Flags == 4 && input[i + 1].Data.Keyboard.Flags == 6,
        "Unicode down/up pairing");
Console.WriteLine("PASS Windows native rules: caret following, fallback editor avoidance, UIA endpoint geometry, mixed-DPI bounds, Enter/Esc, ICU and Unicode ABI");
