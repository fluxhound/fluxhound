"""Unit tests for src.screen.ocr_reader.parse_fraction (pure text parsing -
no need to load the actual rapidocr model for these; read_text itself is
live-verified instead, same as every other real-hardware-dependent path in
this project)."""
from __future__ import annotations

from src.screen.ocr_reader import parse_fraction


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
