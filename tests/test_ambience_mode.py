"""Unit tests for src.modes.ambience_mode's OCR --debug logging helpers
(_open_ocr_debug_log/_make_ocr_debug_callback). The full background-thread
run loop (screen capture, real bulb dispatch) is live-verified instead, same
as every other real-hardware-dependent path in this project - these tests
only cover the CSV-writing wiring in isolation."""
from __future__ import annotations

import csv

import numpy as np

from src.modes.ambience_mode import AmbienceMode, OCR_DEBUG_LOG_COLUMNS

_FRAME = np.zeros((10, 10, 3), dtype=np.uint8)


def test_open_ocr_debug_log_yields_none_when_no_path_given():
    mode = AmbienceMode([], debug_log_path=None)
    with mode._open_ocr_debug_log() as write_row:
        assert write_row is None


def test_open_ocr_debug_log_writes_the_header_when_a_path_is_given(tmp_path):
    log_path = tmp_path / "ocr_debug_test.csv"
    mode = AmbienceMode([], debug_log_path=log_path)
    with mode._open_ocr_debug_log() as write_row:
        assert write_row is not None

    with open(log_path, newline="", encoding="utf-8") as debug_file:
        rows = list(csv.reader(debug_file))
    assert rows == [list(OCR_DEBUG_LOG_COLUMNS)]


def test_ocr_debug_callback_writes_watcher_name_raw_text_and_fraction(tmp_path):
    log_path = tmp_path / "ocr_debug_test.csv"
    mode = AmbienceMode([], debug_log_path=log_path)
    mode._debug_log_start = 0.0
    with mode._open_ocr_debug_log() as write_row:
        callback = mode._make_ocr_debug_callback(write_row, "HP Zahl")
        callback("87/100", 0.87, _FRAME)
        callback("unreadable garbage", None, _FRAME)

    with open(log_path, newline="", encoding="utf-8") as debug_file:
        rows = list(csv.reader(debug_file))
    assert rows[0] == list(OCR_DEBUG_LOG_COLUMNS)
    assert rows[1][1:] == ["HP Zahl", "87/100", "0.87"]
    assert rows[2][1:] == ["HP Zahl", "unreadable garbage", ""]


def test_ocr_debug_log_survives_without_a_clean_close(tmp_path):
    """Regression test for a real report: Ctrl+C in a console raises
    KeyboardInterrupt straight out of Tcl's mainloop callback, killing the
    process before _open_ocr_debug_log's own `with open(...)` block ever
    gets to exit - a session's entire log was lost because nothing had been
    flushed to disk yet. Reads the file from a *separate* handle while the
    context manager is still open, proving each row reaches disk immediately
    rather than sitting in a buffer until a clean close."""
    log_path = tmp_path / "ocr_debug_test.csv"
    mode = AmbienceMode([], debug_log_path=log_path)
    with mode._open_ocr_debug_log() as write_row:
        callback = mode._make_ocr_debug_callback(write_row, "HP")
        callback("79", 0.79, _FRAME)

        with open(log_path, newline="", encoding="utf-8") as debug_file:
            rows_while_still_open = list(csv.reader(debug_file))

    assert rows_while_still_open[0] == list(OCR_DEBUG_LOG_COLUMNS)
    assert rows_while_still_open[1][1:] == ["HP", "79", "0.79"]


def test_ocr_debug_callback_keeps_first_frame_and_updates_latest(tmp_path):
    """A real report - OCR reading nothing at all for an entire session - showed
    the raw text/fraction log alone can't say *why*. Saving each attempt's
    frame as a PNG lets a human see exactly what OCR received: a mask not
    actually covering the number, a blacked-out region, wrong monitor, etc.
    Both "_first" (kept permanently) and "_latest" (overwritten every
    attempt) are saved - a real case showed the very first attempt (fired
    under a second after activation) capturing the FluxHound window/Windows
    taskbar itself, before the user had switched focus back to the game -
    "_first" alone would look wrong for a reason unrelated to the actual
    mask/region; "_latest" shows the steady state once real gameplay is back
    in focus."""
    log_path = tmp_path / "ocr_debug_test.csv"
    mode = AmbienceMode([], debug_log_path=log_path)
    with mode._open_ocr_debug_log() as write_row:
        callback = mode._make_ocr_debug_callback(write_row, "Gaming Mode (built-in)")
        callback("", None, _FRAME)
        callback("", None, _FRAME * 2)  # a later attempt - must update "latest" but not "first"

    first_images = list(tmp_path.glob("ocr_debug_test_*_first.png"))
    latest_images = list(tmp_path.glob("ocr_debug_test_*_latest.png"))
    assert len(first_images) == 1
    assert len(latest_images) == 1

    import cv2
    assert (cv2.imread(str(first_images[0])) == _FRAME[:, :, ::-1]).all()
    assert (cv2.imread(str(latest_images[0])) == (_FRAME * 2)[:, :, ::-1]).all()


def test_ocr_debug_callback_sanitizes_the_watcher_name_for_the_filename(tmp_path):
    log_path = tmp_path / "ocr_debug_test.csv"
    mode = AmbienceMode([], debug_log_path=log_path)
    with mode._open_ocr_debug_log() as write_row:
        callback = mode._make_ocr_debug_callback(write_row, "HP/Mana: 100%")
        callback("", None, _FRAME)

    saved_images = list(tmp_path.glob("ocr_debug_test_*.png"))
    assert len(saved_images) == 2  # "_first" and "_latest"
    for image in saved_images:
        assert "/" not in image.name
        assert ":" not in image.name
        assert "%" not in image.name
