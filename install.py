#!/usr/bin/env python3
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parent
PS='/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'
def query(script): return subprocess.check_output([PS,'-NoProfile','-Command',script],text=True).strip()
def main():
    local=query('[Environment]::GetFolderPath("LocalApplicationData")')
    wt=query('(Get-Command wt.exe).Source')
    dest=Path(subprocess.check_output(['wslpath','-u',local],text=True).strip())/'CodexWinNotify'
    build=dest/'build'
    build.mkdir(parents=True,exist_ok=True)
    for name in ('Program.cs','CodexWinNotify.csproj'): shutil.copy2(ROOT/'windows'/name,build/name)
    project=subprocess.check_output(['wslpath','-w',str(build/'CodexWinNotify.csproj')],text=True).strip()
    output=subprocess.check_output(['wslpath','-w',str(dest/'app')],text=True).strip()
    helper_path=dest/'app/CodexWinNotify.exe'
    if helper_path.exists():
        winpath=subprocess.check_output(['wslpath','-w',str(helper_path)],text=True).strip()
        literal="'"+winpath.replace("'","''")+"'"
        subprocess.run([PS,'-NoProfile','-Command',f'Get-Process CodexWinNotify -ErrorAction SilentlyContinue | Where-Object {{ $_.Path -eq {literal} }} | Stop-Process -Force'],check=True)
    subprocess.run(['/mnt/c/Program Files/dotnet/dotnet.exe' ,'publish',project,'-c','Release','-r','win-x64','--self-contained','false','-o',output],check=True)
    helper=str(dest/'app/CodexWinNotify.exe')
    wtlinux=subprocess.check_output(['wslpath','-u',wt],text=True).strip()
    (ROOT/'installation.json').write_text(json.dumps({'helper':helper,'wt':wtlinux,'root':str(dest)}))
    from native import install_hooks
    install_hooks()
    link=Path.home()/'.local/bin/codex-window'
    if link.is_symlink() and link.resolve()==ROOT/'codex-window': link.unlink()
    print('已安装。重新启动原始 codex 即可使用提醒。')
if __name__=='__main__': main()
