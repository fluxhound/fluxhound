"""Gaming Mode's health/resource-bar detection: turns the "Set area" region
into a 0-1 fill estimate (or, in OCR mode, a directly-read number), and a
small state machine that decides when the bulb should briefly flash or glow
to signal a change.

Three detection modes (TriggerConfig.detection_mode):
- **auto** (the default, for both the free built-in watcher and any new
  custom watcher): tries both fill_fraction and OCR and uses whichever one
  is actually working for this particular region, no manual choice needed -
  see HealthBarTracker.process's AUTO_DETECTION_OCR_FRESHNESS_SECONDS logic
  below for exactly how. This is deliberately the *same* detection
  capability on both the free and paid tier - what stays paid-exclusive is
  the *number of watched regions* (the Custom Trigger Editor's extra
  watchers) and *configurable reactions* (custom flash colours/thresholds/
  multi-step bands) - not which detection method is available.
- **fill_fraction**: works for horizontal bars, vertical bars, and circular
  orbs (Diablo-style) alike, without knowing the bar's shape or orientation
  - the region is assumed to be cropped tightly around the bar/orb's full
  fixed extent, so the fraction of the region's pixels that currently match
  the bar's own fill colour *is* the fill percentage, regardless of
  geometry. An optional boolean mask (see encode_region_mask/
  decode_region_mask) narrows which pixels within that region actually count,
  for a bar that isn't a plain rectangle (a bent/curved arc, a thin diagonal
  sliver) - painted via BrushSelectorWindow instead of the plain rectangle
  drag. mask=None (the default, and the only option before this existed)
  means "the whole region counts", reproducing the original behaviour
  exactly.
- **ocr**: for health/mana shown as text/digits, which a fill-coloured
  region has nothing to measure (see ocr_reader.py and the OCR_POLL_INTERVAL_
  SECONDS note on HealthBarTracker for why this needs its own slower,
  threaded polling cadence rather than running on every capture tick like
  fill_fraction does). The same painted mask also applies here: everything
  outside it is blanked out (see _mask_frame_for_ocr) before the frame ever
  reaches OCR, not just the number's own bounding box - a tightly-painted
  mask keeps a busy/animated background from riding along in the same
  rectangular capture and flipping the read result frame to frame even
  though the number itself never changed. A bare number with no "/max" or
  "%" defaults to being read out of TriggerConfig.ocr_max_value's default
  of 100 (overridable per custom watcher) - the common convention for a
  primary stat, and what lets auto mode work out of the box on a display
  like this without any extra configuration screen for the free tier.

Matching on hue alone isn't enough: many bars' "empty" track is a *darker* shade
of a similar hue (e.g. a dim maroon track behind a bright red fill), not a
neutral grey - same hue, meaningfully lower saturation *and* value. The fill
colour reference therefore captures saturation and value alongside hue, and a
pixel only counts as "filled" if it's close on all three, not just hue.

Matching on hue alone isn't enough: many bars' "empty" track is a *darker* shade
of a similar hue (e.g. a dim maroon track behind a bright red fill), not a
neutral grey - same hue, meaningfully lower saturation *and* value. The fill
colour reference therefore captures saturation and value alongside hue, and a
pixel only counts as "filled" if it's close on all three, not just hue.

The fill colour reference is re-derived fresh from *every single frame*
(calibrate_bar_colour + fill_fraction called together each time - see
HealthBarTracker.process) rather than captured once and reused for the rest of
the session. Two problems that would otherwise exist disappear as a result:
  - A bar whose fill colour itself shifts as it depletes (a common green -> amber
    -> red UI convention) still gets measured correctly, since each frame simply
    asks "what's the dominant vivid colour *right now*, and what fraction of the
    region matches it" - there's no stale reference to fall out of sync with.
  - There's no longer a single "calibration moment" that can get unlucky: if the
    bar happens to be fully empty on some frame (calibrate_bar_colour finds no
    sufficiently vivid pixels), that frame's fill_fraction is correctly read as
    0.0 - a real, meaningful state, not a permanent tracking failure the way a
    one-shot calibration failing at startup used to be.
"""
from __future__ import annotations

import base64
import threading
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from src.screen import ocr_reader
from src.screen.ambience_show import rgb_to_hsv

