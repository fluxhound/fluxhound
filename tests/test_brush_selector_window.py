"""Unit tests for the pure mask-geometry helpers in
src/gui/brush_selector_window.py (no Tkinter/GUI needed for these - the
actual painting widget is live-verified instead, same as
region_selector_window.py)."""
from __future__ import annotations

import numpy as np

from src.gui.brush_selector_window import _stamp_circle, _stamp_stroke


def test_stamp_circle_marks_a_disc_of_the_given_radius():
    mask = np.zeros((40, 40), dtype=bool)
    _stamp_circle(mask, cx=20, cy=20, radius=5, value=True)

    assert mask[20, 20]  # centre is always inside
    assert mask[20, 24]  # within radius
    assert not mask[20, 30]  # well outside radius
    assert np.count_nonzero(mask) > 0


def test_stamp_circle_clips_at_array_bounds():
    mask = np.zeros((10, 10), dtype=bool)
    _stamp_circle(mask, cx=0, cy=0, radius=5, value=True)  # centre right at the corner

    assert mask.any()  # doesn't raise, and still marks the in-bounds portion of the circle
    assert mask[0, 0]


def test_stamp_circle_can_clear_as_well_as_mark():
    mask = np.ones((20, 20), dtype=bool)
    _stamp_circle(mask, cx=10, cy=10, radius=4, value=False)

    assert not mask[10, 10]
    assert mask[0, 0]  # untouched, still True


def test_stamp_stroke_connects_far_apart_points_without_gaps():
    """A fast mouse drag only samples a few points along a long path - the
    stroke between them must still be continuous, not just two separate dots."""
    mask = np.zeros((100, 100), dtype=bool)
    _stamp_stroke(mask, points=[(5, 50), (95, 50)], radius=3, value=True)

    # The midpoint of the stroke must be painted too, not just the two endpoints.
    assert mask[50, 50]
    assert mask[50, 5]
    assert mask[50, 95]


def test_stamp_stroke_with_a_single_point_still_paints_something():
    mask = np.zeros((20, 20), dtype=bool)
    _stamp_stroke(mask, points=[(10, 10)], radius=3, value=True)

    assert mask[10, 10]


def test_stamp_stroke_with_no_points_does_nothing():
    mask = np.zeros((20, 20), dtype=bool)
    _stamp_stroke(mask, points=[], radius=3, value=True)

    assert not mask.any()
