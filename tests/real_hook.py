#!/usr/bin/env python3
"""Opt-in integration check using the user's configured Codex provider."""
import json
import os
from pathlib import Path
import queue
import sys
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rpc import Client
from session import hook_options,toml_value
from bridge import send

root=Path(__file__).resolve().parents[1]
install=json.loads((root/'installation.json').read_text())
env=os.environ.copy(); ident=uuid.uuid4().hex
env.update(CWN_ID=ident,CWN_HELPER=install['helper'],CWN_CWD=str(root))
os.environ.update(CWN_ID=ident,CWN_HELPER=install['helper'],CWN_CWD=str(root))
send('register')
options=hook_options()+['-c','notify='+toml_value([sys.executable,str(root/'bridge.py'),'complete'])]
with Client(options,env=env) as c:
    config=c.call('config/read',{'includeLayers':False})['config']
    hooks=c.call('hooks/list',{'cwds':[str(root)]})['data'][0]['hooks']
    assert any(h['source']=='sessionFlags' and h['trustStatus']=='trusted' for h in hooks)
    # Completion toasts require a persisted user thread, unlike internal reviews.
    thread=c.call('thread/start',{'cwd':str(root),'approvalPolicy':'never','sandbox':'read-only'})
    tid=thread['thread']['id']
    mode={'mode':'plan','settings':{'model':config['model'],'reasoning_effort':'low','developer_instructions':'This is a notification integration test. Call request_user_input exactly once with two choices A and B. After receiving the answer, reply only TEST_OK. Do not use any other tools.'}}
    c.call('turn/start',{'threadId':tid,'collaborationMode':mode,'input':[{'type':'text','text':'Test request_user_input now. Ask which test option to select.'}]})
    asked=False; completed=False; deadline=time.monotonic()+150
    while time.monotonic()<deadline:
        try: message=c.messages.get(timeout=min(10,max(1,deadline-time.monotonic())))
        except queue.Empty: continue
        method=message.get('method','')
        if method=='item/tool/requestUserInput':
            asked=True
            questions=message['params']['questions']
            answers={q['id']:{'answers':[q['options'][0]['label']]} for q in questions}
            # Wait briefly so detached notification worker can finish; tool request already arrived.
            c.write({'id':message['id'],'result':{'answers':answers}})
            print('Real request_user_input received; test answer returned.')
        if method=='turn/completed':
            completed=message['params']['turn'].get('status')=='completed';break
    assert asked and completed, 'request_user_input or continuation did not complete'
    time.sleep(1)
    logfile=Path.home()/'.local/state/codex-win-notify/bridge.log'
    events=[json.loads(line) for line in logfile.read_text().splitlines() if ident in line]
    assert any(e['kind']=='question' and e['result']=='sent' for e in events),events
    assert any(e['kind']=='complete' and e['result']=='sent' for e in events),events
    helper_events=[json.loads(line) for line in (Path(install['root'])/'helper.log').read_text().splitlines() if ident in line]
    for kind in ('question','complete'):
        assert any(e['kind']==kind and e['result'] in ('notified','foreground-suppressed') for e in helper_events),helper_events
    c.call('thread/archive',{'threadId':tid})
    send('forget')
    print('PASS: real question hook, answer continuation and complete notify. Window id:',ident)