DETECTION_MODE_AUTO = "auto"
DETECTION_MODE_FILL_FRACTION = "fill_fraction"
DETECTION_MODE_OCR = "ocr"

# OCR takes roughly 0.3s per reading (see ocr_reader.py) - far too slow to run on
# every ~0.1s capture tick without stalling the rest of Ambience Mode, so an OCR-
# mode HealthBarTracker only starts a new reading this often, on its own
# background thread (see HealthBarTracker._maybe_start_ocr).
OCR_POLL_INTERVAL_SECONDS = 1.0

# auto mode's "is OCR actually working for this region" window: once OCR has
# successfully parsed a reading, its result keeps being trusted over
# fill_fraction's for this long afterward, tolerating an occasional missed
# poll without visibly flip-flopping between detection methods every ~1s
# tick. 5x the poll interval - generous enough to absorb a couple of misses
# in a row, short enough that a region OCR genuinely never works on (a real
# colour bar, no readable text at all) settles into fill_fraction quickly.
# A region OCR has *never* once succeeded on falls back to fill_fraction
# immediately (no delay), since there's nothing to be "stale" yet.
AUTO_DETECTION_OCR_FRESHNESS_SECONDS = 5.0 * OCR_POLL_INTERVAL_SECONDS

# auto mode only (never explicit ocr mode - a custom watcher that deliberately
# chose OCR is presumed to know what it's watching, so it keeps retrying
# forever): once OCR has failed this many consecutive times in a row without
# EVER once succeeding, auto mode stops starting new OCR attempts for the
# rest of the session - a genuine colour bar shouldn't pay for a real OCR
# inference every second forever. Originally 10 (~10s), raised to 30 (~30s)
# after a real --debug session showed OCR needing 11 attempts before its
# first success against one real game's HUD font - 10 was giving up right
# as OCR was about to start working, permanently stranding a perfectly
# valid text region on chaotic fill_fraction instead. 30 gives real-world
# OCR variance (lighting, font, occlusion) a much wider berth while still
# being a bounded, one-time cost rather than truly unlimited. Resets to
# trying again fresh on the next HealthBarTracker (i.e. the next time
# Ambience Mode is (re)activated).
AUTO_DETECTION_MAX_OCR_ATTEMPTS_WITHOUT_SUCCESS = 30

# Deliberately strict: only unambiguously vivid pixels should ever count toward
# identifying "the fill colour" in a frame. A frame where the bar is mostly empty
# is mostly "track" background, which - for a same-hue dark track - can itself
# clear a loose threshold; averaging that in would drag the identified colour's
# saturation/value down toward the track's, and a diluted reference then makes
# fill_fraction's ratio check too permissive, misreading track pixels as filled.
# A real fill colour is designed to read as clearly vivid against its track at a
# glance, so this gap is expected to hold for real game UIs too.
CALIBRATION_SATURATION_THRESHOLD = 0.5
FILL_HUE_TOLERANCE_DEGREES = 20
FILL_SATURATION_RATIO = 0.7  # a match needs saturation >= this fraction of the frame's own fill
FILL_VALUE_RATIO = 0.7       # ...and value >= this fraction of the frame's own fill
CALIBRATION_HUE_BINS = 36

# These four are also HealthBarTracker's/TriggerConfig's *default* values - Gaming
# Mode's built-in, free-tier watcher always uses TriggerConfig() unchanged, so
# these constants are still exactly what drives it. A paid-tier custom watcher
# (see TriggerWatcher in src/ambience_config.py, added via the Trigger Editor)
# constructs its own TriggerConfig instead, with its own thresholds/colours/bands.
LOW_HEALTH_THRESHOLD = 0.10
CHANGE_EPSILON = 0.02  # ignore fractional jitter (compression noise, edge aliasing) below this
BLINK_DURATION_SECONDS = 0.5

DECREASE_COLOUR = (0, 1000, 1000)    # solid red flash
INCREASE_COLOUR = (120, 1000, 1000)  # solid green flash
LOW_HEALTH_COLOUR = (0, 1000, 1000)  # solid red, held continuously


