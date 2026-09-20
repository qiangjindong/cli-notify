import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_notification

class NotificationCommandTests(unittest.TestCase):
    def test_uses_installed_helper_without_codex(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(test_notification, 'ROOT', Path(folder)), \
             patch('test_notification.subprocess.run') as run, \
             patch('builtins.print'):
            helper = Path(folder)/'app/CodexWinNotify.exe'
            helper.parent.mkdir()
            helper.touch()
            (Path(folder)/'installation.json').write_text(json.dumps({'helper':str(helper)}))
            test_notification.main()
        run.assert_called_once_with([str(helper), '--test'], check=True, timeout=15)

    def test_missing_install_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(test_notification, 'ROOT', Path(folder)):
            with self.assertRaisesRegex(RuntimeError, './install.sh'):
                test_notification.helper_path()

if __name__ == '__main__': unittest.main()
