#!/usr/bin/env python3
"""Fail-open Codex event bridge. Never logs conversation content."""
import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parent

def log(kind, result, payload=None):
    try:
        path = Path(os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state'))) / 'codex-win-notify'
        path.mkdir(parents=True, exist_ok=True)
        row = {'id':os.environ.get('CWN_ID',''), 'kind':kind, 'result':result}
        payload=payload or {}
        for field,alias in (('thread-id','session_id'),('turn-id','turn_id')):
            value=payload.get(field,payload.get(alias))
            if isinstance(value, str): row[field] = value
        with (path/'bridge.log').open('a') as f:
            f.write(json.dumps(row)+'\n')
    except Exception:
        pass

def user_completion(payload):
    """0.155.0 internal review turns share notify, but aren't user threads.

    Do not bind to the first notification: an internal turn can finish first.
    Read only thread provenance, never conversation content. If provenance is
    unavailable, suppress our toast while still chaining the original handler.
    """
    thread = payload.get('thread-id')
    if not isinstance(thread, str) or not thread: return False
    home = Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex')))
    try:
        with closing(sqlite3.connect((home/'state_5.sqlite').resolve().as_uri()+'?mode=ro', uri=True, timeout=.25)) as db:
            row = db.execute('SELECT thread_source FROM threads WHERE id = ?', (thread,)).fetchone()
        return row == ('user',)
    except (OSError, sqlite3.Error) as exc:
        log('completion-origin', type(exc).__name__, payload)
        return False

def send(kind, payload=None):
    payload = payload or {}
    identifiers = [payload.get(k) for k in ('session_id','thread-id','turn-id','tool_use_id','tool_call_id')]
    if kind=='approval': identifiers.extend([payload.get('turn_id'),payload.get('request_id')])
    key = hashlib.sha256(json.dumps(identifiers).encode()).hexdigest() if any(identifiers) else ''
    event = {'Id':os.environ['CWN_ID'], 'Kind':kind, 'Cwd':Path(os.environ.get('CWN_CWD',os.getcwd())).name, 'Key':key}
    try:
        result = subprocess.run([os.environ['CWN_HELPER'],'--send'], input=json.dumps(event,ensure_ascii=False), text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
        log(kind, 'sent' if result.returncode==0 else 'helper-failed', payload)
    except Exception as exc:
        log(kind, type(exc).__name__, payload)

def main():
    kind = sys.argv[1]
    if kind=='question':
        try:
            payload=json.load(sys.stdin)
            if payload.get('tool_name','').endswith('request_user_input'):
                identifiers={k:payload.get(k) for k in ('session_id','tool_use_id','tool_call_id')}
                subprocess.Popen([sys.executable,str(ROOT/'bridge.py'),'question-worker',json.dumps(identifiers)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        except Exception as exc:
            log(kind,type(exc).__name__)
    elif kind=='approval':
        try:
            payload=json.load(sys.stdin)
            if payload.get('hook_event_name')=='PermissionRequest':
                identifiers={k:payload.get(k) for k in ('session_id','turn_id','tool_use_id','tool_call_id')}
                # PermissionRequest has no stable request id in 0.155.0. Two
                # approvals of the same command in one turn are distinct waits.
                identifiers['request_id']=uuid.uuid4().hex
                subprocess.Popen([sys.executable,str(ROOT/'bridge.py'),'approval-worker',json.dumps(identifiers)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        except Exception as exc:
            log(kind,type(exc).__name__)
    elif kind=='approval-worker':
        payload=json.loads(sys.argv[2])
        if user_completion({'thread-id':payload.get('session_id')}): send('approval',payload)
        else: log('approval','internal-or-unknown-suppressed',payload)
    elif kind=='question-worker': send('question',json.loads(sys.argv[2]))
    elif kind=='complete':
        raw=sys.argv[-1]
        try:
            payload=json.loads(raw)
            if payload.get('type')=='agent-turn-complete':
                if user_completion(payload): send('complete',payload)
                else: log('complete', 'internal-or-unknown-suppressed', payload)
        except Exception as exc:
            log(kind,type(exc).__name__)
        # Original handler receives the unmodified notify argument.
        try:
            original=json.loads(os.environ.get('CWN_ORIGINAL_NOTIFY','[]'))
            if original:
                subprocess.Popen(original+[raw],stdin=subprocess.DEVNULL)
        except Exception as exc:
            log('original-notify',type(exc).__name__)
    elif kind=='register': send('register')

if __name__=='__main__':
    try: main()
    except Exception as exc: log('bridge',type(exc).__name__)
    # Hooks always succeed; no output changes tool behavior.
