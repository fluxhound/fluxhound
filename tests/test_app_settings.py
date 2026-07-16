"""Unit tests for src.app_settings (no filesystem outside tmp_path)."""
from __future__ import annotations

from src import app_settings
from src.app_settings import AppSettings


def test_load_returns_defaults_when_no_config_file(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "CONFIG_PATH", tmp_path / "app_settings.json")

    config = app_settings.load()

    assert config == AppSettings(minimize_to_tray=True)


def test_save_then_load_round_trips_minimize_to_tray(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "CONFIG_PATH", tmp_path / "app_settings.json")
    original = AppSettings(minimize_to_tray=False)

    app_settings.save(original)
    loaded = app_settings.load()

    assert loaded == original


def test_load_defaults_minimize_to_tray_for_a_file_missing_the_key(tmp_path, monkeypatch):
    config_path = tmp_path / "app_settings.json"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(app_settings, "CONFIG_PATH", config_path)

    loaded = app_settings.load()

    assert loaded.minimize_to_tray is True
