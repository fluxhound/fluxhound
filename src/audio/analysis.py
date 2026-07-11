"""FFT-based bass brightness envelope.

Brightness comes from bass-band FFT magnitude energy, mapped from a
fixed dB range onto 10-1000 and lightly smoothed (fast attack, fast
release) so bass hits stay punchy instead of fading slowly.

DB_FLOOR/DB_CEIL are calibrated against synthetic tones, not a broad
corpus of real music — tune them by ear if brightness feels off.
"""
from __future__ import annotations

import numpy as np

# Bass band only (kick drum / bassline range).
BASS_MIN_FREQ_HZ = 20
BASS_MAX_FREQ_HZ = 200

BRIGHTNESS_MIN = 10
BRIGHTNESS_MAX = 1000

# Fixed loudness calibration (dB of mean bass-band magnitude).
DB_FLOOR = 10.0
DB_CEIL = 40.0
ENERGY_EPSILON = 1e-8

# Light smoothing: fast enough that individual bass hits still read as
# punchy hits rather than a slow fade.
BRIGHTNESS_ATTACK_SECONDS = 0.03
BRIGHTNESS_RELEASE_SECONDS = 0.12


class AudioEnvelope:
    """Turns a stream of audio blocks into a smoothed bass-brightness value."""

    def __init__(self, sample_rate: int, block_size: int):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self._block_seconds = block_size / sample_rate
        self._window = np.hanning(block_size)
        freqs = np.fft.rfftfreq(block_size, d=1 / sample_rate)
        self._bass_mask = (freqs >= BASS_MIN_FREQ_HZ) & (freqs <= BASS_MAX_FREQ_HZ)

        self._brightness = float(BRIGHTNESS_MIN)

    def process(self, block: np.ndarray) -> int:
        """Feed one audio block; return the current brightness (10-1000)."""
        spectrum = np.abs(np.fft.rfft(block * self._window))
        bass_energy = float(np.mean(spectrum[self._bass_mask])) if self._bass_mask.any() else 0.0

        db = 20.0 * np.log10(bass_energy + ENERGY_EPSILON)
        normalized = min(1.0, max(0.0, (db - DB_FLOOR) / (DB_CEIL - DB_FLOOR)))
        target_brightness = BRIGHTNESS_MIN + normalized * (BRIGHTNESS_MAX - BRIGHTNESS_MIN)

        tau = BRIGHTNESS_ATTACK_SECONDS if target_brightness > self._brightness else BRIGHTNESS_RELEASE_SECONDS
        alpha = 1.0 - np.exp(-self._block_seconds / tau)
        self._brightness += alpha * (target_brightness - self._brightness)

        return int(round(self._brightness))
