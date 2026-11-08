using System.Windows.Automation.Peers;
using System.Windows.Automation.Provider;

// A real disposable WPF editor with deliberately broken OPTIONAL UIA providers.
// It keeps normal keyboard/TextPattern behavior so the external bridge exercises
// its actual HWND character path, not a mocked insertion function.
internal sealed class ProviderEditor : System.Windows.Controls.TextBox
{
    private int changes, faultAt;
    internal string Fault { get; private set; } = "none";
    internal ProviderEditor()
    {
        FontSize = 18;
        AcceptsReturn = true;
        TextChanged += (_, _) => changes++;
    }
    internal void SetFault(string fault)
    {
        if (fault is not "none" and not "value-read" and not "value-after-change" and not "no-evidence")
            throw new ArgumentException("Unknown test provider fault");
        Fault = fault;
        faultAt = changes;
    }
    protected override AutomationPeer OnCreateAutomationPeer() => new ProviderPeer(this);

    private sealed class ProviderPeer : TextBoxAutomationPeer, IValueProvider
    {
        private readonly ProviderEditor editor;
        internal ProviderPeer(ProviderEditor owner) : base(owner) => editor = owner;
        public override object GetPattern(PatternInterface pattern)
        {
            if (pattern == PatternInterface.Value)
                return this;
            if (pattern == PatternInterface.Text && editor.Fault == "no-evidence")
                return null!;
            return base.GetPattern(pattern);
        }
        bool IValueProvider.IsReadOnly => editor.IsReadOnly;
        string IValueProvider.Value => editor.Fault is "value-read" or "no-evidence" ||
            (editor.Fault == "value-after-change" && editor.changes > editor.faultAt)
            ? throw new InvalidOperationException("Disposable fixture Value getter failure") : editor.Text;
        void IValueProvider.SetValue(string value) =>
            throw new InvalidOperationException("Whole-field replacement is not an insertion API");
    }
}
