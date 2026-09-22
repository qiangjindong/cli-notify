#!/usr/bin/env python3
"""Fail-open Codex event bridge. Never logs conversation content."""
import hashlib
from contextlib import closing
from enum import Enum, auto
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
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

def user_thread_name(payload):
    """0.155.0 internal review turns share notify, but aren't user threads.

    Do not bind to the first notification: an internal turn can finish first.
    Read only thread provenance and its display name, never conversation
    content. If provenance is unavailable, suppress our toast while still
    chaining the original handler.
    """
    thread = payload.get('thread-id', payload.get('session_id'))
    if not isinstance(thread, str) or not thread: return None
    home = Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex')))
    try:
        with closing(sqlite3.connect((home/'state_5.sqlite').resolve().as_uri()+'?mode=ro', uri=True, timeout=.25)) as db:
            row = db.execute('SELECT thread_source, name FROM threads WHERE id = ?', (thread,)).fetchone()
        if row is None or row[0] != 'user': return None
        return row[1] if isinstance(row[1], str) else ''
    except (OSError, sqlite3.Error) as exc:
        log('completion-origin', type(exc).__name__, payload)
        return None

class CompletionState(Enum):
    READY = auto()
    STOP = auto()
    RETRY = auto()


def goal_state(payload):
    """A completed turn may be an intermediate turn of an unfinished goal."""
    home = Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex')))
    path = home/'goals_1.sqlite'
    if not path.exists(): return CompletionState.READY  # Older Codex versions have no goals DB.
    thread = payload.get('thread-id', payload.get('session_id'))
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=.25)) as db:
            row = db.execute('SELECT status FROM thread_goals WHERE thread_id = ?', (thread,)).fetchone()
        return CompletionState.READY if row is None or row[0] == 'complete' else CompletionState.STOP
    except (OSError, sqlite3.Error) as exc:
        log('completion-goal', type(exc).__name__, payload)
        return CompletionState.RETRY

def turn_state(payload):
    thread = payload.get('thread-id', payload.get('session_id'))
    turn = payload.get('turn-id', payload.get('turn_id'))
    if not isinstance(turn, str) or not turn: return CompletionState.STOP
    home = Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex')))
    try:
        with closing(sqlite3.connect((home/'state_5.sqlite').resolve().as_uri()+'?mode=ro', uri=True, timeout=.25)) as db:
            row = db.execute('SELECT rollout_path FROM threads WHERE id = ?', (thread,)).fetchone()
        if not row: return CompletionState.RETRY
        with Path(row[0]).open('rb') as file:
            start = max(0, file.seek(0, 2) - 262144)
            file.seek(start)
            if start: file.readline()
            lines = file.read().splitlines()
        state = CompletionState.RETRY
        seen_turn = False
        for line in lines:
            event = json.loads(line)
            if event.get('type') != 'event_msg': continue
            data = event.get('payload', {})
            kind = data.get('type')
            if kind not in ('task_started', 'task_complete', 'turn_aborted'): continue
            event_turn = data.get('turn_id')
            if not isinstance(event_turn, str) or not event_turn:
                state = CompletionState.RETRY
                continue
            if event_turn != turn:
                if seen_turn: return CompletionState.STOP
                continue  # An older turn alone cannot prove continuation.
            seen_turn = True
            if kind == 'turn_aborted' or (kind == 'task_started' and state == CompletionState.READY):
                return CompletionState.STOP
            state = CompletionState.READY if kind == 'task_complete' else CompletionState.RETRY
        return state
    except (OSError, sqlite3.Error, ValueError, TypeError, AttributeError) as exc:
        log('completion-settled', type(exc).__name__, payload)
        return CompletionState.RETRY

def completion_state(payload):
    goal = goal_state(payload)
    if goal == CompletionState.STOP: return CompletionState.STOP
    turn = turn_state(payload)
    if turn == CompletionState.STOP: return CompletionState.STOP
    if goal == turn == CompletionState.READY: return CompletionState.READY
    return CompletionState.RETRY

def completion_ready(payload):
    # Sleep only in the worker/legacy notify path, never in the native hook.
    # Three attempts, not three consecutive successes; I/O adds to this delay.
    for _ in range(3):
        time.sleep(1)
        state = completion_state(payload)
        if state == CompletionState.READY: return True
        if state == CompletionState.STOP: return False
    return False

