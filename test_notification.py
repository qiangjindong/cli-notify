#!/usr/bin/env python3
"""Send a real desktop notification without starting Codex."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent

def helper_path():
    record = ROOT/'installation.json'
    if not record.is_file():
        raise RuntimeError('尚未安装，请先运行 ./install.sh。')
    try:
        helper = Path(json.loads(record.read_text())['helper'])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError('安装记录无效，请重新运行 ./install.sh。') from exc
    if not helper.is_file():
        raise RuntimeError('通知程序不存在，请重新运行 ./install.sh。')
    return helper

def main():
    try:
        subprocess.run([str(helper_path()), '--test'], check=True, timeout=15)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f'测试通知发送失败：{exc}') from exc
    print('测试通知已发送。点击通知应返回当前终端。')

if __name__ == '__main__':
    main()
