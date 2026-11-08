using OpenASRInput;

// Execute the real verification/continuation code with independently failing
// provider capabilities. No keyboard injection or actual application data.
internal static class InsertionEvidenceTests
{
    private static int cases;
    private static void Check(bool condition, string message)
    {
        if (!condition)
            throw new Exception(message);
    }
    private static Target Begin()
    {
        Scene.Reset();
        Scene.Start = Scene.End = 1;
        cases++;
        return Target.Read(false) ?? throw new Exception("Expected initial editable target");
    }
    internal static void Run()
    {
        foreach (string failure in new[] { "value-pattern", "value-read", "count", "selection" })
        {
            var target = Begin();
            Scene.HasValue = true;
            Scene.ThrowValue = failure == "value-pattern";
            Scene.ThrowValueRead = failure == "value-read";
            Scene.ThrowCount = failure == "count";
            Scene.ThrowSelection = failure == "selection";
            // Suppress value evidence so counting/selection failures really
            // exercise the remaining bounded document-text capability.
            if (failure is "count" or "selection")
                Scene.HasValue = false;
            var evidence = InsertionEvidence.Read(target);
            Check(evidence.Available, "An optional " + failure + " failure must not hide text evidence");
            Scene.Document = "a中文🙂bc";
            Check(evidence.Confirm("中文🙂") == "text-change-confirmed", "Independent text confirmation: " + failure);
        }
        {
            var target = Begin();
            Scene.HasValue = true;
            Scene.ThrowText = true;
            var evidence = InsertionEvidence.Read(target);
            Scene.Document = "a新bc";
            Check(evidence.Available && evidence.Confirm("新") == "value-change-confirmed",
                "A value-only editor remains usable when TextPattern throws");
        }
        {
            var target = Begin();
            Scene.HasValue = true;
            var evidence = InsertionEvidence.Read(target);
            Scene.ThrowValueRead = true; // Provider can fail after the actual write too.
            Scene.Document = "a新bc";
            Check(evidence.Confirm("新") == "text-change-confirmed",
                "A failed post-write value getter must not mask valid text confirmation");
        }
        {
            var target = Begin();
            Scene.HasValue = true;
            Scene.ThrowTextRead = true;
            var evidence = InsertionEvidence.Read(target);
            Scene.Document = "a新bc";
            Check(evidence.Confirm("新") == "value-change-confirmed", "Broken text reads preserve value confirmation");
        }
        {
            var target = Begin();
            Scene.Document = "前缀旧文字后缀";
            Scene.Start = 2;
            Scene.End = 5;
            Scene.ThrowCount = true;
            var evidence = InsertionEvidence.Read(target);
            Scene.Document = "前缀新🙂\r\n第二行后缀";
            Check(evidence.Confirm("新🙂\n第二行") == "text-change-confirmed",
                "Unicode replacement and paragraph normalization do not require character counting");
        }
        {
            var target = Begin();
            var evidence = InsertionEvidence.Read(target);
            Check(evidence.Confirm("a") == null, "An existing matching suffix is not proof of a write");
            Scene.Document = "zbc";
            Check(evidence.Confirm("新") == null, "An unrelated document change is not confirmation");
        }
        {
            var target = Begin();
            Scene.HasValue = true;
            var evidence = InsertionEvidence.Read(target);
            Scene.ThrowValueRead = Scene.ThrowTextRead = Scene.ThrowSelection = true;
            Check(evidence.Confirm("新") == null, "Losing every confirmation channel must not report success");
            Scene.ThrowTextRead = false;
            Scene.Document = "a新bc";
            Check(evidence.Confirm("新") == "text-change-confirmed",
                "Read-only confirmation can recover from a transient provider failure without another write");
        }
        foreach (bool large in new[] { false, true })
        {
            var target = Begin();
            Scene.HasValue = true;
            Scene.ThrowCount = true;
            if (large)
                Scene.Document = new string('x', 65537);
            else
                Scene.ThrowValueRead = Scene.ThrowTextRead = true;
            Check(!InsertionEvidence.Read(target).Available,
                "Unavailable or oversized snapshots without a count baseline cannot authorize blind insertion");
        }
        {
            var target = Begin();
            Scene.Document = new string('x', 65537);
            Scene.Start = Scene.End = Scene.Document.Length;
            var evidence = InsertionEvidence.Read(target);
            Scene.Document += "🙂e\u0301";
            Scene.Start = Scene.End = Scene.Document.Length;
            Check(evidence.Available && evidence.Confirm("🙂e\u0301") == "caret-text-confirmed",
                "Large documents retain count-plus-caret evidence without storing a large snapshot");
        }
        foreach (bool throughValue in new[] { false, true })
        {
            var target = Begin();
            Action move = () => Scene.Foreground = 9;
            if (throughValue)
            {
                Scene.HasValue = true;
                Scene.OnValueRead = move;
            }
            else
                Scene.OnTextRead = move;
            Check(!InsertionEvidence.Read(target).Available,
                "Snapshots read across a provider-triggered focus change must be discarded");
        }
        {
            var target = Begin();
            Scene.OnIdentity = () => Scene.Foreground = 9;
            Check(!target.InsertionFocusCurrent(), "Recheck native focus AFTER the UIA identity query");
        }
        foreach (string protection in new[] { "disabled", "password", "keyboard-focus" })
        {
            var target = Begin();
            Scene.Disabled = protection == "disabled";
            Scene.Password = protection == "password";
            Scene.KeyboardFocus = protection != "keyboard-focus";
            Check(!target.InsertionFocusCurrent(), "Revalidate changed target state: " + protection);
        }
        {
            var target = Begin();
            Check(InsertionCheckpoint.Read(target) != null, "A stable text/caret supplies continuation evidence");
            Scene.OnTextRead = () => Scene.Foreground = 9;
            Check(InsertionCheckpoint.Read(target) == null, "Do not retain a continuation checkpoint across focus loss");
        }
        Console.WriteLine($"PASS {cases} insertion capability/focus cases: independent provider faults, bounded evidence, Unicode, non-replay confirmation and reentrant focus");
    }
}
