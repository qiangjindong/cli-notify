#!/usr/bin/env python3
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parent

def main():
    install=json.loads((ROOT/'installation.json').read_text())
    helper=Path(install['helper'])
    helperwin=subprocess.check_output(['wslpath','-w',str(helper)],text=True).strip()
    ps='/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'
    # Only terminate the exact installed helper executable.
    literal="'"+helperwin.replace("'","''")+"'"
    subprocess.run([ps,'-NoProfile','-Command',f'Get-Process CodexWinNotify -ErrorAction SilentlyContinue | Where-Object {{ $_.Path -eq {literal} }} | Stop-Process -Force'],check=True)
    subprocess.run([str(helper),'--uninstall'],check=True,timeout=15)
    dest=Path(install['root'])
    if dest.name!='CodexWinNotify' or helper.parent.parent!=dest: raise RuntimeError('Unexpected installation path')
    shutil.rmtree(dest)
    link=Path.home()/'.local/bin/codex-window'
    if link.is_symlink() and link.resolve()==ROOT/'codex-window': link.unlink()
    state=Path(__import__('os').environ.get('XDG_STATE_HOME',str(Path.home()/'.local/state')))/'codex-win-notify'
    if state.exists(): shutil.rmtree(state)
    (ROOT/'installation.json').unlink()
    print('已卸载。Codex 原有配置及项目源码保留。')
if __name__=='__main__': main()