@dataclass
class ThresholdBand:
    """A continuous-glow reaction: hold `colour` for as long as the fill fraction
    stays at or below `threshold` (0-1). A TriggerConfig can carry several of
    these to react differently at different severity levels (e.g. amber glow
    below 50%, red below 20%, on top of the ordinary flash-on-change behaviour) -
    the "multi-step reactions" the Custom Trigger Editor exposes. When more than
    one band's threshold is currently satisfied, the smallest (most severe) one
    wins - see TriggerConfig.active_band."""

    threshold: float
    colour: tuple[int, int, int]


@dataclass
class TriggerConfig:
    """Every tunable in one watcher's reaction behaviour. The reaction defaults
    (everything below detection_mode) reproduce Gaming Mode's original fixed,
    free-tier behaviour exactly - a bare TriggerConfig() is what the built-in
    watcher has always used, and still is. A paid-tier custom watcher (Trigger
    Editor) constructs one with its own reaction values instead - what stays
    paid-exclusive is *configuring* those, and watching more than one region,
    not which detection_mode is available (see module docstring).

    detection_mode picks auto (the default - tries fill_fraction and ocr both
    and uses whichever is actually working for this region, see
    HealthBarTracker.process), or explicitly fill_fraction (the colour-ratio
    approach) or ocr (read a printed number instead) if a custom watcher wants
    to force one. ocr_max_value is only consulted for ocr/auto's OCR side, and
    only when the recognized text is a bare number with no "/max" or "%"
    alongside it - there's no way to know what "full" means from digits alone
    otherwise, so it defaults to 100 (the common convention for a primary
    stat) rather than requiring configuration before auto mode can work on a
    bare-number display out of the box; a custom watcher can still override it
    for a HUD that scales differently."""

    change_epsilon: float = CHANGE_EPSILON
    blink_duration_seconds: float = BLINK_DURATION_SECONDS
    decrease_colour: tuple[int, int, int] = DECREASE_COLOUR
    increase_colour: tuple[int, int, int] = INCREASE_COLOUR
    threshold_bands: list[ThresholdBand] = field(
        default_factory=lambda: [ThresholdBand(threshold=LOW_HEALTH_THRESHOLD, colour=LOW_HEALTH_COLOUR)]
    )
    detection_mode: str = DETECTION_MODE_AUTO
    ocr_max_value: float | None = 100.0

    def active_band(self, fraction: float) -> ThresholdBand | None:
        """The most severe threshold_bands entry the current fraction has crossed
        (smallest threshold among those satisfied), or None if the fraction is
        above all of them. Strict less-than, matching the original single-
        threshold check exactly (fraction == threshold does not yet count)."""
        satisfied = [band for band in self.threshold_bands if fraction < band.threshold]
        if not satisfied:
            return None
        return min(satisfied, key=lambda band: band.threshold)


