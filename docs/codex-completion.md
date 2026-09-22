# Codex 完成通知：源码核对与接入方案

## 核对版本

核对 `openai/codex` 的 `rust-v0.155.1`，对应 commit
`be2951ea34f0d295ed0becf97079f92fa5f6950e`，与本机 `codex-cli 0.155.1` 对齐。
源码克隆在临时目录，不修改已安装 Codex。本页描述调研结论；下述 TUI 外部通知出口尚未实现。

## 为什么 Stop 会误报

1. [`core/src/session/turn.rs:642–704`](https://github.com/openai/codex/blob/rust-v0.155.1/codex-rs/core/src/session/turn.rs#L642-L704)：当模型和当前输入暂时不要求后续采样时运行 Stop hooks。聚合结果若要求阻止停止，注入续跑消息并 `continue`，仍在同一 turn 内。`stop_hook_active` 只表示之前已有 Stop hook 触发续跑，不能用于判断最后一次 Stop。
2. 同一处在 Stop hooks 之后调用 legacy notify，然后退出采样循环。改用 `notify` 可以避开部分 Stop 拦截续跑，但不能识别稍后的 goal 或 TUI 排队续跑。
3. [`core/src/tasks/mod.rs:825–865`](https://github.com/openai/codex/blob/rust-v0.155.1/codex-rs/core/src/tasks/mod.rs#L825-L865)：发出 TurnComplete，清理 active turn，发出内部 thread-idle 生命周期回调，flush rollout，然后仍会尝试启动 pending work。因此 task_complete 不是“全部工作已结束”的承诺。TurnComplete 还可携带 error，不能单凭事件名宣称成功。
4. [`ext/goal/src/extension.rs:176–190`](https://github.com/openai/codex/blob/rust-v0.155.1/codex-rs/ext/goal/src/extension.rs#L176-L190)：goal 扩展的 `on_thread_idle` 调用 `continue_if_idle()`。内部 idle 本身就是续跑触发点，不能简单换成监听 idle 来解决。

## 官方 TUI 实际如何判断

[`tui/src/chatwidget/turn_runtime.rs:212–230`](https://github.com/openai/codex/blob/rust-v0.155.1/codex-rs/tui/src/chatwidget/turn_runtime.rs#L212-L230) 的 `on_task_complete`：

- 只处理 live completion，不为历史回放通知。
- 先调用 `maybe_send_next_queued_input()`，尝试启动 TUI 排队输入。
- 当前 goal 为 active 时抑制完成通知。
- 需要隐藏的 realtime delegation turn 不通知。
- 没有上述续跑/隐藏条件，才调用 `notify(AgentTurnComplete)`。

源码注释为 `Emit a notification only when the live agent is waiting for the user.`，没有固定秒数等待。

[`tui/src/chatwidget/tests/slash_commands.rs:2760–2801`](https://github.com/openai/codex/blob/rust-v0.155.1/codex-rs/tui/src/chatwidget/tests/slash_commands.rs#L2760-L2801) 分别测试 active goal 和普通 queued follow-up 不产生完成通知。

注意这是“等待用户”的语义，不是验证用户目标已经成功达成。官方仅以 active 判断 goal 是否续跑；paused、blocked、usage_limited 等并非成功完成。若映射到本工具，需要区分“已完成”和“需要处理”，而不是把所有 idle 都标成成功。

## 现有扩展口的边界

- [`protocol/src/protocol.rs:1584–1597`](https://github.com/openai/codex/blob/rust-v0.155.1/codex-rs/protocol/src/protocol.rs#L1584-L1597)：公开 hook 枚举没有 Notification / AgentSettled / WaitingForUser。
- [`config/src/types.rs:656–663`](https://github.com/openai/codex/blob/rust-v0.155.1/codex-rs/config/src/types.rs#L656-L663)：TUI notification_method 只有 auto、osc9、bel，没有 command。
- [`tui/src/chatwidget/notifications.rs:6–23`](https://github.com/openai/codex/blob/rust-v0.155.1/codex-rs/tui/src/chatwidget/notifications.rs#L6-L23)：先按通知配置过滤、合并优先级，再向终端投递。审批/计划提示优先于完成。
- [`tui/src/notifications/mod.rs:14–45`](https://github.com/openai/codex/blob/rust-v0.155.1/codex-rs/tui/src/notifications/mod.rs#L14-L45)：后端发送终端控制序列或响铃，未调用 legacy notify。
- app-server 的轮次/状态事件不包含 TUI 是否即将提交本地排队输入的决定；不能把订阅 turn/completed 当成等价替代。另起一个 app-server 也不能假定它就是当前 TUI 所连接的那个实例。

## 推荐的精确接入方向（需要用户确认自编译）

在 Codex TUI 的正式通知出口增加一个**独立、可选的外部命令 sink**，沿用官方 live/queue/goal/realtime 判断，不把旧 notify 的调用位置悄悄搬动，也不复用 Stop。

要求：

1. 出口在 TUI 通知配置过滤和优先级合并之后；为完成消息携带原始 thread/turn 身份，不能投递时再取可能已切换的当前会话。
2. 初版仅转发完成候选事件；提问、审批、压缩继续使用现有 hooks，避免双重提醒。
3. 最小载荷只含来源标志、事件类型、thread/turn ID、目录和必要的结果状态；不携带回复、工具输入或完整 transcript。
4. 异步启动助手，参数按 argv 传递，不经过 shell；失败不阻塞 Codex，也不改变对话。
5. 助手使用专门入口复用已有窗口捕获、来源检查、去重、前台抑制和点击恢复。可信的 TUI 通知不再等固定 3 秒或读取 rollout 猜测完成。
6. 仅在用户启用这个来源时关闭本工具的 Stop 完成提醒；不能在原版 Codex 上直接关闭 Stop 却没有替代来源。保留用户自己的 notify/hooks。
7. 自编译版本需固定上游 commit，并单独安装、可回退；不能覆盖现有官方版本后声称透明兼容。

不修改 Codex 的另一个方向是终端支持的 OSC9，或用 PTY/ConPTY 启动包装器截获 OSC9；后者会引入终端输入输出、控制序列、窗口身份、信号和退出码兼容问题，不是一个小配置调整，也不能默认保留现有点击定位能力。

## 当前采用的轮询缓解方案

用户选择优先低延迟、接受一定误报风险，不修改 Codex 本体。工作区实现为：后台每次等待 1 秒再检查，最多 3 次；首次确认该轮完成、无续跑且无未完成 goal 时立即通知，不要求连续满足。

- 发现续跑、取消、未完成 goal 或缺少 turn ID：停止检查，不通知。
- 完成记录未出现、文件/数据库暂时不可读或格式不兼容：稍后重试；第三次仍无法确认则不通知。
- 文件/数据库读取时间另计，不保证严格在 3 秒内结束。

此实现仍**尚未部署**，不是上述 TUI 接入。它能过滤已观察到的续跑，却不能证明未来不会续跑；通知后才续跑仍可能误报，完成记录过晚仍可能漏报。单元测试不能替代真实终端验收。自编译 TUI 出口保留为后续可选方向，不是本轮部署前提。

## 本轮自动验证

- `PYTHONUTF8=1 python -m unittest discover -s tests -p 'test_*.py'`：42 项，成功，2 项平台相关跳过。
- `dotnet run --project tests/windows/WindowsTests.csproj`：116 项检查通过（包含 Pi 共享助手回归）。
- `node --test tests/pi/*.test.mjs`：14 项通过。
- `git diff --check`：通过。

轮询单元测试使用模拟等待，不消耗真实的 1–3 秒；覆盖首次/第二次/第三次成功、续跑和取消终止、读失败恢复、次数耗尽、原始 notify chaining，以及其他通知不进入轮询。本轮未重新安装助手，未重跑真实 Codex 长任务或系统通知点击验收。

## 后续验收清单

- 普通一次性任务：真实结束后正常通知，无固定 3 秒等待。
- Stop hook 要求当前 turn 续跑：中间 Stop 不通知，最终结束通知一次。
- 非 goal 排队输入：中间 turn 不通知，队列执行结束后通知一次。
- active goal：中间 turn 不通知；最终成功与 blocked/受限等需区别提示。
- 历史回放、线程切换、realtime delegation：不生成过期或串会话通知。
- 取消、错误：不标记为成功完成。
- 前台/后台、双窗口、最小化、窗口关闭和通知点击定位。
- 助手缺失、失败、超时：不影响 Codex；不泄露对话正文。
