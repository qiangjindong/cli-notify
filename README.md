# Codex Windows 通知

Codex 在后台完成任务、等待你回答或等待审批时，向 Windows 发送通知。点击通知即可回到原来的终端窗口。

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

如果安装失败，安装器会说明缺少什么。最常见的问题是 Windows 没有安装 [.NET 9 SDK](https://dotnet.microsoft.com/download/dotnet/9.0)。

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

安装和卸载均不需要管理员权限。hook 输入仅在内存中解析；后台事件和日志不保留问题、回答、命令或 Codex 完成文本。

开发、实现原理、日志和验收说明见 [技术说明](docs/technical.md)。
