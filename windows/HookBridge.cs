using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.Data.Sqlite;

// This record is the entire worker payload. Never forward raw hook input.
record HookWork(string Session, string Kind, Event Event, string Home, string Turn = "");

enum CompletionState { Ready, Stop, Retry }

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
        return new(session, kind, new Event(Hash(session)[..32], kind, cwd, key), Home, Get("turn_id"));
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

    internal static string? UserThreadName(string home, string session) {
        try {
            using var db = new SqliteConnection(new SqliteConnectionStringBuilder {
                DataSource = Path.Combine(home, "state_5.sqlite"), Mode = SqliteOpenMode.ReadOnly, Pooling = false, DefaultTimeout = 1
            }.ToString());
            db.Open();
            using var query = db.CreateCommand();
            query.CommandText = "SELECT thread_source, name FROM threads WHERE id = $id";
            query.Parameters.AddWithValue("$id", session);
            using var row = query.ExecuteReader();
            if(!row.Read() || row.GetString(0) != "user") return null;
            return row.IsDBNull(1) ? "" : row.GetString(1);
        } catch(Exception ex) { Program.Log("", "hook-origin", ex.GetType().Name); return null; }
    }

    // Stop is a completion candidate, not proof that the goal has finished.
    internal static CompletionState GoalState(string home, string session) {
        var path = Path.Combine(home, "goals_1.sqlite");
        if(!File.Exists(path)) return CompletionState.Ready; // Older Codex versions have no goals DB.
        try {
            using var db = new SqliteConnection(new SqliteConnectionStringBuilder {
                DataSource = path, Mode = SqliteOpenMode.ReadOnly, Pooling = false, DefaultTimeout = 1
            }.ToString());
            db.Open();
            using var query = db.CreateCommand();
            query.CommandText = "SELECT status FROM thread_goals WHERE thread_id = $id";
            query.Parameters.AddWithValue("$id", session);
            var status = query.ExecuteScalar();
            return status is null || status is string value && value == "complete" ? CompletionState.Ready : CompletionState.Stop;
        } catch(Exception ex) { Program.Log("", "completion-goal", ex.GetType().Name); return CompletionState.Retry; }
    }

    internal static CompletionState TurnState(string home, string session, string turn) {
        if(string.IsNullOrEmpty(turn)) return CompletionState.Stop;
        try {
            using var db = new SqliteConnection(new SqliteConnectionStringBuilder {
                DataSource = Path.Combine(home, "state_5.sqlite"), Mode = SqliteOpenMode.ReadOnly,
                Pooling = false, DefaultTimeout = 1
            }.ToString());
            db.Open();
            using var query = db.CreateCommand();
            query.CommandText = "SELECT rollout_path FROM threads WHERE id = $id";
            query.Parameters.AddWithValue("$id", session);
            if(query.ExecuteScalar() is not string path) return CompletionState.Retry;
            using var file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            var start = Math.Max(0, file.Length - 262144);
            file.Seek(start, SeekOrigin.Begin);
            using var reader = new StreamReader(file, Encoding.UTF8);
            if(start > 0) reader.ReadLine(); // Discard a possibly partial first record.
            var state = CompletionState.Retry;
            bool seenTurn = false;
            while(reader.ReadLine() is { } line) {
                using var doc = JsonDocument.Parse(line);
                var root = doc.RootElement;
                if(!root.TryGetProperty("type", out var type) || type.GetString() != "event_msg") continue;
                var payload = root.GetProperty("payload");
                if(!payload.TryGetProperty("type", out var eventType)) continue;
                var name = eventType.GetString();
                if(name is not ("task_started" or "task_complete" or "turn_aborted")) continue;
                if(!payload.TryGetProperty("turn_id", out var id) || id.ValueKind != JsonValueKind.String || string.IsNullOrEmpty(id.GetString())) {
                    state = CompletionState.Retry;
                    continue;
                }
                if(id.GetString() != turn) {
                    if(seenTurn) return CompletionState.Stop;
                    continue; // An older turn alone cannot prove continuation.
                }
                seenTurn = true;
                if(name == "turn_aborted" || (name == "task_started" && state == CompletionState.Ready))
                    return CompletionState.Stop;
                state = name == "task_complete" ? CompletionState.Ready : CompletionState.Retry;
            }
            return state;
        } catch(Exception ex) { Program.Log("", "completion-settled", ex.GetType().Name); return CompletionState.Retry; }
    }

    internal static CompletionState CheckCompletion(string home, string session, string turn) {
        var goal = GoalState(home, session);
        if(goal == CompletionState.Stop) return CompletionState.Stop;
        var state = TurnState(home, session, turn);
        if(state == CompletionState.Stop) return CompletionState.Stop;
        return goal == CompletionState.Ready && state == CompletionState.Ready ? CompletionState.Ready : CompletionState.Retry;
    }

    internal static bool CompletionReady(Func<CompletionState> check, Action<int>? sleep = null) {
        sleep ??= Thread.Sleep;
        // Three attempts, not consecutive successes. I/O adds to the wait time.
        for(int attempt = 0; attempt < 3; attempt++) {
            sleep(1000);
            var state = check();
            if(state == CompletionState.Ready) return true;
            if(state == CompletionState.Stop) return false;
        }
        return false;
    }

    internal static void Dispatch() {
        Console.InputEncoding = new UTF8Encoding(false);
        var work = JsonSerializer.Deserialize<HookWork>(Console.In.ReadToEnd())!;
        if(work.Kind != "register") {
            var threadName = UserThreadName(work.Home, work.Session);
            if(threadName is null) {
                Program.Log(work.Event.Id, work.Kind, "internal-or-unknown-suppressed"); return;
            }
            work = work with { Event = work.Event with { ThreadName = threadName } };
        }
        if(work.Kind == "complete") {
            // Wait only in the detached worker, never in the hook itself.
            if(!CompletionReady(() => CheckCompletion(work.Home, work.Session, work.Turn))) {
                Program.Log(work.Event.Id, work.Kind, "not-settled-or-goal-incomplete-suppressed"); return;
            }
        }
        // Re-register every event; failed capture/registration must never use stale state.
        Program.Send(work.Event with { Kind = "register" });
        if(work.Kind != "register") Program.Send(work.Event);
    }
}
