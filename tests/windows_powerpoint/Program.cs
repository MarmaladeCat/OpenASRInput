using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Drawing;
using System.Windows.Automation;
using OpenASRInput;

// Explicit opt-in integration test: uses a new disposable PowerPoint document
// and a real built/extracted bridge. Never opens or edits an existing document.
internal static class PowerPointTests
{
    [DllImport("user32.dll")] private static extern bool SetForegroundWindow(nint window);
    [DllImport("user32.dll")] private static extern bool ShowWindow(nint window, int command);
    [DllImport("user32.dll")] private static extern bool BringWindowToTop(nint window);
    [DllImport("user32.dll")] private static extern bool AttachThreadInput(uint from, uint to, bool attach);
    [DllImport("kernel32.dll")] private static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] private static extern bool SetProcessDpiAwarenessContext(nint context);

    private static void Check(bool value, string message)
    {
        if (!value)
            throw new Exception(message);
    }

    private static void Focus(nint window)
    {
        var deadline = Stopwatch.StartNew();
        do
        {
            uint thread = Native.GetWindowThreadProcessId(Native.GetForegroundWindow(), out _);
            uint current = GetCurrentThreadId();
            ShowWindow(window, 9);
            bool attached = thread != current && AttachThreadInput(current, thread, true);
            try
            {
                BringWindowToTop(window);
                SetForegroundWindow(window);
            }
            finally { if (attached) AttachThreadInput(current, thread, false); }
            Thread.Sleep(100);
            if (Native.GetForegroundWindow() == window)
                return;
        } while (deadline.ElapsedMilliseconds < 3000);
        throw new Exception($"Disposable presentation must be foreground: expected={window}, actual={Native.GetForegroundWindow()}");
    }

    private sealed class Bridge : IDisposable
    {
        private readonly Process process;
        private int sequence;
        internal Bridge(string helper)
        {
            process = Process.Start(new ProcessStartInfo(helper)
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardInput = true,
                RedirectStandardOutput = true,
                StandardInputEncoding = new UTF8Encoding(false),
                StandardOutputEncoding = Encoding.UTF8
            })!;
            Check(Read() == "0\tHELLO\tOpenASRInput.Bridge\t1", "Bridge handshake");
        }
        private string Read() => process.StandardOutput.ReadLineAsync()
            .WaitAsync(TimeSpan.FromSeconds(15)).GetAwaiter().GetResult() ?? throw new Exception("Bridge exited");
        internal string Request(params string[] fields)
        {
            string id = (++sequence).ToString();
            process.StandardInput.WriteLine(id + "\t" + string.Join("\t", fields));
            process.StandardInput.Flush();
            while (true)
            {
                string line = Read();
                if (line.StartsWith("0\tEVENT\t", StringComparison.Ordinal))
                    continue;
                Check(line.StartsWith(id + "\tOK\t", StringComparison.Ordinal), "Bridge response: " + line);
                return line[(id.Length + 4)..];
            }
        }
        public void Dispose()
        {
            process.StandardInput.Close();
            if (!process.WaitForExit(5000))
                process.Kill();
            process.Dispose();
        }
    }

    private static string Hex(string text) => Convert.ToHexString(Encoding.UTF8.GetBytes(text));

    [STAThread]
    private static int Main(string[] args)
    {
        SetProcessDpiAwarenessContext(-4);
        if (args.Length != 2 || !File.Exists(args[0]))
        {
            Console.Error.WriteLine("Usage: PowerPointTests <bridge.exe> <test-results/sandbox>");
            return 2;
        }
        string sandbox = Path.GetFullPath(args[1]);
        Check(sandbox.Split(Path.DirectorySeparatorChar).Contains("test-results", StringComparer.OrdinalIgnoreCase),
            "Sandbox must be under test-results");
        Directory.CreateDirectory(sandbox);
        string filename = "powerpoint-" + Guid.NewGuid().ToString("N");
        dynamic? app = null, presentation = null;
        bool ownedApplication = false;
        try
        {
            app = Activator.CreateInstance(Type.GetTypeFromProgID("PowerPoint.Application")!);
            ownedApplication = app!.Presentations.Count == 0;
            app.Visible = -1;
            presentation = app.Presentations.Add(-1);
            dynamic slide = presentation.Slides.Add(1, 12);
            dynamic shape = slide.Shapes.AddTextbox(1, 100, 120, 520, 120);
            shape.TextFrame.TextRange.Text = "前缀旧文字后缀";
            dynamic other = slide.Shapes.AddTextbox(1, 100, 300, 520, 100);
            other.TextFrame.TextRange.Text = "另一文本框";
            dynamic empty = slide.Shapes.AddTextbox(1, 100, 420, 520, 100);
            dynamic graphic = slide.Shapes.AddShape(1, 650, 100, 100, 100);
            presentation.SaveAs(Path.Combine(sandbox, filename + ".pptx"), 24);
            nint window = Process.GetProcessesByName("POWERPNT")
                .Single(p => p.MainWindowTitle.Contains(filename, StringComparison.OrdinalIgnoreCase)).MainWindowHandle;
            Focus(window);
            using var bridge = new Bridge(Path.GetFullPath(args[0]));
            string Begin()
            {
                Thread.Sleep(250); // Office publishes UIA focus asynchronously.
                Check(Native.GetForegroundWindow() == window, "PowerPoint foreground lost");
                string lease = bridge.Request("BEGIN");
                if (lease == "unavailable")
                {
                    var focused = AutomationElement.FocusedElement;
                    Console.Error.WriteLine($"Focus: {focused?.Current.ControlType.ProgrammaticName} {focused?.Current.Name}, keyboard={focused?.Current.HasKeyboardFocus}, selectionType={app.ActiveWindow.Selection.Type}");
                    Console.Error.WriteLine(bridge.Request("CONTEXT_STATUS"));
                }
                Check(lease != "unavailable", "PowerPoint text editing was rejected");
                Check(bridge.Request("VALID", lease) == "true", "PowerPoint lease invalid");
                return lease;
            }
            string Submit(string lease, string id, string text)
            {
                var deadline = Stopwatch.StartNew();
                string result;
                do
                {
                    result = bridge.Request("COMMIT", lease, id, Hex(text));
                    if (result != "deferred")
                        return result;
                    Thread.Sleep(20);
                } while (deadline.ElapsedMilliseconds < 30000);
                throw new Exception("PowerPoint commit did not finish");
            }
            void Commit(string lease, string id, string text)
            {
                string outcome = Submit(lease, id, text);
                Check(outcome == "accepted", "PowerPoint commit not confirmed: " + outcome + " " + bridge.Request("CONTEXT_STATUS"));
            }
            void Rejected(string state)
            {
                Thread.Sleep(250);
                Check(bridge.Request("BEGIN") == "unavailable", state + " must not authorize text insertion");
                Console.WriteLine("PASS reject " + state);
            }
            void Panel(string lease, string name)
            {
                Check(bridge.Request("SHOW", lease, "1", Hex("测试预览"), "", Hex("listening")) == "accepted", "Show test panel");
                using var status = JsonDocument.Parse(bridge.Request("CONTEXT_STATUS"));
                var root = status.RootElement;
                Check(root.GetProperty("panelVisible").GetBoolean(), "Panel visible");
                Check(root.GetProperty("panelCaretKnown").GetBoolean(), "Caret must be known: " + name);
                Rectangle Rect(string field)
                {
                    var r = root.GetProperty(field);
                    return new Rectangle(r.GetProperty("x").GetInt32(), r.GetProperty("y").GetInt32(),
                        r.GetProperty("width").GetInt32(), r.GetProperty("height").GetInt32());
                }
                var caret = Rect("panelAnchor");
                var bounds = Rect("panelBounds");
                Check(!bounds.IntersectsWith(caret), "Panel must not cover caret");
                int dx = Math.Max(0, Math.Max(bounds.Left - caret.Right, caret.Left - bounds.Right));
                int dy = Math.Max(0, Math.Max(bounds.Top - caret.Bottom, caret.Top - bounds.Bottom));
                Check(Math.Max(dx, dy) <= 30, "Panel must be near caret: " + name);
                File.WriteAllText(Path.Combine(sandbox, name + ".json"), root.GetRawText());
                Thread.Sleep(200);
                if (Native.GetWindowRect(window, out var frame))
                {
                    using var image = new Bitmap(frame.Right - frame.Left, frame.Bottom - frame.Top);
                    using var graphics = Graphics.FromImage(image);
                    graphics.CopyFromScreen(frame.Left, frame.Top, 0, 0, image.Size);
                    image.Save(Path.Combine(sandbox, name + ".png"));
                }
                Console.WriteLine($"PASS panel {name}: caret={caret}, panel={bounds}");
            }

            app.ActiveWindow.View.GotoSlide(1);
            shape.TextFrame.TextRange.Characters(3, 3).Select();
            string lease = Begin();
            Check(bridge.Request("SELECTION", lease) == Hex("旧文字"), "Exact PowerPoint selection");
            Check(bridge.Request("SHOW", lease, "1", Hex("指令录音"), "", Hex("edit-listening")) == "accepted",
                "Non-activating preview");
            Thread.Sleep(200);
            Commit(lease, "replace", "新文字🙂");
            Check((string)shape.TextFrame.TextRange.Text == "前缀新文字🙂后缀", "Replace only selected text");
            Commit(lease, "replace", "新文字🙂");
            Check((string)shape.TextFrame.TextRange.Text == "前缀新文字🙂后缀", "No duplicate replay");
            bridge.Request("CLEAR", lease);
            Console.WriteLine("PASS selection, preview, Unicode replacement and idempotent replay");

            shape.TextFrame.TextRange.Characters(3, 0).Select();
            lease = Begin();
            Check(bridge.Request("SELECTION", lease) == "", "Collapsed caret has no command selection");
            Commit(lease, "caret", "听写");
            Check((string)shape.TextFrame.TextRange.Text == "前缀听写新文字🙂后缀", "Insert at actual caret");
            Commit(lease, "caret-next", "追加");
            Check((string)shape.TextFrame.TextRange.Text == "前缀听写追加新文字🙂后缀", "Consecutive dictation finals");
            bridge.Request("CLEAR", lease);
            Console.WriteLine("PASS caret dictation");

            empty.TextFrame.TextRange.Characters(1, 0).Select();
            lease = Begin();
            Commit(lease, "empty", "空框中文🙂");
            Check((string)empty.TextFrame.TextRange.Text == "空框中文🙂", "Empty text box insertion");
            bridge.Request("CLEAR", lease);
            Console.WriteLine("PASS empty text box");

            shape.Select(-1);
            shape.TextFrame.TextRange.Text = "第一行中文\r第二行目标光标";
            shape.TextFrame.TextRange.Characters(9, 0).Select();
            lease = Begin();
            Panel(lease, "slide-middle-caret");
            bridge.Request("CLEAR", lease);
            shape.TextFrame.TextRange.Characters(2, 10).Select();
            lease = Begin();
            Panel(lease, "slide-multiline-selection");
            bridge.Request("CLEAR", lease);
            shape.TextFrame.TextRange.Text = "";
            shape.TextFrame.TextRange.Characters(1, 0).Select();
            lease = Begin();
            string longText = string.Concat(Enumerable.Repeat("长文本完整输入验证🙂。", 50));
            var timing = Stopwatch.StartNew();
            string longResult = Submit(lease, "long", longText);
            string actualLong = (string)shape.TextFrame.TextRange.Text;
            Console.WriteLine($"LONG result={longResult} expected={longText.Length} actual={actualLong.Length} ms={timing.ElapsedMilliseconds}");
            Console.WriteLine("LONG diagnostics=" + bridge.Request("CONTEXT_STATUS"));
            Check(longResult == "accepted" && actualLong == longText, "Complete long dictation in slide text box");
            Commit(lease, "long", longText);
            Check((string)shape.TextFrame.TextRange.Text == longText, "Completed long final replay is idempotent");
            bridge.Request("CLEAR", lease);

            shape.TextFrame.TextRange.Text = "";
            shape.TextFrame.TextRange.Characters(1, 0).Select();
            lease = Begin();
            Check(bridge.Request("SHOW", lease, "1", Hex("尚未确认的临时文字"), "", Hex("listening")) == "accepted", "Partial appears before final");
            string prefix = (string)shape.TextFrame.TextRange.Text;
            Check(prefix == "尚未确认的临时文字", "Screen buffer contains actual preview");
            shape.TextFrame.TextRange.Characters(1, 0).Select();
            Check(bridge.Request("COMMIT", lease, "interrupted", Hex(longText)) == "stale", "Caret move rejects continuation");
            Check((string)shape.TextFrame.TextRange.Text == prefix, "No duplicate prefix after caret move");
            bridge.Request("CLEAR", lease);
            Console.WriteLine("PASS long replay and moved-caret preview isolation");
            shape.TextFrame.TextRange.Text = "前缀后缀";
            shape.TextFrame.TextRange.Characters(3, 0).Select();
            lease = Begin();
            Check(bridge.Request("SHOW", lease, "1", Hex("今天天气"), "", Hex("listening")) == "accepted", "First partial");
            Check((string)shape.TextFrame.TextRange.Text == "前缀今天天气后缀", "Immediate provisional screen text");
            Check(bridge.Request("SHOW", lease, "2", Hex("今天下雨🙂"), "", Hex("listening")) == "accepted", "Revision of owned screen text");
            Check((string)shape.TextFrame.TextRange.Text == "前缀今天下雨🙂后缀", "Corrected preview, no duplicates");
            Commit(lease, "promote", "今天下雨🙂。");
            Commit(lease, "promote", "今天下雨🙂。");
            Check((string)shape.TextFrame.TextRange.Text == "前缀今天下雨🙂。后缀", "Final promotes preview exactly once");
            Check(bridge.Request("SHOW", lease, "3", Hex("下一句临时"), "", Hex("listening")) == "accepted", "Next utterance preview");
            bridge.Request("CLEAR", lease);
            Check((string)shape.TextFrame.TextRange.Text == "前缀今天下雨🙂。后缀", "Cancel removes only unconfirmed screen buffer");
            shape.TextFrame.TextRange.Characters(1, 2).Select();
            lease = Begin();
            Check(bridge.Request("SHOW", lease, "1", Hex("临时替换"), "", Hex("listening")) == "accepted", "Provisional replacement");
            bridge.Request("CLEAR", lease);
            Check((string)shape.TextFrame.TextRange.Text == "前缀今天下雨🙂。后缀", "Cancel restores original selected text");
            Console.WriteLine("PASS three-layer preview, correction, promotion and cancellation");
            shape.TextFrame.TextRange.Text = "前\v后";
            shape.TextFrame.TextRange.Select();
            lease = Begin();
            Check(bridge.Request("SHOW", lease, "1", Hex("临时替换"), "", Hex("listening")) == "accepted", "Soft-break selection preview is handled safely");
            bridge.Request("CLEAR", lease);
            Check((string)shape.TextFrame.TextRange.Text == "前\v后", "Cancel preserves soft-break source text exactly");
            shape.TextFrame.TextRange.Text = "前缀听写追加新文字🙂后缀";

            shape.Select(-1);
            shape.TextFrame.TextRange.Characters(1, 2).Select();
            lease = Begin();
            other.Select(-1);
            other.TextFrame.TextRange.Characters(1, 0).Select();
            Thread.Sleep(250);
            Check(bridge.Request("VALID", lease) == "false", "Switching shapes revokes lease");
            Check(bridge.Request("COMMIT", lease, "late", Hex("不得输入")) == "stale", "Reject late final");
            Check((string)other.TextFrame.TextRange.Text == "另一文本框", "Other shape remains unchanged");
            Check((string)shape.TextFrame.TextRange.Text == "前缀听写追加新文字🙂后缀", "Old shape remains unchanged");
            Console.WriteLine("PASS cross-shape focus isolation");

            shape.Select(-1);
            Rejected("shape-only selection");
            graphic.Select(-1);
            Rejected("non-text shape");
            app.ActiveWindow.Selection.Unselect();
            Rejected("slide canvas");

            app.ActiveWindow.ViewType = 3; // ppViewNotesPage, disposable presentation only.
            dynamic notes = slide.NotesPage.Shapes.Placeholders(2);
            notes.TextFrame.TextRange.Text = "备注前缀旧文字后缀";
            notes.Select(-1);
            notes.TextFrame.TextRange.Characters(5, 3).Select();
            lease = Begin();
            Panel(lease, "notes-selection");
            Commit(lease, "notes-replace", "备注新文字🙂");
            Check((string)notes.TextFrame.TextRange.Text == "备注前缀备注新文字🙂后缀", "Notes selection replacement");
            bridge.Request("CLEAR", lease);
            notes.TextFrame.TextRange.Text = "";
            notes.TextFrame.TextRange.Characters(1, 0).Select();
            lease = Begin();
            Commit(lease, "notes-long", longText);
            Check((string)notes.TextFrame.TextRange.Text == longText, "Complete long dictation in notes");
            bridge.Request("CLEAR", lease);
            Console.WriteLine("PASS notes positioning, Unicode replacement and long final");
            app.ActiveWindow.ViewType = 9; // ppViewNormal: the everyday bottom notes pane.
            app.ActiveWindow.Panes(3).Activate();
            notes.TextFrame.TextRange.Text = "普通视图备注测试";
            Thread.Sleep(300);
            var notesElement = AutomationElement.FocusedElement;
            var notesPattern = notesElement.GetCurrentPattern(TextPattern.Pattern) as TextPattern;
            Check(notesPattern != null && notesPattern.DocumentRange.GetText(100).Contains("普通视图备注测试"),
                "Normal notes pane must expose the disposable notes text");
            var notesCaret = notesPattern!.DocumentRange.Clone();
            notesCaret.MoveEndpointByRange(System.Windows.Automation.Text.TextPatternRangeEndpoint.End,
                notesCaret, System.Windows.Automation.Text.TextPatternRangeEndpoint.Start);
            notesCaret.Move(System.Windows.Automation.Text.TextUnit.Character, 4);
            notesCaret.Select();
            lease = Begin();
            Panel(lease, "normal-notes-caret");
            Commit(lease, "normal-notes", "插入🙂");
            Check((string)notes.TextFrame.TextRange.Text == "普通视图插入🙂备注测试", "Normal notes pane insertion");
            bridge.Request("CLEAR", lease);
            Console.WriteLine("PASS normal-view notes pane");
            Console.WriteLine("PASS PowerPoint " + (string)app.Version + " with real bridge " + args[0]);
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
        finally
        {
            if (presentation != null)
            {
                presentation!.Saved = -1;
                presentation!.Close();
            }
            if (app != null && ownedApplication && app!.Presentations.Count == 0)
                app!.Quit();
        }
    }
}
