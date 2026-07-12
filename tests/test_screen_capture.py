"""Unit tests for src.screen.capture (real mss/display required - CI running
headless without a display would need to skip this file, but this project only
targets a real Windows desktop)."""
from __future__ import annotations

from src.screen.capture import ScreenCapture, list_monitors


def test_list_monitors_returns_1_indexed_entries_with_dimensions():
    monitors = list_monitors()
    assert len(monitors) >= 1
    for expected_index, monitor in enumerate(monitors, start=1):
        assert monitor["index"] == expected_index
        assert monitor["width"] > 0
        assert monitor["height"] > 0


def test_resolve_grab_area_with_no_region_returns_the_whole_monitor():
    monitor = {"left": 100, "top": 50, "width": 1920, "height": 1080}
    assert ScreenCapture._resolve_grab_area(monitor, None) == monitor


def test_resolve_grab_area_with_region_offsets_from_the_monitors_own_origin():
    monitor = {"left": -1920, "top": 0, "width": 1920, "height": 1080}
    area = ScreenCapture._resolve_grab_area(monitor, (100, 50, 400, 300))
    assert area == {"left": -1820, "top": 50, "width": 400, "height": 300}


def test_resolve_grab_area_clamps_degenerate_region_size_to_at_least_1px():
    monitor = {"left": 0, "top": 0, "width": 1920, "height": 1080}
    area = ScreenCapture._resolve_grab_area(monitor, (0, 0, 0, 0))
    assert area["width"] == 1
    assert area["height"] == 1


def test_select_monitor_falls_back_to_primary_for_an_out_of_range_index():
    capture = ScreenCapture(monitor_index=9999)
    try:
        monitors = list_monitors()
        primary = next((m for m in monitors if m.get("is_primary")), monitors[0])
        assert capture._monitor["left"] == primary["left"]
        assert capture._monitor["top"] == primary["top"]
    finally:
        capture.close()


def test_select_monitor_picks_the_requested_index():
    monitors = list_monitors()
    target = monitors[-1]
    capture = ScreenCapture(monitor_index=target["index"])
    try:
        assert capture._monitor["left"] == target["left"]
        assert capture._monitor["top"] == target["top"]
    finally:
        capture.close()
