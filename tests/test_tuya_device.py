"""Unit tests for src.tuya.device (no network I/O)."""
from __future__ import annotations

from src.tuya.device import _build_colour_data


def test_build_colour_data_matches_dp24_example():
    """DP 24 example from CLAUDE.md: h=236, s=1000, v=1000 -> "00ec03e803e8"."""
    assert _build_colour_data(236, 1000, 1000) == "00ec03e803e8"


def test_build_colour_data_clamps_out_of_range_values():
    """Hue/saturation/value outside their valid ranges are clamped, not wrapped."""
    assert _build_colour_data(-10, 2000, -5) == "0000" + "03e8" + "0000"
