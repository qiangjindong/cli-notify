"""Install the notification hooks as a personal Codex plugin."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid

ROOT = Path(__file__).resolve().parent
NAME = 'codex-win-notify'
OWNED = '.codex-win-notify-owned'
SOURCE = './plugins/' + NAME
EVENTS = {'preToolUse', 'permissionRequest', 'postCompact', 'sessionStart', 'stop'}


def paths():
    marketplace_root = Path.home()/'.agents/plugins'
    return marketplace_root/'marketplace.json', Path.home()/'plugins'/NAME


def _manifest():
    manifest = json.loads((ROOT/'.codex-plugin/plugin.json').read_text())
    digest = hashlib.sha256()
    for path in (ROOT/'.codex-plugin/plugin.json', ROOT/'hooks/hooks.json', ROOT/'bridge.py'):
        digest.update(path.read_bytes())
    manifest['version'] = manifest['version'].split('+', 1)[0] + '+codex.' + digest.hexdigest()[:16]
    return manifest


def _write_json(path, value, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
        if mode is not None: temporary.chmod(mode)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_marketplace():
    marketplace, source = paths()
    if marketplace.is_symlink(): raise ValueError('Refusing to replace a symlinked personal marketplace')
    created = not marketplace.exists()
    if created:
        document = {'name':'personal', 'interface':{'displayName':'Personal'}, 'plugins':[]}
        mode = 0o600
    else:
        document = json.loads(marketplace.read_text())
        mode = marketplace.stat().st_mode & 0o777
    name = document.get('name')
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',name):
        raise ValueError('Invalid personal marketplace name')
    entries = document.get('plugins')
    if not isinstance(entries,list): raise ValueError('Invalid personal marketplace plugins list')
    expected = {'name':NAME, 'source':{'source':'local','path':SOURCE},
                'policy':{'installation':'AVAILABLE','authentication':'ON_INSTALL'}, 'category':'Productivity'}
    found = [entry for entry in entries if isinstance(entry,dict) and entry.get('name')==NAME]
    if len(found)>1: raise ValueError('Duplicate codex-win-notify marketplace entries')
    if found and found[0].get('source') != expected['source']:
        raise ValueError('A different codex-win-notify plugin already exists in the personal marketplace')
    if source.exists():
        if source.is_symlink() or not (source/OWNED).is_file():
            raise ValueError('Personal plugin source path is not owned by codex-win-notify')
        shutil.rmtree(source)
    (source/'.codex-plugin').mkdir(parents=True)
    (source/'hooks').mkdir()
    _write_json(source/'.codex-plugin/plugin.json', _manifest())
    shutil.copy2(ROOT/'hooks/hooks.json', source/'hooks/hooks.json')
    shutil.copy2(ROOT/'bridge.py', source/'bridge.py')
    (source/OWNED).write_text('managed by codex-win-notify\n')
    if found: entries[entries.index(found[0])] = expected
    else: entries.append(expected)
    _write_json(marketplace, document, mode)
    return {'marketplace':str(marketplace), 'marketplace_name':name,
            'plugin_source':str(source), 'marketplace_created':created}


def install_plugin(cwd):
    metadata = prepare_marketplace()
    selector = NAME+'@'+metadata['marketplace_name']
    from native import config_path, install_plugin_trust, uninstall_hooks, BEGIN
    config=config_path();existed=config.exists();old=config.read_text() if existed else ''
    try:
        def add():
            result=subprocess.run(['codex','plugin','add',selector,'--json'],text=True,
                                  stdout=subprocess.PIPE,check=True)
            return json.loads(result.stdout)['pluginId']
        plugin_id=add()
        if BEGIN in old:
            # Codex may place a new config table immediately before our legacy
            # end marker. Remove that block, then let plugin add write its table
            # once more outside the legacy-owned region.
            uninstall_hooks();plugin_id=add()
        from rpc import Client
        with Client(env=os.environ.copy()) as client:
            item=client.call('hooks/list',{'cwds':[str(cwd)]})['data'][0]
        hooks=[hook for hook in item['hooks'] if hook.get('pluginId')==plugin_id]
        if item['errors'] or len(hooks)!=5 or {hook['eventName'] for hook in hooks}!=EVENTS:
            raise RuntimeError('Codex did not load all codex-win-notify plugin hooks')
        install_plugin_trust(plugin_id,[(hook['key'],hook['currentHash']) for hook in hooks])
        with Client(env=os.environ.copy()) as client:
            item=client.call('hooks/list',{'cwds':[str(cwd)]})['data'][0]
        trusted=[hook for hook in item['hooks'] if hook.get('pluginId')==plugin_id]
        if len(trusted)!=5 or any(hook['trustStatus']!='trusted' for hook in trusted):
            raise RuntimeError('Codex did not trust all codex-win-notify plugin hooks')
        return {**metadata,'plugin_id':plugin_id}
    except Exception:
        if existed: config.write_text(old)
        else: config.unlink(missing_ok=True)
        raise


def uninstall_plugin(installation):
    plugin_id = installation.get('plugin_id')
    if not plugin_id: return False
    marketplace = Path(installation.get('marketplace',''))
    source = Path(installation.get('plugin_source',''))
    expected_marketplace, expected_source = paths()
    if (not isinstance(plugin_id,str) or not plugin_id.startswith(NAME+'@') or
            marketplace.resolve()!=expected_marketplace.resolve() or source.resolve()!=expected_source.resolve()):
        raise ValueError('Unexpected plugin installation paths')
    document=json.loads(marketplace.read_text())
    entries=document.get('plugins')
    if not isinstance(entries,list): raise ValueError('Invalid personal marketplace plugins list')
    owned = [entry for entry in entries if isinstance(entry,dict) and entry.get('name')==NAME and
             entry.get('source')=={'source':'local','path':SOURCE}]
    if len(owned)!=1 or source.is_symlink() or not (source/OWNED).is_file():
        raise ValueError('Personal plugin installation is not owned by codex-win-notify')
    subprocess.run(['codex','plugin','remove',plugin_id],check=True)
    from native import uninstall_plugin_trust
    uninstall_plugin_trust()
    document['plugins']=[entry for entry in entries if not (
        isinstance(entry,dict) and entry.get('name')==NAME and entry.get('source')=={'source':'local','path':SOURCE})]
    _write_json(marketplace,document,marketplace.stat().st_mode & 0o777)
    shutil.rmtree(source)
    return True
