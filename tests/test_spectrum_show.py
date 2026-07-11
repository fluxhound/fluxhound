"""Unit tests for src.audio.spectrum_show (synthetic signals, no audio hardware)."""
from __future__ import annotations

import numpy as np

from src.audio.spectrum_show import (
    BRIGHTNESS_MIN,
    HUE_COOL,
    HUE_WARM,
    ONSET_MIN_HISTORY,
    SATURATION_MAX,
    SpectrumShowEnvelope,
)

SAMPLE_RATE = 44100
BLOCK_SIZE = 1024
BLOCK_SECONDS = BLOCK_SIZE / SAMPLE_RATE


def _tone(amplitude: float, freq: float) -> np.ndarray:
    t = np.arange(BLOCK_SIZE) / SAMPLE_RATE
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _noise(amplitude: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (amplitude * rng.standard_normal(BLOCK_SIZE)).astype(np.float32)


def test_silence_stays_at_minimum_brightness_and_full_saturation():
    envelope = SpectrumShowEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    silence = np.zeros(BLOCK_SIZE, dtype=np.float32)
    now = 0.0
    hue = saturation = brightness = None
    for _ in range(30):
        hue, saturation, brightness = envelope.process(silence, now)
        now += BLOCK_SECONDS
    assert brightness == BRIGHTNESS_MIN
    assert saturation == SATURATION_MAX


def test_brightness_rises_with_loud_broadband_sound():
    envelope = SpectrumShowEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    now = 0.0
    brightness_quiet = BRIGHTNESS_MIN
    for i in range(10):
        _, _, brightness_quiet = envelope.process(_noise(0.01, seed=i), now)
        now += BLOCK_SECONDS
    brightness_loud = brightness_quiet
    for i in range(10):
        _, _, brightness_loud = envelope.process(_noise(0.5, seed=100 + i), now)
        now += BLOCK_SECONDS
    assert brightness_loud > brightness_quiet


def test_hue_leans_warm_for_a_steady_bass_tone():
    envelope = SpectrumShowEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    now = 0.0
    hue = HUE_COOL
    for _ in range(40):
        hue, _, _ = envelope.process(_tone(0.5, freq=80.0), now)
        now += BLOCK_SECONDS
    assert hue < (HUE_WARM + HUE_COOL) / 2


def test_hue_leans_cool_for_broadband_noise():
    envelope = SpectrumShowEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    now = 0.0
    hue = HUE_WARM
    for i in range(40):
        hue, _, _ = envelope.process(_noise(0.5, seed=i), now)
        now += BLOCK_SECONDS
    assert hue > (HUE_WARM + HUE_COOL) / 2


def test_sudden_burst_dips_saturation_then_it_recovers():
    envelope = SpectrumShowEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    quiet = _tone(0.02, freq=80.0)
    now = 0.0
    for _ in range(ONSET_MIN_HISTORY + 5):
        envelope.process(quiet, now)
        now += BLOCK_SECONDS

    burst = _tone(1.0, freq=1200.0)  # different frequency content = sharp spectral jump
    _, saturation_at_onset, _ = envelope.process(burst, now)
    assert saturation_at_onset < SATURATION_MAX
    now += BLOCK_SECONDS

    saturation_after_recovery = saturation_at_onset
    for _ in range(20):
        _, saturation_after_recovery, _ = envelope.process(quiet, now)
        now += BLOCK_SECONDS
    assert saturation_after_recovery > saturation_at_onset


def test_no_onset_on_a_perfectly_steady_tone():
    envelope = SpectrumShowEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    quiet = _tone(0.3, freq=80.0)
    now = 0.0
    min_saturation_seen = SATURATION_MAX
    for _ in range(ONSET_MIN_HISTORY + 10):
        _, saturation, _ = envelope.process(quiet, now)
        min_saturation_seen = min(min_saturation_seen, saturation)
        now += BLOCK_SECONDS
    assert min_saturation_seen == SATURATION_MAX
