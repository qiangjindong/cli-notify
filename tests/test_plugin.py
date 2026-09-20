import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import plugin
from native import install_plugin_trust, uninstall_plugin_trust


ROOT = Path(__file__).resolve().parents[1]
EVENTS = {
    'SessionStart': '^(startup|resume|clear|compact)$',
    'PreToolUse': '(^|.*[._])request_user_input$',
    'PermissionRequest': '.*',
    'PostCompact': '^(manual|auto)$',
    'Stop': None,
}


class PluginTests(unittest.TestCase):
    def test_personal_marketplace_is_preserved_and_update_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp, patch('pathlib.Path.home',return_value=Path(temp)):
            marketplace=Path(temp)/'.agents/plugins/marketplace.json'
            marketplace.parent.mkdir(parents=True)
            original={'name':'personal','interface':{'displayName':'My Plugins'},'plugins':[
                {'name':'keep','source':{'source':'local','path':'./plugins/keep'},
                 'policy':{'installation':'AVAILABLE','authentication':'ON_INSTALL'},'category':'Other'}]}
            marketplace.write_text(json.dumps(original))
            first=plugin.prepare_marketplace();second=plugin.prepare_marketplace()
            document=json.loads(marketplace.read_text())
            self.assertFalse(first['marketplace_created']);self.assertEqual(first,second)
            self.assertEqual(document['interface']['displayName'],'My Plugins')
            self.assertEqual([entry['name'] for entry in document['plugins']],['keep',plugin.NAME])
            source=Path(first['plugin_source'])
            self.assertEqual(source,Path(temp)/'plugins'/plugin.NAME)
            self.assertTrue((source/plugin.OWNED).is_file())
            version=json.loads((source/'.codex-plugin/plugin.json').read_text())['version']
            self.assertRegex(version,r'^0\.1\.0\+codex\.[0-9a-f]{16}$')

    def test_personal_marketplace_collision_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp, patch('pathlib.Path.home',return_value=Path(temp)):
            marketplace=Path(temp)/'.agents/plugins/marketplace.json';marketplace.parent.mkdir(parents=True)
            marketplace.write_text(json.dumps({'name':'personal','plugins':[{
                'name':plugin.NAME,'source':{'source':'local','path':'./different'}}]}))
            with self.assertRaisesRegex(ValueError,'different codex-win-notify'):
                plugin.prepare_marketplace()

    def test_uninstall_preserves_other_marketplace_entries(self):
        with tempfile.TemporaryDirectory() as temp, patch('pathlib.Path.home',return_value=Path(temp)), \
                patch('plugin.subprocess.run') as run, patch.dict(os.environ,{'CODEX_HOME':str(Path(temp)/'.codex')}):
            marketplace=Path(temp)/'.agents/plugins/marketplace.json';marketplace.parent.mkdir(parents=True)
            marketplace.write_text(json.dumps({'name':'personal','plugins':[{
                'name':'keep','source':{'source':'local','path':'./plugins/keep'}}]}))
            installation=plugin.prepare_marketplace();installation['plugin_id']='codex-win-notify@personal'
            entries=[(f'codex-win-notify@personal:hooks/hooks.json:event_{i}:0:0','sha256:'+str(i)*64) for i in range(5)]
            install_plugin_trust(installation['plugin_id'],entries)
            self.assertTrue(plugin.uninstall_plugin(installation))
            document=json.loads(marketplace.read_text())
            self.assertEqual([entry['name'] for entry in document['plugins']],['keep'])
            self.assertFalse(Path(installation['plugin_source']).exists())
            self.assertNotIn('codex-win-notify-plugin-trust',(Path(temp)/'.codex/config.toml').read_text())
            run.assert_called_once_with(['codex','plugin','remove','codex-win-notify@personal'],check=True)

    def test_plugin_trust_block_roundtrip_preserves_other_configuration(self):
        entries=[(f'codex-win-notify@personal:hooks/hooks.json:event_{i}:0:0','sha256:'+str(i)*64) for i in range(5)]
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'CODEX_HOME':temp}):
            config=Path(temp)/'config.toml';original='model="test"\n[hooks.state.keep]\ntrusted_hash="original"\n'
            config.write_text(original)
            install_plugin_trust('codex-win-notify@personal',entries)
            installed=config.read_text()
            self.assertIn('codex-win-notify-plugin-trust',installed)
            self.assertIn('[hooks.state.keep]',installed)
            install_plugin_trust('codex-win-notify@personal',entries)
            self.assertEqual(config.read_text(),installed)
            uninstall_plugin_trust()
            self.assertEqual(config.read_text(),original)

    def test_manifest_and_default_hook_file(self):
        manifest = json.loads((ROOT/'.codex-plugin/plugin.json').read_text())
        self.assertEqual(manifest['name'], ROOT.name)
        self.assertNotIn('hooks', manifest)
        self.assertTrue((ROOT/'hooks/hooks.json').is_file())

    def test_plugin_hooks_cover_notification_events(self):
        document = json.loads((ROOT/'hooks/hooks.json').read_text())
        self.assertEqual(set(document['hooks']), set(EVENTS))
        commands = set()
        windows_commands = set()
        for event, matcher in EVENTS.items():
            groups = document['hooks'][event]
            self.assertEqual(len(groups), 1)
            group = groups[0]
            if matcher is None:
                self.assertNotIn('matcher', group)
            else:
                self.assertEqual(group['matcher'], matcher)
            self.assertEqual(len(group['hooks']), 1)
            handler = group['hooks'][0]
            self.assertEqual(handler['type'], 'command')
            self.assertEqual(handler['timeout'], 2)
            self.assertFalse(handler['async'])
            commands.add(handler['command'])
            windows_commands.add(handler['commandWindows'])
        self.assertEqual(commands, {'python3 "${PLUGIN_ROOT}/bridge.py" native'})
        self.assertEqual(len(windows_commands), 1)

    def test_windows_hook_uses_installed_helper_and_preserves_utf8_stdio(self):
        document = json.loads((ROOT/'hooks/hooks.json').read_text())
        command = document['hooks']['Stop'][0]['hooks'][0]['commandWindows']
        encoded = command.rsplit(' ', 1)[1]
        script = base64.b64decode(encoded).decode('utf-16le')
        self.assertIn("GetFolderPath('LocalApplicationData')", script)
        self.assertIn(r"CodexWinNotify\app\CodexWinNotify.exe", script)
        self.assertIn("Arguments='--hook'", script)
        self.assertIn('StandardOutputEncoding=[Text.Encoding]::UTF8', script)
        self.assertIn('[Console]::InputEncoding=[Text.Encoding]::UTF8', script)


if __name__ == '__main__':
    unittest.main()
