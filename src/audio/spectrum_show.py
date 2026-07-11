"""Full-spectrum reactive light show for a single RGBCW bulb.

`src/audio/analysis.py` (used by manual Music Mode) deliberately keeps
brightness bass-only and colour fixed, because that mode's whole point
is a steady, user-chosen pulse. This module is the "autonomous best
show" mode: every HSV component is audio-driven at once.

That's free in terms of bulb load: Tuya's colour_data DP (24) already
bundles hue/saturation/value into one hex string, so varying all three
costs exactly the same single DP write per update as Music Mode's
fixed-hue/brightness-only path.

- **Hue** drifts continuously with the spectral centroid (the
  spectrum's "center of mass" frequency) - warm for bass/tonal-heavy
  sound, cool for bright/noisy sound (cymbals, distortion). Same idea
  as an earlier Music Mode prototype, kept here since "paint the
  timbre" reads well as a show even though Music Mode itself moved to
  a fixed user colour.
- **Brightness** is a weighted blend of bass/mid/treble band energy
  instead of Music Mode's bass-only signal, so it stays alive during
  melodic or cymbal-heavy passages with little bass, not just on kick
  hits. All three bands calibrated the same way as Music Mode's bass
  band: a synthesized, realistically-mixed track (kick + bassline +
  snare + hihat + melody + pad) played and re-captured via real WASAPI
  loopback, not isolated tones.
- **Saturation** dips briefly toward white on a detected onset (beat/
  hit) and recovers, instead of Music Mode's original hard hue-jump-
  on-onset design. A brief desaturation reads as a "flash" accent on
  the beat without the jarring instant colour swap, and without adding
  a second signal that competes with the continuous hue drift above.

Centroid distribution measured on the calibration track was bimodal:
quiet/tonal moments cluster in the low hundreds of Hz, loud broadband
hits (hihat/snare) jump to 10-13 kHz. CENTROID_MAX_HZ clips that to a
"cool" ceiling rather than trying to spread it further - in practice
that reads as tonal passages staying warm and percussive/noisy
passages pulling cool, which is the intended effect, not a bug.
"""
from __future__ import annotations

import numpy as np

BRIGHTNESS_MIN = 10
BRIGHTNESS_MAX = 1000
BRIGHTNESS_ATTACK_SECONDS = 0.055
BRIGHTNESS_RELEASE_SECONDS = 0.185

# (min_hz, max_hz, weight, db_floor, db_ceil) - weight favours bass to keep the
# show reading as "music" rather than hissing along with every cymbal, but mid/
# treble energy still matters so the light doesn't go dark during melodic or
# cymbal-heavy passages that have little bass content.
BANDS: dict[str, tuple[float, float, float, float, float]] = {
    "bass": (40.0, 150.0, 0.5, -5.0, 22.0),
    "mid": (150.0, 2000.0, 0.3, -16.0, 2.0),
    "treble": (2000.0, 8000.0, 0.2, -20.0, -6.0),
}
ENERGY_EPSILON = 1e-8

CENTROID_MIN_HZ = 200.0
CENTROID_MAX_HZ = 6000.0
HUE_WARM = 0.0
HUE_COOL = 270.0
HUE_SMOOTHING_SECONDS = 0.5

SATURATION_MAX = 1000
SATURATION_DIP = 400
SATURATION_RECOVER_SECONDS = 0.2

ONSET_HISTORY_SIZE = 43  # roughly 1 second at a 1024-sample / 44100 Hz block rate
ONSET_MIN_HISTORY = ONSET_HISTORY_SIZE // 2
ONSET_THRESHOLD_MULTIPLIER = 1.8
ONSET_MIN_INTERVAL_SECONDS = 0.15


class SpectrumShowEnvelope:
    """Turns a stream of audio blocks into (hue, saturation, brightness)."""

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

        self._brightness = float(BRIGHTNESS_MIN)
        self._hue = HUE_WARM
        self._saturation = float(SATURATION_MAX)
        self._prev_spectrum: np.ndarray | None = None
        self._flux_history: list[float] = []
        self._last_onset_time: float | None = None

    def process(self, block: np.ndarray, now: float) -> tuple[int, int, int]:
        """Feed one audio block; return (hue 0-360, saturation 0-1000, value 0-1000)."""
        spectrum = np.abs(np.fft.rfft(block * self._window))

        self._update_brightness(spectrum)
        self._update_hue(spectrum)
        self._update_saturation(spectrum, now)

        return int(round(self._hue)), int(round(self._saturation)), int(round(self._brightness))

    def _update_brightness(self, spectrum: np.ndarray) -> None:
        normalized_sum = 0.0
        for name, (_lo, _hi, weight, db_floor, db_ceil) in BANDS.items():
            mask = self._band_masks[name]
            energy = float(np.mean(spectrum[mask])) if mask.any() else 0.0
            db = 20.0 * np.log10(energy + ENERGY_EPSILON)
            normalized = min(1.0, max(0.0, (db - db_floor) / (db_ceil - db_floor)))
            normalized_sum += normalized * weight

        target = BRIGHTNESS_MIN + normalized_sum * (BRIGHTNESS_MAX - BRIGHTNESS_MIN)
        tau = BRIGHTNESS_ATTACK_SECONDS if target > self._brightness else BRIGHTNESS_RELEASE_SECONDS
        alpha = 1.0 - np.exp(-self._block_seconds / tau)
        self._brightness += alpha * (target - self._brightness)

    def _update_hue(self, spectrum: np.ndarray) -> None:
        total = float(np.sum(spectrum))
        centroid = float(np.sum(self._freqs * spectrum) / total) if total > 0 else CENTROID_MIN_HZ
        centroid = min(CENTROID_MAX_HZ, max(CENTROID_MIN_HZ, centroid))
        normalized = (np.log2(centroid) - self._log_centroid_min) / self._log_centroid_range
        target = HUE_WARM + normalized * (HUE_COOL - HUE_WARM)

        alpha = 1.0 - np.exp(-self._block_seconds / HUE_SMOOTHING_SECONDS)
        self._hue += alpha * (target - self._hue)

    def _update_saturation(self, spectrum: np.ndarray, now: float) -> None:
        if self._detect_onset(spectrum, now):
            self._saturation = float(SATURATION_DIP)
        else:
            alpha = 1.0 - np.exp(-self._block_seconds / SATURATION_RECOVER_SECONDS)
            self._saturation += alpha * (SATURATION_MAX - self._saturation)

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
