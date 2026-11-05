using System.Globalization;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;

namespace OpenASRInput;

internal sealed record PreviewBuffer(string Text, int? Words, bool Clipped)
{
    internal static PreviewBuffer From(string text)
    {
        if (text.Length == 0)
            return new("", 0, false);
        nint iterator = 0;
        var pinned = GCHandle.Alloc(text, GCHandleType.Pinned);
        try
        {
            int error = 0;
            // Windows 11 ships ICU. Match Linux's zh dictionary word boundaries.
            iterator = Open(1, "zh", pinned.AddrOfPinnedObject(), text.Length, ref error);
            if (error > 0 || iterator == 0)
                throw new InvalidOperationException("ICU word iterator unavailable");
            var starts = new List<int>();
            int start = First(iterator);
            for (int end = Next(iterator); end != -1; start = end, end = Next(iterator))
                if (Status(iterator) >= 100)
                    starts.Add(start);
            bool clipped = starts.Count > 20;
            return new(SingleLine(text[(clipped ? starts[^20] : 0)..]), Math.Min(20, starts.Count), clipped);
        }
        catch (Exception error) when (error is DllNotFoundException or EntryPointNotFoundException or InvalidOperationException)
        {
            // Display degradation must never affect recognition or submitted text.
            var offsets = StringInfo.ParseCombiningCharacters(text);
            return new(SingleLine(text[(offsets.Length > 160 ? offsets[^160] : 0)..]), null, offsets.Length > 160);
        }
        finally
        {
            if (iterator != 0)
                Close(iterator);
            pinned.Free();
        }
    }

    private static string SingleLine(string text) => Regex.Replace(text, @"\s+", " ").TrimEnd();
    [DllImport("icu.dll", EntryPoint = "ubrk_open", CallingConvention = CallingConvention.Cdecl)]
    private static extern nint Open(int type, [MarshalAs(UnmanagedType.LPStr)] string locale,
        nint text, int length, ref int error);
    [DllImport("icu.dll", EntryPoint = "ubrk_first", CallingConvention = CallingConvention.Cdecl)]
    private static extern int First(nint iterator);
    [DllImport("icu.dll", EntryPoint = "ubrk_next", CallingConvention = CallingConvention.Cdecl)]
    private static extern int Next(nint iterator);
    [DllImport("icu.dll", EntryPoint = "ubrk_getRuleStatus", CallingConvention = CallingConvention.Cdecl)]
    private static extern int Status(nint iterator);
    [DllImport("icu.dll", EntryPoint = "ubrk_close", CallingConvention = CallingConvention.Cdecl)]
    private static extern void Close(nint iterator);
}
