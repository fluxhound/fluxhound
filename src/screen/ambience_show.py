"""Screen-ambience colour analysis: turns a screen capture into one hue/saturation/
brightness reading representing the "mood" of whatever's dominantly colourful on
screen.

Deliberately discounts "boring" pixels - low-saturation, near-black, or near-white -
before picking a dominant colour. Most real screen content (text, window chrome,
black bars, plain backgrounds) is exactly that kind of boring and, by sheer pixel
count, would otherwise wash a flat average toward a muddy grey/brown that doesn't
reflect what's actually visually going on. Discarding it lets a comparatively small
patch of vivid colour (a video thumbnail, an album cover, a game's UI) still produce
a clearly visible, mood-appropriate result.
"""
from __future__ import annotations

import numpy as np

# Pixels below this saturation don't count as "colourful" for hue-picking purposes -
# a near-white or near-grey pixel already has near-zero saturation by definition, so
# this alone is what filters those out (brightness itself doesn't make a colour
# boring - a fully saturated pure blue at maximum brightness is exactly as vivid as
# a dim one). BORING_VALUE_LOW only exists to drop near-black pixels, whose hue is
# numerically noisy at 8-bit quantization (barely any distinct RGB values available).
BORING_SATURATION_THRESHOLD = 0.18
BORING_VALUE_LOW = 0.06

HUE_BINS = 36  # 10-degree buckets for the "most frequent colour" histogram

DEFAULT_SMOOTHING_FACTOR = 0.15  # exponential moving average weight per new reading


def rgb_to_hsv(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorized RGB (..., 3, 0-255) -> separate H (0-360), S (0-1), V (0-1) arrays."""
    normalized = rgb.astype(np.float64) / 255.0
    r, g, b = normalized[..., 0], normalized[..., 1], normalized[..., 2]
    maxc = np.max(normalized, axis=-1)
    minc = np.min(normalized, axis=-1)
    v = maxc
    delta = maxc - minc
    s = np.divide(delta, maxc, out=np.zeros_like(delta), where=maxc != 0)

    hue = np.zeros_like(maxc)
    has_colour = delta != 0
    r_is_max = has_colour & (maxc == r)
    g_is_max = has_colour & (maxc == g) & ~r_is_max
    b_is_max = has_colour & ~r_is_max & ~g_is_max

    hue[r_is_max] = ((g[r_is_max] - b[r_is_max]) / delta[r_is_max]) % 6
    hue[g_is_max] = (b[g_is_max] - r[g_is_max]) / delta[g_is_max] + 2
    hue[b_is_max] = (r[b_is_max] - g[b_is_max]) / delta[b_is_max] + 4
    hue *= 60.0
    return hue, s, v


def _hue_delta(current: float, target: float) -> float:
    """Shortest signed distance from current to target around the 360-degree hue
    circle, so smoothing takes the short way (e.g. 350 -> 10 is +20, not -340)."""
    return (target - current + 180) % 360 - 180


class AmbienceEnvelope:
    """Smoothed hue/saturation/brightness derived from repeated screen captures."""

    def __init__(self, smoothing_factor: float = DEFAULT_SMOOTHING_FACTOR):
        self._smoothing_factor = smoothing_factor
        self._hue: float | None = None
        self._saturation: float = 0.0
        self._value: float = 0.0

    def process(self, rgb_frame: np.ndarray) -> tuple[int, int, int]:
        """Analyse one captured frame and return the smoothed (hue 0-360,
        saturation 0-1000, value 0-1000) reading to send to the bulb."""
        hue_deg, sat, val = rgb_to_hsv(rgb_frame)
        hue_deg = hue_deg.reshape(-1)
        sat = sat.reshape(-1)
        val = val.reshape(-1)

        colourful = (sat >= BORING_SATURATION_THRESHOLD) & (val >= BORING_VALUE_LOW)
        if np.any(colourful):
            hues = hue_deg[colourful]
            sats = sat[colourful]
            # "Most frequent" hue: a saturation-weighted histogram (a more vivid
            # pixel counts more than a barely-colourful one) rather than a flat
            # average, which would blur genuinely distinct colours together (mixed
            # red and blue content averaging to a muddy purple nothing on screen
            # actually shows).
            bin_edges = np.linspace(0, 360, HUE_BINS + 1)
            bin_indices = np.clip(np.digitize(hues, bin_edges) - 1, 0, HUE_BINS - 1)
            weights = np.zeros(HUE_BINS)
            np.add.at(weights, bin_indices, sats)
            peak_bin = int(np.argmax(weights))
            in_peak = bin_indices == peak_bin
            target_hue = float(np.mean(hues[in_peak]))
            target_saturation = float(np.mean(sats[in_peak]))
        else:
            # An entirely "boring" frame (e.g. a plain text document): hold the last
            # hue rather than snapping to a hardcoded default, but drop saturation to
            # 0 - there's no colour to reflect right now.
            target_hue = self._hue if self._hue is not None else 0.0
            target_saturation = 0.0
        # Brightness follows the whole screen, not just the colourful pixels - a
        # bright white document should still produce a bright (if unsaturated) light.
        target_value = float(np.mean(val))

        if self._hue is None:
            self._hue = target_hue
            self._saturation = target_saturation
            self._value = target_value
        else:
            self._hue = (self._hue + _hue_delta(self._hue, target_hue) * self._smoothing_factor) % 360
            self._saturation += (target_saturation - self._saturation) * self._smoothing_factor
            self._value += (target_value - self._value) * self._smoothing_factor

        return (
            int(round(self._hue)) % 360,
            int(round(max(0.0, min(1.0, self._saturation)) * 1000)),
            int(round(max(0.0, min(1.0, self._value)) * 1000)),
        )
