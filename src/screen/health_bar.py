"""Gaming Mode's health/resource-bar fill detection: turns the "Set area" region
into a 0-1 fill estimate, and a small state machine that decides when the bulb
should briefly flash or glow to signal a change.

Works for horizontal bars, vertical bars, and circular orbs (Diablo-style) alike,
without knowing the bar's shape or orientation: the region is assumed to be
cropped tightly around the bar/orb's full fixed extent, so the fraction of the
region's pixels that currently match the bar's own fill colour *is* the fill
percentage, regardless of geometry. Deliberately not OCR-based: reading styled
in-game digits reliably would need a much heavier, more fragile dependency for a
signal this simple colour-ratio approach already gives directly.

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

import numpy as np

from src.screen.ambience_show import rgb_to_hsv

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

LOW_HEALTH_THRESHOLD = 0.10
CHANGE_EPSILON = 0.02  # ignore fractional jitter (compression noise, edge aliasing) below this
BLINK_DURATION_SECONDS = 0.5

DECREASE_COLOUR = (0, 1000, 1000)    # solid red flash
INCREASE_COLOUR = (120, 1000, 1000)  # solid green flash
LOW_HEALTH_COLOUR = (0, 1000, 1000)  # solid red, held continuously


def calibrate_bar_colour(rgb_frame: np.ndarray) -> tuple[float, float, float] | None:
    """Identify the region's dominant vivid colour (hue, mean saturation, mean
    value) *in this one frame*: the peak of a saturation-weighted hue histogram
    among sufficiently vivid pixels - the same "most frequent colour" idea
    Ambience Mode itself uses for the whole screen, applied here to just the
    cropped region. Returns None if nothing in the frame is vivid enough to be a
    fill colour (most commonly: the bar is empty right now)."""
    hue, sat, val = rgb_to_hsv(rgb_frame)
    hue = hue.reshape(-1)
    sat = sat.reshape(-1)
    val = val.reshape(-1)
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


def fill_fraction(rgb_frame: np.ndarray, bar_colour: tuple[float, float, float]) -> float:
    """What fraction (0-1) of the region's pixels currently match bar_colour -
    directly the bar/orb's current fill level, as long as the region was cropped
    around its full fixed extent. Matches on hue, saturation, *and* value
    together, so a darker same-hue "empty track" doesn't get counted as filled."""
    bar_hue, bar_saturation, bar_value = bar_colour
    hue, sat, val = rgb_to_hsv(rgb_frame)
    hue = hue.reshape(-1)
    sat = sat.reshape(-1)
    val = val.reshape(-1)
    if hue.size == 0:
        return 0.0
    hue_delta = np.abs(((hue - bar_hue + 180) % 360) - 180)
    matches = (
        (hue_delta <= FILL_HUE_TOLERANCE_DEGREES)
        & (sat >= bar_saturation * FILL_SATURATION_RATIO)
        & (val >= bar_value * FILL_VALUE_RATIO)
    )
    return float(np.count_nonzero(matches)) / hue.size


def measure_fill(rgb_frame: np.ndarray) -> float:
    """One frame in, current fill fraction out - identifies this frame's own
    dominant vivid colour and measures against it in the same step, so there's no
    persisted reference to fall out of sync with a colour-shifting bar, and no
    single calibration moment that can get unlucky."""
    colour = calibrate_bar_colour(rgb_frame)
    if colour is None:
        return 0.0  # nothing vivid in the frame - the bar reads empty
    return fill_fraction(rgb_frame, colour)


class HealthBarTracker:
    """Tracks the bar's fill fraction across frames and decides what colour (if
    any) should override the normal ambient reading this tick: a brief flash on a
    meaningful increase/decrease, or a continuous glow below
    LOW_HEALTH_THRESHOLD - the latter takes priority over a flash that happens to
    still be active."""

    def __init__(self):
        self._last_fraction: float | None = None
        self._blink_until: float = 0.0
        self._blink_colour: tuple[int, int, int] | None = None

    def process(self, rgb_frame: np.ndarray, now: float) -> tuple[int, int, int] | None:
        """Update from one frame; returns the (hue, saturation, value) to force
        onto the bulb this tick, or None if the normal ambient reading should be
        sent instead. The first call after construction only records a baseline -
        there's nothing to compare it to yet, so it can't be a "change"."""
        fraction = measure_fill(rgb_frame)
        if self._last_fraction is not None:
            delta = fraction - self._last_fraction
            if delta <= -CHANGE_EPSILON:
                self._blink_until = now + BLINK_DURATION_SECONDS
                self._blink_colour = DECREASE_COLOUR
            elif delta >= CHANGE_EPSILON:
                self._blink_until = now + BLINK_DURATION_SECONDS
                self._blink_colour = INCREASE_COLOUR
        self._last_fraction = fraction

        if fraction < LOW_HEALTH_THRESHOLD:
            return LOW_HEALTH_COLOUR
        if now < self._blink_until:
            return self._blink_colour
        return None
