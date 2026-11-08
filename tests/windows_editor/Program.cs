using System.IO;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Windows.Automation;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

internal sealed class TestEditor : Form
{
    private readonly Dictionary<string, TextBoxBase> fields = new();
    private readonly List<object> keyEvents = new();
    private readonly WebView2 browser = new() { Left = 750, Top = 35, Width = 600, Height = 480 };
    private readonly ProviderEditor provider = new();
    private readonly System.Windows.Forms.Integration.ElementHost providerHost = new()
        { Left = 20, Top = 595, Width = 700, Height = 55 };
    private bool browserReady, commandRunning;
    private readonly System.Windows.Forms.Timer timer = new() { Interval = 30 };
    private readonly string directory;
    [DllImport("user32.dll")] private static extern nint GetForegroundWindow();

    internal TestEditor(string output)
    {
        directory = Path.GetFullPath(output);
        Directory.CreateDirectory(directory);
        File.WriteAllText(Path.Combine(directory, "editor-keys.json"), "[]");
        Text = "OpenASRInput Windows Test Editor";
        Width = 1390;
        Height = 720;
        Add("first", "测试输入框 A", 35, 140, multiline: true);
        Add("second", "测试输入框 B", 210, 120, multiline: true);
        Add("password", "密码测试框", 375, 25, password: true);
        Add("readonly", "只读测试框", 415, 25, readOnly: true);
        var rich = new RichTextBox { AccessibleName = "富文本测试框", Left = 20, Top = 460, Width = 700, Height = 110 };
        fields.Add("rich", rich);
        Controls.Add(rich);
        Controls.Add(browser);
        providerHost.Child = provider;
        Controls.Add(providerHost);
        System.Windows.Automation.AutomationProperties.SetName(provider, "Disposable optional-provider editor");
        provider.TextChanged += (_, _) => Save();
        fields["readonly"].Text = "只读测试，不应输入";
        File.WriteAllText(Path.Combine(directory, "editor-identity.json"),
            JsonSerializer.Serialize(new
            {
                processId = Environment.ProcessId,
                title = Text
            }));
        Controls.Add(new Label { Text = "专用测试窗口：光标、选区、中文、Emoji、焦点与密码保护", Left = 20, Top = 10, Width = 700 });
        string state = Path.Combine(directory, "editor-text.json");
        if (File.Exists(state))
        {
            using var prior = JsonDocument.Parse(File.ReadAllText(state));
            foreach (string name in new[] { "first", "second" })
                if (prior.RootElement.TryGetProperty(name, out var value))
                    fields[name].Text = value.GetString() ?? "";
        }
        foreach (var pair in fields)
        {
            pair.Value.TextChanged += (_, _) => Save();
            pair.Value.KeyDown += (_, key) => SaveKey(pair.Key, key, true);
            pair.Value.KeyUp += (_, key) => SaveKey(pair.Key, key, false);
        }
        Shown += async (_, _) =>
        {
            fields["first"].Focus();
            Save();
            try
            {
                var environment = await CoreWebView2Environment.CreateAsync(null, Path.Combine(directory, "webview"));
                await browser.EnsureCoreWebView2Async(environment);
                browser.CoreWebView2.WebMessageReceived += (_, message) =>
                {
                    File.WriteAllText(Path.Combine(directory, "browser-text.json"), message.WebMessageAsJson);
                };
                browser.CoreWebView2.NavigationCompleted += (_, _) =>
                {
                    browserReady = true;
                    File.WriteAllText(Path.Combine(directory, "browser-ready.json"),
                        JsonSerializer.Serialize(new
                        {
                            version = browser.CoreWebView2.Environment.BrowserVersionString,
                            deviceDpi = DeviceDpi,
                            monitors = Screen.AllScreens.Select(screen => new
                            {
                                bounds = screen.Bounds.ToString(),
                                workingArea = screen.WorkingArea.ToString(),
                                primary = screen.Primary
                            }).ToArray()
                        }));
                };
                browser.NavigateToString("""
                    <!doctype html><meta charset="utf-8"><title>Disposable Chromium editor</title>
                    <style>body{font:18px sans-serif}textarea,input,div[contenteditable]{display:block;width:95%;margin:16px 0;min-height:60px;border:1px solid #888}</style>
                    <label>Chromium textarea<textarea id="first" aria-label="Chromium textarea"></textarea></label>
                    <label>Chromium contenteditable<div id="second" contenteditable="true" role="textbox" aria-label="Chromium contenteditable"></div></label>
                    <input id="password" type="password" aria-label="Chromium password">
                    <textarea id="readonly" readonly aria-label="Chromium readonly">readonly fixture</textarea>
                    <textarea id="ignored" aria-label="Chromium rejecting input">unchanged fixture</textarea>
                    <script>
                    function save(){chrome.webview.postMessage({first:document.querySelector('#first').value,second:document.querySelector('#second').innerText,passwordLength:document.querySelector('#password').value.length,readOnly:document.querySelector('#readonly').value,ignored:document.querySelector('#ignored').value})}
                    document.addEventListener('input',save);addEventListener('load',save);
                    document.querySelector('#ignored').addEventListener('beforeinput',e=>e.preventDefault());
                    window.fixture=function(action,name,start,length,enabled){const e=document.getElementById(name);e.focus();if(action==='select-all'){if(e.select)e.select();else{const r=document.createRange();r.selectNodeContents(e);getSelection().removeAllRanges();getSelection().addRange(r)}}else if(action==='select'){e.setSelectionRange(start,start+length)}else if(action==='undo'){document.execCommand('undo')}else if(action==='readonly'){if(name==='second')e.contentEditable=String(!enabled);else e.readOnly=enabled}save()};
                    </script>
                    """);
            }
            catch (Exception error)
            {
                File.WriteAllText(Path.Combine(directory, "browser-error.txt"), error.Message);
            }
        };
        timer.Tick += (_, _) => Command();
        timer.Start();
    }

