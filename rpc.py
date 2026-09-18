"""Small bounded stdio client for local Codex config and integration checks."""
import json
import queue
import subprocess
import threading
import time

class Client:
    def __init__(self, options=(), env=None):
        self.process=subprocess.Popen(['codex',*options,'app-server'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,env=env)
        self.messages=queue.Queue(); self.counter=0
        def read():
            for line in self.process.stdout:
                try: self.messages.put(json.loads(line))
                except ValueError: pass
            self.messages.put(None)
        threading.Thread(target=read,daemon=True).start()
        try: self.call('initialize',{'clientInfo':{'name':'codex_win_notify','version':'1.0'},'capabilities':{'experimentalApi':True}})
        except Exception:
            self.close(); raise
        self.write({'method':'initialized'})
    def write(self,message):
        self.process.stdin.write(json.dumps(message)+'\n'); self.process.stdin.flush()
    def call(self,method,params):
        self.counter+=1; ident=self.counter
        self.write({'id':ident,'method':method,'params':params})
        deadline=time.monotonic()+15
        while True:
            message=self.messages.get(timeout=max(.01,deadline-time.monotonic()))
            if message is None: raise RuntimeError("Codex app-server exited")
            if message.get('id')==ident:
                if 'error' in message: raise RuntimeError('Codex RPC '+method+' failed')
                return message['result']
    def close(self):
        self.process.terminate()
        try: self.process.wait(timeout=3)
        except subprocess.TimeoutExpired: self.process.kill(); self.process.wait()
        self.process.stdin.close(); self.process.stdout.close()
    def __enter__(self): return self
    def __exit__(self,*args): self.close()
