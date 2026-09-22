# CLI Notify

Codex / Pi 在后台完成任务、等待你回答或等待审批时，向 Windows 发送通知。点击通知即可回到原来的终端窗口。

通知第一行显示 Codex 线程名称，第二行显示状态，例如：

```text
补充 PDF 预览并验收
Codex 已完成
```

线程名称为空时，第一行回退为当前工作目录名。

## 安装

### Windows 原生 Codex（验证性实现）

需要 Windows 原生 Codex、Windows Terminal 和 Windows .NET 9 SDK，不需要 Python。在 PowerShell 中进入项目目录运行：

```powershell
.\install.ps1
```

默认修改 `%USERPROFILE%\.codex\config.toml`；设置了 `CODEX_HOME` 时使用该目录，也可传入 `-CodexHome`。安装后重启 Codex，仍直接运行 `codex`。

已验证构建、配置/信任、安装卸载和两个原生终端的合成 hook 窗口登记。真实 Codex 双窗口、通知点击及两种 sandbox 模式尚未完成验收，详见技术说明。

### WSL

先确认你正在 **WSL Ubuntu** 终端中，并已安装：

- Windows Terminal
- Windows .NET 9 SDK
- WSL 中的 Python 3.11 或更高版本

然后进入本项目目录，只运行这一条命令：

```sh
./install.sh
```

看到“安装完成”后，关闭当前 Codex，再重新运行 `codex`。以后仍然照常使用 Codex，不需要改命令。

## Pi coding agent

新增 Pi extension，复用 Windows 通知与窗口关联后端，支持后台完成、等待输入、压缩和错误提醒，点击通知尝试回到原终端窗口。

目前支持 **Windows 原生 Pi + Windows Terminal**（每窗口单标签页、无分屏），无需安装 Codex。在 PowerShell 中进入本仓库：

```powershell
.\install-pi.ps1
pi install .
```

重启 Pi 或 `/reload`，运行 `/cli-notify-test` 发送不消耗模型额度的测试通知。Pi 不读取 Codex 数据库，也不修改 Codex 配置。

安装、卸载、限制及桌面验收见 [Pi 扩展说明](docs/pi.md)。真实 Pi 窗口捕获与系统通知点击仍需按该文档验收。

## 通知图标

默认使用 `assets/cli-notify.png`。如需替换，编辑仓库根目录的 `cli-notify.json`：

```json
{
  "notification": {
    "icon": "/你的/图标路径/icon.png"
  }
}
```

支持 PNG；相对路径以仓库根目录为基准。安装器会将图片转换并嵌入通知程序，使其显示在通知标题栏的应用图标位置，不会占用正文。设为 `null` 可恢复 Windows 默认应用图标。修改后重新运行 `./install.sh`（Windows 原生安装则运行 `.\install.ps1`）即可生效。

## 测试通知

无需启动 Codex 或调用模型即可发送测试通知：

Windows：

```powershell
.\test.ps1
```

WSL：

```sh
./test.sh
```

测试通知会在当前终端位于前台时照常显示。点击通知应返回当前 Windows Terminal，用于验证通知发送和窗口关联；该命令不消耗 Codex 模型额度。

如果安装失败，安装器会说明缺少什么。最常见的问题是 Windows 没有安装 [.NET 9 SDK](https://dotnet.microsoft.com/download/dotnet/9.0)。

## 从 codex-win-notify 升级

本仓库由 `codex-win-notify` 重命名而来；旧仓库保留作为归档，不再更新。程序名、配置文件名、安装路径和配置标记均已改为 `CliNotify` / `cli-notify`。

- **配置块会原地替换**：安装器识别旧版写入的 `codex-win-notify-windows`（WSL 侧为 `codex-win-notify`）标记块，先移除再写入新块，不会叠加两份 hooks。直接运行 `.\install.ps1` 或 `./install.sh` 即可。
- **旧安装目录不会自动清理**：`%LOCALAPPDATA%\CodexWinNotify` 会保留。确认其中不再有 WSL client（`clients\wsl-*.json`）后可以删除；若仍有旧版 WSL 安装，请先在 WSL 中运行旧版 `./uninstall.sh`。
- **旧 Toast 应用身份会残留**：通知身份按 exe 路径注册，旧条目会留在「设置 → 系统 → 通知」列表里。需要彻底清除时，先运行旧版 `uninstall.ps1`（或 `./uninstall.sh`）再安装新版。
- 旧助手进程 `CodexWinNotify.exe` 可能仍在后台驻留，但不再接收新事件；可手动结束，或由旧版卸载脚本清理。
- 不要再用旧源码目录重新安装，否则会把共享助手降级回旧版；升级后请只使用本仓库的安装器。

## 卸载

在本项目目录运行：

Windows：

```powershell
.\uninstall.ps1
```

WSL：

```sh
./uninstall.sh
```

卸载不会删除本项目源码，也不会改动你原有的 Codex 配置。

## 使用限制

WSL 基线为 Ubuntu、Codex 0.155.0；Windows 原生扩展针对 Codex 0.155.1 实现。每个 Windows Terminal 窗口请只使用一个标签页且不要分屏，否则通知可能无法定位到正确位置。

WSL 和 Windows 必须使用独立的 Codex Home。共存时先更新 WSL 侧源码并重新安装，让两侧都使用带 client 清单的新卸载器；旧版 WSL 卸载器会无条件删除共享助手。新版只在最后一个 client 卸载时清除共享助手。

安装和卸载均不需要管理员权限。hook 输入仅在内存中解析；通知载荷会包含线程名称，但后台日志不记录线程名称、问题、回答、命令或 Codex 完成文本。

开发、实现原理、日志和验收说明见 [技术说明](docs/technical.md)。
