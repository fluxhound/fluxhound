"""Screen capture via mss - fast, no GUI-toolkit dependency, and (unlike a plain
full-resolution grab) cheap enough to call repeatedly from Ambience Mode's hot loop.

mss was chosen with an eye toward a planned follow-up: analysing individual screen
regions separately (e.g. to drive a merged group's positioned bulbs from different
parts of the screen) rather than just one overall average - mss's per-monitor and
arbitrary-region grabs make that a natural extension later. The region support here
(watch a hand-picked rectangle of one monitor instead of the whole thing) is the
first step in that direction.
"""
from __future__ import annotations

import mss
import numpy as np

DEFAULT_DOWNSAMPLE_WIDTH = 160


def list_monitors() -> list[dict]:
    """Every individual monitor mss can see (excludes index 0, its "all monitors
    combined" bounding box), each augmented with its own 1-based "index" - the same
    numbering ScreenCapture(monitor_index=...) and ambience_config.py expect."""
    with mss.MSS() as sct:
        monitors = []
        for i, monitor in enumerate(sct.monitors[1:], start=1):
            monitors.append({**monitor, "index": i})
        return monitors


class ScreenCapture:
    """Grabs one monitor - or a fixed sub-region of it - and returns it as a small
    downsampled RGB array, so per-frame colour analysis stays cheap even at a high
    capture rate.

    monitor_index follows mss's own 1-based numbering (see list_monitors); 0 (or any
    index that no longer exists, e.g. a monitor that's since been unplugged) falls
    back to auto-picking whichever monitor mss flags as primary. region, if given, is
    (x, y, width, height) in pixels relative to the chosen monitor's own top-left,
    not the full virtual desktop.
    """

    def __init__(self, monitor_index: int = 0, region: tuple[int, int, int, int] | None = None,
                 downsample_width: int = DEFAULT_DOWNSAMPLE_WIDTH):
        self._sct = mss.MSS()
        self._monitor = self._select_monitor(monitor_index)
        self._grab_area = self._resolve_grab_area(self._monitor, region)
        self._downsample_width = downsample_width

    def _select_monitor(self, monitor_index: int) -> dict:
        # monitors[0] is the bounding box of *all* monitors combined; individual
        # monitors start at index 1, matching monitor_index's own numbering.
        candidates = self._sct.monitors[1:] or self._sct.monitors
        if 1 <= monitor_index <= len(candidates):
            return candidates[monitor_index - 1]
        for monitor in candidates:
            if monitor.get("is_primary"):
                return monitor
        return candidates[0]

    @staticmethod
    def _resolve_grab_area(monitor: dict, region: tuple[int, int, int, int] | None) -> dict:
        if region is None:
            return monitor
        x, y, width, height = region
        return {
            "left": monitor["left"] + x, "top": monitor["top"] + y,
            "width": max(1, width), "height": max(1, height),
        }

    def grab_rgb(self) -> np.ndarray:
        """Return an (H, W, 3) uint8 RGB array, downsampled to roughly
        downsample_width pixels wide (aspect ratio preserved via simple striding)."""
        shot = self._sct.grab(self._grab_area)
        frame = np.asarray(shot)[:, :, :3][:, :, ::-1]  # mss gives BGRA; drop A, reverse to RGB
        width = frame.shape[1]
        if width > self._downsample_width:
            step = max(1, width // self._downsample_width)
            frame = frame[::step, ::step]
        return frame

    def close(self) -> None:
        self._sct.close()
