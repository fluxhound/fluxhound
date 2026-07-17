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
# A bare decimal already *is* a complete 0-1 (or 0-100%, written as 0-1) reading
# on its own - some HUDs/mods show a raw progress value like "0.79" directly,
# no ratio or percent sign attached. The integer part is restricted to exactly
# "0" or "1" (or omitted, e.g. ".79") specifically so this can never accidentally
# swallow the tail of an unrelated number - "79.100" (e.g. a misread "79/100"
# where OCR mistook the slash for a period) has integer part "79", not 0 or 1,
# so it correctly falls through to returning None instead of misreading it as
# 0.1. The lookaround assertions block matching a decimal point that's actually
# part of a *different* number's own decimal or thousands separator.
_DECIMAL_FRACTION_PATTERN = re.compile(r"(?<!\d)(0[.,]\d+|1[.,]0+|[.,]\d+)(?!\d)")
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


# Watched regions are often tightly painted right up against the digits (or,
# in auto/ocr mode, blanked to black right up to the mask edge) - a text
# *detector* (as opposed to the recognizer that reads an already-located
# line) needs some surrounding context to place a bounding box correctly,
# and a real "40" frame with zero margin was detected as *no text at all*,
# despite being perfectly legible to a human and reading fine once even a
# modest border was added. Matches OCR_MASK_FILL_COLOUR (health_bar.py) so
# the border is indistinguishable from whatever the mask already blanked.
_OCR_PADDING_MARGIN_PX = 20
_OCR_PADDING_COLOUR = 0


def _normalize_for_ocr(frame: np.ndarray) -> np.ndarray:
    """Pad with a plain black border, then grayscale + min-max contrast
    stretch, before handing a frame to the OCR engine - both steps are real,
    separate fixes for two different real reports, each confirmed by testing
    several alternatives directly against the actual failing frame rather
    than guessing:

    Padding: a real "40" frame, cropped with essentially no margin around a
    rounded HUD panel's edge, was detected as *no text at all* - the
    detector needs surrounding context to place a bounding box, even though
    the digits themselves were nowhere near the crop edge. A plain
    _OCR_PADDING_MARGIN_PX border (any of 10/20/30px tested worked; 20 is a
    middle-of-the-road choice, not the exact minimum needed) fixed it
    immediately, no other change required, confirmed against two different
    real frames plus no regression on an already-working synthetic case.

    Grayscale + contrast stretch: a separate real "64" frame (ample margin
    already, so not the same failure) failed to read at every resolution
    tried (native through 6x upscale, ruling out resolution as the cause)
    until converted to grayscale and contrast-stretched - reproduced 5/5
    real-engine runs, no regression on the same synthetic case. Grayscale
    strips colour noise while keeping the luminance edges that define
    character shapes; the linear stretch just widens whatever (possibly
    narrow) brightness range the digits already used to fill 0-255 - it
    can't invent detail that isn't there, so it's safe even on a frame with
    nothing to gain (a fully uniform/flat frame degrades gracefully too, see
    tests/test_ocr_reader.py)."""
    import cv2  # already a transitive rapidocr dependency, no new one added

    height, width = frame.shape[:2]
    margin = _OCR_PADDING_MARGIN_PX
    padded = np.full((height + margin * 2, width + margin * 2, 3), _OCR_PADDING_COLOUR, dtype=np.uint8)
    padded[margin:margin + height, margin:margin + width] = frame

    gray = cv2.cvtColor(padded, cv2.COLOR_RGB2GRAY)
    stretched = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    return cv2.cvtColor(stretched, cv2.COLOR_GRAY2RGB)


def read_text(frame: np.ndarray) -> str:
    """Run OCR on one captured frame, returning every recognized text line
    joined by spaces (empty string if nothing was recognized)."""
    engine = _get_engine()
    result, _elapse = engine(_normalize_for_ocr(frame))
    if not result:
        return ""
    return " ".join(line[1] for line in result)


def parse_fraction(text: str, max_value: float | None) -> float | None:
    """Extract a 0-1 fraction from OCR'd text, auto-detecting which of four
    display styles is present - no per-watcher "format" choice needed beyond
    the optional max_value fallback. In priority order: "X/Y" (most reliable -
    the ratio is given directly, and wins even if a redundant "%" or a second,
    unrelated "X/Y" also appears later in the same text - e.g. "79/100 (79%)"
    or "HP 79/100 MP 45/60" both correctly read the first ratio); then "X%";
    then a bare decimal between 0 and 1 (already a complete reading by itself,
    e.g. "0.79" - see _DECIMAL_FRACTION_PATTERN); then finally a bare number
    normalized against max_value if one was configured. Returns None if
    nothing usable was found - a missed OCR read on a given frame, which the
    caller should treat as "no new information" (hold the last known value)
    rather than snapping to 0."""
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

    decimal_match = _DECIMAL_FRACTION_PATTERN.search(text)
    if decimal_match:
        group = decimal_match.group(1)
        value = float(("0" if group[0] in ".," else "") + group.replace(",", "."))
        if 0.0 <= value <= 1.0:
            return value

    if max_value:
        number_match = _NUMBER_PATTERN.search(text)
        if number_match:
            value = float(number_match.group(0).replace(",", "."))
            return max(0.0, min(1.0, value / max_value))

    return None
