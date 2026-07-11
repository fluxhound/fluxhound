"""Persistent storage for Audio Mode's source-to-target assignment and per-source
sensitivity, so both survive mode switches and app restarts alike.

Stored as JSON next to the running app, same pattern as device_config.py.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.audio.custom_show import SENSITIVITY_DEFAULT, SOURCES, TARGETS

# The screenshot the user chose as "the" default configuration: Hue-Energy,
# Brightness-Beat, Saturation-Timbre.
DEFAULT_ASSIGNMENT: dict[str, str | None] = {"hue": "energy", "brightness": "beat", "saturation": "timbre"}
DEFAULT_SENSITIVITY: dict[str, float] = {source: SENSITIVITY_DEFAULT for source in SOURCES}


def _app_dir() -> Path:
    """Directory the config file lives next to."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


CONFIG_PATH = _app_dir() / "audio_mode_config.json"


@dataclass
class AudioModeConfig:
    """Audio Mode's saved source-to-target assignment and per-source sensitivity."""

    assignment: dict[str, str | None] = field(default_factory=lambda: dict(DEFAULT_ASSIGNMENT))
    sensitivity: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_SENSITIVITY))


def load() -> AudioModeConfig:
    """Load the saved Audio Mode config, or the default if none has been saved yet."""
    if not CONFIG_PATH.exists():
        return AudioModeConfig()
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    assignment = {**DEFAULT_ASSIGNMENT, **data.get("assignment", {})}
    sensitivity = {**DEFAULT_SENSITIVITY, **data.get("sensitivity", {})}
    # Guard against a stale/hand-edited file naming a target or source that no longer exists.
    assignment = {target: assignment.get(target) for target in TARGETS}
    sensitivity = {source: sensitivity.get(source, SENSITIVITY_DEFAULT) for source in SOURCES}
    return AudioModeConfig(assignment=assignment, sensitivity=sensitivity)


def save(config: AudioModeConfig) -> None:
    """Persist the Audio Mode config, overwriting any previous one."""
    CONFIG_PATH.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")
