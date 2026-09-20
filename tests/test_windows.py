"""Windows integration tests. Build Release first; no user config changes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rpc import Client
from clients import register, release

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT/'windows/bin/Release/net9.0-windows10.0.17763.0'

@unittest.skipUnless(os.name == 'nt', 'Windows integration')
class WindowsTests(unittest.TestCase):
    def test_config_trust_roundtrip_and_cmd_quoting(self):
        with tempfile.TemporaryDirectory(prefix='CWN 中文 & 空格 ') as folder:
            root = Path(folder)
            app = root/'app'
            shutil.copytree(BUILD, app)
            exe = app/'CodexWinNotify.exe'
            home = root/'home'; home.mkdir()
            config = home/'config.toml'
            old = '# keep\nnotify=["original"]\n[[hooks.Stop]]\n[[hooks.Stop.hooks]]\ntype="command"\ncommand="echo original"\n'
            config.write_text(old, encoding='utf-8')
            def configure(action):
                subprocess.run([exe, '--configure', action, home], check=True, timeout=15)
            configure('install'); first = config.read_bytes(); configure('install')
            self.assertEqual(first, config.read_bytes())
            with Client(env={**os.environ, 'CODEX_HOME':str(home)}) as c:
                entry = c.call('hooks/list', {'cwds':[str(home)]})['data'][0]
                self.assertEqual(entry['errors'], [])
                hooks = [h for h in entry['hooks'] if '-EncodedCommand' in h.get('command', '')]
                self.assertEqual(len(hooks), 5)
                self.assertTrue(all(h['trustStatus'] == 'trusted' for h in hooks), hooks)
                original = next(h for h in entry['hooks'] if h.get('command') == 'echo original')
                self.assertEqual(original['trustStatus'], 'untrusted')
            command = tomllib.loads(first.decode())['hooks']['Stop'][-1]['hooks'][0]['command_windows']
            # Empty session avoids window capture and dispatch; Stop must still reply.
            result = subprocess.run([os.environ['COMSPEC'], '/d', '/s', '/c', command],
                input=json.dumps({'hook_event_name':'Stop','last_assistant_message':'PRIVATE'}),
                text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), '{}')
            self.assertEqual(result.stderr, '')
            configure('uninstall'); self.assertEqual(config.read_text(encoding='utf-8'), old)

    def test_bad_hook_fails_open(self):
        for payload in ('not-json', '{}', '{"hook_event_name":"Stop","session_id":"s"}'):
            result = subprocess.run([BUILD/'CodexWinNotify.exe', '--hook'], input=payload,
                capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0)
            self.assertNotIn('Exception', result.stderr)

class ClientTests(unittest.TestCase):
    def test_uninstall_retains_other_client(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = register(root, root/'one/config.toml')
            second = register(root, root/'two/config.toml')
            self.assertNotEqual(first, second)
            self.assertFalse(release(root, first))
            (root/'clients/windows.json').write_text('{}')
            self.assertFalse(release(root, second))
            (root/'clients/windows.json').unlink()
            self.assertTrue(release(root, second))
