using System.Diagnostics;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using Microsoft.Toolkit.Uwp.Notifications;

record Event(string Id, string Kind, string Cwd = "", string Key = "", string ThreadName = "", long Hwnd = 0, int Pid = 0, long Started = 0, string Client = "Codex");
record Window(long Hwnd, int Pid, long Started, string Cwd);
static class Program {
    static readonly string Root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "CliNotify");
    static readonly string Pipe = "CliNotify-" + Environment.UserName;
    static readonly object Gate = new();
    static readonly Dictionary<string, Window> Windows = new();
    static readonly HashSet<string> Seen = new();
    internal static void Log(string id, string kind, string result) {
        try { lock(Gate) File.AppendAllText(Path.Combine(Root, "helper.log"), JsonSerializer.Serialize(new { at=DateTime.UtcNow, id, kind, result }) + "\n"); }
        catch { /* Logging must never change hook/tool behavior. */ }
    }
    [STAThread] static void Main(string[] args) {
        try {
            Directory.CreateDirectory(Root);
            if(args.Contains("--pi-send")) { PiBridge.Run(); return; }
            if(args.Contains("--hook")) { HookBridge.Run(); return; }
            if(args.Contains("--hook-worker")) { HookBridge.Dispatch(); return; }
            if(args.Length == 3 && args[0] == "--configure") { HookConfig.Update(args[1], args[2]); return; }
            if(args.Contains("--test")) {
                var id = Guid.NewGuid().ToString("N");
                var cwd = new DirectoryInfo(Environment.CurrentDirectory).Name;
                var registration = CaptureWindow(new Event(id, "register", cwd));
                Send(registration);
                Send(registration with { Kind="test", ThreadName="Codex Windows 通知测试" });
                return;
            }
            if (args.Contains("--send")) {
                // WSL writes JSON as UTF-8; do not decode it with the Windows
                // console code page or non-ASCII thread names become mojibake.
                Console.InputEncoding = new UTF8Encoding(false);
                var input = Console.In.ReadToEnd();
                if (input.Length > 16384) return;
                var evt = JsonSerializer.Deserialize<Event>(input)!;
                if(evt.Kind == "register" && evt.Hwnd == 0) evt = CaptureWindow(evt);
                Send(evt);
                return;
            }
            if(args.Contains("--uninstall")) { ToastNotificationManagerCompat.Uninstall(); return; }
            using var mutex = new Mutex(true, "Local\\" + Pipe, out bool owner);
            if(!owner) return;
            var state = Path.Combine(Root, "windows.json");
            if(File.Exists(state)) foreach(var pair in JsonSerializer.Deserialize<Dictionary<string,Window>>(File.ReadAllText(state))!) Windows[pair.Key]=pair.Value;
            var seenFile=Path.Combine(Root,"events.json");
            if(File.Exists(seenFile)) foreach(var key in JsonSerializer.Deserialize<string[]>(File.ReadAllText(seenFile))!) Seen.Add(key);
            ToastNotificationManagerCompat.OnActivated += e => {
                try { var a=ToastArguments.Parse(e.Argument); if(a.Contains("id")) Focus(a["id"]); }
                catch(Exception ex) { Log("", "click", ex.GetType().Name); }
            };
            ToastNotificationManagerCompat.CreateToastNotifier();
            _ = Task.Run(async () => {
                while(true) {
                    using var server = new NamedPipeServerStream(Pipe, PipeDirection.InOut, 1, PipeTransmissionMode.Byte, PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
                    await server.WaitForConnectionAsync();
                    try {
                        using var timeout = new CancellationTokenSource(10000);
                        using var reader = new StreamReader(server, leaveOpen:true);
                        var line = await reader.ReadLineAsync(timeout.Token);
                        if(line is null || line.Length>16384) continue;
                        var evt=JsonSerializer.Deserialize<Event>(line)!;
                        Handle(evt);
                        using var writer=new StreamWriter(server, new UTF8Encoding(false), leaveOpen:true) { AutoFlush=true };
                        await writer.WriteLineAsync("ok");
                    } catch(Exception ex) { Log("", "bridge", ex.GetType().Name); }
                }
            });
            Application.Run();
        } catch(Exception ex) { Log("", "helper", ex.GetType().Name); Environment.ExitCode=args.Contains("--hook") ? 0 : 1; }
    }
    internal static Event CaptureWindow(Event evt) {
        bool attached = false;
        try {
            if(GetConsoleWindow() == 0) attached = AttachConsole(uint.MaxValue);
            var h = GetAncestor(GetConsoleWindow(), 3); // GA_ROOTOWNER
            if(h == 0 || !IsWindowVisible(h)) throw new InvalidOperationException("terminal-window-not-found");
            GetWindowThreadProcessId(h, out uint pid);
            using var process = Process.GetProcessById((int)pid);
            return evt with { Hwnd=h.ToInt64(), Pid=(int)pid, Started=process.StartTime.ToUniversalTime().Ticks };
        } finally { if(attached) FreeConsole(); }
    }
    internal static void Send(Event evt) {
        using var client = new NamedPipeClientStream(".", Pipe, PipeDirection.InOut, PipeOptions.Asynchronous);
        try { client.Connect(400); } catch(TimeoutException) {
            Process.Start(new ProcessStartInfo(Environment.ProcessPath!, "--serve") { UseShellExecute=true, WindowStyle=ProcessWindowStyle.Hidden });
            client.Connect(5000);
        }
        using var writer = new StreamWriter(client, new UTF8Encoding(false), leaveOpen:true) { AutoFlush=true };
        writer.WriteLine(JsonSerializer.Serialize(evt));
        using var reader = new StreamReader(client, leaveOpen:true);
        using var timeout = new CancellationTokenSource(10000);
        if(reader.ReadLineAsync(timeout.Token).AsTask().GetAwaiter().GetResult() != "ok") throw new IOException("registration-or-send-failed");
    }
    static void Handle(Event e) {
        if(!Guid.TryParseExact(e.Id,"N",out _)) throw new ArgumentException("id");
        lock(Gate) {
            if(e.Kind=="register") {
                var window = new Window(e.Hwnd,e.Pid,e.Started,e.Cwd);
                if(!Valid(window)) { Log(e.Id,e.Kind,"window-not-found"); throw new InvalidOperationException(); }
                Windows[e.Id]=window;
                var file=Path.Combine(Root,"windows.json"); File.WriteAllText(file+".tmp",JsonSerializer.Serialize(Windows)); File.Move(file+".tmp",file,true);
                Log(e.Id,e.Kind,"registered"); return;
            }
            if(e.Kind=="forget") { ToastNotificationManagerCompat.History.Remove(e.Id[..16],"Codex"); Windows.Remove(e.Id); File.WriteAllText(Path.Combine(Root,"windows.json"),JsonSerializer.Serialize(Windows)); return; }
            if(e.Kind=="focus") { Focus(e.Id); return; }
            if(e.Kind!="complete" && e.Kind!="question" && e.Kind!="approval" && e.Kind!="compact" && e.Kind!="test" && e.Kind!="error") return;
            if(!Windows.TryGetValue(e.Id,out var w) || !Valid(w)) { Log(e.Id,e.Kind,"invalid-window"); return; }
            if(e.Kind=="test") {
                Toast(e.Id,NotificationTitle(e,w),NotificationStatus(e.Kind,e.Client));
                Log(e.Id,e.Kind,"notified"); return;
            }
            if(e.Key.Length>0 && !Seen.Add(e.Id+":"+e.Kind+":"+e.Key)) { Log(e.Id,e.Kind,"duplicate"); return; }
            if(Seen.Count>10000) { Seen.Clear(); if(e.Key.Length>0) Seen.Add(e.Id+":"+e.Kind+":"+e.Key); }
            var seenFile=Path.Combine(Root,"events.json"); File.WriteAllText(seenFile+".tmp",JsonSerializer.Serialize(Seen)); File.Move(seenFile+".tmp",seenFile,true);
            if(GetForegroundWindow()==(nint)w.Hwnd) { Log(e.Id,e.Kind,"foreground-suppressed"); return; }
            Toast(e.Id,NotificationTitle(e,w),NotificationStatus(e.Kind,e.Client));
            Log(e.Id,e.Kind,"notified");
        }
    }
    internal static string NotificationTitle(Event e, Window w) => string.IsNullOrWhiteSpace(e.ThreadName) ? w.Cwd : e.ThreadName;
    internal static string NotificationStatus(string kind, string client = "Codex") {
        var app = client == "Pi" ? "Pi" : "Codex";
        return kind switch { "complete" => $"{app} 已完成", "approval" => $"{app} 等待命令审批",
            "compact" => $"{app} 上下文已压缩", "error" => $"{app} 运行出错",
            "test" => $"{app} 通知正常，点击可返回此终端", _ => $"{app} 需要回答" };
    }
    static void Toast(string id,string title,string text = "") {
        var toast = new ToastContentBuilder().AddArgument("id",id).AddText(title);
        if(text.Length > 0) toast.AddText(text);
        toast.Show(t=> { t.Tag=id[..16]; t.Group="Codex"; });
    }
    static bool Valid(Window w) {
        try { GetWindowThreadProcessId((nint)w.Hwnd,out uint pid); return IsWindow((nint)w.Hwnd) && pid==w.Pid && Process.GetProcessById(w.Pid).StartTime.ToUniversalTime().Ticks==w.Started; }
        catch { return false; }
    }
    static void Focus(string id) {
        lock(Gate) {
            if(!Windows.TryGetValue(id,out var w) || !Valid(w)) { Toast(id,"目标终端已关闭", ""); Log(id,"click","closed"); return; }
            var h=(nint)w.Hwnd;
            if(IsIconic(h)) ShowWindowAsync(h,9);
            SetForegroundWindow(h);
            Thread.Sleep(150);
            if(GetForegroundWindow()==h) Log(id,"click","focused");
            else { var f=new FLASHWINFO { cbSize=(uint)Marshal.SizeOf<FLASHWINFO>(),hwnd=h,dwFlags=3,uCount=3 }; FlashWindowEx(ref f); Log(id,"click","foreground-denied-flashed"); }
        }
    }
    [DllImport("kernel32.dll")] static extern bool AttachConsole(uint pid);
    [DllImport("kernel32.dll")] static extern bool FreeConsole();
    [DllImport("kernel32.dll")] static extern nint GetConsoleWindow();
    [DllImport("user32.dll")] static extern nint GetAncestor(nint h,uint flags);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(nint h);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(nint h,out uint pid);
    [DllImport("user32.dll")] static extern nint GetForegroundWindow();
    [DllImport("user32.dll")] static extern bool IsWindow(nint h);
    [DllImport("user32.dll")] static extern bool IsIconic(nint h);
    [DllImport("user32.dll")] static extern bool ShowWindowAsync(nint h,int command);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(nint h);
    [StructLayout(LayoutKind.Sequential)] struct FLASHWINFO { public uint cbSize; public nint hwnd; public uint dwFlags,uCount,dwTimeout; }
    [DllImport("user32.dll")] static extern bool FlashWindowEx(ref FLASHWINFO f);
}
