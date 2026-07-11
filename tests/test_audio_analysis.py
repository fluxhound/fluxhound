"""Unit tests for src.audio.analysis (synthetic signals, no audio hardware)."""
from __future__ import annotations

import numpy as np

from src.audio.analysis import (
    BRIGHTNESS_MIN,
    HUE_COOL,
    HUE_WARM,
    AudioEnvelope,
)

SAMPLE_RATE = 44100
BLOCK_SIZE = 1024


def _tone(amplitude: float, freq: float) -> np.ndarray:
    t = np.arange(BLOCK_SIZE) / SAMPLE_RATE
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _noise(amplitude: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (amplitude * rng.standard_normal(BLOCK_SIZE)).astype(np.float32)


def test_silence_stays_at_minimum_brightness():
    envelope = AudioEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    silence = np.zeros(BLOCK_SIZE, dtype=np.float32)
    brightness = BRIGHTNESS_MIN
    for _ in range(30):
        brightness, _ = envelope.process(silence)
    assert brightness == BRIGHTNESS_MIN


def test_brightness_rises_with_a_louder_bass_tone():
    envelope = AudioEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    brightness_quiet = BRIGHTNESS_MIN
    for _ in range(10):
        brightness_quiet, _ = envelope.process(_tone(0.05, freq=80.0))
    brightness_loud = brightness_quiet
    for _ in range(10):
        brightness_loud, _ = envelope.process(_tone(0.9, freq=80.0))
    assert brightness_loud > brightness_quiet


def test_treble_content_does_not_move_bass_driven_brightness():
    """Brightness only watches the bass band, so a pure high-frequency tone must not spike it."""
    envelope = AudioEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    brightness = BRIGHTNESS_MIN
    for _ in range(15):
        brightness, _ = envelope.process(_tone(0.9, freq=5000.0))
    assert brightness == BRIGHTNESS_MIN


def test_hue_leans_warm_for_bass_heavy_sound():
    envelope = AudioEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    hue = HUE_COOL
    for _ in range(30):
        _, hue = envelope.process(_tone(0.5, freq=80.0))
    assert hue < (HUE_WARM + HUE_COOL) / 2


def test_hue_leans_cool_for_treble_heavy_sound():
    envelope = AudioEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    hue = HUE_WARM
    for _ in range(30):
        _, hue = envelope.process(_noise(0.5, seed=1))
    assert hue > (HUE_WARM + HUE_COOL) / 2


def test_hue_moves_smoothly_not_in_a_hard_jump():
    """A single block of very different content must nudge the hue, not snap it instantly."""
    envelope = AudioEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    hue = HUE_WARM
    for _ in range(30):
        _, hue = envelope.process(_tone(0.5, freq=80.0))
    warm_hue = hue

    _, hue_after_one_block = envelope.process(_noise(0.5, seed=2))

    assert hue_after_one_block > warm_hue  # it did move towards cool...
    assert hue_after_one_block < HUE_COOL - 20  # ...but nowhere near an instant jump to it
