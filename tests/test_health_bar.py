"""Unit tests for src.screen.health_bar (synthetic frames, no screen capture)."""
from __future__ import annotations

import numpy as np
import pytest

from src.screen.health_bar import (
    DECREASE_COLOUR,
    INCREASE_COLOUR,
    LOW_HEALTH_COLOUR,
    HealthBarTracker,
    calibrate_bar_colour,
    fill_fraction,
)


def _bar_frame(fill_fraction_pct: float, size: int = 100) -> np.ndarray:
    """A horizontal bar: vivid red fill, dark same-hue "empty track" - the
    realistic case that requires matching on more than just hue."""
    frame = np.zeros((20, size, 3), dtype=np.uint8)
    filled_width = int(size * fill_fraction_pct)
    frame[:, :filled_width] = [220, 20, 20]
    frame[:, filled_width:] = [40, 30, 30]
    return frame


def test_calibrate_bar_colour_picks_up_the_fill_hue_not_the_dark_track():
    colour = calibrate_bar_colour(_bar_frame(1.0))
    assert colour is not None
    hue, saturation, value = colour
    assert hue == 0.0
    assert saturation > 0.8  # the vivid fill, not the dark ~0.25-saturation track


def test_fill_fraction_tracks_the_bar_precisely_despite_a_same_hue_dark_track():
    colour = calibrate_bar_colour(_bar_frame(1.0))
    for pct in (1.0, 0.75, 0.5, 0.25, 0.05, 0.0):
        assert fill_fraction(_bar_frame(pct), colour) == pytest.approx(pct, abs=0.02)


def test_calibrate_returns_none_for_a_frame_with_no_vivid_colour():
    grey_frame = np.full((10, 10, 3), 128, dtype=np.uint8)
    assert calibrate_bar_colour(grey_frame) is None


def test_calibrating_at_a_low_fill_level_is_not_diluted_by_the_dominant_dark_track():
    """Regression guard: calibrating while the bar is mostly empty must still pick
    out the vivid fill's true colour, not an average dragged toward the much more
    numerous dark "track" pixels that happen to share its hue."""
    low_fill_colour = calibrate_bar_colour(_bar_frame(0.05))
    full_colour = calibrate_bar_colour(_bar_frame(1.0))
    assert low_fill_colour is not None
    assert low_fill_colour == pytest.approx(full_colour, abs=0.01)


def test_tracker_flashes_red_on_a_meaningful_decrease():
    tracker = HealthBarTracker()
    tracker.calibrate(_bar_frame(1.0))
    assert tracker.process(_bar_frame(1.0), now=0.0) is None  # baseline, no change yet
    assert tracker.process(_bar_frame(0.5), now=0.2) == DECREASE_COLOUR


def test_tracker_flashes_green_on_a_meaningful_increase():
    tracker = HealthBarTracker()
    tracker.calibrate(_bar_frame(0.3))
    tracker.process(_bar_frame(0.3), now=0.0)
    assert tracker.process(_bar_frame(0.8), now=0.2) == INCREASE_COLOUR


def test_tracker_ignores_tiny_jitter_below_the_change_epsilon():
    tracker = HealthBarTracker()
    tracker.calibrate(_bar_frame(0.5))
    tracker.process(_bar_frame(0.5), now=0.0)
    assert tracker.process(_bar_frame(0.505), now=0.2) is None


def test_tracker_flash_expires_after_the_blink_duration():
    tracker = HealthBarTracker()
    tracker.calibrate(_bar_frame(1.0))
    tracker.process(_bar_frame(1.0), now=0.0)
    assert tracker.process(_bar_frame(0.5), now=0.2) == DECREASE_COLOUR
    assert tracker.process(_bar_frame(0.5), now=0.3) == DECREASE_COLOUR  # still within the window
    assert tracker.process(_bar_frame(0.5), now=1.0) is None  # blink window has elapsed


def test_tracker_holds_low_health_glow_continuously():
    tracker = HealthBarTracker()
    tracker.calibrate(_bar_frame(1.0))
    tracker.process(_bar_frame(1.0), now=0.0)
    assert tracker.process(_bar_frame(0.05), now=0.2) == LOW_HEALTH_COLOUR
    assert tracker.process(_bar_frame(0.05), now=5.0) == LOW_HEALTH_COLOUR  # long after any flash would expire


def test_low_health_glow_takes_priority_over_a_simultaneous_flash():
    tracker = HealthBarTracker()
    tracker.calibrate(_bar_frame(0.5))
    tracker.process(_bar_frame(0.5), now=0.0)
    # A drop straight into low-health territory would normally also qualify as a
    # "decrease" flash - low health should win.
    assert tracker.process(_bar_frame(0.05), now=0.2) == LOW_HEALTH_COLOUR


def test_recovering_above_the_low_health_threshold_resumes_normal_flash_behaviour():
    tracker = HealthBarTracker()
    tracker.calibrate(_bar_frame(0.05))
    tracker.process(_bar_frame(0.05), now=0.0)
    assert tracker.process(_bar_frame(0.05), now=0.2) == LOW_HEALTH_COLOUR
    assert tracker.process(_bar_frame(0.9), now=0.4) == INCREASE_COLOUR


def test_tracker_process_returns_none_before_any_calibration():
    tracker = HealthBarTracker()
    assert tracker.process(_bar_frame(0.5), now=0.0) is None
