"""Install reversible user-level hooks for the unmodified Codex CLI."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys
import tomllib

ROOT = Path(__file__).resolve().parent
BEGIN = '# BEGIN cli-notify\n'
END = '# END cli-notify\n'
# Markers written by the pre-rename codex-win-notify release. Recognized so an
# upgrade replaces the old block in place instead of stacking a second one.
LEGACY_BEGIN = '# BEGIN codex-win-notify\n'
LEGACY_END = '# END codex-win-notify\n'
WINDOWS_MARKERS = ('# BEGIN cli-notify-windows', '# BEGIN codex-win-notify-windows')
EVENTS = (
    ('SessionStart', 'session_start', '^(startup|resume|clear|compact)$'),
    ('PreToolUse', 'pre_tool_use', '(^|.*[._])request_user_input$'),
    ('PermissionRequest', 'permission_request', '.*'),
    ('PostCompact', 'post_compact', '^(manual|auto)$'),
    ('Stop', 'stop', None),
)

def config_path():
    return Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex')))/'config.toml'

def cut_block(text, begin, end):
    if begin not in text: return text
    before, rest = text.split(begin, 1)
    if end not in rest: raise ValueError(f'Incomplete {begin.strip()} configuration block')
    _, after = rest.split(end, 1)
    return before + after

def remove_block(text):
    return cut_block(cut_block(text, LEGACY_BEGIN, LEGACY_END), BEGIN, END)

def install_hooks():
    path = config_path()
    old = path.read_text() if path.exists() else ''
    base = remove_block(old)
    if any(marker in base for marker in WINDOWS_MARKERS):
        raise ValueError('WSL and Windows must use separate CODEX_HOME directories')
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
    if old and not (path.parent/'cli-notify.config.backup').exists():
        backup=path.parent/'cli-notify.config.backup'
        backup.write_text(old); backup.chmod(0o600)
    path.write_text(result)
    path.chmod(0o600)

def uninstall_hooks():
    path = config_path()
    if path.exists():
        old=path.read_text(); new=remove_block(old)
        if new!=old: path.write_text(new)
