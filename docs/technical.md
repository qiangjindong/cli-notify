# 技术说明

本文面向维护者；普通用户只需阅读项目根目录的 README。

已针对 WSL Ubuntu-22.04、Codex 0.155.0、Windows Terminal 和 .NET 9 实现。

## Windows 原生扩展（2026-09-20）

新增 `install.ps1` / `uninstall.ps1` 和 C# `--hook` / `--hook-worker`。安装需要 Windows Codex、Windows Terminal、.NET 9 SDK 和 NuGet 网络；运行不依赖 Windows Python。默认配置位置为 `%USERPROFILE%\.codex`，支持 `CODEX_HOME` 或 `-CodexHome`。切换 Home 前应先卸载旧 Windows client。

`--hook` 从 stdin 读取 JSON，Stop 先输出 `{}`，再保留 session/turn/tool 标识和目录名，计算摘要并捕获 HWND/PID/启动时间。脱敏结果通过 stdin 发给无窗口 worker，不把问答和命令放入进程参数。worker 用 `Microsoft.Data.Sqlite` 只读查询 `thread_source` 和 `name`，只有 `thread_source=user` 才发送四类提醒；缺失、内部线程、结构不兼容均抑制。SessionStart 只登记窗口。每次提醒重新登记，登记失败不使用旧窗口。原有 Named Pipe、Toast、去重和点击恢复共用。

Windows hook 配置使用官方支持的 `command_windows`，POSIX fallback 为 `:`。实测 `cmd /C` 引号边界会破坏带空格的 exe 命令，因此使用系统 Windows PowerShell 的 `-EncodedCommand` 做纯 stdin/stdout 转接，hook 业务仍在 C# 中。编码命令不含用户问答，路径按 PowerShell 字符串转义；无需 8.3 短路径。系统目录本身包含空白或 shell 扩展字符时拒绝安装。此方案增加一次 PowerShell 启动开销；不是 `codex` 的 PATH shim。

