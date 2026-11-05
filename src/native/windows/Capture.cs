using System.Collections.Concurrent;
using System.Runtime.InteropServices;
using System.Text.Json;

namespace OpenASRInput;

internal static class Capture
{
    [StructLayout(LayoutKind.Sequential, Pack = 2)]
    private struct Format
    {
        public ushort Tag, Channels; public uint Rate, BytesPerSecond;
        public ushort BlockAlign, Bits, Extra;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct Header
    {
        public nint Data; public uint Length, Recorded; public nuint User;
        public uint Flags, Loops; public nint Next; public nuint Reserved;
    }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct Caps
    {
        public ushort Manufacturer, Product; public uint Version;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string Name;
        public uint Formats; public ushort Channels, Reserved;
    }
    private delegate void Callback(nint handle, uint message, nuint instance, nint header, nint reserved);
    [DllImport("winmm.dll")] private static extern uint waveInGetNumDevs();
    [DllImport("winmm.dll", CharSet = CharSet.Unicode)] private static extern uint waveInGetDevCapsW(nuint device, out Caps caps, uint size);
    [DllImport("winmm.dll")] private static extern uint waveInOpen(out nint handle, uint device, ref Format format, Callback callback, nuint instance, uint flags);
    [DllImport("winmm.dll")] private static extern uint waveInPrepareHeader(nint handle, nint header, uint size);
    [DllImport("winmm.dll")] private static extern uint waveInUnprepareHeader(nint handle, nint header, uint size);
    [DllImport("winmm.dll")] private static extern uint waveInAddBuffer(nint handle, nint header, uint size);
    [DllImport("winmm.dll")] private static extern uint waveInStart(nint handle);
    [DllImport("winmm.dll")] private static extern uint waveInStop(nint handle);
    [DllImport("winmm.dll")] private static extern uint waveInReset(nint handle);
    [DllImport("winmm.dll")] private static extern uint waveInClose(nint handle);

    internal static void Devices()
    {
        var devices = new List<object>();
        for (uint i = 0; i < waveInGetNumDevs(); ++i)
            if (waveInGetDevCapsW(i, out var caps, (uint)Marshal.SizeOf<Caps>()) == 0)
                devices.Add(new
                {
                    id = i.ToString(),
                    title = caps.Name
                });
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            devices
        }));
    }
    private static void Check(uint result)
    {
        if (result != 0)
            throw new InvalidOperationException($"无法打开或采集麦克风（WinMM {result}），请检查设备及 Windows 麦克风权限。");
    }
    internal static void Run(string device)
    {
        uint id = device == "default" ? uint.MaxValue : uint.Parse(device);
        var format = new Format { Tag = 1, Channels = 1, Rate = 16000, BytesPerSecond = 32000, BlockAlign = 2, Bits = 16 };
        var completed = new BlockingCollection<nint>();
        Callback callback = (_, message, _, header, _) => { if (message == 0x3c0) completed.Add(header); };
        Check(waveInOpen(out var handle, id, ref format, callback, 0, 0x30000));
        uint headerSize = (uint)Marshal.SizeOf<Header>();
        var buffers = new List<(nint Header, nint Data)>();
        int stopping = 0;
        var output = Console.OpenStandardOutput();
        void Write(nint pointer, bool recycle)
        {
            var header = Marshal.PtrToStructure<Header>(pointer);
            if (header.Recorded > 0)
            {
                var bytes = new byte[header.Recorded];
                Marshal.Copy(header.Data, bytes, 0, bytes.Length);
                output.Write(bytes);
                output.Flush();
            }
            if (recycle)
                Check(waveInAddBuffer(handle, pointer, headerSize));
        }
        try
        {
            for (int i = 0; i < 8; ++i)
            {
                nint data = Marshal.AllocHGlobal(640), header = Marshal.AllocHGlobal((int)headerSize);
                Marshal.StructureToPtr(new Header { Data = data, Length = 640 }, header, false);
                buffers.Add((header, data));
                Check(waveInPrepareHeader(handle, header, headerSize));
                Check(waveInAddBuffer(handle, header, headerSize));
            }
            Check(waveInStart(handle));
            Console.Error.WriteLine("OpenASRInput.Capture\tREADY");
            Console.Error.Flush();
            _ = Task.Run(() => { Console.ReadLine(); Interlocked.Exchange(ref stopping, 1); });
            while (Volatile.Read(ref stopping) == 0)
                if (completed.TryTake(out var header, 100))
                    Write(header, true);
            waveInStop(handle);
            waveInReset(handle);
            var until = DateTime.UtcNow.AddSeconds(1);
            while (completed.Count < buffers.Count && DateTime.UtcNow < until)
                Thread.Sleep(5);
            while (completed.TryTake(out var remaining))
                Write(remaining, false);
        }
        finally
        {
            waveInReset(handle);
            foreach (var buffer in buffers)
            {
                if (waveInUnprepareHeader(handle, buffer.Header, headerSize) == 0)
                {
                    Marshal.FreeHGlobal(buffer.Header);
                    Marshal.FreeHGlobal(buffer.Data);
                }
            }
            waveInClose(handle);
            GC.KeepAlive(callback);
        }
    }
}
