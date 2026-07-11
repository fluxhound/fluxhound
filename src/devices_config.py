"""Persistent storage for every configured Tuya bulb, the groups they can be combined
into, and which device/group is currently the active target on the main window.

Stored as JSON next to the running app (same pattern as the other *_config.py
modules). Replaces the older single-device device_config.json: on first load, if
devices_config.json doesn't exist yet but a legacy device_config.json does, that one
device is migrated in as the first entry (see _migrate_legacy_single_device).
"""
from __future__ import annotations

import json
import sys
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.device_config import DeviceConfig

DEVICE_SELECTION_PREFIX = "device:"
GROUP_SELECTION_PREFIX = "group:"
BASE_POSITION = "BASE"
EXT_POSITION_PREFIX = "EXT-"


def _app_dir() -> Path:
    """Directory the config file lives next to."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


CONFIG_PATH = _app_dir() / "devices_config.json"


@dataclass
class DeviceGroup:
    """A named set of devices that get the same command sent to all of them at once.

    positions optionally assigns some of the members a role in a "merged" virtual
    lamp (device_id -> "BASE" or "EXT-<n>", each label unique within the group - see
    can_merge/ordered_merge_device_ids). merged is only meaningful once at least BASE
    and EXT-1 are assigned; members without a position still receive the group's plain
    (unsplit) command even while merged.
    """

    group_id: str
    name: str
    device_ids: list[str] = field(default_factory=list)
    positions: dict[str, str] = field(default_factory=dict)
    merged: bool = False


@dataclass
class DevicesConfig:
    """Every configured device, every group, and which one is currently active."""

    devices: list[DeviceConfig] = field(default_factory=list)
    groups: list[DeviceGroup] = field(default_factory=list)
    active_selection: str = ""  # "" (none yet), "device:<id>", or "group:<id>"


def new_group_id() -> str:
    """A short opaque id for a new group, distinct from any device_id."""
    return uuid.uuid4().hex[:8]


def device_selection_key(device_id: str) -> str:
    return f"{DEVICE_SELECTION_PREFIX}{device_id}"


def group_selection_key(group_id: str) -> str:
    return f"{GROUP_SELECTION_PREFIX}{group_id}"


def position_rank(position: str) -> int:
    """BASE sorts first (rank 0), then EXT-1, EXT-2, ... in numeric order."""
    if position == BASE_POSITION:
        return 0
    if position.startswith(EXT_POSITION_PREFIX):
        try:
            return int(position[len(EXT_POSITION_PREFIX):])
        except ValueError:
            pass
    return -1  # not a real position label; sorts first but callers should never see this


def available_positions(group: DeviceGroup, device_id: str) -> list[str]:
    """Position labels device_id could pick: BASE plus EXT-1..EXT-(member count - 1),
    minus whatever's already taken by a *different* member (each label is unique
    within a group, but a device keeps seeing its own current label as an option)."""
    max_ext = max(0, len(group.device_ids) - 1)
    all_positions = [BASE_POSITION] + [f"{EXT_POSITION_PREFIX}{i}" for i in range(1, max_ext + 1)]
    taken_by_others = {position for did, position in group.positions.items() if did != device_id}
    return [p for p in all_positions if p not in taken_by_others]


def ordered_merge_device_ids(group: DeviceGroup) -> list[str]:
    """Positioned members only, ordered BASE, EXT-1, EXT-2, ... - the sequence a
    merged group's members represent as segments of one virtual lamp."""
    positioned = sorted(group.positions.items(), key=lambda pair: position_rank(pair[1]))
    return [device_id for device_id, _ in positioned]


def can_merge(group: DeviceGroup) -> bool:
    """The minimum needed for "Merge" to be usable: at least a BASE and an EXT-1."""
    assigned = set(group.positions.values())
    return BASE_POSITION in assigned and f"{EXT_POSITION_PREFIX}1" in assigned


def _migrate_legacy_single_device() -> DevicesConfig | None:
    """One-time upgrade from the pre-multi-device device_config.json format, so an
    already-configured bulb isn't lost when this file format is introduced."""
    from src import device_config

    legacy = device_config.load()
    if legacy is None:
        return None
    if not legacy.display_name:
        legacy.display_name = legacy.device_id
    return DevicesConfig(
        devices=[legacy], groups=[], active_selection=device_selection_key(legacy.device_id)
    )


def load() -> DevicesConfig:
    """Load the saved devices/groups config, migrating the legacy single-device file
    on the first run since the multi-device upgrade."""
    if CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return DevicesConfig(
            devices=[DeviceConfig(**d) for d in data.get("devices", [])],
            groups=[DeviceGroup(**g) for g in data.get("groups", [])],
            active_selection=data.get("active_selection", ""),
        )
    migrated = _migrate_legacy_single_device()
    if migrated is not None:
        save(migrated)
        return migrated
    return DevicesConfig()


def save(config: DevicesConfig) -> None:
    """Persist the devices/groups config, overwriting any previous one."""
    data = {
        "devices": [asdict(d) for d in config.devices],
        "groups": [asdict(g) for g in config.groups],
        "active_selection": config.active_selection,
    }
    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
