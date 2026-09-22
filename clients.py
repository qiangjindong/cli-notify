"""Shared Windows helper leases, serialized by a Windows file handle."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess

PS = '/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'

@contextmanager
def installation_lock(root):
    root.mkdir(parents=True, exist_ok=True)
    path = subprocess.check_output(['wslpath', '-w', str(root/'install.lock')], text=True).strip()
    literal = "'" + path.replace("'", "''") + "'"
    script = f"$ErrorActionPreference='Stop'; $f=[IO.File]::Open({literal},'OpenOrCreate','ReadWrite','None'); try {{ [Console]::Out.WriteLine('locked'); [Console]::In.ReadLine() | Out-Null }} finally {{ $f.Dispose() }}"
    with subprocess.Popen([PS, '-NoProfile', '-Command', script], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as process:
        try:
            if process.stdout.readline().strip() != 'locked':
                raise RuntimeError('Another installer is running, or the installation lock is unavailable')
            yield
        finally:
            if process.poll() is None:
                process.stdin.write('\n'); process.stdin.flush()
            process.wait(timeout=10)

def register(root, config):
    identity = os.environ.get('WSL_DISTRO_NAME', '') + ':' + str(config.resolve())
    name = 'wsl-' + hashlib.sha256(identity.encode()).hexdigest()[:16] + '.json'
    clients = root/'clients'
    clients.mkdir(exist_ok=True)
    (clients/name).write_text(json.dumps({'config':str(config.resolve()), 'source':str(Path(__file__).resolve().parent)}))
    return name

def release(root, name):
    if name:
        if Path(name).name != name or not name.startswith('wsl-') or not name.endswith('.json'):
            raise ValueError('Unexpected client name')
        (root/'clients'/name).unlink(missing_ok=True)
    return not any((root/'clients').glob('*.json'))

def stop_helper(helper):
    """Stop this installation's helper, if it is currently running."""
    path = subprocess.check_output(['wslpath', '-w', str(helper)], text=True).strip()
    literal = "'" + path.replace("'", "''") + "'"
    # Keep Get-Process from being the pipeline's last failed command when no
    # helper is running.  PowerShell otherwise exits with status 1 even though
    # an absent process is already the state the installer needs.
    script = f"$process = Get-Process CliNotify -ErrorAction SilentlyContinue; $process | Where-Object {{ $_.Path -eq {literal} }} | Stop-Process -Force"
    subprocess.run([PS, '-NoProfile', '-Command', script], check=True)
