"""OCR-based numeric readout for Gaming Mode watchers whose health/mana is
shown as text/digits rather than a fillable colour bar (e.g. "87/100") -
health_bar.py's fill-fraction approach has nothing to measure there, since
there's no consistently-coloured fill region to compare pixels against.

Wraps rapidocr_onnxruntime, chosen over pytesseract (needs a separately
installed/bundled Tesseract binary, awkward to keep portable and cross-
platform) and Windows' own native OCR (would need untested WinRT/COM
plumbing under PyInstaller) - rapidocr installs like any other pip package
and ships its own small ONNX models, at the cost of a real increase in the
packaged app's size (~150MB, mostly onnxruntime + opencv-python) - see
ARCHITECTURE.md for the full comparison this was decided against.

A single OCR call takes roughly 0.3s - far too slow to run on Ambience
Mode's ~0.1s capture tick without stalling every other watcher and the
ambient reading alongside it. See HealthBarTracker in health_bar.py for how
OCR-mode watchers run this on their own slower background thread instead.
"""
from __future__ import annotations

import re
import threading

import numpy as np

_engine = None
_engine_lock = threading.Lock()

# "87 / 100" (current/max together) - the most reliable case, since the ratio
# is given directly and no extra configuration is needed.
_RATIO_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*/\s*(\d+(?:[.,]\d+)?)")
# "87%" - also self-contained.
_PERCENT_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
# A bare number ("87") needs a caller-supplied max_value to turn into a fraction -
# there's no way to know what "full" means from the digits alone.
_NUMBER_PATTERN = re.compile(r"\d+(?:[.,]\d+)?")


def _get_engine():
    """Lazily constructed and shared across every OCR-mode watcher - loading
    the model takes real setup time, and a fill-fraction-only session (the
    common case) should never pay for it."""
    global _engine
    with _engine_lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR

            _engine = RapidOCR()
    return _engine


def read_text(frame: np.ndarray) -> str:
    """Run OCR on one captured frame, returning every recognized text line
    joined by spaces (empty string if nothing was recognized)."""
    engine = _get_engine()
    result, _elapse = engine(frame)
    if not result:
        return ""
    return " ".join(line[1] for line in result)


def parse_fraction(text: str, max_value: float | None) -> float | None:
    """Extract a 0-1 fraction from OCR'd text. Tries "X/Y" first (most
    reliable - the ratio is given directly), then "X%", then falls back to a
    bare number normalized against max_value if one was configured. Returns
    None if nothing usable was found - a missed OCR read on a given frame,
    which the caller should treat as "no new information" (hold the last
    known value) rather than snapping to 0."""
    ratio_match = _RATIO_PATTERN.search(text)
    if ratio_match:
        current = float(ratio_match.group(1).replace(",", "."))
        maximum = float(ratio_match.group(2).replace(",", "."))
        if maximum > 0:
            return max(0.0, min(1.0, current / maximum))
        return None

    percent_match = _PERCENT_PATTERN.search(text)
    if percent_match:
        value = float(percent_match.group(1).replace(",", "."))
        return max(0.0, min(1.0, value / 100.0))

    if max_value:
        number_match = _NUMBER_PATTERN.search(text)
        if number_match:
            value = float(number_match.group(0).replace(",", "."))
            return max(0.0, min(1.0, value / max_value))

    return None
