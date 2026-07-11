"""Unit tests for src.audio.analysis (synthetic signals, no audio hardware)."""
from __future__ import annotations

import numpy as np

from src.audio.analysis import BRIGHTNESS_MIN, AudioEnvelope

SAMPLE_RATE = 44100
BLOCK_SIZE = 1024


def _tone(amplitude: float, freq: float) -> np.ndarray:
    t = np.arange(BLOCK_SIZE) / SAMPLE_RATE
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_silence_stays_at_minimum_brightness():
    envelope = AudioEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    silence = np.zeros(BLOCK_SIZE, dtype=np.float32)
    brightness = BRIGHTNESS_MIN
    for _ in range(30):
        brightness = envelope.process(silence)
    assert brightness == BRIGHTNESS_MIN


def test_brightness_rises_with_a_louder_bass_tone():
    envelope = AudioEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    brightness_quiet = BRIGHTNESS_MIN
    for _ in range(10):
        brightness_quiet = envelope.process(_tone(0.05, freq=80.0))
    brightness_loud = brightness_quiet
    for _ in range(10):
        brightness_loud = envelope.process(_tone(0.9, freq=80.0))
    assert brightness_loud > brightness_quiet


def test_treble_content_does_not_move_bass_driven_brightness():
    """Brightness only watches the bass band, so a pure high-frequency tone must not spike it."""
    envelope = AudioEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    brightness = BRIGHTNESS_MIN
    for _ in range(15):
        brightness = envelope.process(_tone(0.9, freq=5000.0))
    assert brightness == BRIGHTNESS_MIN


def test_brightness_drops_back_after_a_bass_hit_ends():
    """Release should be fast enough that a hit doesn't leave brightness stuck up for long."""
    envelope = AudioEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    for _ in range(10):
        peak_brightness = envelope.process(_tone(0.9, freq=80.0))
    silence = np.zeros(BLOCK_SIZE, dtype=np.float32)
    brightness_after_release = peak_brightness
    for _ in range(10):
        brightness_after_release = envelope.process(silence)
    assert brightness_after_release < peak_brightness
