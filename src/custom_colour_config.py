"""Persistent storage for the user's custom-picked colour (from the colour-picker
window), so it survives both mode switches and app restarts.

Stored as JSON next to the running app, same pattern as device_config.py.
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


CONFIG_PATH = _app_dir() / "custom_colour_config.json"


@dataclass
class CustomColour:
    """A user-picked HSV colour (hue 0-360, saturation/value 0-1000)."""

    hue: int
    saturation: int
    value: int


def load() -> CustomColour | None:
    """Load the saved custom colour, or None if the user has never picked one."""
    if not CONFIG_PATH.exists():
        return None
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return CustomColour(**data)


def save(colour: CustomColour) -> None:
    """Persist the custom colour, overwriting any previous one."""
    CONFIG_PATH.write_text(json.dumps(asdict(colour), indent=2), encoding="utf-8")
