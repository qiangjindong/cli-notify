#!/usr/bin/env python3
"""Opens two temporary Windows Terminal windows and tests helper behavior.
Focus command exercises the activation handler; actual toast clicks are manual.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid
root=Path(__file__).resolve().parents[1]
install=json.loads((root/'installation.json').read_text())
helper=install['helper']; winroot=Path(install['root'])
ps='/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'

def native(expression):
    script='Add-Type -TypeDefinition @"\nusing System; using System.Runtime.InteropServices; public class CWNTest { [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow(); [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h); [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr h,int n); [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h); }\n"@\n'+expression
    return subprocess.check_output([ps,'-NoProfile','-Command',script],text=True).strip()

def send(ident,kind,key=''):
    subprocess.run([helper,'--send'],input=json.dumps({'Id':ident,'Kind':kind,'Key':key}),text=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True,timeout=10)

def logs(ident,kind):
    return [json.loads(line)['result'] for line in (winroot/'helper.log').read_text().splitlines() if (row:=json.loads(line))['id']==ident and row['kind']==kind]

old=native('[CWNTest]::GetForegroundWindow().ToInt64()')
folders=[]; ids=[]; report=[]
try:
    for i in range(2):
        folder=Path(tempfile.mkdtemp(prefix="CWN 中文 空格 '\" "));folders.append(folder)
        testargs=['中文 空格', 'quote\" and single\'', 'line1\nline2', '$(touch /tmp/CWN_SHOULD_NOT_EXIST); &']
        request=Path('/tmp')/('cwn-launch-'+uuid.uuid4().hex+'.json'); request.write_text(json.dumps({'args':testargs,'cwd':str(folder),'env':dict(os.environ)}))
        # Only this test creates windows; the launcher runs within each test terminal.
        args=[install['wt'],'-w','CWN-test-'+uuid.uuid4().hex,'new-tab','wsl.exe','-d',os.environ['WSL_DISTRO_NAME'],
              '--cd','/tmp','--exec',sys.executable,str(root/'tests/launch_fixture.py'),str(request)]
        subprocess.run(args,check=True)
        deadline=time.monotonic()+20
        while not (folder/'result.json').exists() and time.monotonic()<deadline: time.sleep(.2)
        result=json.loads((folder/'result.json').read_text()); assert result['args'][:len(testargs)]==testargs;assert result['cwd']==str(folder)
        ids.append(result['id'])
    windows=json.loads((winroot/'windows.json').read_text())
    assert len({windows[ident]['Hwnd'] for ident in ids})==2, 'Test terminals must register different windows'
    for ident in ids:
        send(ident,'focus'); time.sleep(.3)
        foreground=int(native('[CWNTest]::GetForegroundWindow().ToInt64()'))
        if foreground==windows[ident]['Hwnd']:
            for kind in ('complete','question','approval'):
                send(ident,kind,uuid.uuid4().hex);assert logs(ident,kind)[-1]=='foreground-suppressed'
            report.append('foreground complete/question/approval suppressed: '+ident)
        else: report.append('focus denied; taskbar fallback: '+ident)
        # Windows may deny Focus; choose a window that is actually background.
        foreground=int(native('[CWNTest]::GetForegroundWindow().ToInt64()'))
        other=next(x for x in ids if windows[x]['Hwnd']!=foreground)
        for kind in ('complete','question','approval'):
            front_before=native('[CWNTest]::GetForegroundWindow().ToInt64()')
            key=uuid.uuid4().hex;send(other,kind,key)
            assert logs(other,kind)[-1]=='notified',logs(other,kind)
            assert native('[CWNTest]::GetForegroundWindow().ToInt64()')==front_before
            send(other,kind,key);assert logs(other,kind)[-1]=='duplicate'
        report.append('background notifications, no focus stealing, dedup: '+other)
    h=windows[ids[0]]['Hwnd']
    native(f'[CWNTest]::ShowWindowAsync([IntPtr]{h},6)');time.sleep(.3)
    assert native(f'[CWNTest]::IsIconic([IntPtr]{h})')=='True'
    send(ids[0],'focus');time.sleep(.3)
    assert native(f'[CWNTest]::IsIconic([IntPtr]{h})')=='False'
    report.append('minimized window restored')
    # Restart the helper, then exercise the exact persisted activation path.
    helperwin=subprocess.check_output(['wslpath','-w',helper],text=True).strip()
    literal="'"+helperwin.replace("'","''")+"'"
    subprocess.run([ps,'-NoProfile','-Command',f'Get-Process CodexWinNotify -ErrorAction SilentlyContinue | Where-Object {{ $_.Path -eq {literal} }} | Stop-Process -Force'],check=True)
    send(ids[1],'focus');assert logs(ids[1],'click')[-1] in ('focused','foreground-denied-flashed')
    report.append('persisted window identity survives helper restart')
    for folder in folders: (folder/'stop').touch()
    time.sleep(2)
    for ident in ids:
        send(ident,'focus');assert logs(ident,'click')[-1]=='closed'
    report.append('closed terminals detected without reopening')
    report.append('Chinese, spaces, quotes and multiline arguments passed exactly')
    print('\n'.join(report))
    (root/'tests/desktop-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
finally:
    for folder in folders: (folder/'stop').touch()
    for ident in ids:
        try: send(ident,'forget')
        except Exception: pass
    if int(old): native(f'[CWNTest]::SetForegroundWindow([IntPtr]{old})')
    import shutil
    for folder in folders: shutil.rmtree(folder,ignore_errors=True)
