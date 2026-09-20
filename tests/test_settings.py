from pathlib import Path
import json
import tempfile
import unittest

from settings import notification_icon


class SettingsTests(unittest.TestCase):
    def test_relative_notification_icon(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            icon = root/'assets/icon.png'
            icon.parent.mkdir()
            icon.write_bytes(b'png')
            (root/'codex-win-notify.json').write_text(
                json.dumps({'notification': {'icon': 'assets/icon.png'}}), encoding='utf-8')
            self.assertEqual(notification_icon(root), icon.resolve())

    def test_null_disables_notification_icon(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'codex-win-notify.json').write_text(
                json.dumps({'notification': {'icon': None}}), encoding='utf-8')
            self.assertIsNone(notification_icon(root))

    def test_invalid_notification_icon_is_actionable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'codex-win-notify.json').write_text(
                json.dumps({'notification': {'icon': 'missing.png'}}), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '找不到通知图标'):
                notification_icon(root)


if __name__ == '__main__': unittest.main()
