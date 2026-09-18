#!/usr/bin/env python3
"""Run the real launcher inside a test terminal with a synthetic Codex executable."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import sys

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
requestpath=Path(sys.argv[1]); request=json.loads(requestpath.read_text()); requestpath.unlink()
# Windows interop must remain attached to this new test terminal. Reusing the
# caller's WSL_INTEROP socket would register the caller's window for both tests.
terminal_env={k:os.environ.get(k) for k in ('WSL_INTEROP','WT_SESSION','WT_PROFILE_ID')}
os.environ.update(request['env'])
for key,value in terminal_env.items():
    if value is None: os.environ.pop(key,None)
    else: os.environ[key]=value
os.chdir(request['cwd'])
loader=importlib.machinery.SourceFileLoader('launcher',str(root/'codex-window'))
spec=importlib.util.spec_from_loader(loader.name,loader)
launcher=importlib.util.module_from_spec(spec)
loader.exec_module(launcher)
launcher.shutil.which=lambda _:str(root/'tests/window_fixture.py')
sys.argv=['codex-window',*request['args']]
launcher.main()
