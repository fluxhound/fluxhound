"""Unit tests for src.audio.analysis (synthetic signals, no audio hardware)."""
from __future__ import annotations

import numpy as np

from src.audio.analysis import (
    BRIGHTNESS_MIN,
    ONSET_MIN_HISTORY,
    ONSET_MIN_INTERVAL_SECONDS,
    AudioEnvelope,
)

SAMPLE_RATE = 44100
BLOCK_SIZE = 1024
BLOCK_SECONDS = BLOCK_SIZE / SAMPLE_RATE


def _tone(amplitude: float, freq: float = 440.0) -> np.ndarray:
    t = np.arange(BLOCK_SIZE) / SAMPLE_RATE
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _noise(amplitude: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (amplitude * rng.standard_normal(BLOCK_SIZE)).astype(np.float32)


def test_silence_stays_at_minimum_and_reports_no_onset():
    envelope = AudioEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    silence = np.zeros(BLOCK_SIZE, dtype=np.float32)
    now = 0.0
    brightness = BRIGHTNESS_MIN
    for _ in range(30):
        brightness, onset = envelope.process(silence, now)
        assert onset is False
        now += BLOCK_SECONDS
    assert brightness == BRIGHTNESS_MIN


def test_brightness_rises_when_loud_broadband_sound_starts():
    envelope = AudioEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    now = 0.0
    brightness_quiet = BRIGHTNESS_MIN
    for i in range(10):
        brightness_quiet, _ = envelope.process(_noise(0.01, seed=i), now)
        now += BLOCK_SECONDS
    brightness_loud = brightness_quiet
    for i in range(10):
        brightness_loud, _ = envelope.process(_noise(0.5, seed=100 + i), now)
        now += BLOCK_SECONDS
    assert brightness_loud > brightness_quiet


def test_sudden_burst_after_steady_quiet_tone_is_an_onset():
    envelope = AudioEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    quiet = _tone(0.02)
    now = 0.0
    onset_seen = False
    for _ in range(ONSET_MIN_HISTORY + 5):
        _, onset = envelope.process(quiet, now)
        onset_seen = onset_seen or onset
        now += BLOCK_SECONDS
    assert onset_seen is False, "a perfectly steady tone must not trigger an onset"

    burst = _tone(1.0, freq=1200.0)  # different frequency content = sharp spectral jump
    _, onset = envelope.process(burst, now)
    assert onset is True


def test_onsets_are_debounced_within_the_minimum_interval():
    envelope = AudioEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    quiet = _tone(0.02)
    now = 0.0
    for _ in range(ONSET_MIN_HISTORY + 5):
        envelope.process(quiet, now)
        now += BLOCK_SECONDS

    _, first_onset = envelope.process(_tone(1.0, freq=1200.0), now)
    assert first_onset is True

    now += ONSET_MIN_INTERVAL_SECONDS / 2  # well within the debounce window
    _, second_onset = envelope.process(_tone(1.0, freq=300.0), now)
    assert second_onset is False
