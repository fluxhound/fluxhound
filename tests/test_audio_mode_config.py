"""Unit tests for src.audio_mode_config (no network I/O)."""
from __future__ import annotations

from src import audio_mode_config
from src.audio_mode_config import AudioModeConfig, DEFAULT_ASSIGNMENT, DEFAULT_SENSITIVITY


def test_load_returns_default_when_no_config_file(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_mode_config, "CONFIG_PATH", tmp_path / "audio_mode_config.json")
    config = audio_mode_config.load()
    assert config.assignment == DEFAULT_ASSIGNMENT
    assert config.sensitivity == DEFAULT_SENSITIVITY


def test_save_then_load_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_mode_config, "CONFIG_PATH", tmp_path / "audio_mode_config.json")
    original = AudioModeConfig(
        assignment={"hue": "beat", "brightness": None, "saturation": "timbre"},
        sensitivity={"timbre": 80.0, "energy": 20.0, "beat": 65.0},
    )

    audio_mode_config.save(original)
    loaded = audio_mode_config.load()

    assert loaded == original


def test_load_fills_in_missing_keys_from_a_partial_file(tmp_path, monkeypatch):
    config_path = tmp_path / "audio_mode_config.json"
    config_path.write_text('{"assignment": {"hue": "beat"}}', encoding="utf-8")
    monkeypatch.setattr(audio_mode_config, "CONFIG_PATH", config_path)

    loaded = audio_mode_config.load()

    assert loaded.assignment["hue"] == "beat"
    assert loaded.assignment["brightness"] == DEFAULT_ASSIGNMENT["brightness"]
    assert loaded.sensitivity == DEFAULT_SENSITIVITY
