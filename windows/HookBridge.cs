using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.Data.Sqlite;

// This record is the entire worker payload. Never forward raw hook input.
record HookWork(string Session, string Kind, Event Event, string Home);

static class HookBridge {
    internal static string Hash(string value) => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(value)));
    internal static string Home => Path.GetFullPath(Environment.GetEnvironmentVariable("CODEX_HOME")
        ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".codex"));

    internal static HookWork? Parse(string input) {
        using var doc = JsonDocument.Parse(input);
        var root = doc.RootElement;
        string Get(string key) => root.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString()! : "";
        var name = Get("hook_event_name");
        var kind = name switch {
            "SessionStart" => "register", "PreToolUse" => "question", "PermissionRequest" => "approval",
            "PostCompact" => "compact", "Stop" => "complete", _ => ""
        };
        if(kind.Length == 0 || Get("session_id").Length == 0) return null;
        if(kind == "question" && !Get("tool_name").EndsWith("request_user_input", StringComparison.Ordinal)) return null;
        var session = Get("session_id");
        var key = Hash(JsonSerializer.Serialize(new[] { session, Get("turn_id"), Get("tool_use_id"), Get("tool_call_id"),
            kind is "approval" or "compact" ? Guid.NewGuid().ToString("N") : "" }));
        var cwd = Path.GetFileName(Path.TrimEndingDirectorySeparator(Get("cwd")));
        return new(session, kind, new Event(Hash(session)[..32], kind, cwd, key), Home);
    }

    internal static void Run() {
        // Hooks fail open, including malformed input or unavailable desktop/SQLite.
        try {
            Console.InputEncoding = new UTF8Encoding(false);
            Console.OutputEncoding = new UTF8Encoding(false);
            var input = Console.In.ReadToEnd().TrimStart('\uFEFF');
            using(var doc = JsonDocument.Parse(input)) {
                if(doc.RootElement.TryGetProperty("hook_event_name", out var name) && name.GetString() == "Stop") {
                    Console.WriteLine("{}"); Console.Out.Flush();
                }
            }
            var work = Parse(input);
            if(work is null) return;
            work = work with { Event = Program.CaptureWindow(work.Event) };
            var start = new ProcessStartInfo(Environment.ProcessPath!) {
                UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true
            };
            start.ArgumentList.Add("--hook-worker");
            using var worker = Process.Start(start)!;
            worker.StandardInput.Write(JsonSerializer.Serialize(work));
            worker.StandardInput.Close();
        } catch(Exception ex) { Program.Log("", "hook", ex.GetType().Name); }
    }

    internal static bool IsUser(string home, string session) {
        try {
            using var db = new SqliteConnection(new SqliteConnectionStringBuilder {
                DataSource = Path.Combine(home, "state_5.sqlite"), Mode = SqliteOpenMode.ReadOnly, Pooling = false, DefaultTimeout = 1
            }.ToString());
            db.Open();
            using var query = db.CreateCommand();
            query.CommandText = "SELECT thread_source FROM threads WHERE id = $id";
            query.Parameters.AddWithValue("$id", session);
            return query.ExecuteScalar() is string source && source == "user";
        } catch(Exception ex) { Program.Log("", "hook-origin", ex.GetType().Name); return false; }
    }

    internal static void Dispatch() {
        Console.InputEncoding = new UTF8Encoding(false);
        var work = JsonSerializer.Deserialize<HookWork>(Console.In.ReadToEnd())!;
        if(work.Kind != "register" && !IsUser(work.Home, work.Session)) {
            Program.Log(work.Event.Id, work.Kind, "internal-or-unknown-suppressed"); return;
        }
        // Re-register every event; failed capture/registration must never use stale state.
        Program.Send(work.Event with { Kind = "register" });
        if(work.Kind != "register") Program.Send(work.Event);
    }
}
