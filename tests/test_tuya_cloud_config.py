"""Unit tests for src.tuya_cloud_config (no network I/O)."""
from __future__ import annotations

from src import tuya_cloud_config
from src.tuya_cloud_config import CloudCredentials


def test_load_returns_defaults_when_no_config_file(tmp_path, monkeypatch):
    monkeypatch.setattr(tuya_cloud_config, "CONFIG_PATH", tmp_path / "tuya_cloud_credentials.json")

    assert tuya_cloud_config.load() == CloudCredentials(api_region="us", api_key="", api_secret="")


def test_save_then_load_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(tuya_cloud_config, "CONFIG_PATH", tmp_path / "tuya_cloud_credentials.json")
    original = CloudCredentials(api_region="eu", api_key="my-key", api_secret="my-secret")

    tuya_cloud_config.save(original)
    loaded = tuya_cloud_config.load()

    assert loaded == original
