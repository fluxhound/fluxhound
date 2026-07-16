"""Audio Mode: user-configurable full-spectrum light show.

Three independent audio "sources" are computed every block, each producing a
normalized 0-1 signal with its own natural smoothing behaviour:
- **Timbre** (spectral centroid): continuous drift, low for bass/tonal-heavy
  sound, high for bright/noisy sound.
- **Energy** (weighted bass/mid/treble band energy): continuous loudness
  pulse, auto-leveled per band against the recently observed dB range
  (see ADAPTIVE_RANGE_* below) so a quieter overall playback volume
  doesn't just shrink Energy's usable range - the song's own internal
  loud/quiet dynamics are what drive it, not the absolute volume.
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
# Raised from the original 1.8 after the first --debug real-music test round: onset
# gaps clustered heavily against ONSET_MIN_INTERVAL_SECONDS (13-24% of detected onsets
# landed within 0.05s of that floor) in dense/percussive passages - the detector was
# firing on nearly every eligible block rather than picking out distinct hits. A wider
# margin over the recent flux baseline should let fewer borderline transients through
# during those passages while still catching genuine strong hits (which cleared the old
# threshold by 2-2.4x at the 99th percentile, well above this increase). A first pass,
# not a final figure - re-evaluate against the next --debug test round's onset spacing.
BEAT_BASE_THRESHOLD_MULTIPLIER = 2.2

# Auto-leveling for Energy's per-band floor/ceiling: BANDS' db_floor/db_ceil above
# are fixed, absolute dB thresholds calibrated at one reference playback volume - at
# a quieter volume (e.g. a browser tab's own volume slider turned down), every
# band's dB level shifts down with it, so normalized_sum stays low even during a
# song's own loud parts, and Energy reads as flat/unreactive. Real music's own
# internal dynamics (loud chorus vs quiet verse) is what should drive Energy, not
# the absolute playback volume - so each band tracks its own recently observed
# dB floor/ceiling instead of using BANDS' constants directly (see
# _update_adaptive_range): a fast "attack" toward any new extreme (a quieter
# moment immediately lowers the floor, a louder one immediately raises the
# ceiling) so the tracker keeps up with a real volume change within a couple of
# seconds, and a slower "release" back toward the current level otherwise (so a
# single one-off transient doesn't leave everything else looking artificially
# dim/bright right after it). Seeded from BANDS' own constants, so at whatever
# volume those were originally calibrated against, behaviour is unchanged from
# before this existed - it only diverges once the observed range actually drifts
# away from that baseline.
#
# Unlike Energy, Timbre (spectral centroid: a ratio of frequency to magnitude)
# and Beat (an adaptive mean+std threshold over recent flux) already scale with
# the signal's own magnitude, so a uniform volume change cancels out in both -
# neither needed this treatment.
ADAPTIVE_RANGE_ATTACK_SECONDS = 2.0
ADAPTIVE_RANGE_RELEASE_SECONDS = 12.0
ADAPTIVE_RANGE_MIN_SPAN_DB = 6.0  # never let floor/ceiling collapse together
ADAPTIVE_RANGE_ABSOLUTE_MIN_DB = -60.0  # guards against drifting toward -inf over long silence
ADAPTIVE_RANGE_ABSOLUTE_MAX_DB = 40.0  # guards against one absurd input pinning the ceiling forever

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
        # Per-band auto-leveled floor/ceiling (see ADAPTIVE_RANGE_* above) -
        # seeded from BANDS' own fixed constants, then tracked live.
        self._band_floor: dict[str, float] = {name: db_floor for name, (_, _, _, db_floor, _) in BANDS.items()}
        self._band_ceiling: dict[str, float] = {name: db_ceil for name, (_, _, _, _, db_ceil) in BANDS.items()}
        self._prev_spectrum: np.ndarray | None = None
        self._flux_history: list[float] = []
        self._last_onset_time: float | None = None
        # Pre-sensitivity, pre-smoothing readings from the most recent process() call -
        # only ever read back via debug_snapshot(), for --debug logging (see
        # CustomMode). Kept separate from the smoothed self._timbre/_energy/_beat
        # above because those already have sensitivity/gain baked in - a value pinned
        # at 0 or 1 in the final output doesn't say whether that's the raw signal
        # genuinely maxed out or just the current gain/threshold being off, and these
        # do.
        self._last_debug: dict[str, float] = {
            "centroid_hz": CENTROID_MIN_HZ, "energy_raw": 0.0, "flux": 0.0, "onset_threshold": 0.0,
        }
        for name in BANDS:
            self._last_debug[f"{name}_floor_db"] = self._band_floor[name]
            self._last_debug[f"{name}_ceiling_db"] = self._band_ceiling[name]

    def debug_snapshot(self) -> dict[str, float]:
        """The raw, pre-sensitivity diagnostic values behind the most recent
        process() call - see the _last_debug comment in __init__."""
        return dict(self._last_debug)

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
        self._last_debug["centroid_hz"] = centroid
        target = (np.log2(centroid) - self._log_centroid_min) / self._log_centroid_range

        smoothing = TIMBRE_BASE_SMOOTHING_SECONDS * _sensitivity_factor(self._sensitivity[SOURCE_TIMBRE])
        alpha = 1.0 - np.exp(-self._block_seconds / smoothing)
        self._timbre += alpha * (target - self._timbre)

    def _update_energy(self, spectrum: np.ndarray) -> None:
        """Sensitivity scales a gain applied before clamping: more sensitive = quieter
        sounds already reach a high brightness instead of needing to be loud."""
        normalized_sum = 0.0
        for name, (_lo, _hi, weight, _db_floor, _db_ceil) in BANDS.items():
            mask = self._band_masks[name]
            band_energy = float(np.mean(spectrum[mask])) if mask.any() else 0.0
            db = 20.0 * np.log10(band_energy + ENERGY_EPSILON)
            self._update_adaptive_range(name, db)
            floor, ceiling = self._band_floor[name], self._band_ceiling[name]
            normalized = min(1.0, max(0.0, (db - floor) / (ceiling - floor)))
            normalized_sum += normalized * weight
        self._last_debug["energy_raw"] = normalized_sum

        gain = _sensitivity_factor(self._sensitivity[SOURCE_ENERGY], inverse=True)
        target = min(1.0, normalized_sum * gain)

        tau = ENERGY_ATTACK_SECONDS if target > self._energy else ENERGY_RELEASE_SECONDS
        alpha = 1.0 - np.exp(-self._block_seconds / tau)
        self._energy += alpha * (target - self._energy)

    def _update_adaptive_range(self, name: str, db: float) -> None:
        """Auto-level one band's floor/ceiling toward the current reading - fast
        "attack" toward a new extreme, slow "release" back toward the current
        level otherwise (see ADAPTIVE_RANGE_* above). Symmetric: the floor is
        exactly the same envelope-follower idea as the ceiling, just tracking
        the minimum instead of the maximum."""
        floor, ceiling = self._band_floor[name], self._band_ceiling[name]

        floor_tau = ADAPTIVE_RANGE_ATTACK_SECONDS if db < floor else ADAPTIVE_RANGE_RELEASE_SECONDS
        floor_alpha = 1.0 - np.exp(-self._block_seconds / floor_tau)
        floor += floor_alpha * (db - floor)

        ceiling_tau = ADAPTIVE_RANGE_ATTACK_SECONDS if db > ceiling else ADAPTIVE_RANGE_RELEASE_SECONDS
        ceiling_alpha = 1.0 - np.exp(-self._block_seconds / ceiling_tau)
        ceiling += ceiling_alpha * (db - ceiling)

        floor = max(ADAPTIVE_RANGE_ABSOLUTE_MIN_DB, floor)
        ceiling = min(ADAPTIVE_RANGE_ABSOLUTE_MAX_DB, ceiling)
        if ceiling - floor < ADAPTIVE_RANGE_MIN_SPAN_DB:
            midpoint = (ceiling + floor) / 2.0
            floor = midpoint - ADAPTIVE_RANGE_MIN_SPAN_DB / 2.0
            ceiling = midpoint + ADAPTIVE_RANGE_MIN_SPAN_DB / 2.0

        self._band_floor[name] = floor
        self._band_ceiling[name] = ceiling
        self._last_debug[f"{name}_floor_db"] = floor
        self._last_debug[f"{name}_ceiling_db"] = ceiling

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
        self._last_debug["flux"] = flux

        self._flux_history.append(flux)
        if len(self._flux_history) > ONSET_HISTORY_SIZE:
            self._flux_history.pop(0)
        if len(self._flux_history) < ONSET_MIN_HISTORY:
            return False

        baseline = self._flux_history[:-1]
        threshold_multiplier = BEAT_BASE_THRESHOLD_MULTIPLIER * _sensitivity_factor(self._sensitivity[SOURCE_BEAT])
        threshold = float(np.mean(baseline) + threshold_multiplier * np.std(baseline))
        self._last_debug["onset_threshold"] = threshold
        if flux <= threshold:
            return False
        if self._last_onset_time is not None and now - self._last_onset_time < ONSET_MIN_INTERVAL_SECONDS:
            return False
        self._last_onset_time = now
        return True
