"""Persistent storage for the configured bulb's connection details.

Stored as JSON next to the running app (the exe when frozen via
PyInstaller, the repo root in dev), keeping the app portable and the
file out of version control.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_PROTOCOL_VERSION = 3.3


def _app_dir() -> Path:
    """Directory the config file lives next to."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


CONFIG_PATH = _app_dir() / "device_config.json"


@dataclass
class DeviceConfig:
    """Connection details for one Tuya bulb, plus its local display name.

    display_name is purely local (see src/devices_config.py) - the local Tuya
    protocol has no device-name field to read from the bulb itself, so this is
    never written back to the device, only shown in this app's own UI.
    """

    device_id: str
    ip_address: str
    local_key: str
    protocol_version: float = DEFAULT_PROTOCOL_VERSION
    display_name: str = ""


def load() -> DeviceConfig | None:
    """Load the saved device config, or None if none has been configured yet."""
    if not CONFIG_PATH.exists():
        return None
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return DeviceConfig(**data)


def save(config: DeviceConfig) -> None:
    """Persist the device config, overwriting any previous one."""
    CONFIG_PATH.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")
