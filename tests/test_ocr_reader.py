"""Unit tests for src.screen.ocr_reader.parse_fraction (pure text parsing -
no need to load the actual rapidocr model for these) and _normalize_for_ocr
(pure image processing, also no model needed) - read_text itself (the part
that actually calls the model) is live-verified instead, same as every other
real-hardware-dependent path in this project."""
from __future__ import annotations

import numpy as np

from src.screen.ocr_reader import _normalize_for_ocr, parse_fraction


def test_ratio_format_takes_priority():
    assert parse_fraction("87/100", max_value=None) == 0.87


def test_ratio_format_with_spaces():
    assert parse_fraction("87 / 100", max_value=None) == 0.87


def test_ratio_format_with_surrounding_text():
    assert parse_fraction("HP: 42/50", max_value=None) == 0.84


def test_percent_format():
    assert parse_fraction("73%", max_value=None) == 0.73


def test_percent_takes_priority_over_bare_number_fallback():
    assert parse_fraction("73%", max_value=1000) == 0.73


def test_bare_number_needs_max_value():
    assert parse_fraction("87", max_value=None) is None
    assert parse_fraction("87", max_value=100) == 0.87


def test_bare_number_with_zero_max_value_is_not_used():
    assert parse_fraction("87", max_value=0) is None


def test_no_number_at_all_returns_none():
    assert parse_fraction("Health", max_value=100) is None
    assert parse_fraction("", max_value=100) is None


def test_result_is_clamped_to_0_1():
    assert parse_fraction("150/100", max_value=None) == 1.0
    assert parse_fraction("150%", max_value=None) == 1.0
    assert parse_fraction("500", max_value=100) == 1.0


def test_ratio_with_zero_max_is_ignored():
    assert parse_fraction("50/0", max_value=None) is None


def test_decimal_numbers_with_comma_or_dot():
    assert parse_fraction("8,5/10", max_value=None) == 0.85
    assert parse_fraction("8.5/10", max_value=None) == 0.85


def test_bare_decimal_fraction_is_already_complete_no_max_value_needed():
    """Some HUDs/mods show a raw 0-1 progress value directly, no ratio or
    percent sign attached - "0.79" already *is* the answer."""
    assert parse_fraction("0.79", max_value=None) == 0.79
    assert parse_fraction(".79", max_value=None) == 0.79
    assert parse_fraction("0,79", max_value=None) == 0.79
    assert parse_fraction("1.0", max_value=None) == 1.0
    assert parse_fraction("1,00", max_value=None) == 1.0


def test_bare_decimal_fraction_does_not_swallow_an_unrelated_larger_number():
    """A decimal whose integer part isn't 0 or 1 (e.g. "10.5") is a bare
    current value with its own separate scale, not an already-complete 0-1
    fraction - must still fall through to the max_value-normalized path."""
    assert parse_fraction("10.5", max_value=100) == 0.105
    assert parse_fraction("10.5", max_value=None) is None


def test_misread_slash_as_period_is_rejected_rather_than_misparsed():
    """A plausible OCR misread of "79/100" as "79.100" (slash confused for a
    period) must not be silently misread as the decimal fraction 0.1 - the
    integer part "79" isn't 0 or 1, so this correctly falls through to None
    (no new information this cycle) instead of a wrong, confident value."""
    assert parse_fraction("79.100", max_value=None) is None


def test_ratio_wins_even_with_a_redundant_percent_or_a_second_ratio_present():
    """Realistic combined HUD text - the ratio is always the first, most
    reliable signal tried, regardless of what else appears alongside it or
    in which order."""
    assert parse_fraction("79/100 (79%)", max_value=None) == 0.79
    assert parse_fraction("79% (79/100)", max_value=None) == 0.79
    assert parse_fraction("HP 79/100 MP 45/60", max_value=None) == 0.79
    assert parse_fraction("79/100/79%", max_value=None) == 0.79


def test_normalize_for_ocr_widens_a_narrow_contrast_range():
    """Regression test for a real report: a legible-to-a-human game HUD
    number (stylized font, low-contrast warm-on-dark colours) failed to
    read at every resolution tried (native through 6x upscale - not a
    resolution problem), but read correctly, reproducibly, once converted
    to grayscale and contrast-stretched - confirmed directly against the
    real failing frame before adopting this. A frame whose brightness only
    spans a narrow low range should end up spanning close to the full 0-255
    range after normalizing."""
    frame = np.full((20, 20, 3), 60, dtype=np.uint8)
    frame[5:15, 5:15] = 90  # a low-contrast "digit" against the background
    normalized = _normalize_for_ocr(frame)
    assert normalized.min() < 10
    assert normalized.max() > 245


def test_normalize_for_ocr_preserves_shape_and_becomes_three_channel_grayscale():
    frame = np.random.randint(0, 256, (30, 50, 3), dtype=np.uint8)
    normalized = _normalize_for_ocr(frame)
    assert normalized.shape == frame.shape
    # grayscale-derived: R, G, and B channels are identical at every pixel
    assert (normalized[:, :, 0] == normalized[:, :, 1]).all()
    assert (normalized[:, :, 1] == normalized[:, :, 2]).all()


def test_normalize_for_ocr_does_not_crash_on_a_flat_uniform_frame():
    """A fully uniform frame (e.g. a masked-out all-black capture) has no
    contrast range to stretch at all - must not divide by zero or crash."""
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    normalized = _normalize_for_ocr(frame)
    assert normalized.shape == frame.shape
