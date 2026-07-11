"""Audio Mode: user-configurable full-spectrum light show.

Three independent audio "sources" are computed every block, each producing a
normalized 0-1 signal with its own natural smoothing behaviour:
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
the one calibrated for that target (hue 0-270, brightness 10-1000,
saturation 400-1000), regardless of which source is feeding it, so
reassigning a source never needs new calibration.

Each source also has a per-source "sensitivity" (0-100, 50 = neutral,
calibrated default) that scales its underlying smoothing/gain/threshold via
`_sensitivity_factor`: an exponential curve so 50 reproduces the original
calibrated behaviour exactly and the full range spans a 4x swing in either
direction. What "sensitivity" scales differs per source because each one
means something different for that source (see _update_* below).
"""
from __future__ import annotations

import numpy as np

SOURCE_TIMBRE = "timbre"
SOURCE_ENERGY = "energy"
SOURCE_BEAT = "beat"
SOURCES = (SOURCE_TIMBRE, SOURCE_ENERGY, SOURCE_BEAT)

TARGET_HUE = "hue"
TARGET_BRIGHTNESS = "brightness"
TARGET_SATURATION = "saturation"
TARGETS = (TARGET_HUE, TARGET_BRIGHTNESS, TARGET_SATURATION)

BRIGHTNESS_MIN = 10.0
BRIGHTNESS_MAX = 1000.0
HUE_WARM = 0.0
HUE_COOL = 270.0
SATURATION_DIP = 400.0
SATURATION_MAX = 1000.0

TARGET_RANGES: dict[str, tuple[float, float]] = {
    TARGET_HUE: (HUE_WARM, HUE_COOL),
    TARGET_BRIGHTNESS: (BRIGHTNESS_MIN, BRIGHTNESS_MAX),
    TARGET_SATURATION: (SATURATION_DIP, SATURATION_MAX),
}

# (min_hz, max_hz, weight, db_floor, db_ceil) for Energy's weighted band blend - weight
# favours bass to keep the show reading as "music" rather than hissing along with every
# cymbal, but mid/treble energy still matters so the light doesn't go dark during melodic
# or cymbal-heavy passages that have little bass content. Calibrated against a
# synthesized, realistically-mixed track (kick + bassline + snare + hihat + melody + pad
# at typical relative mix levels) played and re-captured through real WASAPI loopback -
# isolated tones read far louder in the same band than they do in a real mix.
BANDS: dict[str, tuple[float, float, float, float, float]] = {
    "bass": (40.0, 150.0, 0.5, -5.0, 22.0),
    "mid": (150.0, 2000.0, 0.3, -16.0, 2.0),
    "treble": (2000.0, 8000.0, 0.2, -20.0, -6.0),
}
ENERGY_EPSILON = 1e-8

# Centroid distribution measured on the calibration track was bimodal: quiet/tonal
# moments cluster in the low hundreds of Hz, loud broadband hits (hihat/snare) jump to
# 10-13 kHz. CENTROID_MAX_HZ clips that to a "cool" ceiling rather than trying to spread
# it further - in practice that reads as tonal passages staying warm and percussive/noisy
# passages pulling cool, which is the intended effect, not a bug.
CENTROID_MIN_HZ = 200.0
CENTROID_MAX_HZ = 6000.0

TIMBRE_BASE_SMOOTHING_SECONDS = 0.5
ENERGY_ATTACK_SECONDS = 0.055
ENERGY_RELEASE_SECONDS = 0.185
BEAT_RECOVER_SECONDS = 0.2
BEAT_BASE_THRESHOLD_MULTIPLIER = 1.8

ONSET_HISTORY_SIZE = 43  # roughly 1 second at a 1024-sample / 44100 Hz block rate
ONSET_MIN_HISTORY = ONSET_HISTORY_SIZE // 2
ONSET_MIN_INTERVAL_SECONDS = 0.15

SENSITIVITY_MIN = 0.0
SENSITIVITY_MAX = 100.0
SENSITIVITY_DEFAULT = 50.0