    private void Add(string name, string label, int y, int height, bool multiline = false,
        bool password = false, bool readOnly = false)
    {
        var field = new TextBox
        {
            AccessibleName = label,
            Left = 20,
            Top = y,
            Width = 700,
            Height = height,
            Multiline = multiline,
            AcceptsReturn = multiline,
            UseSystemPasswordChar = password,
            ReadOnly = readOnly
        };
        fields.Add(name, field);
        Controls.Add(field);
    }

    private void Save() => File.WriteAllText(Path.Combine(directory, "editor-text.json"),
        JsonSerializer.Serialize(new
        {
            first = fields["first"].Text,
            second = fields["second"].Text,
            passwordLength = fields["password"].Text.Length,
            readOnly = fields["readonly"].Text,
            rich = fields["rich"].Text,
            provider = provider.Text
        }));

    private void SaveKey(string control, KeyEventArgs key, bool down)
    {
        if (key.KeyCode is not Keys.Enter and not Keys.Escape)
            return;
        keyEvents.Add(new
        {
            control,
            key = (int)key.KeyCode,
            down,
            shift = key.Shift
        });
        File.WriteAllText(Path.Combine(directory, "editor-keys.json"), JsonSerializer.Serialize(keyEvents));
    }

    private static async Task WaitForReadOnlyPublication(int[] identity)
    {
        // ExecuteScriptAsync confirms the DOM mutation, not Chromium's separate
        // accessibility-tree update. Observe UIA independently of the bridge so
        // the test can still catch a bridge that ignores published protection.
        var elapsed = System.Diagnostics.Stopwatch.StartNew();
        while (elapsed.Elapsed < TimeSpan.FromSeconds(2))
        {
            bool published = await Task.Run(() =>
            {
                var focused = AutomationElement.FocusedElement;
                if (focused == null || !focused.GetRuntimeId().SequenceEqual(identity))
                    return true; // A contenteditable may lose focus when disabled.
                if (focused.TryGetCurrentPattern(ValuePattern.Pattern, out var value) &&
                    ((ValuePattern)value).Current.IsReadOnly)
                    return true;
                return focused.TryGetCurrentPattern(TextPattern.Pattern, out var text) &&
                    ((TextPattern)text).DocumentRange.GetAttributeValue(TextPattern.IsReadOnlyAttribute) is true;
            });
            if (published)
                return;
            await Task.Delay(20);
        }
        throw new InvalidOperationException("Chromium did not publish the read-only transition to UIA");
    }

