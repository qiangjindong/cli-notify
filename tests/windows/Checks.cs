using System.Text.Json;
using Microsoft.Data.Sqlite;

static class Checks {
    static int count;
    static void Check(bool value, string message) { if(!value) throw new Exception(message); count++; }
    static void Main() {
        var home = Path.Combine(Path.GetTempPath(), "cwn-tests-" + Guid.NewGuid());
        Directory.CreateDirectory(home);
        try {
            var raw = """{"hook_event_name":"Stop","session_id":"s","turn_id":"t","cwd":"C:\\中文 空格","last_assistant_message":"PRIVATE","tool_input":{"command":"PRIVATE"}}""";
            var work = HookBridge.Parse(raw)!;
            Check(work.Kind == "complete" && work.Event.Cwd == "中文 空格", "mapping/cwd");
            Check(!JsonSerializer.Serialize(work).Contains("PRIVATE"), "privacy");
            Check(work.Event.Key == HookBridge.Parse(raw)!.Event.Key, "completion dedup");
            Check(HookBridge.Parse(raw.Replace("Stop", "PermissionRequest"))!.Event.Key != HookBridge.Parse(raw.Replace("Stop", "PermissionRequest"))!.Event.Key, "repeat approval");
            Check(HookBridge.Parse(raw.Replace("Stop", "PreToolUse")) == null, "tool filter");
            Check(HookBridge.Parse("{}") == null, "missing session");
            Check(HookBridge.UserThreadName(home, "user") is null, "missing db suppresses");
            Check(!File.Exists(Path.Combine(home,"state_5.sqlite")), "read only db");
            using(var db = new SqliteConnection($"Data Source={Path.Combine(home,"state_5.sqlite")};Pooling=False")) {
                db.Open(); using var cmd = db.CreateCommand();
                cmd.CommandText = "CREATE TABLE threads (id TEXT, thread_source TEXT, name TEXT); INSERT INTO threads VALUES ('user','user','补充 PDF 预览并验收'),('empty','user',''),('internal','subagent','内部');";
                cmd.ExecuteNonQuery();
            }
            Check(HookBridge.UserThreadName(home, "user") == "补充 PDF 预览并验收", "named user thread");
            Check(HookBridge.UserThreadName(home, "empty") == "", "empty user thread name");
            Check(HookBridge.UserThreadName(home, "internal") is null && HookBridge.UserThreadName(home, "missing") is null, "internal/unknown suppresses");
            Check(HookBridge.UserThreadName(home, "' OR 1=1 --") is null, "parameterized SQL");
            var rollout = Path.Combine(home, "rollout.jsonl");
            using(var db = new SqliteConnection($"Data Source={Path.Combine(home,"state_5.sqlite")};Pooling=False")) {
                db.Open(); using var cmd = db.CreateCommand();
                cmd.CommandText = "ALTER TABLE threads ADD COLUMN rollout_path TEXT; UPDATE threads SET rollout_path = $path";
                cmd.Parameters.AddWithValue("$path", rollout); cmd.ExecuteNonQuery();
            }
            string Lifecycle(string kind, string turn = "t") => JsonSerializer.Serialize(new { type = "event_msg", payload = new { type = kind, turn_id = turn } }) + "\n";
            var done = Lifecycle("task_complete");
            Check(work.Turn == "t", "worker preserves turn identity");
            Check(HookBridge.TurnState(home, "user", "t") == CompletionState.Retry, "missing rollout retries");
            foreach(var (text, expected) in new[] {
                ("", CompletionState.Retry),
                (Lifecycle("task_complete", "previous"), CompletionState.Retry),
                (Lifecycle("task_started"), CompletionState.Retry), (done, CompletionState.Ready),
                (done + Lifecycle("task_started", "next"), CompletionState.Stop),
                (Lifecycle("task_started") + Lifecycle("task_started", "next"), CompletionState.Stop),
                (done + Lifecycle("task_complete", "next"), CompletionState.Stop),
                (done + Lifecycle("task_started"), CompletionState.Stop),
                (Lifecycle("turn_aborted"), CompletionState.Stop), (done + "{partial", CompletionState.Retry),
                (done + Lifecycle("task_started", ""), CompletionState.Retry),
                (new string('x', 300000) + "\n" + done, CompletionState.Ready)
            }) {
                File.WriteAllText(rollout, text);
                Check(HookBridge.TurnState(home, "user", "t") == expected, "settled lifecycle check");
            }
            Check(HookBridge.TurnState(home, "user", "") == CompletionState.Stop, "missing turn suppresses");
            foreach(var (states, expected) in new[] {
                (new[] { CompletionState.Ready }, true),
                (new[] { CompletionState.Retry, CompletionState.Ready }, true),
                (new[] { CompletionState.Retry, CompletionState.Retry, CompletionState.Ready }, true),
                (new[] { CompletionState.Stop }, false),
                (new[] { CompletionState.Retry, CompletionState.Stop }, false),
                (new[] { CompletionState.Retry, CompletionState.Retry, CompletionState.Retry }, false)
            }) {
                int checks = 0, waits = 0;
                Check(HookBridge.CompletionReady(() => {
                    Check(waits == checks + 1, "wait before each check");
                    return states[checks++];
                }, ms => { Check(ms == 1000, "one second interval"); waits++; }) == expected, "polling result");
                Check(checks == states.Length && waits == checks, "no extra attempts");
            }
            File.Delete(rollout);
            int recoveryWaits = 0;
            Check(HookBridge.CompletionReady(() => HookBridge.CheckCompletion(home, "user", "t"), ms => {
                if(++recoveryWaits == 2) File.WriteAllText(rollout, done);
            }), "missing file recovers");
            Check(recoveryWaits == 2, "recovery not delayed to third attempt");
            Check(HookBridge.GoalState(home, "user") == CompletionState.Ready, "no goals DB preserves completion");
            var goalsPath = Path.Combine(home, "goals_1.sqlite");
            Check(!File.Exists(goalsPath), "goal check does not create DB");
            using(var db = new SqliteConnection($"Data Source={goalsPath};Pooling=False")) {
                db.Open(); using var cmd = db.CreateCommand();
                cmd.CommandText = "CREATE TABLE thread_goals (thread_id TEXT PRIMARY KEY, status TEXT);";
                cmd.ExecuteNonQuery();
                Check(HookBridge.GoalState(home, "user") == CompletionState.Ready, "no goal preserves completion");
                foreach(var status in new[] { "active", "paused", "blocked", "usage_limited", "budget_limited", "unknown", "complete" }) {
                    cmd.CommandText = "INSERT OR REPLACE INTO thread_goals VALUES ('user', $status)";
                    cmd.Parameters.Clear(); cmd.Parameters.AddWithValue("$status", status); cmd.ExecuteNonQuery();
                    var expected = status == "complete" ? CompletionState.Ready : CompletionState.Stop;
                    Check(HookBridge.GoalState(home, "user") == expected, "goal status " + status);
                    Check(HookBridge.CheckCompletion(home, "user", "t") == expected, "combined goal status " + status);
                    Check(HookBridge.GoalState(home, "other") == CompletionState.Ready, "goals are scoped to thread");
                }
                cmd.CommandText = "DROP TABLE thread_goals"; cmd.ExecuteNonQuery();
                Check(HookBridge.GoalState(home, "user") == CompletionState.Retry, "unknown schema retries");
                Check(HookBridge.CheckCompletion(home, "user", "t") == CompletionState.Retry, "goal failure prevents ready");
                File.WriteAllText(rollout, Lifecycle("turn_aborted"));
                Check(HookBridge.CheckCompletion(home, "user", "t") == CompletionState.Stop, "abort wins over goal read failure");
            }
            Check(System.Reflection.CustomAttributeExtensions.GetCustomAttribute<System.Reflection.AssemblyTitleAttribute>(typeof(Program).Assembly)?.Title == "CLI Notify", "shared notification display name");
            var window = new Window(1, 1, 1, "project-folder");
            Check(Program.NotificationTitle(new Event("a", "complete", ThreadName:"补充 PDF 预览并验收"), window) == "补充 PDF 预览并验收", "thread name title");
            Check(Program.NotificationTitle(new Event("a", "complete"), window) == "project-folder", "cwd title fallback");
            Check(Program.NotificationStatus("complete") == "Codex 已完成"
                && Program.NotificationStatus("question") == "Codex 需要回答"
                && Program.NotificationStatus("approval") == "Codex 等待命令审批"
                && Program.NotificationStatus("compact") == "Codex 上下文已压缩"
                && Program.NotificationStatus("test") == "Codex 通知正常，点击可返回此终端", "status bodies");
            var piJson = """{"Id":"0123456789abcdef0123456789abcdef","Kind":"complete","Key":"abcdef0123456789abcdef0123456789","Cwd":"中文项目","ThreadName":"Pi 会话","Hwnd":123,"Pid":456,"Started":789,"Client":"Other","prompt":"PRIVATE"}""";
            var piEvent = PiBridge.Parse(piJson);
            Check(piEvent.Client == "Pi" && piEvent.Hwnd == 0 && piEvent.Pid == 0 && piEvent.Started == 0, "pi captures identity locally");
            Check(piEvent.ThreadName == "Pi 会话" && piEvent.Cwd == "中文项目" && !JsonSerializer.Serialize(piEvent).Contains("PRIVATE"), "pi metadata only");
            Check(Program.NotificationStatus("complete", "Pi") == "Pi 已完成"
                && Program.NotificationStatus("question", "Pi") == "Pi 需要回答"
                && Program.NotificationStatus("compact", "Pi") == "Pi 上下文已压缩"
                && Program.NotificationStatus("error", "Pi") == "Pi 运行出错"
                && Program.NotificationStatus("test", "Pi") == "Pi 通知正常，点击可返回此终端", "pi status bodies");
            Check(JsonSerializer.Deserialize<Event>("""{"Id":"a","Kind":"complete"}""")!.Client == "Codex", "old clients default to Codex");
            var piSent = new List<Event>();
            PiBridge.Dispatch(piEvent, e => e with { Hwnd = 42, Pid = 43, Started = 44 }, piSent.Add);
            Check(piSent.Count == 2 && piSent[0].Kind == "register" && piSent[1].Kind == "complete"
                && piSent.All(e => e.Hwnd == 42 && e.Pid == 43 && e.Started == 44 && e.Client == "Pi"), "pi captures then registers then sends");
            piSent.Clear();
            PiBridge.Dispatch(piEvent with { Kind = "register" }, e => e, piSent.Add);
            Check(piSent.Count == 1 && piSent[0].Kind == "register", "pi registration has no toast");
            piSent.Clear();
            try { PiBridge.Dispatch(piEvent, e => throw new IOException(), piSent.Add); } catch(IOException) { }
            Check(piSent.Count == 0, "pi capture failure sends nothing");
            try { PiBridge.Dispatch(piEvent, e => e, e => { piSent.Add(e); throw new IOException(); }); } catch(IOException) { }
            Check(piSent.Count == 1 && piSent[0].Kind == "register", "pi registration failure prevents stale notification");
            foreach(var invalid in new[] { "null", "{}", piJson.Replace("complete", "focus"), piJson.Replace("complete", "forget"), piJson.Replace("0123456789abcdef0123456789abcdef", "bad"), new string('x', 16385) }) {
                bool failed = false; try { PiBridge.Parse(invalid); } catch { failed = true; }
                Check(failed, "reject invalid pi event");
            }
            var old = "# existing\nnotify=['keep']\n[[hooks.Stop]]\n[[hooks.Stop.hooks]]\ntype='command'\ncommand='keep'\n";
            var config = Path.Combine(home, "config.toml");
            var first = HookConfig.Install(old, config, @"C:\中文 空格 & test\CliNotify.exe");
            Check(HookConfig.Install(first, config, @"C:\中文 空格 & test\CliNotify.exe") == first, "idempotent");
            Check(HookConfig.Remove(first) == old, "preserve config");
            foreach(var invalid in new[] { "# BEGIN cli-notify-windows\n", "# END cli-notify-windows\n", "invalid = [", "# BEGIN cli-notify\n", "# BEGIN codex-win-notify\n" }) {
                bool failed = false; try { HookConfig.Install(invalid, config, @"C:\test.exe"); } catch { failed = true; }
                Check(failed, "reject invalid/shared configuration");
            }
            // Upgrading over a pre-rename install must replace the old block, not stack a second one.
            var legacyFirst = HookConfig.Install("# BEGIN codex-win-notify-windows\n[[hooks.Stop]]\n# END codex-win-notify-windows\n", config, @"C:\test.exe");
            Check(!legacyFirst.Contains("codex-win-notify") && legacyFirst.Contains("# BEGIN cli-notify-windows"), "replace legacy block in place");
            Check(HookConfig.Remove(legacyFirst) == "", "remove upgraded block");
            Console.WriteLine($"Passed {count} Windows bridge/config checks.");
        } finally { Directory.Delete(home, true); }
    }
}