def _resize_mask_nearest(mask: np.ndarray, height: int, width: int) -> np.ndarray:
    """Nearest-neighbour resize of a boolean mask to an exact (height, width) -
    same indexing technique as MainWindow's _resize_frame_nearest, no PIL.
    Needed because ScreenCapture downsamples its captured frame by default
    (see capture.py's DEFAULT_DOWNSAMPLE_WIDTH) for any region wider than
    ~160px, but the mask is always encoded/decoded at the region's own,
    un-downsampled resolution (see encode_region_mask) - without this, a
    painted mask on a region wider than the downsample threshold silently
    stops matching the frame it's meant to restrict."""
    src_height, src_width = mask.shape
    ys = np.clip(np.arange(height) * src_height // height, 0, src_height - 1)
    xs = np.clip(np.arange(width) * src_width // width, 0, src_width - 1)
    return mask[ys][:, xs]


def _match_mask_to_frame(mask: np.ndarray | None, frame_height: int, frame_width: int) -> np.ndarray | None:
    """Resizes mask to the frame's actual shape if they differ - see
    _resize_mask_nearest for why they can differ at all."""
    if mask is None or mask.shape == (frame_height, frame_width):
        return mask
    return _resize_mask_nearest(mask, frame_height, frame_width)


def _flatten_masked(hue: np.ndarray, sat: np.ndarray, val: np.ndarray,
                     mask: np.ndarray | None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Flatten hue/sat/val to 1D, restricted to mask's True pixels if given -
    shared by calibrate_bar_colour and fill_fraction so both honour the same
    painted mask (see BrushSelectorWindow/encode_region_mask) identically."""
    if mask is not None:
        mask = _match_mask_to_frame(mask, hue.shape[0], hue.shape[1])
        return hue[mask], sat[mask], val[mask]
    return hue.reshape(-1), sat.reshape(-1), val.reshape(-1)


def calibrate_bar_colour(rgb_frame: np.ndarray, mask: np.ndarray | None = None) -> tuple[float, float, float] | None:
    """Identify the region's dominant vivid colour (hue, mean saturation, mean
    value) *in this one frame*: the peak of a saturation-weighted hue histogram
    among sufficiently vivid pixels - the same "most frequent colour" idea
    Ambience Mode itself uses for the whole screen, applied here to just the
    cropped region (or, if mask is given, just its painted pixels - see
    encode_region_mask). Returns None if nothing in the frame is vivid enough to
    be a fill colour (most commonly: the bar is empty right now)."""
    hue, sat, val = rgb_to_hsv(rgb_frame)
    hue, sat, val = _flatten_masked(hue, sat, val, mask)
    colourful = sat >= CALIBRATION_SATURATION_THRESHOLD
    if not np.any(colourful):
        return None
    bin_edges = np.linspace(0, 360, CALIBRATION_HUE_BINS + 1)
    bins = np.clip(np.digitize(hue[colourful], bin_edges) - 1, 0, CALIBRATION_HUE_BINS - 1)
    weights = np.zeros(CALIBRATION_HUE_BINS)
    np.add.at(weights, bins, sat[colourful])
    peak_bin = int(np.argmax(weights))
    peak_mask = bins == peak_bin
    return (
        float(np.mean(hue[colourful][peak_mask])),
        float(np.mean(sat[colourful][peak_mask])),
        float(np.mean(val[colourful][peak_mask])),
    )


def fill_fraction(rgb_frame: np.ndarray, bar_colour: tuple[float, float, float],
                   mask: np.ndarray | None = None) -> float:
    """What fraction (0-1) of the region's pixels currently match bar_colour -
    directly the bar/orb's current fill level, as long as the region was cropped
    around its full fixed extent. Matches on hue, saturation, *and* value
    together, so a darker same-hue "empty track" doesn't get counted as filled.
    If mask is given (a painted, non-rectangular watched area - see
    encode_region_mask), only its True pixels are considered at all, so
    whatever's around a curved/thin bar within the same bounding rectangle
    never dilutes the measurement."""
    bar_hue, bar_saturation, bar_value = bar_colour
    hue, sat, val = rgb_to_hsv(rgb_frame)
    hue, sat, val = _flatten_masked(hue, sat, val, mask)
    if hue.size == 0:
        return 0.0
    hue_delta = np.abs(((hue - bar_hue + 180) % 360) - 180)
    matches = (
        (hue_delta <= FILL_HUE_TOLERANCE_DEGREES)
        & (sat >= bar_saturation * FILL_SATURATION_RATIO)
        & (val >= bar_value * FILL_VALUE_RATIO)
    )
    return float(np.count_nonzero(matches)) / hue.size


def measure_fill(rgb_frame: np.ndarray, mask: np.ndarray | None = None) -> float:
    """One frame in, current fill fraction out - identifies this frame's own
    dominant vivid colour and measures against it in the same step, so there's no
    persisted reference to fall out of sync with a colour-shifting bar, and no
    single calibration moment that can get unlucky."""
    colour = calibrate_bar_colour(rgb_frame, mask)
    if colour is None:
        return 0.0  # nothing vivid in the frame - the bar reads empty
    return fill_fraction(rgb_frame, colour, mask)


def encode_region_mask(mask: np.ndarray) -> str:
    """Pack a boolean mask (shape (height, width), from BrushSelectorWindow)
    into a compact base64 string for JSON storage (AmbienceRegion.mask) -
    8 pixels per byte via numpy's bit-packing. The mask's shape isn't stored
    alongside it since it always matches the owning AmbienceRegion's own
    height/width - see decode_region_mask."""
    packed = np.packbits(mask.astype(np.uint8))
    return base64.b64encode(packed.tobytes()).decode("ascii")


def decode_region_mask(mask_str: str, height: int, width: int) -> np.ndarray:
    """Inverse of encode_region_mask - height/width must match the region the
    mask was originally painted/cropped against."""
    packed = np.frombuffer(base64.b64decode(mask_str), dtype=np.uint8)
    bits = np.unpackbits(packed)[: height * width]
    return bits.reshape(height, width).astype(bool)


# Plain black - low risk of introducing a false edge/contrast an OCR text
# detector could latch onto, and it's what most game HUD backgrounds already
# lean toward anyway. Only matters for the blanked-out surroundings; the
# painted-in pixels (the digits themselves) are left completely untouched.
OCR_MASK_FILL_COLOUR = (0, 0, 0)


def _mask_frame_for_ocr(rgb_frame: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Blank out every pixel the brush didn't paint before handing a frame to
    OCR. Unlike fill_fraction (which just filters a flattened pixel list),
    OCR needs a real 2D image, so "restricting to the mask" here means
    overwriting the excluded pixels rather than dropping them. See
    _match_mask_to_frame for why the mask might not already be the frame's
    exact shape - a real bug (see CHANGELOG) had this silently raise an
    IndexError on *every* OCR attempt, swallowed by _run_ocr's broad except,
    for any watcher region wider than ScreenCapture's ~160px downsample
    threshold."""
    mask = _match_mask_to_frame(mask, rgb_frame.shape[0], rgb_frame.shape[1])
    masked = rgb_frame.copy()
    masked[~mask] = OCR_MASK_FILL_COLOUR
    return masked


class HealthBarTracker:
    """Tracks one region's fill fraction (or OCR reading) across frames and
    decides what colour (if any) should override the normal ambient reading
    this tick: a brief flash on a meaningful increase/decrease, or a
    continuous glow while inside one of config's threshold_bands - the
    latter takes priority over a flash that happens to still be active.
    config defaults to TriggerConfig()'s fixed reaction values (Gaming
    Mode's original, free-tier behaviour) and auto detection_mode; a
    paid-tier custom watcher passes its own TriggerConfig for different
    reactions/more regions, not different detection (see module docstring).
    mask restricts fill_fraction mode to a painted, non-rectangular area
    within the region (see encode_region_mask/decode_region_mask); in ocr
    mode (and auto mode's OCR side) it instead blanks out everything
    outside the painted area before the frame reaches OCR, so a mask painted
    tightly around just the digits keeps whatever's around them out of the
    read entirely. debug_callback, if given, is called from the OCR
    background thread after every read attempt (success or fail) with
    (raw_text, parsed_fraction) - see AmbienceMode's --debug OCR log, for
    diagnosing a misread frame without having to eyeball it live."""

    def __init__(self, config: TriggerConfig | None = None, mask: np.ndarray | None = None,
                 debug_callback: Callable[[str, float | None], None] | None = None):
        self._config = config or TriggerConfig()
        self._mask = mask
        self._debug_callback = debug_callback
        self._last_fraction: float | None = None
        self._blink_until: float = 0.0
        self._blink_colour: tuple[int, int, int] | None = None
        # OCR-mode-only state (also used by auto mode's OCR side): a reading
        # arrives from a background thread (see _maybe_start_ocr) at most once
        # every OCR_POLL_INTERVAL_SECONDS, far slower than process() itself
        # gets called - _ocr_lock guards the handoff between that thread and
        # process()'s caller. _last_ocr_success_at (auto mode only) is when
        # _ocr_fraction was last actually updated (not just attempted) - see
        # AUTO_DETECTION_OCR_FRESHNESS_SECONDS.
        self._ocr_lock = threading.Lock()
        self._ocr_fraction: float | None = None
        self._last_ocr_success_at: float | None = None
        self._ocr_attempts_without_success = 0  # auto mode's give-up counter, see AUTO_DETECTION_MAX_OCR_ATTEMPTS_WITHOUT_SUCCESS
        self._ocr_thread_running = False
        self._last_ocr_start: float | None = None  # None, not 0.0 - now itself can legitimately be 0.0

    def process(self, rgb_frame: np.ndarray, now: float) -> tuple[int, int, int] | None:
        """Update from one frame; returns the (hue, saturation, value) to force
        onto the bulb this tick, or None if the normal ambient reading should be
        sent instead. The first reading only records a baseline - there's
        nothing to compare it to yet, so it can't be a "change". In ocr mode,
        a tick with no new reading yet (still waiting on the background OCR
        thread) simply re-evaluates against the last known fraction, the same
        way a fill_fraction tick would if called with an unchanged frame."""
        if self._config.detection_mode == DETECTION_MODE_AUTO:
            self._maybe_start_ocr(rgb_frame, now)
            with self._ocr_lock:
                ocr_fraction = self._ocr_fraction
                ocr_is_fresh = (
                    self._last_ocr_success_at is not None
                    and now - self._last_ocr_success_at <= AUTO_DETECTION_OCR_FRESHNESS_SECONDS
                )
            fraction = ocr_fraction if ocr_is_fresh else measure_fill(rgb_frame, self._mask)
        elif self._config.detection_mode == DETECTION_MODE_OCR:
            self._maybe_start_ocr(rgb_frame, now)
            with self._ocr_lock:
                fraction = self._ocr_fraction
        else:
            fraction = measure_fill(rgb_frame, self._mask)

        if fraction is not None:
            if self._last_fraction is not None:
                delta = fraction - self._last_fraction
                if delta <= -self._config.change_epsilon:
                    self._blink_until = now + self._config.blink_duration_seconds
                    self._blink_colour = self._config.decrease_colour
                elif delta >= self._config.change_epsilon:
                    self._blink_until = now + self._config.blink_duration_seconds
                    self._blink_colour = self._config.increase_colour
            self._last_fraction = fraction

        if self._last_fraction is not None:
            band = self._config.active_band(self._last_fraction)
            if band is not None:
                return band.colour
        if now < self._blink_until:
            return self._blink_colour
        return None

    def _maybe_start_ocr(self, rgb_frame: np.ndarray, now: float) -> None:
        """Kick off a new OCR reading on a background thread if enough time has
        passed and the previous one has finished - never lets readings pile up
        (an OCR call is slow enough that the capture tick will have moved on
        several times over by the time it completes). In auto mode only, also
        stops trying at all once AUTO_DETECTION_MAX_OCR_ATTEMPTS_WITHOUT_SUCCESS
        has been reached with zero successes ever - see that constant."""
        if self._ocr_thread_running:
            return
        if (self._config.detection_mode == DETECTION_MODE_AUTO
                and self._last_ocr_success_at is None
                and self._ocr_attempts_without_success >= AUTO_DETECTION_MAX_OCR_ATTEMPTS_WITHOUT_SUCCESS):
            return
        if self._last_ocr_start is not None and now - self._last_ocr_start < OCR_POLL_INTERVAL_SECONDS:
            return
        self._last_ocr_start = now
        self._ocr_thread_running = True
        threading.Thread(target=self._run_ocr, args=(rgb_frame, now), daemon=True).start()

    def _run_ocr(self, rgb_frame: np.ndarray, now: float) -> None:
        """now is the value process() was called with when this attempt started
        (not real time) - _last_ocr_success_at is compared against process()'s
        own now in auto mode's freshness check, so it needs to live in that
        same clock domain (matters for tests, which pass synthetic now values;
        in production both ultimately come from time.monotonic() via
        AmbienceMode's capture loop anyway)."""
        text = ""
        fraction: float | None = None
        try:
            frame = _mask_frame_for_ocr(rgb_frame, self._mask) if self._mask is not None else rgb_frame
            text = ocr_reader.read_text(frame)
            fraction = ocr_reader.parse_fraction(text, self._config.ocr_max_value)
            if fraction is not None:
                with self._ocr_lock:
                    self._ocr_fraction = fraction
                    self._last_ocr_success_at = now
        except Exception:
            pass  # a missed/failed OCR read this cycle - keep the last known value
        finally:
            self._ocr_thread_running = False
            with self._ocr_lock:
                if fraction is not None:
                    self._ocr_attempts_without_success = 0
                else:
                    self._ocr_attempts_without_success += 1
            if self._debug_callback is not None:
                self._debug_callback(text, fraction)
