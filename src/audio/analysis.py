"""FFT-based brightness envelope and onset (hard colour-change) detection.

Two independent signals are derived from the same audio block:
- brightness: band energy from the FFT magnitude spectrum, mapped from a
  fixed dB range onto 10-1000 and smoothed with an attack/release
  envelope, so it tracks loudness without flickering.
- onset: a spectral-flux beat/hit detector with an adaptive threshold
  and a minimum interval, so hard colour changes stay reactive without
  strobing.

An earlier version normalized brightness against a self-adapting peak
(classic AGC). That collapsed to "near-max brightness for any sustained
sound" because the peak locks onto whatever level is currently playing
within a single block, quiet or loud, making relative loudness
indistinguishable. Fixed dB bounds avoid that; DB_FLOOR/DB_CEIL below
are calibrated against synthetic tones and broadband noise, not a
broad corpus of real music, and may need retuning by ear.
"""
from __future__ import annotations

import numpy as np

MIN_FREQ_HZ = 30
MAX_FREQ_HZ = 8000

BRIGHTNESS_MIN = 10
BRIGHTNESS_MAX = 1000

# Fixed loudness calibration (dB of mean band magnitude) mapped onto the
# brightness range. See module docstring for why this isn't adaptive.
DB_FLOOR = -10.0
DB_CEIL = 20.0
ENERGY_EPSILON = 1e-8

# Envelope smoothing time constants (seconds): brightness rises quickly on
# a hit but decays slowly, which reads as "pulsing with the music" rather
# than flickering.
BRIGHTNESS_ATTACK_SECONDS = 0.05
BRIGHTNESS_RELEASE_SECONDS = 0.25

# Onset detection (spectral flux with an adaptive threshold).
ONSET_HISTORY_SIZE = 43  # roughly 1 second at a 1024-sample / 44100 Hz block rate
ONSET_MIN_HISTORY = ONSET_HISTORY_SIZE // 2
ONSET_THRESHOLD_MULTIPLIER = 1.8
ONSET_MIN_INTERVAL_SECONDS = 0.18  # debounce: caps hard colour jumps at ~5-6/second


class AudioEnvelope:
    """Turns a stream of audio blocks into a smoothed brightness value and onset events."""

    def __init__(self, sample_rate: int, block_size: int):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self._block_seconds = block_size / sample_rate
        self._window = np.hanning(block_size)
        freqs = np.fft.rfftfreq(block_size, d=1 / sample_rate)
        self._band_mask = (freqs >= MIN_FREQ_HZ) & (freqs <= MAX_FREQ_HZ)

        self._brightness = float(BRIGHTNESS_MIN)
        self._prev_spectrum: np.ndarray | None = None
        self._flux_history: list[float] = []
        self._last_onset_time: float | None = None

    def process(self, block: np.ndarray, now: float) -> tuple[int, bool]:
        """Feed one audio block; return (brightness in 10-1000, whether an onset fired)."""
        spectrum = np.abs(np.fft.rfft(block * self._window))
        band_energy = float(np.mean(spectrum[self._band_mask])) if self._band_mask.any() else 0.0

        db = 20.0 * np.log10(band_energy + ENERGY_EPSILON)
        normalized = min(1.0, max(0.0, (db - DB_FLOOR) / (DB_CEIL - DB_FLOOR)))
        target_brightness = BRIGHTNESS_MIN + normalized * (BRIGHTNESS_MAX - BRIGHTNESS_MIN)

        tau = BRIGHTNESS_ATTACK_SECONDS if target_brightness > self._brightness else BRIGHTNESS_RELEASE_SECONDS
        alpha = 1.0 - np.exp(-self._block_seconds / tau)
        self._brightness += alpha * (target_brightness - self._brightness)

        onset = self._detect_onset(spectrum, now)
        return int(round(self._brightness)), onset

    def _detect_onset(self, spectrum: np.ndarray, now: float) -> bool:
        """Spectral flux: sum of positive frame-to-frame magnitude increases."""
        if self._prev_spectrum is None:
            self._prev_spectrum = spectrum
            return False
        flux = float(np.sum(np.maximum(0.0, spectrum - self._prev_spectrum)))
        self._prev_spectrum = spectrum

        self._flux_history.append(flux)
        if len(self._flux_history) > ONSET_HISTORY_SIZE:
            self._flux_history.pop(0)
        if len(self._flux_history) < ONSET_MIN_HISTORY:
            return False

        baseline = self._flux_history[:-1]
        threshold = float(np.mean(baseline) + ONSET_THRESHOLD_MULTIPLIER * np.std(baseline))
        if flux <= threshold:
            return False
        if self._last_onset_time is not None and now - self._last_onset_time < ONSET_MIN_INTERVAL_SECONDS:
            return False
        self._last_onset_time = now
        return True
