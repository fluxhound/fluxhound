"""Unit tests for src.audio.custom_show (synthetic signals, no audio hardware)."""
from __future__ import annotations

import numpy as np
import pytest

from src.audio.custom_show import (
    BANDS,
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


def test_debug_snapshot_reflects_raw_pre_sensitivity_readings():
    """--debug logging (CustomMode) reads these back every block - a value pinned
    at 0 or 1 in the final smoothed output shouldn't hide whether that's the real
    signal or just the current gain/threshold, so these track the raw numbers."""
    envelope = CustomShowEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    envelope.process(_tone(0.5, freq=1200.0), 0.0)
    snapshot = envelope.debug_snapshot()
    expected_keys = {"centroid_hz", "energy_raw", "flux", "onset_threshold"}
    expected_keys |= {f"{name}_floor_db" for name in BANDS} | {f"{name}_ceiling_db" for name in BANDS}
    assert set(snapshot) == expected_keys
    assert snapshot["centroid_hz"] > 0.0
    assert snapshot["energy_raw"] >= 0.0


def test_debug_snapshot_flux_reacts_to_a_sudden_burst():
    envelope = CustomShowEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    quiet = _tone(0.02, freq=80.0)
    now = 0.0
    for _ in range(ONSET_MIN_HISTORY + 5):
        envelope.process(quiet, now)
        now += BLOCK_SECONDS
    quiet_flux = envelope.debug_snapshot()["flux"]

    envelope.process(_tone(1.0, freq=1200.0), now)
    burst_flux = envelope.debug_snapshot()["flux"]
    assert burst_flux > quiet_flux


# -- Energy's per-band auto-leveling (a lower overall playback volume must not -----
# -- just flatten Energy's usable range - see ADAPTIVE_RANGE_* in custom_show.py) --

def _song(volume_scale: float, cycles: int = 10, loud_blocks: int = 10, quiet_blocks: int = 10):
    """A synthetic "song": alternating louder/quieter noise bursts (its own internal
    dynamics), all scaled by volume_scale - mimicking turning overall playback volume
    up/down without changing the music's own loud/quiet structure. Returns
    (blocks, is_loud) parallel arrays."""
    blocks: list[np.ndarray] = []
    is_loud: list[bool] = []
    seed = 0
    for _ in range(cycles):
        for _ in range(loud_blocks):
            blocks.append(_noise(0.5 * volume_scale, seed))
            is_loud.append(True)
            seed += 1
        for _ in range(quiet_blocks):
            blocks.append(_noise(0.05 * volume_scale, seed))
            is_loud.append(False)
            seed += 1
    return blocks, np.array(is_loud)


def test_quiet_overall_volume_no_longer_clips_the_songs_own_quiet_passages_to_zero():
    """Regression guard for the exact real-world complaint: at a much lower overall
    playback volume, the fixed BANDS db_floor previously clipped a song's own
    quieter passages to a flat 0 (verified separately against the pre-fix formula:
    50% of blocks landing exactly at 0.0 at a 20dB-quieter volume) - the adaptive
    floor/ceiling should keep at least some daylight between loud and quiet instead."""
    quiet_volume_song, is_loud = _song(volume_scale=0.1)  # -20dB overall
    envelope = CustomShowEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    now = 0.0
    energy = np.zeros(len(quiet_volume_song))
    for i, block in enumerate(quiet_volume_song):
        energy[i] = envelope.process(block, now)[SOURCE_ENERGY]
        now += BLOCK_SECONDS

    tail = slice(len(quiet_volume_song) // 2, None)  # let the range adapt first
    assert np.mean(energy[tail] < 0.02) == 0.0  # never clips flat to 0 once adapted
    assert energy[tail][is_loud[tail]].mean() > energy[tail][~is_loud[tail]].mean()


def test_adaptive_range_tracks_a_volume_increase_back_up():
    """If a genuinely louder signal follows a long quiet stretch (the volume gets
    turned back up, or a louder passage arrives), the ceiling should track it
    within a few seconds rather than staying pinned to the quiet calibration."""
    envelope = CustomShowEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    now = 0.0
    quiet = _noise(0.02, seed=1)
    for _ in range(200):  # ~4.6s - enough for the floor/ceiling to adapt down
        envelope.process(quiet, now)
        now += BLOCK_SECONDS
    quiet_ceiling = envelope.debug_snapshot()["bass_ceiling_db"]

    loud = _noise(0.9, seed=2)
    for _ in range(130):  # ~3s - within the 2s attack time constant
        envelope.process(loud, now)
        now += BLOCK_SECONDS
    louder_ceiling = envelope.debug_snapshot()["bass_ceiling_db"]

    assert louder_ceiling > quiet_ceiling


def test_true_silence_does_not_drag_the_floor_down_and_inflate_energy_on_resume():
    """Regression guard for a real bug found in a --debug log: a gap of true
    digital silence (between songs, before playback starts) has no real content
    to calibrate against, but the floor's fast attack chased it all the way down
    to ADAPTIVE_RANGE_ABSOLUTE_MIN_DB anyway - when music resumed, the floor sat
    miscalibrated there and only crawled back up over the slow ~12s release, so
    Energy read inflated (pinned near/at 1.0) for many seconds right after every
    silence gap. SILENCE_GATE_DB fixes this by freezing floor/ceiling instead of
    chasing a reading that quiet."""
    envelope = CustomShowEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    music = _noise(0.3, seed=1)
    silence = np.zeros(BLOCK_SIZE, dtype=np.float32)
    now = 0.0
    for i in range(100):  # establish a normal, sensibly-adapted floor first
        envelope.process(_noise(0.3, i), now)
        now += BLOCK_SECONDS
    floor_before_silence = envelope.debug_snapshot()["bass_floor_db"]

    for _ in range(260):  # ~6s of true silence - long enough to have triggered the bug
        envelope.process(silence, now)
        now += BLOCK_SECONDS
    floor_after_silence = envelope.debug_snapshot()["bass_floor_db"]
    assert floor_after_silence == pytest.approx(floor_before_silence, abs=0.5)

    energy_right_after_resume = envelope.process(music, now)[SOURCE_ENERGY]
    assert energy_right_after_resume < 0.95  # no longer pinned near-max immediately on resume
