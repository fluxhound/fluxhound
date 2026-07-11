"""Unit tests for src.audio.custom_show (synthetic signals, no audio hardware)."""
from __future__ import annotations

import numpy as np

from src.audio.custom_show import (
    SOURCE_BEAT,
    SOURCE_ENERGY,
    SOURCE_TIMBRE,
    TARGET_BRIGHTNESS,
    TARGET_HUE,
    ONSET_MIN_HISTORY,
    CustomShowEnvelope,
    _sensitivity_factor,
    target_value,
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


def test_target_value_maps_normalized_range_and_clamps():
    assert target_value(TARGET_HUE, 0.0) == 0
    assert target_value(TARGET_HUE, 1.0) == 270
    assert target_value(TARGET_HUE, -5.0) == 0  # clamped below range
    assert target_value(TARGET_HUE, 5.0) == 270  # clamped above range
    assert target_value(TARGET_BRIGHTNESS, 0.5) == 505  # 10 + 0.5*(1000-10)


def test_silence_keeps_energy_at_zero_and_no_beat():
    envelope = CustomShowEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    silence = np.zeros(BLOCK_SIZE, dtype=np.float32)
    now = 0.0
    values = None
    for _ in range(30):
        values = envelope.process(silence, now)
        now += BLOCK_SECONDS
    assert values[SOURCE_ENERGY] == 0.0
    assert values[SOURCE_BEAT] == 0.0


def test_timbre_rises_for_broadband_vs_bass_tone():
    envelope = CustomShowEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    now = 0.0
    timbre_bass = 0.0
    for _ in range(40):
        values = envelope.process(_tone(0.5, freq=80.0), now)
        timbre_bass = values[SOURCE_TIMBRE]
        now += BLOCK_SECONDS

    envelope2 = CustomShowEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    timbre_noise = 0.0
    for i in range(40):
        values = envelope2.process(_noise(0.5, seed=i), now)
        timbre_noise = values[SOURCE_TIMBRE]
        now += BLOCK_SECONDS

    assert timbre_noise > timbre_bass


def test_beat_spikes_on_sudden_burst_then_decays():
    envelope = CustomShowEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    quiet = _tone(0.02, freq=80.0)
    now = 0.0
    for _ in range(ONSET_MIN_HISTORY + 5):
        values = envelope.process(quiet, now)
        now += BLOCK_SECONDS
    assert values[SOURCE_BEAT] == 0.0

    burst = _tone(1.0, freq=1200.0)
    values = envelope.process(burst, now)
    assert values[SOURCE_BEAT] == 1.0
    now += BLOCK_SECONDS

    beat_after_decay = values[SOURCE_BEAT]
    for _ in range(20):
        values = envelope.process(quiet, now)
        beat_after_decay = values[SOURCE_BEAT]
        now += BLOCK_SECONDS
    assert beat_after_decay < 1.0


def test_set_initial_seeds_timbre_and_energy():
    envelope = CustomShowEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    envelope.set_initial(timbre=0.7, energy=0.4)
    silence = np.zeros(BLOCK_SIZE, dtype=np.float32)
    # A single silent block should barely move the seeded values (slow release), not
    # snap instantly back to 0 - confirms the seed actually took effect.
    values = envelope.process(silence, 0.0)
    assert values[SOURCE_TIMBRE] > 0.5
    assert values[SOURCE_ENERGY] > 0.2


def test_sensitivity_factor_is_neutral_at_50_and_symmetric():
    assert _sensitivity_factor(50.0) == 1.0
    assert _sensitivity_factor(50.0, inverse=True) == 1.0
    # non-inverse: higher sensitivity -> smaller factor
    assert _sensitivity_factor(100.0) < _sensitivity_factor(50.0) < _sensitivity_factor(0.0)
    # inverse: higher sensitivity -> larger factor
    assert _sensitivity_factor(100.0, inverse=True) > _sensitivity_factor(50.0, inverse=True) > \
        _sensitivity_factor(0.0, inverse=True)
    # symmetric around 50 in log-space: factor(0) * factor(100) == 1 for either direction
    assert abs(_sensitivity_factor(0.0) * _sensitivity_factor(100.0) - 1.0) < 1e-9


def test_higher_energy_sensitivity_reaches_target_brightness_from_quieter_sound():
    quiet_noise = _noise(0.05, seed=7)

    low_sensitivity = CustomShowEnvelope(SAMPLE_RATE, BLOCK_SIZE, sensitivity={
        SOURCE_TIMBRE: 50.0, SOURCE_ENERGY: 10.0, SOURCE_BEAT: 50.0,
    })
    high_sensitivity = CustomShowEnvelope(SAMPLE_RATE, BLOCK_SIZE, sensitivity={
        SOURCE_TIMBRE: 50.0, SOURCE_ENERGY: 90.0, SOURCE_BEAT: 50.0,
    })

    energy_low = energy_high = 0.0
    for _ in range(20):
        energy_low = low_sensitivity.process(quiet_noise, 0.0)[SOURCE_ENERGY]
        energy_high = high_sensitivity.process(quiet_noise, 0.0)[SOURCE_ENERGY]
    assert energy_high > energy_low


def test_set_sensitivity_updates_live():
    envelope = CustomShowEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    assert envelope._sensitivity[SOURCE_BEAT] == 50.0
    envelope.set_sensitivity(SOURCE_BEAT, 90.0)
    assert envelope._sensitivity[SOURCE_BEAT] == 90.0
