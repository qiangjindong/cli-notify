"""Install reversible user-level hooks for the unmodified Codex CLI."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys
import tomllib

ROOT = Path(__file__).resolve().parent
BEGIN = '# BEGIN codex-win-notify\n'
END = '# END codex-win-notify\n'
EVENTS = (
    ('SessionStart', 'session_start', '^(startup|resume|clear|compact)$'),
    ('PreToolUse', 'pre_tool_use', '(^|.*[._])request_user_input$'),
    ('PermissionRequest', 'permission_request', '.*'),
    ('PostCompact', 'post_compact', '^(manual|auto)$'),
    ('Stop', 'stop', None),
)

def config_path():
    return Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex')))/'config.toml'

def remove_block(text):
    if BEGIN not in text: return text
    before, rest = text.split(BEGIN, 1)
    if END not in rest: raise ValueError('Incomplete codex-win-notify configuration block')
    _, after = rest.split(END, 1)
    return before + after

def install_hooks():
    path = config_path()
    old = path.read_text() if path.exists() else ''
    base = remove_block(old)
    config = tomllib.loads(base)
    hooks = config.get('hooks', {})
    from session import toml_value
    lines = [BEGIN.rstrip('\n')]
    for event, name, matcher in EVENTS:
        handler = {'type':'command', 'command':shlex.join([sys.executable,str(ROOT/'bridge.py'),'native']), 'timeout':2, 'async':False}
        group = {'hooks':[handler]}
        if matcher is not None: group['matcher'] = matcher
        index = len(hooks.get(event, []))
        identity = {'event_name':name, **group}
        fingerprint = 'sha256:'+hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        key = f'{path.resolve()}:{name}:{index}:0'
        if key in hooks.get('state', {}): raise ValueError('Hook trust key already owned by another configuration')
        lines.extend([f'[[hooks.{event}]]'])
        if matcher is not None: lines.append('matcher='+toml_value(matcher))
        lines.extend([f'[[hooks.{event}.hooks]]', *[k+'='+toml_value(v) for k,v in handler.items()],
                      '[hooks.state.'+json.dumps(key)+']', 'trusted_hash='+json.dumps(fingerprint)])
    lines.append(END.rstrip('\n'))
    result = base + ('' if not base or base.endswith('\n') else '\n') + '\n'.join(lines)+'\n'
    tomllib.loads(result)
    path.parent.mkdir(parents=True,exist_ok=True)
    if old and not (path.parent/'codex-win-notify.config.backup').exists():
        backup=path.parent/'codex-win-notify.config.backup'
        backup.write_text(old); backup.chmod(0o600)
    path.write_text(result)
    path.chmod(0o600)

def uninstall_hooks():
    path = config_path()
    if path.exists():
        old=path.read_text(); new=remove_block(old)
        if new!=old: path.write_text(new)
