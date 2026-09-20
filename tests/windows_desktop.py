"""Two native Windows Terminal fixtures; synthetic hooks, no model requests.

Run after install.ps1, or pass --helper pointing at a published helper.
Only the fixtures open windows. Real toast clicks remain manual acceptance.
"""
import ctypes
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid

ROOT = Path(__file__).resolve().parents[1]
STATE = Path(os.environ['LOCALAPPDATA'])/'CodexWinNotify'
USER32 = ctypes.windll.user32
USER32.GetForegroundWindow.restype = ctypes.c_void_p
USER32.ShowWindowAsync.argtypes = [ctypes.c_void_p, ctypes.c_int]
USER32.IsIconic.argtypes = [ctypes.c_void_p]
USER32.SetForegroundWindow.argtypes = [ctypes.c_void_p]

def wait_for(predicate, seconds=15):
    deadline = time.monotonic()+seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result: return result
        time.sleep(.1)
    raise TimeoutError('Desktop fixture did not respond')

def worker(folder):
    folder = Path(folder)
    try:
        request = json.loads((folder/'request.json').read_text(encoding='utf-8'))
        os.environ['CODEX_HOME'] = request['home']
        command = request['command']
        def hook(name):
            payload = {'hook_event_name':name, 'session_id':request['session'], 'turn_id':uuid.uuid4().hex,
                       'tool_name':'functions.request_user_input', 'cwd':str(folder), 'tool_input':'PRIVATE'}
            invocation = [request['helper'], '--hook'] if request.get('direct') else [os.environ['COMSPEC'], '/d', '/s', '/c', command]
            result = subprocess.run(invocation,
                input=json.dumps(payload), capture_output=True, text=True, timeout=5)
            assert result.returncode == 0, result.stderr
            assert result.stdout.strip() == ('{}' if name == 'Stop' else ''), result.stdout
        hook('SessionStart')
        (folder/'ready').touch()
        while not (folder/'stop').exists():
            task = folder/'event.json'
            if task.exists():
                event = json.loads(task.read_text()); task.unlink()
                hook(event['name']); (folder/'done').touch()
            time.sleep(.1)
    except Exception as exc:
        (folder/'error.txt').write_text(str(exc), encoding='utf-8')
        raise

def main():
    helper = Path(sys.argv[sys.argv.index('--helper')+1]) if '--helper' in sys.argv else STATE/'app/CodexWinNotify.exe'
    helper = helper.resolve()
    previous = USER32.GetForegroundWindow()
    ids = []; folders = []
    def send(ident, kind):
        subprocess.run([helper, '--send'], input=json.dumps({'Id':ident,'Kind':kind}), text=True, check=True, timeout=15)
    def windows():
        try: return json.loads((STATE/'windows.json').read_text(encoding='utf-8'))
        except (FileNotFoundError, json.JSONDecodeError): return {}
    def results(ident, kind):
        return [x['result'] for line in (STATE/'helper.log').read_text(encoding='utf-8').splitlines()
                if (x:=json.loads(line))['id']==ident and x['kind']==kind]
    with tempfile.TemporaryDirectory(prefix='CWN 原生 桌面 ') as temp:
        home = Path(temp)
        subprocess.run([helper, '--configure', 'install', home], check=True)
        command = tomllib.loads((home/'config.toml').read_text(encoding='utf-8'))['hooks']['Stop'][0]['hooks'][0]['command_windows']
        try:
            for i in range(2):
                folder = home/str(i); folder.mkdir(); folders.append(folder)
                session = uuid.uuid4().hex; ident = hashlib.sha256(session.encode()).hexdigest()[:32]; ids.append(ident)
                with closing(sqlite3.connect(home/'state_5.sqlite')) as db:
                    db.execute('CREATE TABLE IF NOT EXISTS threads (id TEXT, thread_source TEXT, name TEXT)')
                    db.execute('INSERT INTO threads VALUES (?, ?, ?)', (session, 'user', f'原生测试线程 {i+1}'))
                    db.commit()
                (folder/'request.json').write_text(json.dumps({'home':str(home),'session':session,'command':command,'helper':str(helper),'direct':'--direct' in sys.argv}), encoding='utf-8')
                subprocess.run(['wt.exe','-w','CWN-'+uuid.uuid4().hex,'new-tab',sys.executable,str(Path(__file__).resolve()),'--worker',str(folder)], check=True)
                wait_for(lambda: (folder/'ready').exists() or (folder/'error.txt').exists())
                if (folder/'error.txt').exists(): raise RuntimeError((folder/'error.txt').read_text())
                wait_for(lambda: ident in windows())
            assert len({windows()[i]['Hwnd'] for i in ids}) == 2, 'Wrong window association'
            if '--registration-only' in sys.argv:
                print('PASS: synthetic SessionStart hooks registered two distinct native Windows Terminal windows.')
                return
            time.sleep(2) # Let asynchronous Terminal startup/activation settle.
            if '--background-only' in sys.argv:
                USER32.SetForegroundWindow(previous)
                wait_for(lambda: USER32.GetForegroundWindow() not in {windows()[i]['Hwnd'] for i in ids})
                time.sleep(.5)
                for target, ident in enumerate(ids):
                    for name, kind in [('Stop','complete'),('PreToolUse','question'),('PermissionRequest','approval'),('PostCompact','compact')]:
                        folder = folders[target]
                        before = len(results(ident,kind)); foreground = USER32.GetForegroundWindow()
                        (folder/'done').unlink(missing_ok=True)
                        (folder/'event.json').write_text(json.dumps({'name':name}))
                        wait_for(lambda: (folder/'done').exists())
                        wait_for(lambda: len(results(ident,kind)) > before)
                        assert results(ident,kind)[-1] == 'notified'
                        assert USER32.GetForegroundWindow() == foreground, ('Background hook changed foreground', foreground, USER32.GetForegroundWindow())
                print('PASS: all four synthetic hooks from both background windows; foreground unchanged.')
                return
            for index, ident in enumerate(ids):
                h = windows()[ident]['Hwnd']
                USER32.SetForegroundWindow(h)
                wait_for(lambda: USER32.GetForegroundWindow() == h)
                time.sleep(.3)
                for name, kind in [('Stop','complete'),('PreToolUse','question'),('PermissionRequest','approval'),('PostCompact','compact')]:
                    for target, expected in [(index,'foreground-suppressed'),(1-index,'notified')]:
                        folder = folders[target]; target_id = ids[target]
                        before = len(results(target_id,kind))
                        foreground = USER32.GetForegroundWindow()
                        (folder/'done').unlink(missing_ok=True)
                        (folder/'event.json').write_text(json.dumps({'name':name}))
                        wait_for(lambda: (folder/'done').exists())
                        wait_for(lambda: len(results(target_id,kind)) > before)
                        assert results(target_id,kind)[-1] == expected, (expected, results(target_id,kind), foreground, USER32.GetForegroundWindow(), windows())
                        assert USER32.GetForegroundWindow() == foreground, 'Notification stole focus'
                USER32.ShowWindowAsync(h,6)
                wait_for(lambda: USER32.IsIconic(h))
                send(ident,'focus')
                wait_for(lambda: not USER32.IsIconic(h))
            print('PASS: two native windows; all four hooks foreground/background; no focus stealing; minimized restore.')
        finally:
            for ident in ids:
                try: send(ident,'forget')
                except Exception: pass
            for folder in folders: (folder/'stop').touch()
            if previous: USER32.SetForegroundWindow(previous)
            time.sleep(1)

if __name__ == '__main__':
    if '--worker' in sys.argv: worker(sys.argv[sys.argv.index('--worker')+1])
    else: main()
