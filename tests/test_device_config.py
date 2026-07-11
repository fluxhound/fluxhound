"""Unit tests for src.device_config (no network I/O)."""
from __future__ import annotations

from src import device_config
from src.device_config import DeviceConfig


def test_load_returns_none_when_no_config_file(tmp_path, monkeypatch):
    monkeypatch.setattr(device_config, "CONFIG_PATH", tmp_path / "device_config.json")
    assert device_config.load() is None


def test_save_then_load_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(device_config, "CONFIG_PATH", tmp_path / "device_config.json")
    original = DeviceConfig(device_id="abc123", ip_address="192.168.1.42", local_key="s3cr3t")

    device_config.save(original)
    loaded = device_config.load()

    assert loaded == original
