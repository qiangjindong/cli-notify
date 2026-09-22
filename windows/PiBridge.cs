using System.Text;
using System.Text.Json;

// Pi uses its own lifecycle and session metadata; never query the Codex database.
static class PiBridge {
    internal static Event Parse(string input) {
        if(input.Length > 16384) throw new ArgumentException("pi-payload-too-large");
        var e = JsonSerializer.Deserialize<Event>(input) ?? throw new ArgumentException("pi-event");
        if(!Guid.TryParseExact(e.Id, "N", out _) || !Guid.TryParseExact(e.Key, "N", out _))
            throw new ArgumentException("pi-id");
        if(e.Kind is not ("register" or "complete" or "question" or "compact" or "error" or "test"))
            throw new ArgumentException("pi-kind");
        // Only metadata crosses the bridge. Window identity must come from this
        // process's console, never from caller-supplied HWNDs or the foreground.
        return new Event(e.Id, e.Kind, (e.Cwd ?? "")[..Math.Min(e.Cwd?.Length ?? 0, 256)], e.Key,
            (e.ThreadName ?? "")[..Math.Min(e.ThreadName?.Length ?? 0, 256)], Client: "Pi");
    }

    internal static void Run() {
        Console.InputEncoding = new UTF8Encoding(false);
        Dispatch(Parse(Console.In.ReadToEnd()), Program.CaptureWindow, Program.Send);
    }

    internal static void Dispatch(Event e, Func<Event, Event> capture, Action<Event> send) {
        e = capture(e);
        // One invocation captures, registers, then sends; any failure prevents
        // the notification from falling back to an old window registration.
        send(e with { Kind = "register" });
        if(e.Kind != "register") send(e);
    }
}
