namespace OpenASRInput;

// Only unmodified Enter/Esc in the bound voice target are consumed. Remote
// desktops and keyboard remappers can mark genuine user keys as injected.
// Keep the matching release consumed even after Esc clears the session.
internal sealed class SessionKeys
{
    private readonly HashSet<int> held = new(), consumed = new();

    internal (bool Consume, string? Action) Handle(int key, bool down, bool eligible)
    {
        if (key != 0x0d && key != 0x1b)
            return (false, null);
        if (!down)
        {
            held.Remove(key);
            return (consumed.Remove(key), null);
        }
        bool first = held.Add(key);
        if (consumed.Contains(key))
            return (true, null);
        if (!first || !eligible)
            return (false, null);
        consumed.Add(key);
        return (true, key == 0x1b ? "cancel" : "pause");
    }
}
