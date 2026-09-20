#!/usr/bin/env python3
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parent

def main():
    from native import uninstall_hooks, config_path
    install=json.loads((ROOT/'installation.json').read_text())
    if install.get('home') and str(config_path().parent.resolve()) != install['home']:
        raise RuntimeError('CODEX_HOME does not match the installed WSL client')
    helper=Path(install['helper'])
    dest=Path(install['root'])
    if dest.name!='CodexWinNotify' or helper.parent.parent!=dest: raise RuntimeError('Unexpected installation path')
    from clients import installation_lock, release
    with installation_lock(dest):
        uninstall_hooks()
        if release(dest, install.get('client')):
            from clients import stop_helper
            stop_helper(helper)
            subprocess.run([str(helper),'--uninstall'],check=True,timeout=15)
            for child in dest.iterdir():
                if child.name == 'install.lock': continue
                if child.is_dir(): shutil.rmtree(child)
                else: child.unlink()
        elif not any((dest/'clients').glob('wsl-*.json')) and (dest/'build').exists():
            shutil.rmtree(dest/'build')
    link=Path.home()/'.local/bin/codex-window'
    if link.is_symlink() and link.resolve()==ROOT/'codex-window': link.unlink()
    state=Path(__import__('os').environ.get('XDG_STATE_HOME',str(Path.home()/'.local/state')))/'codex-win-notify'
    if state.exists(): shutil.rmtree(state)
    (ROOT/'installation.json').unlink()
    print('已卸载。Codex 原有配置及项目源码保留。')
if __name__=='__main__': main()
