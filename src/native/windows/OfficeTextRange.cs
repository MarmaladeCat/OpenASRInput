namespace OpenASRInput;

// Fallback for PowerPoint providers without UIA text ranges. Every operation is
// scoped to the DocumentWindow obtained from the focused pane, never ActiveWindow.
internal static class OfficeTextRange
{
    internal static string LastStatus = "";

    private readonly record struct Owner(int View, int Slide, int Shape);

    private static Owner? Identity(dynamic window, dynamic frame)
    {
        // Office can return a new COM proxy for the SAME TextFrame on every
        // getter. Managed proxy equality is not a stable owner key.
        // IDs are scoped to this HWND-bound DocumentWindow and its current view.
        // Providers without a stable shape/slide owner (some table/group ranges)
        // remain unsupported by this fallback, rather than weakening isolation.
        // Keep the original nativeWindow throughout; its optional HWND getter
        // is absent in some Office builds. The caller validates the bound HWND.
        int view = (int)window.ViewType;
        dynamic shape = frame.Parent;
        int id = (int)shape.Id, slide = (int)shape.Parent.SlideID;
        if (view <= 0 || id <= 0 || slide <= 0 || (int)window.View.Slide.SlideID != slide)
            return null;
        return new Owner(view, slide, id);
    }

    // Text is already normalized to Office paragraph separators by the caller.
    internal static string Replace(object nativeWindow, string text, Func<bool> current,
        Func<string>? collapse = null)
    {
        bool writing = false;
        string stage = "native-range";
        LastStatus = stage;
        try
        {
            dynamic window = nativeWindow;
            if (!current() || (int)window.Selection.Type != 3)
                return "stale";
            dynamic range = window.Selection.TextRange;
            dynamic frame = range.Parent;
            if (frame == null)
                return "unsupported"; // Some table-cell providers have no parent.
            Owner? owner = Identity(window, frame);
            if (owner == null)
                return "unsupported";
            dynamic document = frame.TextRange;
            string before = (string)document.Text;
            int start = (int)range.Start - 1, length = (int)range.Length;
            if (before.Length > 65536 || start < 0 || start > before.Length || length < 0 ||
                length > before.Length - start || before.Substring(start, length) != (string)range.Text)
                return "unsupported";
            string expected = before[..start] + text + before[(start + length)..];
            dynamic latest = window.Selection.TextRange;
            if (!current() || (int)window.Selection.Type != 3 ||
                Identity(window, latest.Parent) != owner || (int)latest.Start != start + 1 ||
                (int)latest.Length != length || (string)document.Text != before || !current())
                return "stale";
            writing = true;
            LastStatus = stage = "native-range-write";
            range.Text = text; // Only the selected range/caret, never the TextFrame.
            // Retained ranges can keep their old length after a setter. Read a
            // fresh owning range for confirmation and for the new caret.
            if (!current() || (string)frame.TextRange.Text != expected || !current())
                return "unknown";
            LastStatus = stage = "native-range-collapse";
            int end = start + text.Length + 1;
            // Some Office setters already collapse the selection. Selecting
            // it again through COM can rebuild the UIA element/runtime identity.
            // Verify the existing caret before asking Office to move anything.
            dynamic existing = window.Selection.TextRange;
            if ((int)window.Selection.Type == 3 && Identity(window, existing.Parent) == owner &&
                (int)existing.Start == end && (int)existing.Length == 0 && current())
            {
                LastStatus = "native-range-confirmed";
                return "accepted";
            }
            string collapsed = collapse?.Invoke() ?? "unsupported";
            if (collapsed == "unsupported")
            {
                dynamic insertionPoint = frame.TextRange.Characters(end, 0);
                if (!current())
                    return "unknown";
                LastStatus = stage = "native-range-select";
                insertionPoint.Select();
            }
            else if (collapsed != "accepted")
                return "unknown"; // Never retry an ambiguous selection operation.
            dynamic caret = window.Selection.TextRange;
            if (!current() || (int)window.Selection.Type != 3 ||
                Identity(window, caret.Parent) != owner || (int)caret.Start != end || (int)caret.Length != 0 || !current())
                return "unknown";
            LastStatus = "native-range-confirmed";
            return "accepted";
        }
        catch (Exception error)
        {
            LastStatus = stage + ":" + error.GetType().Name + ":" + error.HResult;
            return writing ? "unknown" : "unsupported";
        }
    }
}
