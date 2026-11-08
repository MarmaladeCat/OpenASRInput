namespace OpenASRInput;

// Fallback for PowerPoint providers without UIA text ranges. Every operation is
// scoped to the DocumentWindow obtained from the focused pane, never ActiveWindow.
internal static class OfficeTextRange
{
    internal static string LastStatus = "";

    // Text is already normalized to Office paragraph separators by the caller.
    internal static string Replace(object nativeWindow, string text, Func<bool> current)
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
            dynamic document = frame.TextRange;
            string before = (string)document.Text;
            int start = (int)range.Start - 1, length = (int)range.Length;
            if (before.Length > 65536 || start < 0 || start > before.Length || length < 0 ||
                length > before.Length - start || before.Substring(start, length) != (string)range.Text)
                return "unsupported";
            string expected = before[..start] + text + before[(start + length)..];
            dynamic latest = window.Selection.TextRange;
            if (!current() || (int)window.Selection.Type != 3 ||
                !Equals((object)latest.Parent, (object)frame) || (int)latest.Start != start + 1 ||
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
            dynamic insertionPoint = frame.TextRange.Characters(end, 0);
            if (!current())
                return "unknown";
            insertionPoint.Select();
            dynamic caret = window.Selection.TextRange;
            if (!current() || (int)window.Selection.Type != 3 ||
                !Equals((object)caret.Parent, (object)frame) || (int)caret.Start != end || (int)caret.Length != 0 || !current())
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