    private async void Command()
    {
        string path = Path.Combine(directory, "editor-command.json");
        if (commandRunning || !File.Exists(path))
            return;
        commandRunning = true;
        string? nonce = null;
        try
        {
            using var command = JsonDocument.Parse(File.ReadAllText(path));
            File.Delete(path);
            var value = command.RootElement;
            nonce = value.GetProperty("nonce").GetString();
            // Test API only operates while this disposable editor is foreground.
            if (GetForegroundWindow() != Handle)
                throw new InvalidOperationException("test editor is not foreground");
            string control = value.GetProperty("control").GetString()!;
            string action = value.GetProperty("action").GetString()!;
            if (control == "provider")
            {
                switch (action)
                {
                    case "focus":
                        providerHost.Focus();
                        provider.Focus();
                        System.Windows.Input.Keyboard.Focus(provider);
                        break;
                    case "set":
                        provider.Text = value.GetProperty("text").GetString()!;
                        provider.Select(provider.Text.Length, 0);
                        break;
                    case "select":
                        provider.Select(value.GetProperty("start").GetInt32(), value.GetProperty("length").GetInt32());
                        break;
                    case "select-all":
                        provider.SelectAll();
                        break;
                    case "fault":
                        provider.SetFault(value.GetProperty("mode").GetString()!);
                        break;
                    case "readonly":
                        provider.IsReadOnly = value.GetProperty("enabled").GetBoolean();
                        break;
                    default:
                        throw new InvalidOperationException("unsupported provider fixture command");
                }
            }
            else if (control.StartsWith("web-", StringComparison.Ordinal))
            {
                if (!browserReady)
                    throw new InvalidOperationException("Chromium fixture is not ready");
                if (action == "focus")
                    browser.Focus();
                bool readOnly = value.TryGetProperty("enabled", out var enabled) && enabled.GetBoolean();
                int[]? identity = action == "readonly" && readOnly
                    ? await Task.Run(() => AutomationElement.FocusedElement.GetRuntimeId()) : null;
                string args = string.Join(",", JsonSerializer.Serialize(action), JsonSerializer.Serialize(control[4..]),
                    value.TryGetProperty("start", out var start) ? start.GetInt32() : 0,
                    value.TryGetProperty("length", out var length) ? length.GetInt32() : 0,
                    JsonSerializer.Serialize(readOnly));
                await browser.ExecuteScriptAsync("window.fixture(" + args + ")");
                if (identity != null)
                    await WaitForReadOnlyPublication(identity);
            }
            else
            {
                var field = fields[control];
                switch (action)
                {
                    case "focus":
                        field.Focus();
                        break;
                    case "select":
                        field.Select(value.GetProperty("start").GetInt32(), value.GetProperty("length").GetInt32());
                        break;
                    case "select-all":
                        field.SelectAll();
                        break;
                    case "undo":
                        field.Undo();
                        break;
                    case "readonly":
                        field.ReadOnly = value.GetProperty("enabled").GetBoolean();
                        break;
                    default:
                        throw new InvalidOperationException("unsupported fixture command");
                }
            }
            Save();
            File.WriteAllText(Path.Combine(directory, "editor-answer.json"), JsonSerializer.Serialize(new
            {
                nonce,
                ok = true
            }));
        }
        catch (JsonException) { } // A non-atomic test writer may still be writing.
        catch (IOException) { }
        catch (Exception error)
        {
            File.WriteAllText(Path.Combine(directory, "editor-answer.json"), JsonSerializer.Serialize(new
            {
                nonce,
                ok = false,
                error = error.Message
            }));
        }
        finally { commandRunning = false; }
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
            timer.Dispose();
        base.Dispose(disposing);
    }

    [STAThread]
    private static void Main(string[] args)
    {
        Application.SetHighDpiMode(HighDpiMode.PerMonitorV2);
        Application.EnableVisualStyles();
        string directory = args.Length == 1 ? args[0] : Path.Combine(Environment.CurrentDirectory, "test-results", "windows-editor");
        Application.Run(new TestEditor(directory));
    }
}
