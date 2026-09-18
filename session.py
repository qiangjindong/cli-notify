#!/usr/bin/env python3
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from bridge import log, send

ROOT=Path(__file__).resolve().parent

def overrides(args):
    """Read CLI notify overrides so chaining preserves the user's effective handler."""
    values=[]
    for i,arg in enumerate(args):
        if arg in ('-c','--config') and i+1<len(args): values.append(args[i+1])
        elif arg.startswith('--config='): values.append(arg.split('=',1)[1])
        elif arg.startswith('-c') and arg!='-c': values.append(arg[2:])
    return values

def config_options(args):
    options=[]; i=0
    while i<len(args):
        arg=args[i]
        if arg in ('-c','--config','-p','--profile','--enable','--disable') and i+1<len(args):
            options.extend(args[i:i+2]); i+=2; continue
        if arg.startswith(('--config=','--profile=','--enable=','--disable=')) or (arg.startswith('-c') and len(arg)>2): options.append(arg)
        i+=1
    return options

def original_notify(cwd,args):
    # app-server does not accept --profile in 0.155.0. Resolve its user layer
    # in a temporary config home; Codex still resolves system/project/CLI layers.
    import tempfile
    import tomllib
    from rpc import Client
    options=config_options(args); profile=None; clean=[]; i=0
    while i<len(options):
        if options[i] in ('-p','--profile'):
            profile=options[i+1]; i+=2; continue
        if options[i].startswith('--profile='):
            profile=options[i].split('=',1)[1]; i+=1; continue
        clean.append(options[i]); i+=1
    if profile is None:
        with Client(clean) as client:
            return client.call('config/read',{'cwd':str(cwd),'includeLayers':False})['config'].get('notify') or []
    if Path(profile).name!=profile or profile in ('.','..'): raise ValueError('profile name')
    home=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))
    base=tomllib.loads((home/'config.toml').read_text()) if (home/'config.toml').exists() else {}
    selected=tomllib.loads((home/(profile+'.config.toml')).read_text())
    def merge(left,right):
        for key,value in right.items():
            if isinstance(value,dict) and isinstance(left.get(key),dict): merge(left[key],value)
            else: left[key]=value
    merge(base,selected)
    with tempfile.TemporaryDirectory(prefix='codex-win-notify-config-') as temporary:
        config=Path(temporary)/'config.toml'
        config.write_text('\n'.join(json.dumps(k)+'='+toml_value(v) for k,v in base.items()))
        config.chmod(0o600)
        env=os.environ.copy();env['CODEX_HOME']=temporary
        with Client(clean,env=env) as client:
            return client.call('config/read',{'cwd':str(cwd),'includeLayers':False})['config'].get('notify') or []

def toml_value(value):
    if isinstance(value, str): return json.dumps(value,ensure_ascii=False)
    if isinstance(value, bool): return 'true' if value else 'false'
    if isinstance(value, (int,float)): return str(value)
    if isinstance(value, list): return '['+','.join(toml_value(v) for v in value)+']'
    if isinstance(value, dict): return '{'+','.join(json.dumps(k)+'='+toml_value(v) for k,v in value.items())+'}'
    raise TypeError(type(value).__name__)

def hook_options(args=()):
    import tomllib
    existing={'PreToolUse':[], 'PermissionRequest':[], 'PostCompact':[]}; states={}
    for override in overrides(args):
        try: hooks=tomllib.loads(override).get('hooks',{})
        except tomllib.TOMLDecodeError: continue
        for event in existing:
            if event in hooks: existing[event]=hooks[event]
        if 'state' in hooks:
            for key,value in hooks['state'].items(): states.setdefault(key,{}).update(value)

    options=[]
    for event,event_name,kind,matcher in (
        ('PreToolUse','pre_tool_use','question','(^|.*[._])request_user_input$'),
        ('PermissionRequest','permission_request','approval','.*'),
        ('PostCompact','post_compact','compact','^(manual|auto)$'),
    ):
        command=shlex.join([sys.executable,str(ROOT/'bridge.py'),kind])
        handler={'type':'command','command':command,'timeout':2,'async':False}
        group={'matcher':matcher,'hooks':[handler]}
        identity={'event_name':event_name,**group}
        fingerprint='sha256:'+hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        key=f'/<session-flags>/config.toml:{event_name}:{len(existing[event])}:0'
        states[key]={'trusted_hash':fingerprint}
        options.extend(['-c','hooks.'+event+'='+toml_value([*existing[event],group])])
    return [*options,'-c','hooks.state='+toml_value(states)]

def run(req):
    os.environ.update(req.get('env',{}))
    os.chdir(req['cwd'])
    from native import BEGIN, config_path
    path=config_path()
    if path.exists() and BEGIN in path.read_text():
        # Compatibility with callers retaining the old launcher: global hooks
        # already provide notifications, so do not inject a second set.
        os.execv(req['codex'],[req['codex'],*req['args']])
        return
    os.environ.update(CWN_ID=req['id'],CWN_HELPER=req['helper'],CWN_CWD=req['cwd'])
    try: os.environ['CWN_ORIGINAL_NOTIFY']=json.dumps(original_notify(Path.cwd(),req['args']))
    except Exception as exc:
        log('configuration',type(exc).__name__)
        # Cannot safely chain unknown existing notify: run Codex unmodified.
        os.execv(req['codex'],[req['codex'],*req['args']])
    send('register')
    notify=[sys.executable,str(ROOT/'bridge.py'),'complete']
    # Trust only our exact hook for this process, preserving trust for other hooks.
    options=['-c','notify='+toml_value(notify),*hook_options(req['args'])]
    args=req['args']; split=args.index('--') if '--' in args else len(args)
    os.execv(req['codex'],[req['codex'],*args[:split],*options,*args[split:]])

def main():
    path=Path(sys.argv[1]); req=json.loads(path.read_text()); path.unlink()
    run(req)

if __name__=='__main__': main()
