"""Unit tests for src.ambience_config (no network/screen I/O)."""
from __future__ import annotations

from src import ambience_config
from src.ambience_config import AUTO_MONITOR_INDEX, AmbienceConfig, AmbienceRegion, TriggerWatcher
from src.screen.ambience_show import AMBIENCE_SLIDER_DEFAULT
from src.screen.health_bar import ThresholdBand, TriggerConfig


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


def test_load_defaults_trigger_watchers_to_empty_for_a_pre_trigger_editor_file(tmp_path, monkeypatch):
    config_path = tmp_path / "ambience_config.json"
    config_path.write_text('{"monitor_index": 1, "region": null, "gaming_mode": true}', encoding="utf-8")
    monkeypatch.setattr(ambience_config, "CONFIG_PATH", config_path)

    loaded = ambience_config.load()

    assert loaded.trigger_watchers == []


def test_save_then_load_round_trips_trigger_watchers(tmp_path, monkeypatch):
    monkeypatch.setattr(ambience_config, "CONFIG_PATH", tmp_path / "ambience_config.json")
    original = AmbienceConfig(
        gaming_mode=True,
        trigger_watchers=[
            TriggerWatcher(
                watcher_id="abc123",
                name="Mana orb",
                region=AmbienceRegion(x=10, y=20, width=30, height=40),
                config=TriggerConfig(
                    change_epsilon=0.05,
                    blink_duration_seconds=0.8,
                    decrease_colour=(240, 900, 1000),
                    increase_colour=(180, 900, 1000),
                    threshold_bands=[
                        ThresholdBand(threshold=0.5, colour=(40, 1000, 1000)),
                        ThresholdBand(threshold=0.2, colour=(0, 1000, 1000)),
                    ],
                ),
            ),
        ],
    )

    ambience_config.save(original)
    loaded = ambience_config.load()

    assert loaded == original


def test_trigger_watcher_config_falls_back_to_defaults_for_missing_keys(tmp_path, monkeypatch):
    """A hand-edited or older-format watcher entry missing some TriggerConfig
    keys should still load, falling back to TriggerConfig()'s own defaults for
    whatever's missing, not crash."""
    config_path = tmp_path / "ambience_config.json"
    config_path.write_text(
        '{"monitor_index": 1, "region": null, "gaming_mode": true, "trigger_watchers": '
        '[{"watcher_id": "x1", "name": "Partial", "region": {"x": 0, "y": 0, "width": 10, "height": 10}, '
        '"config": {"change_epsilon": 0.1}}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(ambience_config, "CONFIG_PATH", config_path)

    loaded = ambience_config.load()

    watcher = loaded.trigger_watchers[0]
    assert watcher.config.change_epsilon == 0.1
    assert watcher.config.decrease_colour == TriggerConfig().decrease_colour
    assert watcher.config.threshold_bands == TriggerConfig().threshold_bands


def test_trigger_config_falls_back_to_current_defaults_for_a_pre_ocr_file(tmp_path, monkeypatch):
    """A watcher saved before OCR mode existed has no detection_mode/
    ocr_max_value keys at all - must still load, defaulting to whatever
    TriggerConfig()'s current defaults are (auto detection, ocr_max_value=100),
    not whatever they happened to be when this watcher was first saved."""
    config_path = tmp_path / "ambience_config.json"
    config_path.write_text(
        '{"monitor_index": 1, "region": null, "gaming_mode": true, "trigger_watchers": '
        '[{"watcher_id": "x1", "name": "Old watcher", "region": {"x": 0, "y": 0, "width": 10, "height": 10}, '
        '"config": {"change_epsilon": 0.1}}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(ambience_config, "CONFIG_PATH", config_path)

    loaded = ambience_config.load()

    watcher = loaded.trigger_watchers[0]
    assert watcher.config.detection_mode == TriggerConfig().detection_mode
    assert watcher.config.ocr_max_value == TriggerConfig().ocr_max_value


def test_save_then_load_round_trips_ocr_detection_mode_and_a_painted_mask(tmp_path, monkeypatch):
    """A watcher using OCR mode (with a max_value fallback configured) and a
    painted, non-rectangular region (see BrushSelectorWindow) round-trips
    through save/load exactly."""
    monkeypatch.setattr(ambience_config, "CONFIG_PATH", tmp_path / "ambience_config.json")
    original = AmbienceConfig(
        gaming_mode=True,
        trigger_watchers=[
            TriggerWatcher(
                watcher_id="def456",
                name="Mana readout",
                region=AmbienceRegion(x=5, y=5, width=10, height=10, mask="deadbeef=="),
                config=TriggerConfig(detection_mode="ocr", ocr_max_value=250.0),
            ),
        ],
    )

    ambience_config.save(original)
    loaded = ambience_config.load()

    assert loaded == original
    assert loaded.trigger_watchers[0].region.mask == "deadbeef=="
    assert loaded.trigger_watchers[0].config.detection_mode == "ocr"
    assert loaded.trigger_watchers[0].config.ocr_max_value == 250.0


def test_ambience_region_mask_defaults_to_none_for_a_pre_mask_file(tmp_path, monkeypatch):
    config_path = tmp_path / "ambience_config.json"
    config_path.write_text(
        '{"monitor_index": 1, "region": {"x": 0, "y": 0, "width": 100, "height": 50}, "gaming_mode": false}',
        encoding="utf-8",
    )
    monkeypatch.setattr(ambience_config, "CONFIG_PATH", config_path)

    loaded = ambience_config.load()

    assert loaded.region.mask is None


def test_load_defaults_colour_sensitivity_and_smoothing_for_a_pre_slider_file(tmp_path, monkeypatch):
    config_path = tmp_path / "ambience_config.json"
    config_path.write_text('{"monitor_index": 1, "region": null, "gaming_mode": false}', encoding="utf-8")
    monkeypatch.setattr(ambience_config, "CONFIG_PATH", config_path)

    loaded = ambience_config.load()

    assert loaded.colour_sensitivity == AMBIENCE_SLIDER_DEFAULT
    assert loaded.smoothing == AMBIENCE_SLIDER_DEFAULT


def test_save_then_load_round_trips_colour_sensitivity_and_smoothing(tmp_path, monkeypatch):
    monkeypatch.setattr(ambience_config, "CONFIG_PATH", tmp_path / "ambience_config.json")
    original = AmbienceConfig(colour_sensitivity=80.0, smoothing=20.0)

    ambience_config.save(original)
    loaded = ambience_config.load()

    assert loaded == original
