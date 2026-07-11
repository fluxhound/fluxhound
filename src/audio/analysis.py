"""FFT-based bass brightness envelope and spectral-centroid-driven hue.

Two independent signals are derived from the same audio block:
- brightness: bass-band FFT magnitude energy, mapped from a fixed dB
  range onto 10-1000 and lightly smoothed (fast attack, fast release)
  so bass hits stay punchy instead of fading slowly.
- hue: the spectrum's centroid (its "center of mass" frequency) mapped
  onto a warm (bass-heavy) to cool (treble-heavy) hue range and
  smoothed, so colour drifts continuously with the sound's timbre
  instead of jumping hard on a trigger.

DB_FLOOR/DB_CEIL and CENTROID_MIN_HZ/CENTROID_MAX_HZ are calibrated
against synthetic tones and noise, not a broad corpus of real music —
tune them by ear if brightness or colour movement feels off.
"""
from __future__ import annotations

import numpy as np

# Brightness: bass band only (kick drum / bassline range).
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

# Hue: spectral centroid mapped log-scale across a warm-to-cool hue
# range (stops short of 360 so it doesn't wrap back to red/warm).
CENTROID_MIN_HZ = 200.0
CENTROID_MAX_HZ = 6000.0
HUE_WARM = 0.0
HUE_COOL = 270.0
HUE_SMOOTHING_SECONDS = 0.4


class AudioEnvelope:
    """Turns a stream of audio blocks into a smoothed brightness value and hue."""

    def __init__(self, sample_rate: int, block_size: int):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self._block_seconds = block_size / sample_rate
        self._window = np.hanning(block_size)
        self._freqs = np.fft.rfftfreq(block_size, d=1 / sample_rate)
        self._bass_mask = (self._freqs >= BASS_MIN_FREQ_HZ) & (self._freqs <= BASS_MAX_FREQ_HZ)
        self._log_centroid_min = np.log2(CENTROID_MIN_HZ)
        self._log_centroid_range = np.log2(CENTROID_MAX_HZ) - self._log_centroid_min

        self._brightness = float(BRIGHTNESS_MIN)
        self._hue = HUE_WARM

    def process(self, block: np.ndarray) -> tuple[int, float]:
        """Feed one audio block; return (brightness in 10-1000, hue in 0-360)."""
        spectrum = np.abs(np.fft.rfft(block * self._window))

        bass_energy = float(np.mean(spectrum[self._bass_mask])) if self._bass_mask.any() else 0.0
        db = 20.0 * np.log10(bass_energy + ENERGY_EPSILON)
        normalized = min(1.0, max(0.0, (db - DB_FLOOR) / (DB_CEIL - DB_FLOOR)))
        target_brightness = BRIGHTNESS_MIN + normalized * (BRIGHTNESS_MAX - BRIGHTNESS_MIN)
        brightness_tau = BRIGHTNESS_ATTACK_SECONDS if target_brightness > self._brightness else BRIGHTNESS_RELEASE_SECONDS
        brightness_alpha = 1.0 - np.exp(-self._block_seconds / brightness_tau)
        self._brightness += brightness_alpha * (target_brightness - self._brightness)

        target_hue = self._centroid_to_hue(spectrum)
        hue_alpha = 1.0 - np.exp(-self._block_seconds / HUE_SMOOTHING_SECONDS)
        self._hue += hue_alpha * (target_hue - self._hue)

        return int(round(self._brightness)), float(self._hue)

    def _centroid_to_hue(self, spectrum: np.ndarray) -> float:
        """Map the spectrum's centroid frequency onto the warm-to-cool hue range."""
        total = float(np.sum(spectrum))
        centroid = float(np.sum(self._freqs * spectrum) / total) if total > 0 else CENTROID_MIN_HZ
        centroid = min(CENTROID_MAX_HZ, max(CENTROID_MIN_HZ, centroid))
        normalized = (np.log2(centroid) - self._log_centroid_min) / self._log_centroid_range
        return HUE_WARM + normalized * (HUE_COOL - HUE_WARM)