def _sensitivity_factor(value: float, inverse: bool = False) -> float:
    """Map a 0-100 sensitivity (50 = neutral) to a multiplier via an exponential curve,
    so 50 always reproduces exactly 1.0 (the calibrated default) and the full range
    spans a 4x swing in either direction.

    inverse=False: higher value -> smaller factor. Use this to scale a constant where
    "more sensitive" means a smaller underlying value (smoothing time, onset threshold).
    inverse=True: higher value -> larger factor. Use this to scale a gain, where "more
    sensitive" means amplifying the signal more.
    """
    value = max(SENSITIVITY_MIN, min(SENSITIVITY_MAX, value))
    exponent = (value - SENSITIVITY_DEFAULT) / 25.0
    return 2.0 ** exponent if inverse else 2.0 ** (-exponent)


def target_value(target: str, normalized: float) -> int:
    """Map a source's normalized [0,1] value onto a target's own DP range."""
    lo, hi = TARGET_RANGES[target]
    normalized = max(0.0, min(1.0, normalized))
    return int(round(lo + normalized * (hi - lo)))


class CustomShowEnvelope:
    """Computes all three source signals every block; the caller decides which
    (if any) target each one feeds."""

    def __init__(self, sample_rate: int, block_size: int, sensitivity: dict[str, float] | None = None):
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

        self._sensitivity: dict[str, float] = dict(sensitivity) if sensitivity else {
            source: SENSITIVITY_DEFAULT for source in SOURCES
        }

        self._timbre = 0.0
        self._energy = 0.0
        self._beat = 0.0
        self._prev_spectrum: np.ndarray | None = None
        self._flux_history: list[float] = []
        self._last_onset_time: float | None = None

    def set_sensitivity(self, source: str, value: float) -> None:
        """Update one source's sensitivity (0-100) while running."""
        self._sensitivity[source] = value

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
        """Sensitivity scales the smoothing time: more sensitive = hue drifts faster."""
        total = float(np.sum(spectrum))
        centroid = float(np.sum(self._freqs * spectrum) / total) if total > 0 else CENTROID_MIN_HZ
        centroid = min(CENTROID_MAX_HZ, max(CENTROID_MIN_HZ, centroid))
        target = (np.log2(centroid) - self._log_centroid_min) / self._log_centroid_range

        smoothing = TIMBRE_BASE_SMOOTHING_SECONDS * _sensitivity_factor(self._sensitivity[SOURCE_TIMBRE])
        alpha = 1.0 - np.exp(-self._block_seconds / smoothing)
        self._timbre += alpha * (target - self._timbre)

    def _update_energy(self, spectrum: np.ndarray) -> None:
        """Sensitivity scales a gain applied before clamping: more sensitive = quieter
        sounds already reach a high brightness instead of needing to be loud."""
        normalized_sum = 0.0
        for name, (_lo, _hi, weight, db_floor, db_ceil) in BANDS.items():
            mask = self._band_masks[name]
            band_energy = float(np.mean(spectrum[mask])) if mask.any() else 0.0
            db = 20.0 * np.log10(band_energy + ENERGY_EPSILON)
            normalized = min(1.0, max(0.0, (db - db_floor) / (db_ceil - db_floor)))
            normalized_sum += normalized * weight

        gain = _sensitivity_factor(self._sensitivity[SOURCE_ENERGY], inverse=True)
        target = min(1.0, normalized_sum * gain)

        tau = ENERGY_ATTACK_SECONDS if target > self._energy else ENERGY_RELEASE_SECONDS
        alpha = 1.0 - np.exp(-self._block_seconds / tau)
        self._energy += alpha * (target - self._energy)

    def _update_beat(self, spectrum: np.ndarray, now: float) -> None:
        if self._detect_onset(spectrum, now):
            self._beat = 1.0
        else:
            alpha = 1.0 - np.exp(-self._block_seconds / BEAT_RECOVER_SECONDS)
            self._beat += alpha * (0.0 - self._beat)

    def _detect_onset(self, spectrum: np.ndarray, now: float) -> bool:
        """Spectral flux: sum of positive frame-to-frame magnitude increases. Sensitivity
        scales the adaptive threshold: more sensitive = smaller transients trigger it."""
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
        threshold_multiplier = BEAT_BASE_THRESHOLD_MULTIPLIER * _sensitivity_factor(self._sensitivity[SOURCE_BEAT])
        threshold = float(np.mean(baseline) + threshold_multiplier * np.std(baseline))
        if flux <= threshold:
            return False
        if self._last_onset_time is not None and now - self._last_onset_time < ONSET_MIN_INTERVAL_SECONDS:
            return False
        self._last_onset_time = now
        return True
