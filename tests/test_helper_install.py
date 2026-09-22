import json
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch
from contextlib import nullcontext

import install
from helper_install import compatible_helper, record_helper


class HelperInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name)/'source'
        windows = self.source/'windows'
        windows.mkdir(parents=True)
        for name in ('Program.cs', 'CliNotify.csproj', 'make-icon.ps1'):
            (windows/name).write_text(name + '\n')
        self.icon = self.source/'icon.png'
        self.icon.write_bytes(b'icon')
        self.root = Path(self.temp.name)/'CliNotify'
        app = self.root/'app'
        app.mkdir(parents=True)
        for name in ('CliNotify.exe', 'CliNotify.dll', 'CliNotify.deps.json', 'CliNotify.runtimeconfig.json'):
            (app/name).write_text(name)

    def record(self):
        record_helper(self.root, self.source, self.icon)

    def compatible(self):
        return compatible_helper(self.root, self.source, self.icon)

    def test_unmarked_legacy_is_not_assumed_compatible(self):
        self.assertFalse(self.compatible())

    def test_receipt_roundtrip_and_powershell_bom(self):
        self.record()
        self.assertTrue(self.compatible())
        receipt = self.root/'helper-install.json'
        data = json.loads(receipt.read_text())
        receipt.write_text(json.dumps(data, indent=2), encoding='utf-8-sig')
        self.assertTrue(self.compatible())

    def test_changed_source_dependency_icon_or_binary_requires_update(self):
        self.record()
        for path in (self.source/'windows/Program.cs', self.source/'windows/CliNotify.csproj',
                     self.source/'windows/make-icon.ps1', self.icon, self.root/'app/CliNotify.dll'):
            before = path.read_bytes()
            path.write_bytes(b'changed')
            self.assertFalse(self.compatible(), str(path))
            path.write_bytes(before)
        self.assertFalse(compatible_helper(self.root, self.source, None))
        self.assertTrue(self.compatible())

    def test_missing_binary_and_corrupt_receipt(self):
        self.record()
        (self.root/'app/CliNotify.exe').unlink()
        self.assertFalse(self.compatible())
        (self.root/'helper-install.json').write_text('{bad')
        self.assertFalse(self.compatible())

    def test_null_icon(self):
        record_helper(self.root, self.source, None)
        self.assertTrue(compatible_helper(self.root, self.source, None))

    @unittest.skipUnless(Path(install.PS).is_file(), 'Requires WSL Windows interop')
    def test_powershell_receipt_interoperability(self):
        def literal(path):
            value = subprocess.check_output(['wslpath', '-w', str(path)], text=True).strip()
            return "'" + value.replace("'", "''") + "'"
        library = Path(__file__).resolve().parents[1]/'windows/installation.ps1'
        args = f'{literal(self.root)} {literal(self.source)} {literal(self.icon)}'
        self.record()
        for path in (self.source/'windows').iterdir():
            path.write_bytes(path.read_bytes().replace(b'\n', b'\r\n'))
        self.assertTrue(self.compatible())
        script = (f"$ErrorActionPreference='Stop'; . {literal(library)}; "
                  f"if (-not (Test-CompatibleHelper {args})) {{ throw 'Python receipt rejected' }}; "
                  f"Write-HelperReceipt {args}")
        subprocess.run([install.PS, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script],
                       check=True, timeout=30)
        self.assertTrue(self.compatible())
        (self.root/'app/CliNotify.dll').write_bytes(b'changed')
        script = (f"$ErrorActionPreference='Stop'; . {literal(library)}; "
                  f"if (Test-CompatibleHelper {args}) {{ throw 'Damaged binary accepted' }}")
        subprocess.run([install.PS, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script],
                       check=True, timeout=30)

    def test_wsl_reuse_registers_without_build_or_stop(self):
        self.record()
        home = Path(self.temp.name)/'home'
        with patch.object(install, 'ROOT', self.source), \
             patch.object(install, 'check_requirements'), \
             patch.object(install, 'query', side_effect=['local', 'wt']), \
             patch.object(install.subprocess, 'check_output', side_effect=[str(self.root.parent), '/wt']), \
             patch.object(install, 'build_helper') as build, \
             patch('settings.notification_icon', return_value=self.icon), \
             patch('native.config_path', return_value=home/'config.toml'), \
             patch('native.install_hooks') as hooks, \
             patch('clients.installation_lock', return_value=nullcontext()), \
             patch('clients.stop_helper') as stop, \
             patch('clients.register', return_value='client') as register:
            install.main()
        build.assert_not_called()
        stop.assert_not_called()
        hooks.assert_called_once()
        register.assert_called_once()
        self.assertEqual(json.loads((self.source/'installation.json').read_text())['client'], 'client')


if __name__ == '__main__':
    unittest.main()
