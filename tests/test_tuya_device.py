"""Unit tests for src.tuya.device (no network I/O)."""
from __future__ import annotations

from src.tuya.device import _build_colour_data, split_value_across_bulbs


def test_build_colour_data_matches_dp24_example():
    """DP 24 example from CLAUDE.md: h=236, s=1000, v=1000 -> "00ec03e803e8"."""
    assert _build_colour_data(236, 1000, 1000) == "00ec03e803e8"


def test_build_colour_data_clamps_out_of_range_values():
    """Hue/saturation/value outside their valid ranges are clamped, not wrapped."""
    assert _build_colour_data(-10, 2000, -5) == "0000" + "03e8" + "0000"


def test_split_value_across_bulbs_three_bulb_example():
    """From the spec: 50% across 3 bulbs -> BASE 100%, EXT-1 50%, EXT-2 0%."""
    assert split_value_across_bulbs(500, 1000, 3) == [1000, 500, 0]


def test_split_value_across_bulbs_two_bulb_example():
    """From the spec: 50% across 2 bulbs -> BASE 100%, EXT-1 0%."""
    assert split_value_across_bulbs(500, 1000, 2) == [1000, 0]


def test_split_value_across_bulbs_full_value_fills_every_bulb():
    assert split_value_across_bulbs(1000, 1000, 3) == [1000, 1000, 1000]


def test_split_value_across_bulbs_zero_value_fills_nothing():
    assert split_value_across_bulbs(0, 1000, 3) == [0, 0, 0]


def test_split_value_across_bulbs_single_bulb_gets_the_whole_value():
    assert split_value_across_bulbs(360, 1000, 1) == [360]


def test_split_value_across_bulbs_zero_count_returns_empty():
    assert split_value_across_bulbs(500, 1000, 0) == []
