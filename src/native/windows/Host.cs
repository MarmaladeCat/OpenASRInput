using System.Globalization;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Windows.Automation;
using System.Windows.Automation.Text;
using Forms = System.Windows.Forms;

namespace OpenASRInput;

internal sealed class Host : Forms.Form
{
    private readonly Overlay panel = new();
    private readonly Forms.NotifyIcon tray;
    private readonly Forms.Timer timer = new() { Interval = 60 };
    private readonly Forms.Timer noticeTimer = new() { Interval = 8000 };
    private readonly Dictionary<string, (string Lease, string Text, string Ack)> commits = new();
    private sealed record PendingText(string Lease, string Text, string Normalized,
        int Offset, InsertionCheckpoint Checkpoint);
    private readonly Dictionary<string, PendingText> pending = new();
    private ScreenBuffer screenBuffer = new();
    private int confirmedCharacters, abandonedPreviewCharacters;
    private string screenMode = "ready";
    private readonly AutomationFocusChangedEventHandler focusHandler;
    private Target? target;
    private Target? observed;
    private long observedAt;
    private bool observedGeometry;
    private string lease = "";
    private TextPatternRange? selectedRange;
    private string selectedText = "";
    private ulong generation, revision;
    private bool shiftSpace, altX;
    private bool resourcesDisposed;
    private readonly SessionKeys sessionKeys = new();
    private readonly Native.KeyboardHook keyboardCallback;
    private readonly nint keyboardHook;
    private int focusEpoch;
    private string lastLoss = "", lastValidationFailure = "", lastFocusEvent = "";
    private int lastFocusEventProcess;
    private string lastCommitResult = "";
    private int lastCommitCharacters;
    private Target? lostTarget, lostObserved;
    private static readonly UTF8Encoding Utf8 = new(false, true);
    // UIA counts UTF-16 units; the shared Python/Linux limit counts Unicode
    // characters. Allow surrogate pairs without accepting an oversized selection.
    private const int SelectionCharacters = 16000;
    private const int SelectionUnits = SelectionCharacters * 2 + 1;