def send(kind, payload=None):
    payload = payload or {}
    identifiers = [payload.get(k) for k in ('session_id','thread-id','turn-id','tool_use_id','tool_call_id')]
    if kind in ('approval','compact'): identifiers.extend([payload.get('turn_id'),payload.get('request_id')])
    key = hashlib.sha256(json.dumps(identifiers).encode()).hexdigest() if any(identifiers) else ''
    event = {'Id':os.environ['CWN_ID'], 'Kind':kind, 'Cwd':Path(os.environ.get('CWN_CWD',os.getcwd())).name,
             'Key':key, 'ThreadName':payload.get('thread_name','')}
    try:
        result = subprocess.run([os.environ['CWN_HELPER'],'--send'], input=json.dumps(event,ensure_ascii=False), text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
        log(kind, 'sent' if result.returncode==0 else 'helper-failed', payload)
        return result.returncode==0
    except Exception as exc:
        log(kind, type(exc).__name__, payload)
        return False

def main():
    kind = sys.argv[1]
    if kind=='native':
        payload=json.load(sys.stdin)
        event=payload.get('hook_event_name')
        mapping={'SessionStart':'register','PreToolUse':'question','PermissionRequest':'approval','PostCompact':'compact','Stop':'complete'}
        if event not in mapping: return
        if event=='Stop': print('{}')
        if event=='PreToolUse' and not payload.get('tool_name','').endswith('request_user_input'): return
        identifiers={k:payload.get(k) for k in ('session_id','turn_id','tool_use_id','tool_call_id','cwd')}
        if not isinstance(identifiers['session_id'],str) or not identifiers['session_id']: return
        log('native-hook',event,identifiers)
        if event in ('PermissionRequest','PostCompact'): identifiers['request_id']=uuid.uuid4().hex
        subprocess.Popen([sys.executable,str(ROOT/'bridge.py'),'native-worker',mapping[event],json.dumps(identifiers)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    elif kind=='native-worker':
        event_kind=sys.argv[2]; payload=json.loads(sys.argv[3])
        install=json.loads((ROOT/'installation.json').read_text())
        os.environ.update(CWN_ID=hashlib.sha256(payload['session_id'].encode()).hexdigest()[:32],CWN_HELPER=install['helper'],CWN_CWD=payload.get('cwd') or os.getcwd())
        thread_name = '' if event_kind=='register' else user_thread_name(payload)
        if event_kind=='complete' and not completion_ready(payload):
            log(event_kind,'not-settled-or-goal-incomplete-suppressed',payload)
            return
        if event_kind=='register' or thread_name is not None:
            if event_kind!='register' and not send('register',payload):
                log(event_kind,'registration-failed',payload)
                return
            if event_kind=='complete':
                payload={'thread-id':payload['session_id'],'turn-id':payload.get('turn_id')}
            payload['thread_name']=thread_name
            send(event_kind,payload)
        else: log(event_kind,'internal-or-unknown-suppressed',payload)
    elif kind=='question':
        try:
            payload=json.load(sys.stdin)
            if payload.get('tool_name','').endswith('request_user_input'):
                identifiers={k:payload.get(k) for k in ('session_id','tool_use_id','tool_call_id')}
                subprocess.Popen([sys.executable,str(ROOT/'bridge.py'),'question-worker',json.dumps(identifiers)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        except Exception as exc:
            log(kind,type(exc).__name__)
    elif kind in ('approval','compact'):
        try:
            payload=json.load(sys.stdin)
            if payload.get('hook_event_name')=={'approval':'PermissionRequest','compact':'PostCompact'}[kind]:
                identifiers={k:payload.get(k) for k in ('session_id','turn_id','tool_use_id','tool_call_id')}
                # These hooks have no stable event id in 0.155.0. Repeated
                # approvals or compactions in one turn are distinct events.
                identifiers['request_id']=uuid.uuid4().hex
                subprocess.Popen([sys.executable,str(ROOT/'bridge.py'),kind+'-worker',json.dumps(identifiers)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        except Exception as exc:
            log(kind,type(exc).__name__)
    elif kind in ('approval-worker','compact-worker'):
        event_kind=kind.removesuffix('-worker')
        payload=json.loads(sys.argv[2])
        thread_name=user_thread_name(payload)
        if thread_name is not None:
            payload['thread_name']=thread_name
            send(event_kind,payload)
        else: log(event_kind,'internal-or-unknown-suppressed',payload)
    elif kind=='question-worker':
        payload=json.loads(sys.argv[2])
        thread_name=user_thread_name(payload)
        if thread_name is not None:
            payload['thread_name']=thread_name
            send('question',payload)
        else: log('question','internal-or-unknown-suppressed',payload)
    elif kind=='complete':
        raw=sys.argv[-1]
        try:
            payload=json.loads(raw)
            if payload.get('type')=='agent-turn-complete':
                thread_name=user_thread_name(payload)
                if thread_name is not None:
                    if completion_ready(payload):
                        payload['thread_name']=thread_name
                        send('complete',payload)
                    else: log('complete','not-settled-or-goal-incomplete-suppressed',payload)
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
