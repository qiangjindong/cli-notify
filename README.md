# WSL Codex Windows 通知

已针对 WSL Ubuntu-22.04、Codex 0.155.0、Windows Terminal 和 .NET 9 实现。

## 使用

在想工作的目录执行：

```sh
codex-window
codex-window --model gpt-5.5
codex-window resume --last
```

在当前终端直接运行 Codex，不新建窗口，也不修改标题。完成、调用 `request_user_input`、触发权限审批或完成上下文压缩时，只有该窗口不在前台才发送通知。审批提醒标题为“Codex 等待命令审批”。点击通知恢复并聚焦窗口；窗口关闭后提示“目标终端已关闭”。前台激活被 Windows 拒绝时，闪烁任务栏。

参数、当前目录和环境直接沿用当前进程。发送事件只包含窗口关联、类型、目录名称及标识摘要。

不定位标签页或分屏。审批提醒不代替审批，仍需回到终端选择允许或拒绝。当前仅支持每个窗口一个标签页、无分屏。

## 安装与卸载

```sh
python3 $HOME/codex-win-notify/install.py
python3 $HOME/codex-win-notify/uninstall.py
```

安装需要 WSL Python 3.11+、Windows .NET 9 SDK、Windows Terminal、WSL Windows 互操作和 NuGet 网络连接。安装至 `%LOCALAPPDATA%\CodexWinNotify`，命令链接位于 `~/.local/bin/codex-window`。确保 `~/.local/bin` 已在 PATH 中。助手按需启动，无管理员权限要求，无开机启动。

重新安装会停止本工具的助手并更新文件；下一次事件会重新启动助手。卸载停止助手，调用通知组件的 `Uninstall()` 清理通知与注册，再删除 Windows 安装文件、命令链接和 WSL 状态目录。保留此源码目录便于审查；不修改原有 Codex 配置。

## 配置与失败处理

启动时调用本地 Codex app-server 的 `config/read`，获取原有 `notify`，包括项目层和命令行覆盖。0.155.0 的 app-server 不接受 `--profile`，因此命名配置在临时私有配置目录中合并其用户层，再由 Codex 解析其余配置层；该目录随后删除。完成事件把原始 JSON 原样交给原处理程序。现有 user/project/plugin hooks 仍由 Codex 加载，命令行注入的 hooks 也会保留，新提问、`PermissionRequest` 审批和 `PostCompact` 压缩完成 hook 作为 session flags 层追加。

按 0.155.0 的算法为本工具的确切 hook 计算信任摘要，仅在该进程注入对应信任状态；不修改已有 hooks 的信任状态。提问、审批和压缩 hook 启动独立工作进程立即成功返回，不等待助手、点击或回答；无标准输出，不修改工具参数或权限决定。审批桥接只传递会话、轮次和独立请求标识，不传递命令或审批原因。

无法解析原通知配置时运行原始 Codex，不注入本工具配置。登记或桥接失败记录错误后继续 Codex。若显式关闭 Codex hooks，提问、审批和压缩通知随之关闭，完成通知仍使用 notify。

登记时通过关联控制台的 `GetConsoleWindow` 与 `GetAncestor(GA_ROOTOWNER)` 获取终端窗口；无法取得时不猜测前台窗口，记录失败并继续 Codex。助手保存 HWND、PID 和进程启动时间，点击时重新校验，不依赖标题。通知按会话替换，事件摘要去重并持久化。已关闭的窗口不会重新创建，也不会恢复旧会话。

完成、审批和压缩通知读取 Codex 0.155.0 的 `state_5.sqlite` 中该线程的 `thread_source`，仅接受已持久登记的 `user` 会话，排除自动评审的临时线程和子代理。来源缺失或数据库不可读时，本工具抑制对应通知并记录原因，原通知处理程序仍接收原始完成事件。此判断依赖当前 Codex 状态库结构，升级后需验证。桥接日志记录 thread/turn 标识，不记录问答内容。

审批 hook 由 Codex 在审批流程开始时触发；接口不提供“最终是否等待人工选择”的信号。其他 hooks 或自动审批随后直接作出决定时，仍可能收到审批提醒。后台发送有短暂延迟，审批很快结束时也可能收到稍晚的提醒。手动或自动压缩完成后显示“Codex 上下文已压缩”。新增审批和压缩 hook 需要重新启动 `codex-window` 会话才会注入。

日志：

- Windows：`%LOCALAPPDATA%\CodexWinNotify\helper.log`
- WSL：`${XDG_STATE_HOME:-~/.local/state}/codex-win-notify/bridge.log`

日志不记录完整提问、回答或 Codex 完成文本。

## 验证

```sh
cd $HOME/codex-win-notify
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 tests/desktop.py
python3 tests/real_hook.py
```

`desktop.py` 会打开并关闭两个临时测试终端，发送测试通知，短暂切换窗口，最后尝试恢复原前台窗口。`real_hook.py` 使用当前配置的模型运行一个临时会话，真实调用提问工具，自动选择测试答案，确认后续完成；会使用模型额度。

当前窗口关联版本已通过单元测试、Release 编译安装与自动桌面验证：

- Release 编译安装；助手首次启动成功，事件通过 JSON 标准输入传递。
- 前台完成/提问/审批/压缩均抑制；后台完成/提问/审批/压缩均发送；通知发送不切换前台；重复事件抑制。桌面测试直接发送事件验证助手，不代替真实命令审批或上下文压缩 hook 的端到端验收。
- 在测试终端内直接运行启动器；应用改变标题后仍能通知和聚焦；两个窗口分别聚焦；最小化恢复；助手重启后使用持久窗口身份；已关闭窗口检测。
- 中文目录、空格、单双引号、多行和 shell 特殊字符参数原样传递。
- 现有 hooks、notify、命名配置与命令行 notify 覆盖保留；桥接失败不抛出；日志无完整问答。

此前版本还验证过真实 `request_user_input` hook 触发、测试答案后继续完成及完成 notify 触发；本次未重跑使用模型额度的测试。

**仍需人工桌面验收**：上述自动桌面测试直接调用同一个聚焦处理函数，未代替系统通知点击。分别在两个真实 Codex 窗口后台完成后，点击系统横幅、通知中心的延迟通知；停止助手后点击旧通知，确认 COM 重新激活；关闭窗口后再点击旧通知。对真实交互提问，选择选项并确认继续。重新启动 `codex-window` 后触发一次真实命令审批，切到其他窗口检查提醒，再点击通知并在终端选择允许或拒绝。

助手进程可用以下 Windows PowerShell 命令停止以测试重新激活：

```powershell
Get-Process CodexWinNotify -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -eq "$env:LOCALAPPDATA\CodexWinNotify\app\CodexWinNotify.exe" } |
  Stop-Process -Force
```

参考：[Codex hooks](https://learn.chatgpt.com/docs/hooks)、[0.155.0 hook 调度源码](https://github.com/openai/codex/blob/rust-v0.155.0/codex-rs/core/src/tools/registry.rs)、[Windows 通知激活与卸载](https://learn.microsoft.com/en-us/dotnet/api/microsoft.toolkit.uwp.notifications.toastnotificationmanagercompat?view=win-comm-toolkit-dotnet-7.1)。
