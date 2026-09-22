# Pi Windows Terminal 通知扩展

本仓库现在也是一个本地 Pi package。扩展直接调用共享 Windows 助手，不使用 Codex hooks、不读取 Codex 数据库，也不修改 Codex 配置。

## 支持范围

- **Windows 原生 Pi + Windows Terminal**；本次 Pi 适配不支持 WSL、SSH、RPC、JSON 或 print 模式。原有 Codex WSL 支持不变。
- Windows .NET 9 SDK（安装构建及运行所需桌面运行时）。不需要 Python，也不需要安装 Codex。
- Pi 版本必须提供 `agent_settled`、`agent_before_settle`、`ui_prompt_start` 等扩展事件；以本机 `@earendil-works/pi-coding-agent` 文档为基线。旧版本只支持 `agent_end` 时请升级，不回退到可能提前通知的事件。
- 每个 Windows Terminal **窗口一个标签页且不分屏**。定位的是窗口，不是标签页或 pane。

## 安装

在 Windows PowerShell 中进入本仓库：

```powershell
.\install-pi.ps1
pi install .
```

第一步构建/更新 `%LOCALAPPDATA%\CliNotify\app\CliNotify.exe`，登记 `clients\pi-windows.json`。第二步将本仓库作为本地 package 加入 Pi。重启 Pi，或执行 `/reload`。

即便之前安装了 Codex 通知，也需要运行第一步以更新助手的 `--pi-send` 接口。它会停止旧助手，更新共享文件；下次通知自动启动助手，不停止 Codex/Pi 本身。

本地 package 不复制源码，请保留仓库。以后更新代码后重新运行 `install-pi.ps1` 并在 Pi `/reload`。仍使用共享助手的 Codex 应同步使用本仓库新版安装器，避免旧源码重装降级助手。

助手、Toast 应用身份和图标与 Codex 共用，系统通知标题栏统一显示 `CLI Notify`；正文状态及测试消息使用 Pi / Codex 前缀区分来源，会话名为空时回退为目录名。更新后须重新运行 `install-pi.ps1`，由新助手刷新通知显示名；旧通知可能仍显示旧名称。

## 行为

- `session_start`：登记当前窗口。首次启动时在 Pi 交互界面显示“Pi 启动耗时 X.XX 秒”，统计 Node 进程启动至此事件的时间（不含 shell 启动器及后续资源发现、助手登记耗时）；`/reload`、新建或切换会话不重复显示。
- `agent_settled`：所有自动重试、压缩和排队续跑结束后，通知“Pi 已完成”；失败显示“Pi 运行出错”，取消不提醒。
- `ui_prompt_start`：扩展的 select/confirm/input/editor/custom 等阻塞 UI 开始时，通知“Pi 需要回答”。不是 Codex 的权限审批 hook，也不会替用户确认。
- `session_compact`：通知“Pi 上下文已压缩”。
- 自动提醒仅在对应窗口位于后台时发送；测试通知不受此限制。

每个发送进程通过自己的控制台捕获 HWND、PID、启动时间，先登记再通知。登记失败不会使用旧窗口，也不会猜测当前前台窗口。点击时校验窗口身份并尝试恢复/聚焦；Windows 拒绝前台激活时闪烁任务栏。

事件使用每个扩展实例/会话独立的随机 ID，避免同一会话在两个 Pi 进程中打开时相互覆盖。延迟通知在 `/reload`、切换会话后仍指向原窗口，不承诺切回原 Pi 会话。关闭窗口后点击会显示“目标终端已关闭”。

通知发送排队且有超时，不阻塞模型和交互 UI。退出/重载取消进行中的发送并丢弃队列，保留已经发出的通知与窗口关联。异常只在 Pi 中提示一次，不影响工具或审批结果。

载荷仅含随机标识、事件类型、目录名、会话显示名；不传问题、回答、命令、压缩摘要或 UI 标题。文本通过 UTF-8 stdin 传递，不拼接 shell。助手日志不记录会话显示名或对话。

## 测试与验收

在 Pi 中运行，不消耗模型额度：

```text
/cli-notify-test
```

切换到其他窗口后，点击测试 Toast，确认回到发送它的那个终端。分别在两个独立 Windows Terminal 窗口中测试，另外验证：

1. 最小化后点击，恢复原窗口。
2. 后台真实完成任务、打开交互提示、执行 `/compact` 时收到对应通知。
3. 前台完成不弹窗；取消不显示完成；重试期间不提前显示完成。
4. `/reload` 或新建会话后点击旧通知，仍回到原窗口；关闭原窗口后不会聚焦其他终端。
5. 从通知中心点击延迟通知，以及停止助手后点击旧通知的 COM 重新激活。

**自动单元测试不等于桌面验收**。尤其 Node 启动助手时的控制台关联、系统 Toast 点击、前台激活限制，必须在真实终端按上述步骤确认。

自动测试：

```powershell
npm test
dotnet run --project tests/windows/WindowsTests.csproj -c Release
$env:PYTHONUTF8 = '1'
python -m unittest discover -s tests -p 'test_*.py' -v
```

发送失败时先更新助手，再查看 `%LOCALAPPDATA%\CliNotify\helper.log`。若系统屏蔽通知或开启勿扰，助手发送成功也不代表横幅一定显示。

## 卸载

在本仓库目录执行：

```powershell
pi remove .
# 退出并重新启动 Pi，或者 /reload，再执行：
.\uninstall-pi.ps1
```

如果从其他路径安装，以 `pi list` 中的包路径为准。Pi 的 `remove` 不会自动运行助手卸载脚本。

卸载脚本仅移除 Pi 的助手租约，不改 Codex 配置。有其他 Codex/WSL client 或旧版 WSL 安装时保留共享助手；最后一个 client 卸载时才移除助手及共享通知注册。全局/项目级多处使用此扩展时，请全部移除后再卸载助手。
