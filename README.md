# WSL Codex Windows 通知

Codex 在后台完成任务、等待你回答或等待审批时，向 Windows 发送通知。点击通知即可回到原来的终端窗口。

## 安装

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

```sh
./uninstall.sh
```

卸载不会删除本项目源码，也不会改动你原有的 Codex 配置。

## 使用限制

目前支持 WSL Ubuntu、Windows Terminal 和 Codex 0.155.0。每个 Windows Terminal 窗口请只使用一个标签页且不要分屏，否则通知可能无法定位到正确位置。

安装和卸载均不需要管理员权限。程序不会读取或发送你的问题、回答、命令或 Codex 输出。

开发、实现原理、日志和验收说明见 [技术说明](docs/technical.md)。
