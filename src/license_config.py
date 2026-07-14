"""Persistent storage for the locally cached license state: whether the app is
currently unlocked, and the key/instance id that got it there (src/licensing/
license_check.py owns actually talking to Lemon Squeezy; this is just the
cache that lets is_licensed() answer without a network call on every launch).

Stored as JSON next to the running app, same pattern as device_config.py.
Never written to a file that gets versioned - the key itself is the same
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


CONFIG_PATH = _app_dir() / "license_config.json"


@dataclass
class LicenseState:
    """unlocked is the one field gate.py actually cares about; key/instance_id
    are kept so a re-activation attempt or support request has something to
    go on, and so "Remove licence" has something to describe to the user."""

    key: str = ""
    instance_id: str | None = None
    unlocked: bool = False


def load() -> LicenseState:
    """Load the cached license state, or defaults (locked, no key) if none was
    ever saved."""
    if not CONFIG_PATH.exists():
        return LicenseState()
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return LicenseState(
        key=data.get("key", ""), instance_id=data.get("instance_id"), unlocked=data.get("unlocked", False),
    )


def save(state: LicenseState) -> None:
    """Persist the license state, overwriting any previous one."""
    CONFIG_PATH.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
