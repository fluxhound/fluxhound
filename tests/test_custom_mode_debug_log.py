"""Unit tests for CustomMode's --debug CSV logging (src/modes/custom_mode.py) -
just the file-writing helpers, not the real audio background thread (no audio
hardware in CI, same reasoning as AmbienceMode having no dedicated test file)."""
from __future__ import annotations

import csv

import numpy as np

from src.audio.custom_show import SOURCE_BEAT, SOURCE_ENERGY, SOURCE_TIMBRE, CustomShowEnvelope
from src.modes.custom_mode import DEBUG_LOG_COLUMNS, CustomMode

SAMPLE_RATE = 44100
BLOCK_SIZE = 1024


def _make_mode(debug_log_path=None) -> CustomMode:
    sensitivity = {SOURCE_TIMBRE: 50.0, SOURCE_ENERGY: 50.0, SOURCE_BEAT: 50.0}
    return CustomMode([], {}, sensitivity, debug_log_path=debug_log_path)


def test_open_debug_log_yields_none_when_no_path_given():
    mode = _make_mode(debug_log_path=None)
    with mode._open_debug_log() as write_row:
        assert write_row is None


def test_open_debug_log_writes_header(tmp_path):
    log_path = tmp_path / "audio_debug_test.csv"
    mode = _make_mode(debug_log_path=log_path)
    with mode._open_debug_log():
        pass
    rows = list(csv.reader(log_path.open(encoding="utf-8")))
    assert rows[0] == list(DEBUG_LOG_COLUMNS)


def test_write_debug_row_produces_one_row_per_call(tmp_path):
    log_path = tmp_path / "audio_debug_test.csv"
    mode = _make_mode(debug_log_path=log_path)
    envelope = CustomShowEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    source_values = envelope.process(np.zeros(BLOCK_SIZE, dtype=np.float32), 0.0)
    sensitivity_snapshot = {SOURCE_TIMBRE: 50.0, SOURCE_ENERGY: 50.0, SOURCE_BEAT: 50.0}

    with mode._open_debug_log() as write_row:
        mode._write_debug_row(write_row, 0.023, source_values, envelope, sensitivity_snapshot)
        mode._write_debug_row(write_row, 0.046, source_values, envelope, sensitivity_snapshot)

    rows = list(csv.reader(log_path.open(encoding="utf-8")))
    assert rows[0] == list(DEBUG_LOG_COLUMNS)
    assert len(rows) == 3  # header + 2 data rows
    assert rows[1][0] == "0.023"
    assert rows[2][0] == "0.046"
    assert len(rows[1]) == len(DEBUG_LOG_COLUMNS)


def test_debug_log_survives_without_a_clean_close(tmp_path):
    """Regression test for a real report: Ctrl+C in a console raises
    KeyboardInterrupt straight out of Tcl's mainloop callback, killing the
    process before _open_debug_log's own `with open(...)` block ever gets to
    exit - a whole session's log was lost because nothing had been flushed
    to disk yet. Reads the file from a *separate* handle while the context
    manager is still open, proving each row reaches disk immediately rather
    than sitting in a buffer until a clean close."""
    log_path = tmp_path / "audio_debug_test.csv"
    mode = _make_mode(debug_log_path=log_path)
    envelope = CustomShowEnvelope(SAMPLE_RATE, BLOCK_SIZE)
    source_values = envelope.process(np.zeros(BLOCK_SIZE, dtype=np.float32), 0.0)
    sensitivity_snapshot = {SOURCE_TIMBRE: 50.0, SOURCE_ENERGY: 50.0, SOURCE_BEAT: 50.0}

    with mode._open_debug_log() as write_row:
        mode._write_debug_row(write_row, 0.023, source_values, envelope, sensitivity_snapshot)
        rows_while_still_open = list(csv.reader(log_path.open(encoding="utf-8")))

    assert len(rows_while_still_open) == 2  # header + the one row written so far
    assert rows_while_still_open[1][0] == "0.023"
