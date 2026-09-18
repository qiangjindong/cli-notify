import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import bridge
from native import install_hooks, uninstall_hooks
from rpc import Client

class NativeTests(unittest.TestCase):
    def test_failed_registration_does_not_use_stale_window(self):
        payload={'session_id':'main','turn_id':'turn','cwd':'/tmp/native'}
        with patch.object(sys,'argv',['bridge.py','native-worker','complete',json.dumps(payload)]),patch('bridge.user_completion',return_value=True),patch('bridge.send',return_value=False) as send,patch('bridge.log'),patch.dict(os.environ,{}):
            bridge.main()
            send.assert_called_once_with('register',payload)

    def test_old_launcher_does_not_duplicate_global_hooks(self):
        from session import run
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'CODEX_HOME':temp}),patch('session.os.chdir'),patch('session.os.execv') as execute,patch('session.send') as send:
            install_hooks()
            run({'cwd':temp,'codex':'/bin/codex','args':['resume','--last']})
            execute.assert_called_once_with('/bin/codex',['/bin/codex','resume','--last'])
            send.assert_not_called()

    def test_install_idempotent_trusted_and_uninstall_preserves_config(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'CODEX_HOME':temp}):
            path=Path(temp)/'config.toml'
            old='notify=["/bin/true"]\n[[hooks.PreToolUse]]\nmatcher="Bash"\n[[hooks.PreToolUse.hooks]]\ntype="command"\ncommand="/bin/true"\n'
            path.write_text(old)
            install_hooks(); first=path.read_text(); install_hooks()
            self.assertEqual(first,path.read_text())
            self.assertEqual(tomllib.loads(first)['notify'],['/bin/true'])
            with Client() as c:
                entry=c.call('hooks/list',{'cwds':[temp]})['data'][0]
                self.assertFalse(entry['errors'])
                ours=[h for h in entry['hooks'] if 'bridge.py native' in h.get('command','')]
                self.assertEqual(len(ours),5)
                self.assertTrue(all(h['trustStatus']=='trusted' for h in ours),ours)
                self.assertTrue(any(h.get('command')=='/bin/true' and h['trustStatus']=='untrusted' for h in entry['hooks']))
            uninstall_hooks();self.assertEqual(path.read_text(),old)

    def test_native_detaches_private_payload_and_stop_returns_json(self):
        payload={'hook_event_name':'Stop','session_id':'main','turn_id':'turn','cwd':'/tmp/test','last_assistant_message':'PRIVATE'}
        with patch('bridge.json.load',return_value=payload),patch.object(sys,'argv',['bridge.py','native']),patch('bridge.subprocess.Popen') as worker,patch('builtins.print') as output:
            bridge.main()
            output.assert_called_once_with('{}')
            self.assertNotIn('PRIVATE',worker.call_args.args[0][-1])
            self.assertTrue(worker.call_args.kwargs['start_new_session'])

    def test_native_worker_ignores_inherited_window_and_notify(self):
        payload={'session_id':'main','turn_id':'turn','cwd':'/tmp/native'}
        with patch.dict(os.environ,{'CWN_ID':'old-window','CWN_CWD':'/old'}),patch.object(sys,'argv',['bridge.py','native-worker','complete',json.dumps(payload)]),patch('bridge.user_completion',return_value=True),patch('bridge.send') as send:
            bridge.main()
            self.assertNotEqual(os.environ['CWN_ID'],'old-window')
            self.assertEqual(os.environ['CWN_CWD'],'/tmp/native')
            self.assertEqual(send.call_args_list[0].args,('register',payload))
            self.assertEqual(send.call_args_list[1].args,('complete',{'thread-id':'main','turn-id':'turn'}))
