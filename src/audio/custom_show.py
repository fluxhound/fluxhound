"""Music Mode 3 ("Custom Mode"): user-configurable full-spectrum light show.

Three independent audio "sources" are computed every block, each producing a
normalized 0-1 signal with its own natural smoothing behaviour, reusing the
exact calibration from Music Mode 2 (src/audio/spectrum_show.py):
- **Timbre** (spectral centroid): continuous drift, low for bass/tonal-heavy
  sound, high for bright/noisy sound.
- **Energy** (weighted bass/mid/treble band energy): continuous loudness
  pulse.
- **Beat** (onset/spectral-flux detection): idle at 0, spikes to 1 the
  instant a hit is detected, decaying back down - a "flash" envelope.

The GUI lets the user assign each source to at most one of Hue/Brightness/
Saturation (a bijection enforced there, not here - `MainWindow` disables a
source's buttons in the other two categories once it's assigned somewhere).
A target with no source assigned simply isn't touched by `target_value` -
the caller keeps sending whatever that target's last value was.

Whatever a source ends up assigned to, its normalized value maps onto that
target's own natural range the same way:
`target_min + normalized * (target_max - target_min)`. That range is always
the one already calibrated for that target in Music Mode 2 - hue 0-270,
brightness 10-1000, saturation 400-1000 - regardless of which source is
feeding it, so reassigning a source never needs new calibration.
"""
from __future__ import annotations

import numpy as np

from src.audio.spectrum_show import (
    BANDS,
    BRIGHTNESS_MAX,
    BRIGHTNESS_MIN,
    CENTROID_MAX_HZ,
    CENTROID_MIN_HZ,
    ENERGY_EPSILON,
    HUE_COOL,
    HUE_WARM,
    SATURATION_DIP,
    SATURATION_MAX,
)

SOURCE_TIMBRE = "timbre"
SOURCE_ENERGY = "energy"
SOURCE_BEAT = "beat"
SOURCES = (SOURCE_TIMBRE, SOURCE_ENERGY, SOURCE_BEAT)

TARGET_HUE = "hue"
TARGET_BRIGHTNESS = "brightness"
TARGET_SATURATION = "saturation"
TARGETS = (TARGET_HUE, TARGET_BRIGHTNESS, TARGET_SATURATION)

TARGET_RANGES: dict[str, tuple[float, float]] = {
    TARGET_HUE: (HUE_WARM, HUE_COOL),
    TARGET_BRIGHTNESS: (BRIGHTNESS_MIN, BRIGHTNESS_MAX),
    TARGET_SATURATION: (SATURATION_DIP, SATURATION_MAX),
}

TIMBRE_SMOOTHING_SECONDS = 0.5
ENERGY_ATTACK_SECONDS = 0.055
ENERGY_RELEASE_SECONDS = 0.185
BEAT_RECOVER_SECONDS = 0.2

ONSET_HISTORY_SIZE = 43  # roughly 1 second at a 1024-sample / 44100 Hz block rate
ONSET_MIN_HISTORY = ONSET_HISTORY_SIZE // 2
ONSET_THRESHOLD_MULTIPLIER = 1.8
ONSET_MIN_INTERVAL_SECONDS = 0.15


def target_value(target: str, normalized: float) -> int:
    """Map a source's normalized [0,1] value onto a target's own DP range."""
    lo, hi = TARGET_RANGES[target]
    normalized = max(0.0, min(1.0, normalized))
    return int(round(lo + normalized * (hi - lo)))


class CustomShowEnvelope:
    """Computes all three source signals every block; the caller decides which
    (if any) target each one feeds."""

    def __init__(self, sample_rate: int, block_size: int):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self._block_seconds = block_size / sample_rate
        self._window = np.hanning(block_size)
        self._freqs = np.fft.rfftfreq(block_size, d=1 / sample_rate)
        self._band_masks = {
            name: (self._freqs >= lo) & (self._freqs <= hi) for name, (lo, hi, *_rest) in BANDS.items()
        }
        self._log_centroid_min = np.log2(CENTROID_MIN_HZ)
        self._log_centroid_range = np.log2(CENTROID_MAX_HZ) - self._log_centroid_min

        self._timbre = 0.0
        self._energy = 0.0
        self._beat = 0.0
        self._prev_spectrum: np.ndarray | None = None
        self._flux_history: list[float] = []
        self._last_onset_time: float | None = None

    def set_initial(self, timbre: float | None = None, energy: float | None = None) -> None:
        """Seed the smoothed timbre/energy signals, e.g. from the bulb's current state
        translated back through whichever target they're currently assigned to, so the
        show drifts from there instead of snapping from 0. Beat is a transient spike, not
        a resting level, so it isn't seeded - it naturally starts idle."""
        if timbre is not None:
            self._timbre = max(0.0, min(1.0, timbre))
        if energy is not None:
            self._energy = max(0.0, min(1.0, energy))

    def process(self, block: np.ndarray, now: float) -> dict[str, float]:
        """Feed one audio block; return {"timbre": .., "energy": .., "beat": ..}, each 0-1."""
        spectrum = np.abs(np.fft.rfft(block * self._window))

        self._update_timbre(spectrum)
        self._update_energy(spectrum)
        self._update_beat(spectrum, now)

        return {SOURCE_TIMBRE: self._timbre, SOURCE_ENERGY: self._energy, SOURCE_BEAT: self._beat}

    def _update_timbre(self, spectrum: np.ndarray) -> None:
        total = float(np.sum(spectrum))
        centroid = float(np.sum(self._freqs * spectrum) / total) if total > 0 else CENTROID_MIN_HZ
        centroid = min(CENTROID_MAX_HZ, max(CENTROID_MIN_HZ, centroid))
        target = (np.log2(centroid) - self._log_centroid_min) / self._log_centroid_range
        alpha = 1.0 - np.exp(-self._block_seconds / TIMBRE_SMOOTHING_SECONDS)
        self._timbre += alpha * (target - self._timbre)

    def _update_energy(self, spectrum: np.ndarray) -> None:
        normalized_sum = 0.0
        for name, (_lo, _hi, weight, db_floor, db_ceil) in BANDS.items():
            mask = self._band_masks[name]
            band_energy = float(np.mean(spectrum[mask])) if mask.any() else 0.0
            db = 20.0 * np.log10(band_energy + ENERGY_EPSILON)
            normalized = min(1.0, max(0.0, (db - db_floor) / (db_ceil - db_floor)))
            normalized_sum += normalized * weight

        tau = ENERGY_ATTACK_SECONDS if normalized_sum > self._energy else ENERGY_RELEASE_SECONDS
        alpha = 1.0 - np.exp(-self._block_seconds / tau)
        self._energy += alpha * (normalized_sum - self._energy)

    def _update_beat(self, spectrum: np.ndarray, now: float) -> None:
        if self._detect_onset(spectrum, now):
            self._beat = 1.0
        else:
            alpha = 1.0 - np.exp(-self._block_seconds / BEAT_RECOVER_SECONDS)
            self._beat += alpha * (0.0 - self._beat)

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
