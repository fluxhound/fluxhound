"""Screen capture via mss - fast, no GUI-toolkit dependency, and (unlike a plain
full-resolution grab) cheap enough to call repeatedly from Ambience Mode's hot loop.

mss was chosen with an eye toward a planned follow-up: analysing individual screen
regions separately (e.g. to drive a merged group's positioned bulbs from different
parts of the screen) rather than just one overall average - mss's per-monitor and
arbitrary-region grabs make that a natural extension later.
"""
from __future__ import annotations

import mss
import numpy as np

DEFAULT_DOWNSAMPLE_WIDTH = 160


class ScreenCapture:
    """Grabs one monitor (the primary one, if mss can tell) and returns it as a
    small downsampled RGB array, so per-frame colour analysis stays cheap even at a
    high capture rate."""

    def __init__(self, downsample_width: int = DEFAULT_DOWNSAMPLE_WIDTH):
        self._sct = mss.MSS()
        self._monitor = self._select_monitor()
        self._downsample_width = downsample_width

    def _select_monitor(self) -> dict:
        # monitors[0] is the bounding box of *all* monitors combined; individual
        # monitors start at index 1. Prefer whichever one mss flags as primary.
        candidates = self._sct.monitors[1:] or self._sct.monitors
        for monitor in candidates:
            if monitor.get("is_primary"):
                return monitor
        return candidates[0]

    def grab_rgb(self) -> np.ndarray:
        """Return an (H, W, 3) uint8 RGB array, downsampled to roughly
        downsample_width pixels wide (aspect ratio preserved via simple striding)."""
        shot = self._sct.grab(self._monitor)
        frame = np.asarray(shot)[:, :, :3][:, :, ::-1]  # mss gives BGRA; drop A, reverse to RGB
        width = frame.shape[1]
        if width > self._downsample_width:
            step = max(1, width // self._downsample_width)
            frame = frame[::step, ::step]
        return frame

    def close(self) -> None:
        self._sct.close()
