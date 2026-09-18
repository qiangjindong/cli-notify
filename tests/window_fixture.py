#!/usr/bin/env python3
# Synthetic arguments only; never used for a real Codex session.
import json
import os
from pathlib import Path
import time
print('\033]0;APPLICATION_TITLE_SHOULD_NOT_APPLY\007',end='',flush=True)
root=Path(os.environ['CWN_CWD'])
(root/'result.json').write_text(json.dumps({'args':__import__('sys').argv[1:],'cwd':os.getcwd(),'id':os.environ['CWN_ID']},ensure_ascii=False))
while not (root/'stop').exists(): time.sleep(.2)
