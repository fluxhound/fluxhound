"""Unit tests for src.modes.ambience_mode's OCR --debug logging helpers
(_open_ocr_debug_log/_make_ocr_debug_callback). The full background-thread
run loop (screen capture, real bulb dispatch) is live-verified instead, same
as every other real-hardware-dependent path in this project - these tests
only cover the CSV-writing wiring in isolation."""
from __future__ import annotations

import csv

from src.modes.ambience_mode import AmbienceMode, OCR_DEBUG_LOG_COLUMNS


def test_open_ocr_debug_log_yields_none_when_no_path_given():
    mode = AmbienceMode([], debug_log_path=None)
    with mode._open_ocr_debug_log() as writer:
        assert writer is None


def test_open_ocr_debug_log_writes_the_header_when_a_path_is_given(tmp_path):
    log_path = tmp_path / "ocr_debug_test.csv"
    mode = AmbienceMode([], debug_log_path=log_path)
    with mode._open_ocr_debug_log() as writer:
        assert writer is not None

    with open(log_path, newline="", encoding="utf-8") as debug_file:
        rows = list(csv.reader(debug_file))
    assert rows == [list(OCR_DEBUG_LOG_COLUMNS)]


def test_ocr_debug_callback_writes_watcher_name_raw_text_and_fraction(tmp_path):
    log_path = tmp_path / "ocr_debug_test.csv"
    mode = AmbienceMode([], debug_log_path=log_path)
    mode._debug_log_start = 0.0
    with mode._open_ocr_debug_log() as writer:
        callback = mode._make_ocr_debug_callback(writer, "HP Zahl")
        callback("87/100", 0.87)
        callback("unreadable garbage", None)

    with open(log_path, newline="", encoding="utf-8") as debug_file:
        rows = list(csv.reader(debug_file))
    assert rows[0] == list(OCR_DEBUG_LOG_COLUMNS)
    assert rows[1][1:] == ["HP Zahl", "87/100", "0.87"]
    assert rows[2][1:] == ["HP Zahl", "unreadable garbage", ""]
