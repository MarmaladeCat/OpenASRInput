using System.Drawing;
using System.Runtime.InteropServices;

namespace OpenASRInput;

internal static class Branding
{
    // The same product-level branding directory feeds web/Linux assets and the
    // optional embedded Windows ICO. No dependency on the series checkout.
    internal static Icon LoadIcon()
    {
        using var stream = typeof(Branding).Assembly.GetManifestResourceStream("OpenASRInput.Logo");
        if (stream != null)
        {
            using var icon = new Icon(stream);
            return (Icon)icon.Clone();
        }
        // Neutral reserved mark instead of the unrelated Windows information logo.
        using var bitmap = new Bitmap(32, 32);
        using (var graphics = Graphics.FromImage(bitmap))
        using (var background = new SolidBrush(Color.FromArgb(100, 116, 139)))
        using (var pen = new Pen(Color.White, 2))
        {
            graphics.FillRectangle(background, 2, 2, 28, 28);
            graphics.DrawRectangle(pen, 10, 10, 12, 12);
        }
        var handle = bitmap.GetHicon();
        try
        {
            using var icon = Icon.FromHandle(handle);
            return (Icon)icon.Clone();
        }
        finally { DestroyIcon(handle); }
    }

    [DllImport("user32.dll")]
    private static extern bool DestroyIcon(nint icon);
}