    internal Host()
    {
        ShowInTaskbar = false;
        Text = "OpenASRInput 语音输入";
        CreateHandle();
        shiftSpace = Native.RegisterHotKey(Handle, 1, 0x4000 | 4, 0x20);
        altX = Native.RegisterHotKey(Handle, 2, 0x4000 | 1, 0x58);
        keyboardCallback = KeyboardEvent;
        keyboardHook = Native.SetWindowsHookExW(13, keyboardCallback, Native.GetModuleHandleW(null), 0);
        var menu = new Forms.ContextMenuStrip();
        menu.Items.Add("设置", null, (_, _) => Program.Send("0\tEVENT\tsettings"));
        menu.Items.Add("取消本轮语音", null, (_, _) => { Clear(); Program.Send("0\tEVENT\tcancel"); });
        menu.Items.Add("退出", null, (_, _) => Program.Send("0\tEVENT\tquit"));
        tray = new Forms.NotifyIcon
        {
            Icon = Branding.LoadIcon(),
            Visible = true,
            Text = "OpenASRInput · Shift+Space / Alt+X",
            ContextMenuStrip = menu
        };
        tray.DoubleClick += (_, _) => Program.Send("0\tEVENT\tsettings");
        focusHandler = (sender, _) =>
        {
            try
            {
                string identity = sender is AutomationElement element ? string.Join(".", element.GetRuntimeId()) : "";
                int eventProcess = sender is AutomationElement source ? source.Current.ProcessId : 0;
                int epoch = Volatile.Read(ref focusEpoch);
                BeginInvoke(() =>
                {
                    lastFocusEvent = identity;
                    lastFocusEventProcess = eventProcess;
                    // WinForms reports UIA focus when our non-activating overlay
                    // becomes visible, even while native keyboard focus stays in
                    // the external editor. Native foreground/focus polling still
                    // revokes the lease if one of our windows really takes focus.
                    if (epoch == focusEpoch && eventProcess != Environment.ProcessId && target != null && target.Identity != identity)
                    {
                        // Chromium may emit its containing document's focus
                        // event after the editable descendant already has focus.
                        // A genuine sibling/foreign focus event still revokes
                        // the lease, including a rapid leave-and-return.
                        var bound = target;
                        bool ancestor = Valid(true) && bound.FocusAncestor(identity);
                        if (epoch == focusEpoch && ReferenceEquals(bound, target) && !ancestor)
                            Lost("focus-event");
                    }
                });
            }
            catch { /* The next foreground/target poll revalidates it. */ }
        };
        Automation.AddAutomationFocusChangedEventHandler(focusHandler);
        timer.Tick += (_, _) =>
        {
            var bound = target;
            // UIA may pump an Escape callback that has already cleared this lease.
            if (bound != null && !Valid(true) && ReferenceEquals(bound, target))
                Lost(lastValidationFailure);
        };
        timer.Start();
        noticeTimer.Tick += (_, _) => { noticeTimer.Stop(); panel.Hide(); };
        Program.Send("0\tHELLO\tOpenASRInput.Bridge\t1");
    }
    protected override void SetVisibleCore(bool value) => base.SetVisibleCore(false);
    private nint KeyboardEvent(int code, nint message, nint data)
    {
        if (code >= 0 && (message == 0x100 || message == 0x104 || message == 0x101 || message == 0x105))
        {
            var key = Marshal.PtrToStructure<Native.HookKey>(data);
            bool down = message == 0x100 || message == 0x104;
            // Injection flags do not identify application-generated text: remote
            // desktops/remappers also set them on the user's Enter/Esc. Unicode
            // text packets have a different virtual key and are never consumed.
            var bound = target;
            // UIA identity validation stays in the focus observer/timer. Calling
            // it here can process the release reentrantly before the down, or
            // exceed Windows' low-level hook timeout and leak the Enter press.
            bool eligible = down && (key.Key == 0x0d || key.Key == 0x1b) &&
                bound != null && bound.Same(observed) && bound.NativeFocusCurrent() &&
                !Native.ModifiersHeld() && !Native.Composing(bound.Focus);
            var decision = sessionKeys.Handle((int)key.Key, down, eligible);
            if (decision.Action != null)
            {
                if (decision.Action == "cancel")
                    Clear(deferRollback: true); // Keep UIA outside the low-level keyboard hook.
                Program.Send("0\tEVENT\t" + decision.Action);
            }
            if (decision.Consume)
                return 1;
        }
        return Native.CallNextHookEx(keyboardHook, code, message, data);
    }
    protected override void WndProc(ref Forms.Message message)
    {
        if (message.Msg == 0x0010) // Installer/Restart Manager requests shutdown.
        {
            Program.Send("0\tEVENT\tquit");
            return; // Python closes sessions/capture, then closes this bridge.
        }
        if (message.Msg == 0x0312)
        {
            Program.Send(message.WParam == 2 ? "0\tEVENT\tcommand" : "0\tEVENT\ttoggle");
            return;
        }
        base.WndProc(ref message);
    }
    private Target? Observe(bool fresh = false, bool geometry = true)
    {
        if (fresh || (geometry && !observedGeometry) || Environment.TickCount64 - observedAt >= 60)
        {
            observed = Target.Read(geometry);
            observedAt = Environment.TickCount64;
            observedGeometry = geometry;
        }
        return observed;
    }
    private bool Valid(bool fresh = false)
    {
        var bound = target;
        // Per-character authorization must not recalculate layout/selection
        // rectangles. SHOW explicitly requests fresh geometry when needed.
        var latest = bound == null ? null : Observe(fresh, geometry: false);
        lastValidationFailure = bound == null || !ReferenceEquals(bound, target) ? "no-target" :
            Native.GetForegroundWindow() != bound.Window ? "foreground-window" :
            !bound.Same(latest) ? "focused-control" : "";
        return lastValidationFailure.Length == 0;
    }
    private void Lost(string reason)
    {
        lastLoss = reason;
        lostTarget = target;
        lostObserved = observed;
        Clear();
        Program.Send("0\tEVENT\tcontext-lost");
    }
    private void Clear(bool deferRollback = false)
    {
        var oldTarget = target;
        var oldBuffer = screenBuffer;
        if (oldBuffer.FinalId.Length != 0)
            commits[oldBuffer.FinalId] = (lease, oldBuffer.FinalText, "stale");
        screenBuffer = new();
        target = null; // Revoke first, including reentrant key/focus callbacks.
        if (oldTarget != null && oldBuffer.Active)
        {
            void Rollback()
            {
                if (oldBuffer.Cancel(oldTarget, oldTarget.InsertionFocusCurrent) != "accepted")
                    abandonedPreviewCharacters += oldBuffer.Text.Length;
            }
            if (deferRollback)
                BeginInvoke(Rollback);
            else
                Rollback();
        }
        foreach (var item in pending)
            commits[item.Key] = (item.Value.Lease, item.Value.Text, "stale");
        pending.Clear();
        Interlocked.Increment(ref focusEpoch);
        target = null;
        selectedRange = null;
        selectedText = "";
        lease = "";
        revision = 0;
        panel.Hide();
    }
    private static string Decode(string value) => Utf8.GetString(Convert.FromHexString(value));
    internal string Request(string line)
    {
        string[] f = line.Split('\t');
        string id = f.Length > 0 ? f[0] : "0";
        try
        {
            if (line.Length > 1024 * 1024 || f.Length < 2)
                throw new ArgumentException();
            string result;
            switch (f[1])
            {
                case "HOTKEYS":
                    result = (shiftSpace ? "shift-space" : "") + "," + (altX ? "alt-x" : "");
                    break;
                case "PANEL_BACKEND":
                    result = "windows";
                    break;
                case "CONTEXT_STATUS":
                    object? Describe(Target? value) => value == null ? null : new
                    {
                        window = value.Window.ToInt64(),
                        focus = value.Focus.ToInt64(),
                        process = value.Process,
                        identity = value.Identity
                    };
                    result = JsonSerializer.Serialize(new
                    {
                        backend = "windows",
                        process = Environment.ProcessId,
                        active = target != null,
                        lastLoss,
                        lastFocusEvent,
                        lastFocusEventProcess,
                        commitCount = commits.Count,
                        pendingCommitCount = pending.Count,
                        panelBufferCharacters = screenBuffer.PanelText.Length,
                        screenBufferCharacters = screenBuffer.Text.Length,
                        confirmedCharacters,
                        abandonedPreviewCharacters,
                        screenMode,
                        screenFailure = screenBuffer.LastFailure,
                        officeStatus = OfficeInsertion.LastStatus,
                        lastCommitResult,
                        lastCommitCharacters,
                        lastInsertionMethod = TextInsertion.LastMethod,
                        lastInsertionVerification = TextInsertion.LastVerification,
                        panelVisible = panel.Visible,
                        panelBounds = new
                        {
                            x = panel.Left,
                            y = panel.Top,
                            width = panel.Width,
                            height = panel.Height
                        },
                        panelAnchor = new
                        {
                            x = panel.CaretAnchor.Left,
                            y = panel.CaretAnchor.Top,
                            width = panel.CaretAnchor.Width,
                            height = panel.CaretAnchor.Height
                        },
                        panelCaretKnown = panel.CaretKnown,
                        foreground = Native.GetForegroundWindow().ToInt64(),
                        target = Describe(target),
                        observed = Describe(observed),
                        lostTarget = Describe(lostTarget),
                        lostObserved = Describe(lostObserved)
                    });
                    break;
                case "KEYBOARD_PREEDIT":
                    result = "accepted";
                    break;
                case "THEME":
                    if (f.Length != 8 && f.Length != 10)
                        throw new ArgumentException();
                    double scale = double.Parse(f[3], CultureInfo.InvariantCulture);
                    int width = int.Parse(f[4]), size = int.Parse(f[5]), radius = int.Parse(f[6]);
                    var colors = f[7].Split(',').Select(rgb => int.Parse(rgb, NumberStyles.HexNumber)).ToArray();
                    if (!double.IsFinite(scale) || scale < .8 || scale > 1.5 || width < 480 || width > 960 ||
                        size < 12 || size > 22 || radius < 8 || radius > 24 || colors.Length != 11 ||
                        colors.Any(rgb => rgb < 0 || rgb > 0xffffff))
                        throw new ArgumentException();
                    panel.UserScale = scale;
                    string position = f.Length == 10 ? f[8] : "cursor";
                    int transparency = f.Length == 10 ? int.Parse(f[9]) : 0;
                    if (!new[] { "cursor", "hidden", "top", "bottom", "top-left", "top-right", "bottom-left", "bottom-right" }.Contains(position)
                        || transparency < 0 || transparency > 100)
                        throw new ArgumentException();
                    panel.PanelPosition = position;
                    panel.Transparency = transparency;
                    panel.LogicalWidth = width;
                    panel.TextSize = size;
                    panel.Radius = radius;
                    panel.Colors = colors;
                    panel.Reconfigure();
                    result = "accepted";
                    break;
                case "BEGIN":
                    noticeTimer.Stop();
                    if (keyboardHook == 0)
                    {
                        panel.Present(null, "无法启用 Enter / Esc 操作，请重启语音输入。", "", "needs-config");
                        noticeTimer.Start();
                        result = "unavailable";
                        break;
                    }
                    var next = Observe(true);
                    if (next == null || Native.Composing(next.Focus))
                    {
                        panel.Present(null, "请聚焦可编辑输入框，并结束当前输入法候选。", "", "needs-config");
                        noticeTimer.Start();
                        result = "unavailable";
                        break;
                    }
                    Clear();
                    target = next;
                    confirmedCharacters = abandonedPreviewCharacters = 0;
                    screenMode = "ready";
                    selectedRange = null;
                    selectedText = "";
                    Interlocked.Increment(ref focusEpoch);
                    lease = (++generation).ToString();
                    revision = 0;
                    result = lease;
                    break;
                case "SELECTION":
                    result = "unsupported";
                    if (f.Length == 3 && f[2] == lease && Valid(true))
                    {
                        var element = AutomationElement.FocusedElement;
                        if (element != null && element.TryGetCurrentPattern(TextPattern.Pattern, out var pattern))
                        {
                            var ranges = ((TextPattern)pattern).GetSelection();
                            if (ranges.Length == 1)
                            {
                                var value = ranges[0].GetText(SelectionUnits);
                                if (value.EnumerateRunes().Count() <= SelectionCharacters)
                                {
                                    selectedText = value;
                                    selectedRange = value.Length == 0 ? null : ranges[0].Clone();
                                    result = Convert.ToHexString(Utf8.GetBytes(value));
                                }
                            }
                            else if (ranges.Length == 0)
                                result = "";
                        }
                    }
                    break;
                case "VALID":
                    // An explicit lease check must not report a cached control
                    // after focus has moved inside the same foreground window.
                    result = f.Length == 3 && f[2] == lease && Valid(true) ? "true" : "false";
                    break;
                case "SHOW":
                    if (f.Length != 7)
                        throw new ArgumentException();
                    if (f[2] != lease || !Valid())
                    {
                        result = "stale";
                        break;
                    }
                    ulong incoming = ulong.Parse(f[3]);
                    if (incoming > revision)
                    {
                        revision = incoming;
                        string preview = Decode(f[4]), state = Decode(f[6]);
                        bool dictation = state is "connecting" or "listening" or "pausing";
                        string displayed = preview;
                        if (dictation && screenBuffer.FinalId.Length == 0 && pending.Count == 0 &&
                            !Native.ModifiersHeld() && !Native.Composing(target!.Focus))
                        {
                            var previewTarget = target!;
                            string shown = screenBuffer.Update(previewTarget, preview,
                                () => previewTarget.Same(target) && previewTarget.InsertionFocusCurrent());
                            screenMode = shown == "unsupported" ? "panel-only" : "owned-range";
                            if (shown is "unknown" or "stale")
                            {
                                result = shown;
                                break;
                            }
                            if (shown != "unsupported")
                                displayed = screenBuffer.PanelText;
                        }
                        else if (screenBuffer.FinalId.Length != 0)
                            displayed = screenBuffer.PanelText;
                        panel.BufferStatus = dictation
                            ? $"待上屏 {displayed.Length} · 待确认 {screenBuffer.Text.Length} · 已确认 {confirmedCharacters}"
                            : "";
                        panel.Present(Observe(), displayed, Decode(f[5]), state);
                    }
                    result = "accepted";
                    break;
                case "COMMIT":
                    if (f.Length != 5 || f[3].Length == 0)
                        throw new ArgumentException();
                    string text = Decode(f[4]);
                    TextInsertion.Validate(text);
                    if (commits.TryGetValue(f[3], out var prior))
                    {
                        result = prior.Lease == f[2] && prior.Text == text ? prior.Ack : "failed";
                        break;
                    }
                    pending.TryGetValue(f[3], out var progress);
                    if (progress != null && (progress.Lease != f[2] || progress.Text != text))
                    {
                        result = "failed";
                        break;
                    }
                    if (f[2] != lease || !Valid())
                    {
                        result = "stale";
                        break;
                    }
                    if (progress == null && pending.Count != 0)
                    {
                        result = "deferred"; // Preserve ordering across final utterances.
                        break;
                    }
                    if (Native.ModifiersHeld() || Native.Composing(target!.Focus))
                    {
                        result = "deferred";
                        break;
                    }
                    // Revalidate immediately before committing to the target.
                    if (!Valid(true))
                    {
                        result = "stale";
                        break;
                    }
                    if (screenBuffer.Active || screenBuffer.FinalId.Length != 0)
                    {
                        var screenTarget = target!;
                        result = screenBuffer.Finish(screenTarget, f[3], text,
                            () => screenTarget.Same(target) && screenTarget.InsertionFocusCurrent());
                        if (result != "deferred")
                            commits[f[3]] = (f[2], text, result);
                        if (result == "accepted")
                            confirmedCharacters += text.Length;
                        lastCommitResult = result;
                        lastCommitCharacters = text.Length;
                        break;
                    }
                    if (progress == null && selectedRange != null)
                    {
                        var element = AutomationElement.FocusedElement;
                        var pattern = element?.GetCurrentPattern(TextPattern.Pattern) as TextPattern;
                        var ranges = pattern?.GetSelection();
                        if (ranges?.Length != 1 || ranges[0].GetText(SelectionUnits) != selectedText ||
                            ranges[0].CompareEndpoints(TextPatternRangeEndpoint.Start, selectedRange, TextPatternRangeEndpoint.Start) != 0 ||
                            ranges[0].CompareEndpoints(TextPatternRangeEndpoint.End, selectedRange, TextPatternRangeEndpoint.End) != 0)
                        {
                            result = "stale";
                            break;
                        }
                    }
                    var destination = target!;
                    bool nativeEdit = TextInsertion.NativeEdit(destination) || OfficeInsertion.Supports(destination);
                    string normalized = progress?.Normalized ?? TextInsertion.Normalize(text);
                    int offset = progress?.Offset ?? 0;
                    int length = nativeEdit ? normalized.Length : Math.Min(16, normalized.Length - offset);
                    if (!nativeEdit && offset + length < normalized.Length && length > 0 &&
                        char.IsHighSurrogate(normalized[offset + length - 1]))
                        length--;
                    bool more = offset + length < normalized.Length;
                    if (progress != null && !progress.Checkpoint.Matches(InsertionCheckpoint.Read(destination)))
                    {
                        pending.Remove(f[3]);
                        commits[f[3]] = (f[2], text, "stale");
                        result = "stale";
                        break;
                    }
                    // Do not start a multi-batch write without a reliable resume
                    // boundary. Standard Edit/RichEdit remain one native insert.
                    if (progress == null && more && InsertionCheckpoint.Read(destination) == null)
                    {
                        result = "failed";
                        break;
                    }
                    string batch = nativeEdit ? text : normalized.Substring(offset, length);
                    result = TextInsertion.Commit(destination, batch,
                        () => destination.Same(target) && destination.InsertionFocusCurrent());
                    if (result == "accepted" && !Valid(true))
                        result = "unknown";
                    if (result == "accepted" && more)
                    {
                        var checkpoint = InsertionCheckpoint.Read(destination);
                        if (checkpoint != null)
                        {
                            pending[f[3]] = new(f[2], text, normalized, offset + length, checkpoint);
                            result = "deferred";
                        }
                        else
                            result = "unknown";
                    }
                    lastCommitResult = result;
                    lastCommitCharacters = text.Length;
                    if (result == "accepted")
                        confirmedCharacters += text.Length;
                    if (result != "deferred")
                    {
                        pending.Remove(f[3]);
                        commits[f[3]] = (f[2], text, result); // Never replay an ambiguous batch.
                    }
                    if (result == "unknown")
                        panel.Present(Observe() ?? target, "暂无法确认文字是否已输入，请检查输入框。结果不会自动重复提交。", "", "needs-config");
                    break;
                case "CLEAR":
                    if (f.Length != 3)
                        throw new ArgumentException();
                    if (f[2] == lease)
                        Clear();
                    result = "accepted";
                    break;
                case "NOTICE":
                    if (f.Length != 4)
                        throw new ArgumentException();
                    if (f[2] != lease || !Valid())
                    {
                        result = "stale";
                        break;
                    }
                    var old = Observe() ?? target;
                    Clear();
                    panel.Present(old, Decode(f[3]), "", "needs-config");
                    noticeTimer.Start();
                    result = "accepted";
                    break;
                default:
                    throw new ArgumentException();
            }
            return id + "\tOK\t" + result;
        }
        catch { return id + "\tERROR\tinvalid-request"; }
    }
    protected override void Dispose(bool disposing)
    {
        if (disposing && !resourcesDisposed)
        {
            resourcesDisposed = true;
            timer.Stop();
            Clear();
            timer.Dispose();
            noticeTimer.Dispose();
            Automation.RemoveAutomationFocusChangedEventHandler(focusHandler);
            Native.UnregisterHotKey(Handle, 1);
            Native.UnregisterHotKey(Handle, 2);
            if (keyboardHook != 0)
                Native.UnhookWindowsHookEx(keyboardHook);
            tray.Visible = false;
            tray.ContextMenuStrip?.Dispose();
            tray.Icon?.Dispose();
            tray.Dispose();
            panel.Dispose();
        }
        base.Dispose(disposing);
    }
}
