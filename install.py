#!/usr/bin/env python3
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
PS='/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'

class InstallError(RuntimeError):
    pass

def query(script):
    return subprocess.check_output(
        [PS, '-NoProfile', '-Command', script], text=True, stderr=subprocess.STDOUT
    ).strip()

def check_requirements():
    if sys.version_info < (3, 11):
        raise InstallError('WSL 中需要 Python 3.11 或更高版本。')
    if 'microsoft' not in Path('/proc/sys/kernel/osrelease').read_text().lower():
        raise InstallError('请在 WSL Ubuntu 终端中运行 ./install.sh。')
    if not Path(PS).is_file() or not shutil.which('wslpath'):
        raise InstallError('WSL 的 Windows 互操作不可用，请先在 WSL 中确认 powershell.exe 可以运行。')
    dotnet = Path('/mnt/c/Program Files/dotnet/dotnet.exe')
    if not dotnet.is_file():
        raise InstallError('Windows 中未找到 .NET 9 SDK。请安装后重新运行 ./install.sh。')
    try:
        sdks = subprocess.check_output([dotnet, '--list-sdks'], text=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as exc:
        raise InstallError('无法运行 Windows .NET SDK。') from exc
    if not any(line.startswith('9.') for line in sdks.splitlines()):
        raise InstallError('Windows 中未找到 .NET 9 SDK。请安装后重新运行 ./install.sh。')

def main():
    print('[1/4] 检查运行环境…')
    check_requirements()
    from settings import notification_icon
    try:
        icon = notification_icon(ROOT)
    except ValueError as exc:
        raise InstallError(str(exc)) from exc
    from native import config_path
    record = ROOT/'installation.json'
    if record.exists():
        previous = json.loads(record.read_text())
        if previous.get('home') and previous['home'] != str(config_path().parent.resolve()):
            raise InstallError('切换 CODEX_HOME 前，请先卸载此源码目录安装的 WSL client。')
    print('[2/4] 查找 Windows Terminal…')
    local=query('[Environment]::GetFolderPath("LocalApplicationData")')
    try:
        wt=query('(Get-Command wt.exe -ErrorAction Stop).Source')
    except subprocess.CalledProcessError as exc:
        raise InstallError('Windows 中未找到 Windows Terminal，请安装后重新运行 ./install.sh。') from exc
    dest=Path(subprocess.check_output(['wslpath','-u',local],text=True).strip())/'CodexWinNotify'
    from clients import installation_lock
    with installation_lock(dest):
        build=dest/'build'
        build.mkdir(parents=True,exist_ok=True)
        for source in (ROOT/'windows').glob('*.cs'): shutil.copy2(source,build/source.name)
        shutil.copy2(ROOT/'windows/CodexWinNotify.csproj',build/'CodexWinNotify.csproj')
        project=subprocess.check_output(['wslpath','-w',str(build/'CodexWinNotify.csproj')],text=True).strip()
        output=subprocess.check_output(['wslpath','-w',str(dest/'app')],text=True).strip()
        app_icon=build/'app.ico'
        publish=['/mnt/c/Program Files/dotnet/dotnet.exe','publish',project,'-c','Release','-r','win-x64','--self-contained','false','-o',output]
        if icon is None:
            app_icon.unlink(missing_ok=True)
        else:
            icon_input=subprocess.check_output(['wslpath','-w',str(icon)],text=True).strip()
            icon_output=subprocess.check_output(['wslpath','-w',str(app_icon)],text=True).strip()
            icon_script=subprocess.check_output(['wslpath','-w',str(ROOT/'windows/make-icon.ps1')],text=True).strip()
            subprocess.run([PS,'-NoProfile','-ExecutionPolicy','Bypass','-File',icon_script,icon_input,icon_output],check=True)
            publish.append(f'-p:ApplicationIcon={icon_output}')
        helper_path=dest/'app/CodexWinNotify.exe'
        if helper_path.exists():
            from clients import stop_helper
            stop_helper(helper_path)
        print('[3/4] 构建并安装通知程序（首次运行可能需要几分钟）…')
        subprocess.run(publish,check=True)
        for old_icon in dest.glob('notification-icon-*.png'):
            old_icon.unlink()
        (dest/'notification-icon.png').unlink(missing_ok=True)
        helper=str(dest/'app/CodexWinNotify.exe')
        wtlinux=subprocess.check_output(['wslpath','-u',wt],text=True).strip()
        print('[4/4] 配置 Codex 提醒…')
        from native import config_path
        from clients import register
        client = register(dest, config_path())
        installation={'helper':helper,'wt':wtlinux,'root':str(dest),'client':client,'home':str(config_path().parent.resolve())}
        (ROOT/'installation.json').write_text(json.dumps(installation))
        state=Path(__import__('os').environ.get('XDG_STATE_HOME',str(Path.home()/'.local/state')))/'codex-win-notify'
        state.mkdir(parents=True,exist_ok=True)
        runtime_record=state/'installation.json'
        runtime_record.write_text(json.dumps(installation))
        runtime_record.chmod(0o600)
        from plugin import install_plugin
        installation.update(install_plugin(Path.cwd()))
        (ROOT/'installation.json').write_text(json.dumps(installation))
        runtime_record.write_text(json.dumps(installation))
    link=Path.home()/'.local/bin/codex-window'
    if link.is_symlink() and link.resolve()==ROOT/'codex-window': link.unlink()
    print('\n安装完成。请关闭所有正在运行的 Codex，再重新运行 codex 以加载通知 plugin。')

if __name__=='__main__':
    try:
        main()
    except InstallError as exc:
        print(f'\n安装未完成：{exc}', file=sys.stderr)
        raise SystemExit(1)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stdout or '').strip() if isinstance(exc.stdout, str) else ''
        print('\n安装未完成：外部程序运行失败。', file=sys.stderr)
        if detail:
            print(detail, file=sys.stderr)
        print('请检查网络连接以及上方错误信息，然后重新运行 ./install.sh。', file=sys.stderr)
        raise SystemExit(1)
