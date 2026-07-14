"""Unit tests for src.license_config (no network I/O)."""
from __future__ import annotations

from src import license_config
from src.license_config import LicenseState


def test_load_returns_defaults_when_no_config_file(tmp_path, monkeypatch):
    monkeypatch.setattr(license_config, "CONFIG_PATH", tmp_path / "license_config.json")

    assert license_config.load() == LicenseState(key="", instance_id=None, unlocked=False)


def test_save_then_load_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(license_config, "CONFIG_PATH", tmp_path / "license_config.json")
    original = LicenseState(key="ABCD-1234", instance_id="inst-1", unlocked=True)

    license_config.save(original)
    loaded = license_config.load()

    assert loaded == original
