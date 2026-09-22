"""Conservative shared-helper compatibility receipts (also used by PowerShell)."""
import hashlib
import json
from pathlib import Path

RECEIPT = 'helper-install.json'


def digest(path, text=False):
    data = path.read_bytes()
    if text:
        data = data.replace(b'\r\n', b'\n')
    return hashlib.sha256(data).hexdigest()


def source_hashes(source, icon):
    files = list((source/'windows').glob('*.cs')) + [source/'windows/CliNotify.csproj']
    result = {p.name: digest(p, text=True) for p in files}
    if icon is not None:
        result['notification.icon'] = digest(icon)
        result['make-icon.ps1'] = digest(source/'windows/make-icon.ps1', text=True)
    return result


def app_hashes(root):
    app = root/'app'
    if not all((app/name).is_file() for name in ('CliNotify.exe', 'CliNotify.dll', 'CliNotify.deps.json', 'CliNotify.runtimeconfig.json')):
        raise ValueError('Incomplete helper installation')
    return {p.relative_to(app).as_posix(): digest(p) for p in app.rglob('*') if p.is_file()}


def compatible_helper(root, source, icon):
    try:
        receipt = json.loads((root/RECEIPT).read_text(encoding='utf-8-sig'))
        return (receipt['schema'] == 1 and receipt['source'] == source_hashes(source, icon)
                and receipt['files'] == app_hashes(root))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def record_helper(root, source, icon):
    receipt = {'schema': 1, 'source': source_hashes(source, icon), 'files': app_hashes(root)}
    temporary = root/(RECEIPT + '.tmp')
    temporary.write_text(json.dumps(receipt), encoding='utf-8')
    temporary.replace(root/RECEIPT)
