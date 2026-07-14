"""Unit tests for src.ambience_config (no network/screen I/O)."""
from __future__ import annotations

from src import ambience_config
from src.ambience_config import AUTO_MONITOR_INDEX, AmbienceConfig, AmbienceRegion


def test_load_returns_defaults_when_no_config_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ambience_config, "CONFIG_PATH", tmp_path / "ambience_config.json")

    config = ambience_config.load()

    assert config == AmbienceConfig(monitor_index=AUTO_MONITOR_INDEX, region=None, gaming_mode=False)


def test_save_then_load_round_trips_monitor_region_and_gaming_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(ambience_config, "CONFIG_PATH", tmp_path / "ambience_config.json")
    original = AmbienceConfig(
        monitor_index=2, region=AmbienceRegion(x=100, y=50, width=800, height=600), gaming_mode=True
    )

    ambience_config.save(original)
    loaded = ambience_config.load()

    assert loaded == original


def test_load_defaults_gaming_mode_to_false_for_a_pre_gaming_mode_file(tmp_path, monkeypatch):
    config_path = tmp_path / "ambience_config.json"
    config_path.write_text('{"monitor_index": 1, "region": null}', encoding="utf-8")
    monkeypatch.setattr(ambience_config, "CONFIG_PATH", config_path)

    loaded = ambience_config.load()

    assert loaded.gaming_mode is False


def test_load_handles_null_region_in_json(tmp_path, monkeypatch):
    config_path = tmp_path / "ambience_config.json"
    config_path.write_text('{"monitor_index": 1, "region": null}', encoding="utf-8")
    monkeypatch.setattr(ambience_config, "CONFIG_PATH", config_path)

    loaded = ambience_config.load()

    assert loaded == AmbienceConfig(monitor_index=1, region=None)


def test_load_defaults_multi_region_fields_for_a_pre_multi_region_file(tmp_path, monkeypatch):
    config_path = tmp_path / "ambience_config.json"
    config_path.write_text('{"monitor_index": 1, "region": null, "gaming_mode": false}', encoding="utf-8")
    monkeypatch.setattr(ambience_config, "CONFIG_PATH", config_path)

    loaded = ambience_config.load()

    assert loaded.multi_region_mode is False
    assert loaded.position_regions == {}


def test_save_then_load_round_trips_multi_region_mode_and_position_regions(tmp_path, monkeypatch):
    monkeypatch.setattr(ambience_config, "CONFIG_PATH", tmp_path / "ambience_config.json")
    original = AmbienceConfig(
        monitor_index=1,
        multi_region_mode=True,
        position_regions={
            "BASE": AmbienceRegion(x=0, y=0, width=640, height=1080),
            "EXT-1": AmbienceRegion(x=640, y=0, width=640, height=1080),
        },
    )

    ambience_config.save(original)
    loaded = ambience_config.load()

    assert loaded == original


def test_multi_region_mode_and_gaming_mode_can_both_be_persisted_independently(tmp_path, monkeypatch):
    """Mutual exclusion is enforced by the GUI, not the persistence layer - the
    config format itself just stores whatever it's given."""
    monkeypatch.setattr(ambience_config, "CONFIG_PATH", tmp_path / "ambience_config.json")
    original = AmbienceConfig(gaming_mode=False, multi_region_mode=True)

    ambience_config.save(original)
    loaded = ambience_config.load()

    assert loaded.gaming_mode is False
    assert loaded.multi_region_mode is True
