using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using Tomlyn;
using Tomlyn.Model;

static class HookConfig {
    const string Begin = "# BEGIN codex-win-notify-windows";
    const string End = "# END codex-win-notify-windows";
    static readonly JsonSerializerOptions Json = new() { Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping };
    static string Quote(string s) => JsonSerializer.Serialize(s, Json);
    static readonly (string Event, string Name, string? Matcher)[] Events = [
        ("SessionStart", "session_start", "^(startup|resume|clear|compact)$"),
        ("PreToolUse", "pre_tool_use", "(^|.*[._])request_user_input$"),
        ("PermissionRequest", "permission_request", ".*"),
        ("PostCompact", "post_compact", "^(manual|auto)$"), ("Stop", "stop", null)
    ];

    internal static string Remove(string text) {
        // Match complete marker lines only, retaining all bytes outside our block.
        var start = text.IndexOf(Begin, StringComparison.Ordinal);
        if(start < 0) {
            if(text.Contains(End)) throw new InvalidDataException("Orphan configuration marker");
            return text;
        }
        var end = text.IndexOf(End, start, StringComparison.Ordinal);
        if(end < 0 || (start > 0 && text[start-1] != '\n') || text.IndexOf(Begin, start+Begin.Length, StringComparison.Ordinal) >= 0)
            throw new InvalidDataException("Incomplete or duplicated configuration block");
        var tail = end + End.Length;
        if(tail < text.Length && text[tail] == '\r') tail++;
        if(tail < text.Length && text[tail] == '\n') tail++;
        return text[..start] + text[tail..];
    }

    internal static string Install(string old, string configPath, string executable) {
        var basis = Remove(old);
        if(basis.Contains("# BEGIN codex-win-notify\n") || basis.Contains("# BEGIN codex-win-notify\r\n"))
            throw new InvalidDataException("WSL and Windows must use separate CODEX_HOME directories");
        var model = Toml.ToModel(basis);
        var hooks = model.TryGetValue("hooks", out var h) ? (TomlTable)h : new TomlTable();
        // cmd /C quoting differs between Codex releases. Keep its entire command
        // quote-free; PowerShell only transports stdio, all hook logic stays in C#.
        var shell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), @"WindowsPowerShell\v1.0\powershell.exe");
        if(shell.Any(c => char.IsWhiteSpace(c) || "&|<>^%!\"".Contains(c)))
            throw new InvalidDataException("Unsupported Windows system directory");
        var script = "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; $p=New-Object System.Diagnostics.Process; " +
            "$p.StartInfo.FileName='" + executable.Replace("'", "''") + "'; " +
            "$p.StartInfo.Arguments='--hook'; $p.StartInfo.UseShellExecute=$false; " +
            "$p.StartInfo.RedirectStandardInput=$true; $p.StartInfo.RedirectStandardOutput=$true; " +
            "$p.StartInfo.StandardOutputEncoding=[Text.Encoding]::UTF8; " +
            "[Console]::InputEncoding=[Text.Encoding]::UTF8; [Console]::OutputEncoding=[Text.Encoding]::UTF8; " +
            "$null=$p.Start(); $b=[Text.Encoding]::UTF8.GetBytes([Console]::In.ReadToEnd()); $p.StandardInput.BaseStream.Write($b,0,$b.Length); $p.StandardInput.BaseStream.Close(); " +
            "[Console]::Out.Write($p.StandardOutput.ReadToEnd()); $p.WaitForExit(); $p.Dispose()";
        var command = shell + " -NoProfile -NonInteractive -EncodedCommand " + Convert.ToBase64String(Encoding.Unicode.GetBytes(script));
        var lines = new StringBuilder(Begin + "\n");
        foreach(var (ev, name, matcher) in Events) {
            // Sorted dictionaries reproduce Codex's canonical JSON trust hash.
            var handler = new SortedDictionary<string, object>(StringComparer.Ordinal) {
                // PowerShell + .NET startup alone can approach two seconds on Windows.
                // This is a ceiling, not a delay; notification delivery stays detached.
                ["async"] = false, ["command"] = ":", ["command_windows"] = command, ["timeout"] = 10, ["type"] = "command"
            };
            // Codex hashes the platform-resolved command, not command_windows.
            var effective = new SortedDictionary<string, object>(handler, StringComparer.Ordinal);
            effective.Remove("command_windows"); effective["command"] = command;
            var identity = new SortedDictionary<string, object>(StringComparer.Ordinal) { ["event_name"] = name, ["hooks"] = new[] { effective } };
            if(matcher != null) identity["matcher"] = matcher;
            var index = hooks.TryGetValue(ev, out var groups) ? ((TomlTableArray)groups).Count : 0;
            var key = $"{Path.GetFullPath(configPath)}:{name}:{index}:0";
            if(hooks.TryGetValue("state", out var state) && ((TomlTable)state).ContainsKey(key))
                throw new InvalidDataException("Hook trust key already owned by another configuration");
            lines.AppendLine($"[[hooks.{ev}]]");
            if(matcher != null) lines.AppendLine("matcher=" + Quote(matcher));
            lines.AppendLine($"[[hooks.{ev}.hooks]]");
            foreach(var pair in handler) lines.AppendLine(pair.Key + "=" + JsonSerializer.Serialize(pair.Value, Json));
            lines.AppendLine("[hooks.state." + Quote(key) + "]");
            lines.AppendLine("trusted_hash=" + Quote("sha256:" + HookBridge.Hash(JsonSerializer.Serialize(identity, Json))));
        }
        lines.AppendLine(End);
        var result = basis + (basis.Length == 0 || basis.EndsWith('\n') ? "" : "\n") + lines;
        Toml.ToModel(result); // Reject invalid TOML before touching the user's file.
        return result;
    }

    internal static void Update(string action, string home) {
        var path = Path.Combine(Path.GetFullPath(home), "config.toml");
        var old = File.Exists(path) ? File.ReadAllText(path) : "";
        var result = action switch {
            "install" => Install(old, path, Path.Combine(AppContext.BaseDirectory, "CodexWinNotify.exe")),
            "check" => Install(old, path, Path.Combine(AppContext.BaseDirectory, "CodexWinNotify.exe")),
            "uninstall" => Remove(old), _ => throw new ArgumentException("action")
        };
        if(action == "check" || result == old) return;
        Toml.ToModel(result);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var backup = Path.Combine(home, "codex-win-notify.windows.config.backup");
        if(File.Exists(path) && !File.Exists(backup)) File.Copy(path, backup);
        var temp = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try { File.WriteAllText(temp, result, new UTF8Encoding(false)); File.Move(temp, path, true); }
        finally { if(File.Exists(temp)) File.Delete(temp); }
    }
}
