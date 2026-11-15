using OpenASRInput;

// Native object-model contract doubles, not real Office acceptance. These run
// the actual fallback with no UIA assembly, clipboard, keyboard or desktop.
public sealed class OfficeWindow
{
    public OfficeSelection Selection { get; } = new();
    public int ViewType { get; set; } = 9;
    public OfficeView View { get; } = new();
}
public sealed class OfficeView { public OfficeSlide Slide { get; } = new(); }
public sealed class OfficeSlide { public int SlideID { get; set; } = 256; }
public sealed class OfficeShape
{
    public int Id { get; set; } = 2;
    public OfficeSlide Parent { get; } = new();
}
public sealed class OfficeFrameProxy
{
    private readonly OfficeFrame frame;
    public OfficeFrameProxy(OfficeFrame frame) => this.frame = frame;
    public OfficeRange TextRange => frame.TextRange;
    public OfficeShape Parent => frame.Parent;
}
public sealed class OfficeSelection
{
    public int Type { get; set; } = 3;
    public OfficeRange TextRange { get; set; } = null!;
}
public sealed class OfficeFrame
{
    public string Content = "";
    public int Writes, Reads, Collapses;
    public Action<int>? OnRead;
    public Action? OnCharacters;
    public bool ThrowAfterWrite, IgnoreWrite, IgnoreCollapse, MissingParent, CollapseOnWrite;
    public OfficeWindow Window = new();
    public OfficeShape Parent { get; } = new();
    public OfficeRange TextRange => new(this, 1, Content.Length);
    public void Select(int start, int length) => Window.Selection.TextRange = new(this, start, length);
}
public sealed class OfficeRange
{
    private readonly OfficeFrame frame;
    public OfficeFrameProxy? Parent => frame.MissingParent ? null : new(frame);
    public int Start { get; }
    public int Length { get; private set; }
    public OfficeRange(OfficeFrame frame, int start, int length)
    {
        this.frame = frame;
        Start = start;
        Length = length;
    }
    public string Text
    {
        get
        {
            string snapshot = frame.Content.Substring(Start - 1, Length);
            frame.OnRead?.Invoke(++frame.Reads);
            return snapshot;
        }
        set
        {
            frame.Writes++;
            if (frame.IgnoreWrite)
                return;
            frame.Content = frame.Content[..(Start - 1)] + value + frame.Content[(Start - 1 + Length)..];
            Length = value.Length;
            if (frame.CollapseOnWrite)
                frame.Select(Start + value.Length, 0);
            if (frame.ThrowAfterWrite)
                throw new InvalidOperationException("Ambiguous COM completion");
        }
    }
    public OfficeRange Characters(int start, int length)
    {
        frame.OnCharacters?.Invoke();
        return new(frame, start, length);
    }
    public void Select()
    {
        frame.Collapses++;
        if (!frame.IgnoreCollapse)
            frame.Window.Selection.TextRange = this;
    }
}

