#!/usr/bin/env python3
"""Exercise global config loading and native hook ingress in a real terminal.
Hook input is synthetic; this does not submit a model prompt.
"""
import hashlib
import json
import os
from pathlib import Path
import shlex
import sqlite3
import subprocess
import sys
import time
import uuid
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from rpc import Client
requestpath=Path(sys.argv[1]);request=json.loads(requestpath.read_text());requestpath.unlink()
terminal_env={k:os.environ.get(k) for k in ('WSL_INTEROP','WT_SESSION','WT_PROFILE_ID')}
os.environ.update(request['env'])
for key,value in terminal_env.items():
    if value is None: os.environ.pop(key,None)
    else: os.environ[key]=value
# Do not inherit window identities injected by an older launcher.
for key in tuple(os.environ):
    if key.startswith('CWN_'): os.environ.pop(key,None)
folder=Path(request['cwd']);os.chdir(folder)
try:
    with Client() as c:
        hooks=c.call('hooks/list',{'cwds':[str(folder)]})['data'][0]['hooks']
        ours=[h for h in hooks if 'bridge.py native' in h.get('command','')]
        assert len(ours)==5 and all(h['enabled'] and h['trustStatus']=='trusted' for h in ours)
    # Synthetic persisted provenance stays isolated from the user's state DB.
    thread=uuid.uuid4().hex
    os.environ['CODEX_HOME']=str(folder)
    with sqlite3.connect(folder/'state_5.sqlite') as db:
        db.execute('CREATE TABLE threads (id TEXT, thread_source TEXT)')
        db.execute('INSERT INTO threads VALUES (?, ?)',(thread,'user'))
    ident=hashlib.sha256(thread.encode()).hexdigest()[:32]
    install=json.loads((root/'installation.json').read_text())
    # Skip SessionStart to test lazy registration on the first notification.
    payload={'hook_event_name':'PermissionRequest','session_id':thread,'turn_id':'synthetic','cwd':str(folder)}
    command=shlex.join([sys.executable,str(root/'bridge.py'),'native'])
    subprocess.run(['/bin/sh','-c',command],input=json.dumps(payload),text=True,check=True)
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        path=Path(install['root'])/'windows.json'
        if path.exists() and ident in json.loads(path.read_text()):
            (folder/'result.json').write_text(json.dumps({'id':ident,'thread':thread}))
            break
        time.sleep(.2)
    else: raise RuntimeError('Native hook failed to register terminal window')
    while not (folder/'stop').exists(): time.sleep(.2)
except Exception as exc:
    (folder/'error.txt').write_text(str(exc))
    raise
