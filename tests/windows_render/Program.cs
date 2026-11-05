using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Reflection;
using System.Windows.Forms;
using OpenASRInput;

internal static class RenderCheck
{
    [STAThread]
    private static void Main(string[] args)
    {
        string output = Path.GetFullPath(args[0]);
        Directory.CreateDirectory(output);
        Application.SetHighDpiMode(HighDpiMode.PerMonitorV2);
        Application.EnableVisualStyles();
        foreach (int width in new[] { 480, 760, 960 })
            foreach (float scale in new[] { 1f, 1.5f })
                foreach (string state in new[] { "connecting", "listening", "edit-connecting", "edit-listening", "edit-pausing", "edit-processing", "needs-config" })
                {
                    using var panel = new Overlay { LogicalWidth = width, TextSize = width == 960 ? 22 : 15 };
                    string text = state == "needs-config" ? "请聚焦可编辑输入框，并结束当前输入法候选。" :
                        state.StartsWith("edit-", StringComparison.Ordinal) ? "请把选中的内容改成简短的中文。🙂" :
                        "今天我们一起测试语音输入的全新外观。Hello world 🙂";
                    void Set(string name, object value) => typeof(Overlay).GetField(name,
                        BindingFlags.Instance | BindingFlags.NonPublic)!.SetValue(panel, value);
                    Set("scale", scale);
                    Set("buffer", PreviewBuffer.From(text));
                    Set("wave", "▁▂▃▅▆█▆▃▂▁▂▅▆▃▂▁");
                    Set("state", state);
                    panel.Size = new Size((int)(width * scale), (int)(156 * scale));
                    using var bitmap = new Bitmap(panel.Width, panel.Height);
                    panel.DrawToBitmap(bitmap, panel.ClientRectangle);
                    bitmap.Save(Path.Combine(output, $"panel-{width}-{scale}-{state}.png"), ImageFormat.Png);
                }
        Console.WriteLine("PASS native panel rendering: 42 cases; 480/760/960 widths, 100/150% DPI, buffered recording, selection editing and notice");
    }
}
