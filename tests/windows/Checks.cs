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
            var window = new Window(1, 1, 1, "project-folder");
            Check(Program.NotificationTitle(new Event("a", "complete", ThreadName:"补充 PDF 预览并验收"), window) == "补充 PDF 预览并验收", "thread name title");
            Check(Program.NotificationTitle(new Event("a", "complete"), window) == "project-folder", "cwd title fallback");
            Check(Program.NotificationStatus("complete") == "Codex 已完成"
                && Program.NotificationStatus("question") == "Codex 需要回答"
                && Program.NotificationStatus("approval") == "Codex 等待命令审批"
                && Program.NotificationStatus("compact") == "Codex 上下文已压缩", "status bodies");
            var old = "# existing\nnotify=['keep']\n[[hooks.Stop]]\n[[hooks.Stop.hooks]]\ntype='command'\ncommand='keep'\n";
            var config = Path.Combine(home, "config.toml");
            var first = HookConfig.Install(old, config, @"C:\中文 空格 & test\CodexWinNotify.exe");
            Check(HookConfig.Install(first, config, @"C:\中文 空格 & test\CodexWinNotify.exe") == first, "idempotent");
            Check(HookConfig.Remove(first) == old, "preserve config");
            foreach(var invalid in new[] {"# BEGIN codex-win-notify-windows\n", "# END codex-win-notify-windows\n", "invalid = [", "# BEGIN codex-win-notify\n"}) {
                bool failed = false; try { HookConfig.Install(invalid, config, @"C:\test.exe"); } catch { failed = true; }
                Check(failed, "reject invalid/shared configuration");
            }
            Console.WriteLine($"Passed {count} Windows bridge/config checks.");
        } finally { Directory.Delete(home, true); }
    }
}
