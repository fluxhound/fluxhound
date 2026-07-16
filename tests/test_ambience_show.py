"""Unit tests for src.screen.ambience_show (synthetic frames, no screen capture)."""
from __future__ import annotations

import numpy as np

from src.screen.ambience_show import (
    AMBIENCE_SLIDER_DEFAULT,
    AMBIENCE_SLIDER_MAX,
    AMBIENCE_SLIDER_MIN,
    BORING_SATURATION_THRESHOLD,
    DEFAULT_SMOOTHING_FACTOR,
    AmbienceEnvelope,
    colour_sensitivity_to_threshold,
    rgb_to_hsv,
    smoothing_to_factor,
)


def _solid_frame(rgb: tuple[int, int, int], size: int = 20) -> np.ndarray:
    frame = np.zeros((size, size, 3), dtype=np.uint8)
    frame[:, :] = rgb
    return frame


def test_rgb_to_hsv_matches_known_pure_colours():
    frame = np.array([[[255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 255, 255]]], dtype=np.uint8)
    hue, sat, val = rgb_to_hsv(frame)
    assert list(hue[0]) == [0.0, 120.0, 240.0, 0.0]
    assert list(sat[0]) == [1.0, 1.0, 1.0, 0.0]
    assert list(val[0]) == [1.0, 1.0, 1.0, 1.0]


def test_pure_saturated_colour_at_full_brightness_is_not_treated_as_boring():
    """A regression guard: brightness alone must never disqualify a fully saturated
    colour just for being bright (only low saturation makes a pixel "boring")."""
    env = AmbienceEnvelope(smoothing_factor=1.0)
    hue, saturation, value = env.process(_solid_frame((0, 0, 255)))
    assert (hue, saturation, value) == (240, 1000, 1000)


def test_mostly_boring_background_with_a_vivid_patch_picks_the_vivid_colour():
    """The whole point of the feature: a small saturated area should still produce a
    clearly visible, mood-appropriate colour instead of being averaged away by a
    much larger boring (near-white) background."""
    frame = np.full((100, 100, 3), 230, dtype=np.uint8)
    frame[40:60, 40:60] = [220, 20, 20]  # vivid red patch, ~4% of the frame
    env = AmbienceEnvelope(smoothing_factor=1.0)
    hue, saturation, value = env.process(frame)
    assert hue == 0
    assert saturation > 800  # clearly saturated, not washed toward grey


def test_fully_boring_frame_drops_saturation_to_zero_but_keeps_screen_brightness():
    env = AmbienceEnvelope(smoothing_factor=1.0)
    hue, saturation, value = env.process(_solid_frame((128, 128, 128)))
    assert saturation == 0
    assert value == 502  # 128/255 * 1000, rounded


def test_boring_frame_holds_the_last_hue_instead_of_resetting():
    env = AmbienceEnvelope(smoothing_factor=1.0)
    env.process(_solid_frame((0, 0, 255)))  # establishes hue=240
    hue, saturation, _ = env.process(_solid_frame((128, 128, 128)))
    assert hue == 240
    assert saturation == 0


def test_mixed_distinct_colours_pick_one_dominant_hue_not_a_blended_average():
    """Half red, half blue must not average out to a muddy purple that nothing on
    screen actually shows."""
    frame = np.zeros((20, 20, 3), dtype=np.uint8)
    frame[:, :10] = [255, 0, 0]
    frame[:, 10:] = [0, 0, 255]
    env = AmbienceEnvelope(smoothing_factor=1.0)
    hue, saturation, _ = env.process(frame)
    assert hue in (0, 240)  # one of the two, never something in between
    assert saturation == 1000


def test_smoothing_takes_the_short_way_around_the_hue_wrap():
    env = AmbienceEnvelope(smoothing_factor=0.5)
    env.process(_solid_frame((255, 0, 0)))  # hue 0
    hue, _, _ = env.process(_solid_frame((255, 0, 50)))  # hue close to 350 (just past red)
    # Moving from 0 toward ~350 the short way goes negative (wraps near 360), not
    # through 180 - so the result should land near 355-360/0, not near 175.
    assert hue > 340 or hue < 5


# -- Colour sensitivity / smoothing sliders (0-100, 50 = neutral) --------------------

def test_slider_default_reproduces_fixed_thresholds_exactly():
    assert colour_sensitivity_to_threshold(AMBIENCE_SLIDER_DEFAULT) == BORING_SATURATION_THRESHOLD
    assert smoothing_to_factor(AMBIENCE_SLIDER_DEFAULT) == DEFAULT_SMOOTHING_FACTOR


def test_higher_colour_sensitivity_raises_the_threshold():
    low = colour_sensitivity_to_threshold(AMBIENCE_SLIDER_MIN)
    high = colour_sensitivity_to_threshold(AMBIENCE_SLIDER_MAX)
    assert low < BORING_SATURATION_THRESHOLD < high


def test_higher_smoothing_lowers_the_ema_factor():
    """Higher "Smoothing" means slower colour transitions - a smaller EMA weight."""
    low = smoothing_to_factor(AMBIENCE_SLIDER_MIN)
    high = smoothing_to_factor(AMBIENCE_SLIDER_MAX)
    assert high < DEFAULT_SMOOTHING_FACTOR < low


def test_envelope_setters_change_behaviour_without_resetting_smoothed_state():
    env = AmbienceEnvelope(smoothing_factor=1.0)
    env.process(_solid_frame((255, 0, 0)))  # establishes hue=0, fully smoothed already
    env.set_smoothing_factor(0.0)  # freeze future updates entirely
    hue, saturation, _ = env.process(_solid_frame((0, 0, 255)))
    assert hue == 0  # frozen - the new blue reading never took effect
    assert saturation == 1000  # untouched by the frozen update either


def test_envelope_boring_threshold_setter_takes_effect_next_call():
    frame = np.full((20, 20, 3), 200, dtype=np.uint8)
    frame[:, :] = [200, 190, 190]  # low saturation, would normally count as boring
    env = AmbienceEnvelope(smoothing_factor=1.0, boring_saturation_threshold=0.5)
    _, saturation, _ = env.process(frame)
    assert saturation == 0  # too dull to clear the strict threshold

    env.set_boring_saturation_threshold(0.0)
    _, saturation, _ = env.process(frame)
    assert saturation > 0  # now everything with any saturation at all counts