internal static class OfficeRangeTests
{
    private static void Check(bool value, string message)
    {
        if (!value)
            throw new Exception(message + ": " + OfficeTextRange.LastStatus);
    }
    internal static void Run()
    {
        var frame = new OfficeFrame { Content = "前缀旧文字后缀" };
        frame.Select(3, 3);
        Check(OfficeTextRange.Replace(frame.Window, "新🙂\r第二行", () => true) == "accepted",
            "native range can replace a selection without UIA");
        Check(frame.Content == "前缀新🙂\r第二行后缀", "only selected text is replaced, preserving UTF-16 and paragraphs");
        Check(OfficeTextRange.Replace(frame.Window, "追加", () => true) == "accepted" &&
            frame.Content == "前缀新🙂\r第二行追加后缀", "consecutive finals append at the collapsed end");
        frame = new OfficeFrame();
        frame.Select(1, 0);
        Check(OfficeTextRange.Replace(frame.Window, "空框🙂", () => true) == "accepted" && frame.Content == "空框🙂",
            "empty PowerPoint range receives Unicode text");
        frame.Select(1, frame.Content.Length);
        Check(OfficeTextRange.Replace(frame.Window, "", () => true) == "accepted" && frame.Content == "",
            "selection deletion is confirmed without replay");
        frame = new OfficeFrame { Content = "unchanged" };
        frame.Select(1, 0);
        frame.Window.Selection.Type = 2;
        Check(OfficeTextRange.Replace(frame.Window, "blocked", () => true) == "stale" && frame.Writes == 0,
            "shape-only selection must never receive text");
        frame.Window.Selection.Type = 3;
        int checks = 0;
        Check(OfficeTextRange.Replace(frame.Window, "blocked", () => ++checks < 2) == "stale" && frame.Writes == 0,
            "focus loss before the setter performs no write");
        frame.MissingParent = true;
        Check(OfficeTextRange.Replace(frame.Window, "blocked", () => true) == "unsupported" && frame.Writes == 0,
            "unverifiable table-cell parent cannot trigger a blind write");
        foreach (bool changeSlide in new[] { false, true })
        {
            frame = new OfficeFrame { Content = "same text" };
            frame.Select(2, 0);
            var other = new OfficeFrame { Content = frame.Content, Window = frame.Window };
            if (changeSlide)
                other.Parent.Parent.SlideID++;
            else
                other.Parent.Id++;
            frame.OnRead = reads => { if (reads == 2) other.Select(2, 0); };
            Check(OfficeTextRange.Replace(frame.Window, "blocked", () => true) == "stale" && frame.Writes == 0 && other.Writes == 0,
                "equal text and offsets in another owner cannot authorize a write");
        }
        frame = new OfficeFrame { Content = "same text" };
        frame.Select(2, 0);
        frame.Parent.Id = 0;
        Check(OfficeTextRange.Replace(frame.Window, "blocked", () => true) == "unsupported" && frame.Writes == 0,
            "missing stable shape identity prevents a fallback write");
        frame = new OfficeFrame { Content = "前后", CollapseOnWrite = true };
        frame.Select(2, 0);
        frame.OnCharacters = () => throw new Exception("Already collapsed caret must not be selected again");
        Check(OfficeTextRange.Replace(frame.Window, "中🙂", () => true) == "accepted" && frame.Collapses == 0,
            "Office setter's verified collapsed caret preserves its UIA identity");
        foreach (bool ambiguous in new[] { false, true })
        {
            frame = new OfficeFrame { Content = "前后" };
            frame.Select(2, 0);
            frame.OnCharacters = () => throw new Exception("Optional selection must not replay through native Select");
            int selections = 0;
            string result = OfficeTextRange.Replace(frame.Window, "中🙂", () => true, () =>
            {
                selections++;
                frame.Select(5, 0);
                return ambiguous ? "unknown" : "accepted";
            });
            Check(result == (ambiguous ? "unknown" : "accepted") && selections == 1 && frame.Collapses == 0,
                "independent selection provider is confirmed once; ambiguous collapse never replays");
        }
        for (int fault = 0; fault < 3; fault++)
        {
            frame = new OfficeFrame
            {
                Content = "前后", ThrowAfterWrite = fault == 0,
                IgnoreWrite = fault == 1, IgnoreCollapse = fault == 2
            };
            frame.Select(2, 0);
            Check(OfficeTextRange.Replace(frame.Window, "中🙂", () => true) == "unknown" && frame.Writes == 1,
                "setter/caret ambiguity is unknown and never automatically retried");
        }
        for (int stage = 0; stage < 3; stage++)
        {
            frame = new OfficeFrame { Content = "前后" };
            frame.Select(2, 0);
            bool focused = true;
            // COM getters may deliver a queued focus change after the caller's
            // last guard: during revalidation, confirmation, or caret lookup.
            if (stage < 2)
            {
                int loseAt = stage == 0 ? 3 : 4;
                frame.OnRead = reads => { if (reads == loseAt) focused = false; };
            }
            else
                frame.OnCharacters = () => focused = false;
            string outcome = OfficeTextRange.Replace(frame.Window, "中🙂", () => focused);
            Check(outcome == (stage == 0 ? "stale" : "unknown") && frame.Writes == (stage == 0 ? 0 : 1) &&
                frame.Collapses == 0, "provider-triggered focus loss prevents the next write/selection at stage " + stage);
        }
        Console.WriteLine("PASS Office native range contract: Unicode, paragraphs, empty caret, replacement, continuation, reentrant focus guards and ambiguous writes");
    }
}
