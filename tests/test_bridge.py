import json
from contextlib import closing
import os
from pathlib import Path
import subprocess
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import bridge
from rpc import Client
from session import hook_options,original_notify,toml_value

class BridgeTests(unittest.TestCase):
    def test_event_excludes_question_and_answer(self):
        payload={'session_id':'s','tool_use_id':'t','tool_input':{'question':'PRIVATE QUESTION'},'answers':['PRIVATE ANSWER']}
        with patch.dict(os.environ,{'CWN_ID':'a'*32,'CWN_HELPER':'helper','CWN_CWD':'/tmp/中文 空格'}),patch('bridge.subprocess.run') as run,patch('bridge.log'):
            run.return_value.returncode=0
            bridge.send('question',payload)
            event=json.loads(run.call_args.kwargs['input'])
            self.assertEqual(event['Cwd'],'中文 空格')
            self.assertNotIn('PRIVATE',run.call_args.kwargs['input'])
    def test_failure_does_not_raise(self):
        with patch.dict(os.environ,{'CWN_ID':'a'*32,'CWN_HELPER':'missing'}),patch('bridge.subprocess.run',side_effect=OSError),patch('bridge.log') as log:
            bridge.send('complete')
            log.assert_called_once_with('complete','OSError',{})
    def test_question_hook_returns_before_slow_worker(self):
        with tempfile.TemporaryDirectory() as temp:
            env=os.environ.copy();env.update(CWN_ID='a'*32,CWN_HELPER='/missing',XDG_STATE_HOME=temp)
            start=time.monotonic()
            p=subprocess.run([sys.executable,str(bridge.ROOT/'bridge.py'),'question'],input=json.dumps({'tool_name':'functions.request_user_input','tool_use_id':'t'}),text=True,capture_output=True,env=env)
            self.assertEqual(p.returncode,0);self.assertEqual(p.stdout,'');self.assertLess(time.monotonic()-start,1)
    def test_approval_hook_detaches_and_omits_command(self):
        payload={'hook_event_name':'PermissionRequest','session_id':'main','turn_id':'turn','tool_name':'Bash','tool_input':{'command':'PRIVATE COMMAND','description':'PRIVATE REASON'}}
        with patch('bridge.json.load',return_value=payload),patch.object(sys,'argv',['bridge.py','approval']),patch('bridge.subprocess.Popen') as worker:
            bridge.main();bridge.main()
            calls=worker.call_args_list
            first=json.loads(calls[0].args[0][-1]);second=json.loads(calls[1].args[0][-1])
            self.assertEqual(first['session_id'],'main')
            self.assertNotEqual(first['request_id'],second['request_id'])
            self.assertNotIn('PRIVATE',calls[0].args[0][-1])
            self.assertTrue(calls[0].kwargs['start_new_session'])
            self.assertEqual(calls[0].kwargs['stdout'],subprocess.DEVNULL)

    def test_approval_hook_returns_no_permission_decision(self):
        with tempfile.TemporaryDirectory() as temp:
            env=os.environ.copy();env.update(CODEX_HOME=temp,XDG_STATE_HOME=temp,CWN_ID='a'*32,CWN_HELPER='/missing')
            start=time.monotonic()
            p=subprocess.run([sys.executable,str(bridge.ROOT/'bridge.py'),'approval'],input=json.dumps({'hook_event_name':'PermissionRequest','session_id':'missing'}),text=True,capture_output=True,env=env)
            self.assertEqual(p.returncode,0);self.assertEqual(p.stdout,'');self.assertEqual(p.stderr,'')
            self.assertLess(time.monotonic()-start,1)

    def test_approval_worker_filters_internal_threads(self):
        for user in (False,True):
            with self.subTest(user=user),patch.object(sys,'argv',['bridge.py','approval-worker',json.dumps({'session_id':'thread','turn_id':'turn','request_id':'request'})]),patch('bridge.user_completion',return_value=user),patch('bridge.send') as send,patch('bridge.log'):
                bridge.main()
                self.assertEqual(send.called,user)
                if user:self.assertEqual(send.call_args.args[0],'approval')

    def test_approval_events_are_private_and_distinct_per_request(self):
        with patch.dict(os.environ,{'CWN_ID':'a'*32,'CWN_HELPER':'helper'}),patch('bridge.subprocess.run') as run,patch('bridge.log'):
            run.return_value.returncode=0
            keys=[]
            for request in ('first','second'):
                bridge.send('approval',{'session_id':'main','turn_id':'turn','request_id':request,'tool_input':{'command':'PRIVATE'}})
                raw=run.call_args.kwargs['input'];event=json.loads(raw)
                self.assertEqual(event['Kind'],'approval');self.assertNotIn('PRIVATE',raw)
                keys.append(event['Key'])
            self.assertNotEqual(*keys)
    def test_compaction_detaches_and_filters_internal_threads(self):
        payload={'hook_event_name':'PostCompact','session_id':'main','turn_id':'turn','trigger':'auto','transcript_path':'PRIVATE'}
        with patch('bridge.json.load',return_value=payload),patch.object(sys,'argv',['bridge.py','compact']),patch('bridge.subprocess.Popen') as worker:
            bridge.main();bridge.main()
            calls=worker.call_args_list
            self.assertEqual(calls[0].args[0][-2],'compact-worker')
            self.assertNotIn('PRIVATE',calls[0].args[0][-1])
            self.assertNotEqual(json.loads(calls[0].args[0][-1])['request_id'],json.loads(calls[1].args[0][-1])['request_id'])
        for user in (False,True):
            with self.subTest(user=user),patch.object(sys,'argv',['bridge.py','compact-worker',calls[0].args[0][-1]]),patch('bridge.user_completion',return_value=user),patch('bridge.send') as send,patch('bridge.log'):
                bridge.main()
                self.assertEqual(send.called,user)
                if user:self.assertEqual(send.call_args.args[0],'compact')

    def test_original_notify_receives_exact_payload(self):
        raw=json.dumps({'type':'agent-turn-complete','last-assistant-message':'中文\nquote"'},ensure_ascii=False)
        with patch.dict(os.environ,{'CWN_ORIGINAL_NOTIFY':json.dumps(['original','--arg'])}),patch.object(sys,'argv',['bridge.py','complete',raw]),patch('bridge.send'),patch('bridge.subprocess.Popen') as popen:
            bridge.main();self.assertEqual(popen.call_args.args[0],['original','--arg',raw])

    def test_internal_completion_before_user_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            with closing(sqlite3.connect(str(Path(temp)/'state_5.sqlite'))) as db, db:
                db.execute('CREATE TABLE threads (id TEXT, source TEXT, thread_source TEXT)')
                db.executemany('INSERT INTO threads VALUES (?, ?, ?)',[
                    ('main', 'cli', 'user'), ('child', '{"subagent":"review"}', 'subagent')])
            with patch.dict(os.environ,{'CODEX_HOME':temp,'CWN_ORIGINAL_NOTIFY':'["original"]'}),patch('bridge.send') as send,patch('bridge.log') as log,patch('bridge.subprocess.Popen') as original:
                for thread in ('ephemeral-review', 'child', 'main'):
                    payload={'type':'agent-turn-complete','thread-id':thread,'turn-id':'turn','last-assistant-message':'PRIVATE'}
                    raw=json.dumps(payload)
                    with patch.object(sys,'argv',['bridge.py','complete',raw]): bridge.main()
                    self.assertEqual(original.call_args.args[0],['original',raw])
                self.assertEqual(send.call_count,1)
                self.assertEqual(send.call_args.args[1]['thread-id'],'main')
                self.assertEqual(log.call_count,2)

    def test_missing_or_incompatible_origin_database_suppresses_toast(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'CODEX_HOME':temp}),patch('bridge.log'):
            payload={'thread-id':'main'}
            self.assertFalse(bridge.user_completion(payload))
            self.assertFalse((Path(temp)/'state_5.sqlite').exists())
            with closing(sqlite3.connect(str(Path(temp)/'state_5.sqlite'))) as db, db:
                db.execute('CREATE TABLE threads (id TEXT)')
            self.assertFalse(bridge.user_completion(payload))
            self.assertFalse(bridge.user_completion({}))

    def test_origin_failure_still_chains_original_notify(self):
        raw=json.dumps({'type':'agent-turn-complete','thread-id':'main'})
        with patch.dict(os.environ,{'CWN_ORIGINAL_NOTIFY':'["original"]'}),patch.object(sys,'argv',['bridge.py','complete',raw]),patch('bridge.user_completion',return_value=False),patch('bridge.send') as send,patch('bridge.log'),patch('bridge.subprocess.Popen') as original:
            bridge.main()
            send.assert_not_called()
            self.assertEqual(original.call_args.args[0],['original',raw])

    def test_log_records_identity_without_conversation(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'XDG_STATE_HOME':temp}):
            bridge.log('complete','internal-or-unknown-suppressed',{'thread-id':'thread','turn-id':'turn','last-assistant-message':'PRIVATE'})
            text=(Path(temp)/'codex-win-notify/bridge.log').read_text()
            self.assertNotIn('PRIVATE',text)
            self.assertEqual(json.loads(text)['thread-id'],'thread')
    def test_cli_hooks_preserved(self):
        group={'matcher':'Bash','hooks':[{'type':'command','command':'/bin/true'}]}
        args=['-c','hooks.PreToolUse='+toml_value([group]),'-c','hooks.state='+toml_value({'custom':{'enabled':False}})]
        import tomllib
        options=hook_options(args)
        parsed=tomllib.loads(options[1])
        self.assertEqual(parsed['hooks']['PreToolUse'][0],group)
        state=tomllib.loads(options[-1])['hooks']['state']
        self.assertEqual(state['custom'],{'enabled':False})
        self.assertIn('/<session-flags>/config.toml:pre_tool_use:1:0',state)

    def test_cli_approval_hooks_and_trust_preserved(self):
        import tomllib
        group={'matcher':'Bash','hooks':[{'type':'command','command':'/bin/true'}]}
        options=hook_options(['-c','hooks.PermissionRequest='+toml_value([group]),'-c','hooks.state='+toml_value({'existing':{'enabled':False,'trusted_hash':'original'}})])
        groups=tomllib.loads(options[3])['hooks']['PermissionRequest']
        self.assertEqual(groups[0],group)
        self.assertEqual(groups[1]['matcher'],'.*')
        state=tomllib.loads(options[-1])['hooks']['state']
        self.assertEqual(state['existing'],{'enabled':False,'trusted_hash':'original'})
        self.assertIn('/<session-flags>/config.toml:permission_request:1:0',state)

    def test_launcher_runs_in_current_process(self):
        import importlib.machinery
        import importlib.util
        loader=importlib.machinery.SourceFileLoader('launcher',str(bridge.ROOT/'codex-window'))
        spec=importlib.util.spec_from_loader(loader.name,loader)
        launcher=importlib.util.module_from_spec(spec)
        loader.exec_module(launcher)
        with patch('pathlib.Path.read_text',return_value='{"helper":"test-helper"}'), patch.object(launcher,'run') as run, patch.object(launcher.shutil,'which',return_value='/bin/codex'), patch.object(sys,'argv',['codex-window','resume','--last']):
            launcher.main()
            req=run.call_args.args[0]
            self.assertEqual(req['cwd'],os.getcwd())
            self.assertEqual(req['args'],['resume','--last'])
            self.assertEqual(req['codex'],'/bin/codex')
            self.assertNotIn('env',req)

    @unittest.skipIf(os.name == 'nt', 'WSL session-flag trust uses POSIX paths')
    def test_existing_config_hooks_and_notify_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp)
            original=['/bin/true','original-notify']
            cfg='notify='+toml_value(original)+'\n[[hooks.PreToolUse]]\nmatcher="Bash"\n[[hooks.PreToolUse.hooks]]\ntype="command"\ncommand="/bin/true"\n'
            (home/'config.toml').write_text(cfg)
            (home/'named.config.toml').write_text('notify=["/bin/true","profile"]\n')
            with patch.dict(os.environ,{'CODEX_HOME':temp}):
                self.assertEqual(original_notify(home,[]),original)
                self.assertEqual(original_notify(home,['-p','named']),['/bin/true','profile'])
                self.assertEqual(original_notify(home,['-c','notify=["/bin/true","override"]']),['/bin/true','override'])
                with Client(hook_options()) as c:
                    hooks=c.call('hooks/list',{'cwds':[temp]})['data'][0]['hooks']
                    self.assertTrue(any(h['command']=='/bin/true' and h['trustStatus']=='untrusted' for h in hooks))
                    self.assertTrue(any(h['source']=='sessionFlags' and h['trustStatus']=='trusted' for h in hooks))
                    for event in ('preToolUse','permissionRequest','postCompact'):
                        self.assertTrue(any(h['source']=='sessionFlags' and h['eventName']==event and h['trustStatus']=='trusted' for h in hooks),hooks)
                self.assertEqual((home/'config.toml').read_text(),cfg)

if __name__=='__main__': unittest.main()
