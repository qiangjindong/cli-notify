import json
from pathlib import Path


CONFIG_NAME = 'cli-notify.json'


def notification_icon(root: Path) -> Path | None:
    """Return the configured PNG icon, resolving relative paths from the repo."""
    config_path = root / CONFIG_NAME
    try:
        config = json.loads(config_path.read_text(encoding='utf-8'))
        value = config['notification']['icon']
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(f'{CONFIG_NAME} 中缺少有效的 notification.icon 配置。') from exc
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError('notification.icon 必须是 PNG 文件路径，或设为 null。')
    icon = Path(value).expanduser()
    if not icon.is_absolute():
        icon = root / icon
    icon = icon.resolve()
    if icon.suffix.lower() != '.png':
        raise ValueError('notification.icon 目前仅支持 PNG 文件。')
    if not icon.is_file():
        raise ValueError(f'找不到通知图标：{icon}')
    return icon
