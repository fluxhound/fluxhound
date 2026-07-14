"""Persistent storage for the user's own, optional Tuya Cloud IoT Platform API
credentials (region/key/secret), used only if they choose the "Fetch via Tuya
Cloud" local_key lookup in DeviceConfigDialog instead of entering it by hand - see
src/tuya/cloud_discovery.py.

Stored as JSON next to the running app, same pattern as device_config.py. Never
written to a file that gets versioned - these are account credentials, same
sensitivity as a password.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


def _app_dir() -> Path:
    """Directory the config file lives next to."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


CONFIG_PATH = _app_dir() / "tuya_cloud_credentials.json"


@dataclass
class CloudCredentials:
    """The user's own Tuya IoT Platform developer account credentials."""

    api_region: str = "us"
    api_key: str = ""
    api_secret: str = ""


def load() -> CloudCredentials:
    """Load the saved Cloud API credentials, or defaults if none were ever saved."""
    if not CONFIG_PATH.exists():
        return CloudCredentials()
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return CloudCredentials(**data)


def save(credentials: CloudCredentials) -> None:
    """Persist the Cloud API credentials, overwriting any previous ones."""
    CONFIG_PATH.write_text(json.dumps(asdict(credentials), indent=2), encoding="utf-8")
