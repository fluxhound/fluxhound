"""Unit tests for src.ambience_config (no network/screen I/O)."""
from __future__ import annotations

from src import ambience_config
from src.ambience_config import AUTO_MONITOR_INDEX, AmbienceConfig, AmbienceRegion


def test_load_returns_defaults_when_no_config_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ambience_config, "CONFIG_PATH", tmp_path / "ambience_config.json")

    config = ambience_config.load()

    assert config == AmbienceConfig(monitor_index=AUTO_MONITOR_INDEX, region=None)


def test_save_then_load_round_trips_monitor_and_region(tmp_path, monkeypatch):
    monkeypatch.setattr(ambience_config, "CONFIG_PATH", tmp_path / "ambience_config.json")
    original = AmbienceConfig(monitor_index=2, region=AmbienceRegion(x=100, y=50, width=800, height=600))

    ambience_config.save(original)
    loaded = ambience_config.load()

    assert loaded == original


def test_load_handles_null_region_in_json(tmp_path, monkeypatch):
    config_path = tmp_path / "ambience_config.json"
    config_path.write_text('{"monitor_index": 1, "region": null}', encoding="utf-8")
    monkeypatch.setattr(ambience_config, "CONFIG_PATH", config_path)

    loaded = ambience_config.load()

    assert loaded == AmbienceConfig(monitor_index=1, region=None)