`Tomlyn` 校验配置，但不重写已有文本，只追加/移除 `cli-notify-windows` 标记块。标记识别兼容旧版 `codex-win-notify-windows` 名称，因此从 `codex-win-notify` 升级时原地替换旧块，不会留下两份 hooks。首次备份为 `cli-notify.windows.config.backup`。Codex 0.155.1 的信任摘要按平台解析后的命令计算，已通过真实 `hooks/list` 验证五项均 trusted；已有 notify、hook、信任配置保留。参考：[官方 hooks 文档](https://developers.openai.com/zh-Hans/docs/hooks)。

Windows 五类 hook 的超时上限为 10 秒。原先的 2 秒可能被 PowerShell 与 .NET 启动开销耗尽，出现通知已发送但 CLI 仍显示 `hook timed out after 2s` 的情况。10 秒是执行上限，不是固定等待；通知仍由分离的 worker 发送。修改后运行 `install.ps1` 更新配置及对应信任摘要，再退出并重启 Codex；不要只手改 `timeout`，否则信任摘要会失效。

两侧使用同一个 Windows `install.lock` 文件共享模式锁串行安装卸载。`clients/windows.json` 记录 Windows Home；`clients/wsl-<摘要>.json` 按发行版和 WSL 配置路径区分。还有其他 client 时保留助手，最后一个 client 才卸载 Toast 并清除数据，保留空锁文件。遇到旧版 WSL `build` 目录且没有 client 清单时，Windows 卸载保守保留助手。旧版 WSL 卸载器不认识清单，必须更新后重装再用于共存卸载。共享同一个 Codex Home 会改变 hook 索引和信任键，首版明确拒绝；应使用两个独立 Home。

Windows 验证命令（测试使用 Python，产品安装/运行不需要）：

```powershell
dotnet run --project tests/windows/WindowsTests.csproj -c Release
$env:PYTHONUTF8 = '1'
python -m unittest discover -s tests -p 'test_*.py' -v
python tests/windows_desktop.py --registration-only
python tests/windows_desktop.py --background-only
python tests/windows_desktop.py
```

本轮验收：

- Release 编译零警告/错误；21 项 C# 检查通过，覆盖脱敏、事件去重、参数化只读来源与线程名查询、空名回退、通知状态文本、配置保留、重装和非法配置拒绝。
- Windows Python 测试 23 项通过，2 项 POSIX 路径/信任专属检查跳过；真实 Codex 0.155.1 `hooks/list` 确认五类 hook 可信，原有 hook 未被自动信任。
- 含中文、空格和 `&` 的安装路径通过实际 `cmd /C` 执行 Stop，正确返回 `{}`。安装器用隔离的临时 Codex Home 实测重装幂等、卸载配置清除、旧 WSL 助手保留；未修改用户默认 Windows Codex 配置。
- 两个真实 Windows Terminal 原生窗口分别通过合成 SessionStart 登记不同 HWND。
- 等待 Terminal 异步启动/激活稳定后，两个后台窗口各自真实执行四类合成 hook，均发送通知且前台不变。初次测试未等待窗口启动稳定，出现前台漂移；增加等待后后台专项通过。
- 完整桌面测试仍未通过：测试进程请求将目标窗口切到前台被 Windows 拒绝，等待前台窗口超时。因此本轮未验证原生端前台抑制、最小化恢复和通知点击；不将后台专项结果替代完整桌面验收。
- WSL 回归尝试被环境阻塞：本机默认 Python 为 3.10，没有 `tomllib`，未发现现成 3.11+ 解释器。未改变现有 WSL 运行环境；其安装/卸载改动需在满足原有 Python 3.11+ 要求的环境复验。
- 真实 Codex TUI 的 SessionStart/提问/审批/压缩/Stop、`windows.sandbox=elevated` 与 `unelevated`、系统通知点击和 COM 重新激活仍待验收。未增加启动 shim；是否需要取决于真实 hook 进程模型。

以下既有桌面结果来自 WSL，不代表 Windows 原生端到端验收。

## 使用

在想工作的目录执行：

```sh
codex
codex --model gpt-5.5
codex resume --last
```

在当前终端直接运行 Codex，不新建窗口，也不修改标题。完成、调用 `request_user_input`、触发权限审批或完成上下文压缩时，只有该窗口不在前台才发送通知。Toast 第一行是 `threads.name`（空值回退到当前工作目录名），第二行是事件状态，例如“Codex 已完成”或“Codex 等待命令审批”。点击通知恢复并聚焦窗口；窗口关闭后仍使用独立标题“目标终端已关闭”。前台激活被 Windows 拒绝时，闪烁任务栏。

无需调用模型的人工冒烟测试：WSL 运行 `./test.sh`，Windows 运行 `.\test.ps1`。命令调用已安装助手的 `--test` 模式，登记当前 Windows Terminal 并发送可点击通知；测试事件特意不做前台抑制，以便直接在当前终端验证。它不启动 Codex、不读取状态数据库，也不消耗模型额度。

参数、当前目录和环境直接沿用当前进程。发送事件只包含窗口关联、类型、目录名称、线程名称及标识摘要。

不定位标签页或分屏。审批提醒不代替审批，仍需回到终端选择允许或拒绝。当前仅支持每个窗口一个标签页、无分屏。

## 安装与卸载实现

```sh
python3 install.py
python3 uninstall.py
```

安装需要 WSL Python 3.11+、Windows .NET 9 SDK、Windows Terminal、WSL Windows 互操作和 NuGet 网络连接。安装至 `%LOCALAPPDATA%\CliNotify`，用户配置自动加载提醒 hooks。助手按需启动，无管理员权限要求，无开机启动。

通知图标由源码根目录的 `cli-notify.json` 中 `notification.icon` 配置。安装器校验 PNG 路径，以 Windows `System.Drawing` 将其转换为包含 16–256px 九档 PNG 图像的 ICO，再通过 MSBuild `ApplicationIcon` 嵌入助手 EXE；因此图标位于通知标题栏的应用身份位置，而不是 Toast 正文的 `appLogoOverride` 图片位。相对路径以源码根目录为基准，`null` 表示不嵌入自定义应用图标。配置只在安装时读取，修改后需要重新安装。

重新安装会停止本工具的助手并更新文件；下一次事件会重新启动助手。卸载停止助手，调用通知组件的 `Uninstall()` 清理通知与注册，再删除 Windows 安装文件、本工具配置块和 WSL 状态目录。保留此源码目录便于审查；保留原有 Codex 配置。

## 配置与失败处理

安装器在 `${CODEX_HOME:-~/.codex}/config.toml` 追加带标记的配置块，配置 `SessionStart`、`PreToolUse`、`PermissionRequest`、`PostCompact` 和 `Stop`。原始 `codex` 自动加载这些 hooks，无需 alias、PATH 包装或修改 Codex 可执行文件。`SessionStart` 登记会话对应窗口；每次提醒也先登记当前窗口，避免依赖启动 hook 的触发时机，然后按会话标识发送提醒，完成提醒使用 `Stop`。原有 `notify` 不修改，继续由 Codex 调用。已有 hooks 和信任状态保留，只信任本工具五个确切 hook。

重装替换本工具配置块；卸载只移除该块。标记识别同时兼容旧版 `codex-win-notify` 名称，升级不需要先手动卸载。首次修改已有配置时保存 `cli-notify.config.backup`，不会用备份覆盖后续用户修改。hooks 在新进程启动时加载，安装后须退出并重新运行 `codex`。显式关闭 hooks 会关闭全部四类提醒。

hook 立即分离通知工作进程，不等待点击、回答或审批；`Stop` 仅输出空 JSON，其余无输出。事件不携带命令、提问、回答或完成文本。登记或桥接失败记录日志后继续 Codex。

**工作区待验证的缓解方案，尚未部署，不是最终完成信号接入**（源码核对和推荐方向见 [Codex 完成通知](codex-completion.md)）：完成通知不能仅凭 `Stop` 判定，该 hook 可能早于本轮真正结束，随后还可能自动续跑。Windows/WSL 原生 worker 在后台每次等待 1 秒后，只读检查当前线程的 goal 状态及 rollout 尾部最多 256 KiB 的生命周期记录，最多检查 3 次。无 goal（含旧版本无 goal 数据库）或 goal 为 `complete`，且该 turn 已完成、未发现后续生命周期活动时，首次满足即通知，不要求连续满足。发现该 turn 之后的其他 turn 活动、完成后重新启动、取消、缺少 turn ID 或未完成的 goal，立即结束检查且不通知。完成记录尚未出现、状态暂时读不到或格式不兼容则重试，第三次仍无法确认就跳过。仅见较早轮次记录不能证明当前轮已续跑，按尚未确认重试。审批、提问、压缩不受此延迟影响。旧 launcher 的 notify 路径也使用同一检查，并继续传递原始通知给原 handler。

rollout 读取仅用于生命周期判定，不转发或记录正文；日志只记抑制原因。此机制依赖 Codex 私有存储格式，属于尽力而为的状态确认，不是官方“所有任务已静止”事件：任一次通知之后才发生的续跑仍可能误报，写盘过慢可能漏通知。正常约 1 秒通知，未确认时最多等待三次；文件和数据库读取耗时另计，因此不是严格 3 秒超时。升级 Codex 后需要重新验证。

登记时通过关联控制台的 `GetConsoleWindow` 与 `GetAncestor(GA_ROOTOWNER)` 获取终端窗口；无法取得时不猜测前台窗口，记录失败并继续 Codex。助手保存 HWND、PID 和进程启动时间，点击时重新校验，不依赖标题。通知按会话替换，事件摘要去重并持久化。已关闭的窗口不会重新创建，也不会恢复旧会话。

完成、提问、审批和压缩通知同时读取 Codex 0.155.0 的 `state_5.sqlite` 中该线程的 `thread_source` 和 `name`，仅接受已持久登记的 `user` 会话，排除自动评审的临时线程和子代理。来源缺失或数据库不可读时，本工具抑制对应通知并记录原因，原有 notify 保持不变。此判断依赖当前 Codex 状态库结构，升级后需验证。线程名称只进入通知载荷；桥接和助手日志仍只记录必要标识与结果，不记录线程名称、问答、命令或完成文本。

审批 hook 由 Codex 在审批流程开始时触发；接口不提供“最终是否等待人工选择”的信号。其他 hooks 或自动审批随后直接作出决定时，仍可能收到审批提醒。后台发送有短暂延迟，审批很快结束时也可能收到稍晚的提醒。手动或自动压缩完成后显示“Codex 上下文已压缩”。新增审批和压缩 hook 需要重新启动 `codex` 会话才会加载。

日志：

- Windows：`%LOCALAPPDATA%\CliNotify\helper.log`
- WSL：`${XDG_STATE_HOME:-~/.local/state}/cli-notify/bridge.log`

日志不记录线程名称、完整提问、回答、命令或 Codex 完成文本。

## 验证

```sh
cd $HOME/cli-notify
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 tests/desktop.py --native
python3 tests/real_hook.py
```

`desktop.py --native` 会打开并关闭两个临时测试终端，通过原始 Codex app-server 检查全局 hooks，并用合成 hook 输入验证窗口登记，发送测试通知，短暂切换窗口，最后尝试恢复原前台窗口。`real_hook.py` 使用当前配置的模型运行一个临时会话，真实调用提问工具，自动选择测试答案，确认后续完成；会使用模型额度。

当前窗口关联版本已通过单元测试、Release 编译安装与自动桌面验证：

- Release 编译安装；助手首次启动成功，事件通过 JSON 标准输入传递。
- 前台完成/提问/审批/压缩均抑制；后台完成/提问/审批/压缩均发送；通知发送不切换前台；重复事件抑制。桌面测试直接发送事件验证助手，不代替真实命令审批或上下文压缩 hook 的端到端验收。
- 在两个真实测试终端加载原始 Codex 配置，使用合成 hook 输入及隔离的测试来源数据库，验证无需启动包装的窗口登记；两个窗口分别聚焦；最小化恢复；助手重启后使用持久窗口身份；已关闭窗口检测。
- 测试目录包含中文、空格和引号；不拦截或重新解析原始 Codex 参数。
- 现有 hooks 和 notify 配置保留；安装可重复执行，卸载仅移除本工具配置块；桥接失败不抛出；日志无完整问答。

此前版本还验证过真实 `request_user_input` hook 触发、测试答案后继续完成及完成 notify 触发；本次未重跑使用模型额度的测试；原始 CLI 的真实提问、完成、审批与压缩触发仍需端到端验收。

**仍需人工桌面验收**：上述自动桌面测试直接调用同一个聚焦处理函数，未代替系统通知点击。分别在两个真实 Codex 窗口后台完成后，点击系统横幅、通知中心的延迟通知；停止助手后点击旧通知，确认 COM 重新激活；关闭窗口后再点击旧通知。对真实交互提问，选择选项并确认继续。重新启动 `codex` 后触发一次真实命令审批，切到其他窗口检查提醒，再点击通知并在终端选择允许或拒绝。

助手进程可用以下 Windows PowerShell 命令停止以测试重新激活：

```powershell
Get-Process CliNotify -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -eq "$env:LOCALAPPDATA\CliNotify\app\CliNotify.exe" } |
  Stop-Process -Force
```

参考：[Codex hooks](https://learn.chatgpt.com/docs/hooks)、[0.155.0 hook 调度源码](https://github.com/openai/codex/blob/rust-v0.155.0/codex-rs/core/src/tools/registry.rs)、[Windows 通知激活与卸载](https://learn.microsoft.com/en-us/dotnet/api/microsoft.toolkit.uwp.notifications.toastnotificationmanagercompat?view=win-comm-toolkit-dotnet-7.1)。
