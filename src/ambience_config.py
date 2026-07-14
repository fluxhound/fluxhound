"""Persistent storage for Ambience Mode's monitor, capture-region, and Gaming
Mode choice, so they survive both mode switches and app restarts.

Stored as JSON next to the running app, same pattern as device_config.py.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
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
    """Which monitor Ambience Mode watches, optionally a specific region of it
    instead of the whole thing, and whether Gaming Mode is on - see
    src/modes/ambience_mode.py for what that does with the region differently.

    multi_region_mode/position_regions are a third, mutually exclusive
    alternative to both: instead of one region driving every bulb the same way,
    each merged-group position (BASE, EXT-1, EXT-2, ...) gets its own region,
    read independently, so a merged group's positioned bulbs can each reflect a
    different part of the screen. position_regions is keyed by position label
    rather than by group, so the same "BASE = left third of the screen" mapping
    carries over regardless of which physical group is currently active -
    consistent with this file already treating monitor/region as one global
    choice rather than per-group state. A position with no region assigned (or
    a group member with no position at all) falls back to the whole monitor's
    reading."""

    monitor_index: int = AUTO_MONITOR_INDEX
    region: AmbienceRegion | None = None
    gaming_mode: bool = False
    multi_region_mode: bool = False
    position_regions: dict[str, AmbienceRegion] = field(default_factory=dict)


def load() -> AmbienceConfig:
    """Load the saved monitor/region/gaming-mode/multi-region choice, or defaults
    if none was ever saved."""
    if not CONFIG_PATH.exists():
        return AmbienceConfig()
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    region_data = data.get("region")
    position_regions_data = data.get("position_regions", {})
    return AmbienceConfig(
        monitor_index=data.get("monitor_index", AUTO_MONITOR_INDEX),
        region=AmbienceRegion(**region_data) if region_data is not None else None,
        gaming_mode=data.get("gaming_mode", False),
        multi_region_mode=data.get("multi_region_mode", False),
        position_regions={
            position: AmbienceRegion(**region) for position, region in position_regions_data.items()
        },
    )


def save(config: AmbienceConfig) -> None:
    """Persist the monitor/region/gaming-mode/multi-region choice, overwriting
    any previous one."""
    data = {
        "monitor_index": config.monitor_index,
        "region": asdict(config.region) if config.region is not None else None,
        "gaming_mode": config.gaming_mode,
        "multi_region_mode": config.multi_region_mode,
        "position_regions": {
            position: asdict(region) for position, region in config.position_regions.items()
        },
    }
    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
