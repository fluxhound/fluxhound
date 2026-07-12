"""Full-monitor overlay for drag-selecting a screen region (Ambience Mode's
"Set area" button).

A borderless, topmost, semi-transparent Toplevel positioned to exactly cover one
monitor's physical pixel bounds (see src/screen/capture.py's list_monitors). Lining
that up with mss's own physical-pixel coordinates depends on the app being marked
per-monitor DPI aware (src/main.py's _enable_dpi_awareness) - without it, Windows'
DPI virtualization would shift where this overlay actually appears relative to what
mss captures whenever display scaling isn't 100%.
"""
from __future__ import annotations

import tkinter
from typing import Callable

import customtkinter as ctk

SELECTION_COLOR = "#2563eb"
OVERLAY_ALPHA = 0.25
MIN_SELECTION_SIZE = 5  # ignore accidental clicks/near-zero drags


class RegionSelectorWindow(ctk.CTkToplevel):
    """Drag a rectangle anywhere on the given monitor; on release, on_select is
    called with (x, y, width, height) relative to that monitor's own top-left
    (matching what ScreenCapture(region=...) and ambience_config.py expect - not
    the full virtual desktop). Escape cancels without calling on_select."""

    def __init__(self, master: ctk.CTk, monitor: dict, on_select: Callable[[int, int, int, int], None]):
        super().__init__(master)
        self._on_select = on_select
        self._start_x: int | None = None
        self._start_y: int | None = None
        self._rect_id: int | None = None

        self.overrideredirect(True)
        self.geometry(f"{monitor['width']}x{monitor['height']}+{monitor['left']}+{monitor['top']}")
        self.attributes("-topmost", True)
        self.attributes("-alpha", OVERLAY_ALPHA)
        self.configure(cursor="crosshair")

        self.canvas = tkinter.Canvas(self, bg="black", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_text(
            monitor["width"] / 2, 40, text="Drag to select an area - Esc to cancel",
            fill="white", font=("", 14),
        )

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Escape>", lambda event: self._cancel())

        self.after(50, self._make_modal)

    def _make_modal(self) -> None:
        self.grab_set()
        self.focus_force()

    def _on_press(self, event: tkinter.Event) -> None:
        self._start_x, self._start_y = event.x, event.y
        self._rect_id = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y, outline=SELECTION_COLOR, width=2
        )

    def _on_drag(self, event: tkinter.Event) -> None:
        if self._rect_id is not None:
            self.canvas.coords(self._rect_id, self._start_x, self._start_y, event.x, event.y)

    def _on_release(self, event: tkinter.Event) -> None:
        if self._start_x is None or self._start_y is None:
            return
        x0, y0, x1, y1 = self._start_x, self._start_y, event.x, event.y
        x, y = min(x0, x1), min(y0, y1)
        width, height = abs(x1 - x0), abs(y1 - y0)
        self.destroy()
        if width >= MIN_SELECTION_SIZE and height >= MIN_SELECTION_SIZE:
            self._on_select(x, y, width, height)

    def _cancel(self) -> None:
        self.destroy()
