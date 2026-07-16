"""Persistent storage for Ambience Mode's monitor, capture-region, and Gaming
Mode choice, so they survive both mode switches and app restarts.

Stored as JSON next to the running app, same pattern as device_config.py.
"""
from __future__ import annotations

import json
import sys
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.screen.ambience_show import AMBIENCE_SLIDER_DEFAULT
from src.screen.health_bar import ThresholdBand, TriggerConfig

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
    """A capture sub-area, in pixels relative to the top-left of its monitor.

    mask is an optional painted, non-rectangular sub-selection within this
    same bounding box (see BrushSelectorWindow, health_bar.py's
    encode_region_mask/decode_region_mask) - a base64 packed-bits string, or
    None to mean "the whole rectangle counts" (every AmbienceRegion before
    this field existed, and every Ambience-Mode colour-zone region: only
    Gaming Mode's built-in watcher and Trigger Editor watchers ever populate
    it, since those are the only regions describing a bar/orb shape rather
    than a plain screen zone)."""

    x: int
    y: int
    width: int
    height: int
    mask: str | None = None


def new_watcher_id() -> str:
    """A short opaque id for a new trigger watcher, distinct from any other."""
    return uuid.uuid4().hex[:8]


@dataclass
class TriggerWatcher:
    """One paid-tier custom trigger watcher, added via the Trigger Editor: its
    own screen region plus its own TriggerConfig (src/screen/health_bar.py) -
    thresholds, flash colours, and any number of threshold_bands for "multi-step"
    glow reactions. Entirely additive: Gaming Mode's built-in watcher (this
    file's region/gaming_mode fields) is separate, always uses TriggerConfig()'s
    fixed defaults, and is unaffected by how many custom watchers exist."""

    watcher_id: str
    name: str
    region: AmbienceRegion
    config: TriggerConfig


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
    reading.

    trigger_watchers is the paid-tier Custom Trigger Editor's list of extra
    watchers - see TriggerWatcher above. Purely additive to gaming_mode/region;
    empty by default, same as every other user of this file before the feature
    existed.

    colour_sensitivity/smoothing are the two Ambience tab sliders (0-100, 50 =
    neutral) that tune AmbienceEnvelope's colour-mood analysis - see
    src/screen/ambience_show.py for what each one scales and why."""

    monitor_index: int = AUTO_MONITOR_INDEX
    region: AmbienceRegion | None = None
    gaming_mode: bool = False
    multi_region_mode: bool = False
    position_regions: dict[str, AmbienceRegion] = field(default_factory=dict)
    trigger_watchers: list[TriggerWatcher] = field(default_factory=list)
    colour_sensitivity: float = AMBIENCE_SLIDER_DEFAULT
    smoothing: float = AMBIENCE_SLIDER_DEFAULT


def _threshold_band_to_dict(band: ThresholdBand) -> dict:
    return {"threshold": band.threshold, "colour": list(band.colour)}


def _threshold_band_from_dict(data: dict) -> ThresholdBand:
    return ThresholdBand(threshold=data["threshold"], colour=tuple(data["colour"]))


def _trigger_config_to_dict(config: TriggerConfig) -> dict:
    return {
        "change_epsilon": config.change_epsilon,
        "blink_duration_seconds": config.blink_duration_seconds,
        "decrease_colour": list(config.decrease_colour),
        "increase_colour": list(config.increase_colour),
        "threshold_bands": [_threshold_band_to_dict(band) for band in config.threshold_bands],
        "detection_mode": config.detection_mode,
        "ocr_max_value": config.ocr_max_value,
    }


def _trigger_config_from_dict(data: dict) -> TriggerConfig:
    """Missing keys fall back to TriggerConfig()'s own defaults, so a config
    saved by an older version of this file (or edited by hand) still loads."""
    default = TriggerConfig()
    bands_data = data.get("threshold_bands")
    return TriggerConfig(
        change_epsilon=data.get("change_epsilon", default.change_epsilon),
        blink_duration_seconds=data.get("blink_duration_seconds", default.blink_duration_seconds),
        decrease_colour=tuple(data.get("decrease_colour", default.decrease_colour)),
        increase_colour=tuple(data.get("increase_colour", default.increase_colour)),
        threshold_bands=(
            [_threshold_band_from_dict(band) for band in bands_data]
            if bands_data is not None else default.threshold_bands
        ),
        detection_mode=data.get("detection_mode", default.detection_mode),
        ocr_max_value=data.get("ocr_max_value", default.ocr_max_value),
    )


def _watcher_to_dict(watcher: TriggerWatcher) -> dict:
    return {
        "watcher_id": watcher.watcher_id,
        "name": watcher.name,
        "region": asdict(watcher.region),
        "config": _trigger_config_to_dict(watcher.config),
    }


def _watcher_from_dict(data: dict) -> TriggerWatcher:
    return TriggerWatcher(
        watcher_id=data["watcher_id"],
        name=data["name"],
        region=AmbienceRegion(**data["region"]),
        config=_trigger_config_from_dict(data.get("config", {})),
    )


def load() -> AmbienceConfig:
    """Load the saved monitor/region/gaming-mode/multi-region/trigger-watcher
    choice, or defaults if none was ever saved."""
    if not CONFIG_PATH.exists():
        return AmbienceConfig()
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    region_data = data.get("region")
    position_regions_data = data.get("position_regions", {})
    trigger_watchers_data = data.get("trigger_watchers", [])
    return AmbienceConfig(
        monitor_index=data.get("monitor_index", AUTO_MONITOR_INDEX),
        region=AmbienceRegion(**region_data) if region_data is not None else None,
        gaming_mode=data.get("gaming_mode", False),
        multi_region_mode=data.get("multi_region_mode", False),
        position_regions={
            position: AmbienceRegion(**region) for position, region in position_regions_data.items()
        },
        trigger_watchers=[_watcher_from_dict(w) for w in trigger_watchers_data],
        colour_sensitivity=data.get("colour_sensitivity", AMBIENCE_SLIDER_DEFAULT),
        smoothing=data.get("smoothing", AMBIENCE_SLIDER_DEFAULT),
    )


def save(config: AmbienceConfig) -> None:
    """Persist the monitor/region/gaming-mode/multi-region/trigger-watcher
    choice, overwriting any previous one."""
    data = {
        "monitor_index": config.monitor_index,
        "region": asdict(config.region) if config.region is not None else None,
        "gaming_mode": config.gaming_mode,
        "multi_region_mode": config.multi_region_mode,
        "position_regions": {
            position: asdict(region) for position, region in config.position_regions.items()
        },
        "trigger_watchers": [_watcher_to_dict(w) for w in config.trigger_watchers],
        "colour_sensitivity": config.colour_sensitivity,
        "smoothing": config.smoothing,
    }
    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
