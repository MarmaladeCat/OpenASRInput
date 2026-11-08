using System.Runtime.InteropServices;
using System.Text;

namespace OpenASRInput;

internal static class Native
{
    [StructLayout(LayoutKind.Sequential)]
    internal struct Rect
    {
        public int Left, Top, Right, Bottom;
    }
    [StructLayout(LayoutKind.Sequential)]
    internal struct Point
    {
        public int X, Y;
    }
    [StructLayout(LayoutKind.Sequential)]
    internal struct GuiThreadInfo
    {
        public uint Size, Flags;
        public nint Active, Focus, Capture, MenuOwner, MoveSize, Caret;
        public Rect CaretRect;
    }
    [StructLayout(LayoutKind.Sequential)]
    internal struct HookKey
    {
        public uint Key, Scan, Flags, Time;
        public nuint Extra;
    }
    internal delegate nint KeyboardHook(int code, nint message, nint data);
    [DllImport("user32.dll", SetLastError = true)]
    internal static extern nint SetWindowsHookExW(
        int kind, KeyboardHook callback, nint module, uint thread);
    [DllImport("user32.dll")] internal static extern bool UnhookWindowsHookEx(nint hook);
    [DllImport("user32.dll")] internal static extern nint CallNextHookEx(nint hook, int code, nint message, nint data);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] internal static extern nint GetModuleHandleW(string? name);
    [StructLayout(LayoutKind.Sequential)]
    internal struct KeyInput
    {
        public ushort VirtualKey, Scan;
        public uint Flags, Time;
        public nuint Extra;
    }
    [StructLayout(LayoutKind.Sequential)]
    internal struct MouseInput
    {
        public int X, Y;
        public uint Data, Flags, Time;
        public nuint Extra;
    }
    [StructLayout(LayoutKind.Explicit)]
    internal struct InputUnion
    {
        [FieldOffset(0)] public KeyInput Keyboard;
        [FieldOffset(0)] public MouseInput Mouse;
    }
    [StructLayout(LayoutKind.Sequential)]
    internal struct Input
    {
        public uint Type; public InputUnion Data;
    }
    [DllImport("user32.dll")] internal static extern nint GetForegroundWindow();
    [DllImport("user32.dll")] internal static extern nint GetAncestor(nint window, uint flags);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetClassNameW(nint window, StringBuilder name, int capacity);
    [DllImport("user32.dll")] internal static extern uint GetWindowThreadProcessId(nint hwnd, out uint pid);
    [DllImport("user32.dll")] internal static extern bool GetGUIThreadInfo(uint thread, ref GuiThreadInfo info);
    [DllImport("user32.dll")] internal static extern bool ClientToScreen(nint window, ref Point point);
    [DllImport("user32.dll")] internal static extern bool GetWindowRect(nint window, out Rect rect);
    [DllImport("user32.dll")] internal static extern bool RegisterHotKey(nint window, int id, uint modifiers, uint key);
    [DllImport("user32.dll")] internal static extern bool UnregisterHotKey(nint window, int id);
    [DllImport("user32.dll")] internal static extern short GetAsyncKeyState(int key);
    [DllImport("user32.dll", SetLastError = true)] internal static extern uint SendInput(uint count, Input[] input, int size);
    [DllImport("imm32.dll")] internal static extern nint ImmGetContext(nint window);
    [DllImport("imm32.dll")] internal static extern bool ImmReleaseContext(nint window, nint context);
    [DllImport("imm32.dll")] internal static extern int ImmGetCompositionStringW(nint context, uint index, nint buffer, uint length);
    [DllImport("user32.dll")] internal static extern uint GetDpiForWindow(nint window);
    [DllImport("user32.dll")] internal static extern nint MonitorFromPoint(Point point, uint flags);
    [DllImport("shcore.dll")] internal static extern int GetDpiForMonitor(nint monitor, int kind, out uint x, out uint y);

    internal static string WindowClass(nint window)
    {
        var name = new StringBuilder(256);
        return GetClassNameW(window, name, name.Capacity) == 0 ? "" : name.ToString();
    }

    internal static bool ModifiersHeld() => new[] { 0x10, 0x11, 0x12, 0x5b, 0x5c }
        .Any(key => (GetAsyncKeyState(key) & 0x8000) != 0);

    internal static bool Composing(nint window)
    {
        nint context = ImmGetContext(window);
        if (context == 0)
            return false;
        try
        {
            return ImmGetCompositionStringW(context, 8, 0, 0) > 0;
        }
        finally { ImmReleaseContext(window, context); }
    }

    internal static Input[] EncodeUnicode(string text)
    {
        if (text.Length > 32768 || text.Contains('\0'))
            throw new ArgumentException("Invalid final text");
        var input = new Input[text.Length * 2];
        for (int i = 0; i < text.Length; i++)
        {
            input[i * 2] = new Input { Type = 1, Data = new InputUnion { Keyboard = new KeyInput { Scan = text[i], Flags = 4 } } };
            input[i * 2 + 1] = new Input { Type = 1, Data = new InputUnion { Keyboard = new KeyInput { Scan = text[i], Flags = 6 } } };
        }
        return input;
    }
    internal static bool Insert(string text)
    {
        var input = EncodeUnicode(text);
        return input.Length == 0 || SendInput((uint)input.Length, input, Marshal.SizeOf<Input>()) == input.Length;
    }
}
