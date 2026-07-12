"""Persistent storage for Ambience Mode's monitor and capture-region choice, so it
survives both mode switches and app restarts.

Stored as JSON next to the running app, same pattern as device_config.py.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

# 0 means "not chosen yet" - ScreenCapture falls back to auto-picking the primary
# monitor. Real monitors are indices 1..N, matching mss's own numbering (mss's index
# 0 is "all monitors combined", which this app never wants to use as a single target).
AUTO_MONITOR_INDEX = 0


def _app_dir() -> Path:
    """Directory the config file lives next to."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


CONFIG_PATH = _app_dir() / "ambience_config.json"


@dataclass
class AmbienceRegion:
    """A capture sub-area, in pixels relative to the top-left of its monitor."""

    x: int
    y: int
    width: int
    height: int


@dataclass
class AmbienceConfig:
    """Which monitor Ambience Mode watches, and optionally a specific region of it
    instead of the whole thing."""

    monitor_index: int = AUTO_MONITOR_INDEX
    region: AmbienceRegion | None = None


def load() -> AmbienceConfig:
    """Load the saved monitor/region choice, or defaults if none was ever saved."""
    if not CONFIG_PATH.exists():
        return AmbienceConfig()
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    region_data = data.get("region")
    return AmbienceConfig(
        monitor_index=data.get("monitor_index", AUTO_MONITOR_INDEX),
        region=AmbienceRegion(**region_data) if region_data is not None else None,
    )


def save(config: AmbienceConfig) -> None:
    """Persist the monitor/region choice, overwriting any previous one."""
    data = {
        "monitor_index": config.monitor_index,
        "region": asdict(config.region) if config.region is not None else None,
    }
    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
