"""Unit tests for src.devices_config (no network I/O)."""
from __future__ import annotations

from src import device_config, devices_config
from src.device_config import DeviceConfig
from src.devices_config import DeviceGroup, DevicesConfig


def test_load_returns_empty_config_when_nothing_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(devices_config, "CONFIG_PATH", tmp_path / "devices_config.json")
    monkeypatch.setattr(device_config, "CONFIG_PATH", tmp_path / "device_config.json")

    config = devices_config.load()

    assert config == DevicesConfig()


def test_save_then_load_round_trips_devices_and_groups(tmp_path, monkeypatch):
    monkeypatch.setattr(devices_config, "CONFIG_PATH", tmp_path / "devices_config.json")
    original = DevicesConfig(
        devices=[
            DeviceConfig(device_id="a1", ip_address="192.168.1.10", local_key="key1", display_name="Lamp A"),
            DeviceConfig(device_id="b2", ip_address="192.168.1.11", local_key="key2", display_name="Lamp B"),
        ],
        groups=[DeviceGroup(group_id="g1", name="Living Room", device_ids=["a1", "b2"])],
        active_selection=devices_config.group_selection_key("g1"),
    )

    devices_config.save(original)
    loaded = devices_config.load()

    assert loaded == original


def test_load_migrates_legacy_single_device_file(tmp_path, monkeypatch):
    monkeypatch.setattr(devices_config, "CONFIG_PATH", tmp_path / "devices_config.json")
    monkeypatch.setattr(device_config, "CONFIG_PATH", tmp_path / "device_config.json")
    legacy = DeviceConfig(device_id="legacy1", ip_address="192.168.1.20", local_key="legacykey")
    device_config.save(legacy)

    config = devices_config.load()

    assert len(config.devices) == 1
    migrated = config.devices[0]
    assert migrated.device_id == "legacy1"
    assert migrated.display_name == "legacy1"  # falls back to device_id, the only identity we have locally
    assert config.active_selection == devices_config.device_selection_key("legacy1")
    # The migration is persisted, not redone on every load.
    assert (tmp_path / "devices_config.json").exists()


def test_selection_key_helpers_round_trip():
    assert devices_config.device_selection_key("abc").startswith(devices_config.DEVICE_SELECTION_PREFIX)
    assert devices_config.group_selection_key("xyz").startswith(devices_config.GROUP_SELECTION_PREFIX)


def test_new_group_id_is_unique():
    assert devices_config.new_group_id() != devices_config.new_group_id()
