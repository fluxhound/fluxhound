"""General app-preferences file: currently just whether closing the main
window minimizes to the tray instead of quitting. Same load/save pattern as
every other config file in this project (see devices_config.py).
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


CONFIG_PATH = _app_dir() / "app_settings.json"


@dataclass
class AppSettings:
    """minimize_to_tray: when True (the default), closing the main window
    hides it to the tray instead of quitting - see MainWindow._on_close.
    When False, closing the window quits the app normally, same as if no
    tray icon existed at all."""

    minimize_to_tray: bool = True


def load() -> AppSettings:
    """Load the saved preferences, or defaults if none was ever saved."""
    if not CONFIG_PATH.exists():
        return AppSettings()
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return AppSettings(minimize_to_tray=data.get("minimize_to_tray", True))


def save(settings: AppSettings) -> None:
    """Persist the preferences, overwriting any previous ones."""
    CONFIG_PATH.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
