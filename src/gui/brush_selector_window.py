"""Full-monitor overlay for painting an irregular watched-region mask with an
adjustable brush - Gaming Mode's built-in watcher and the Trigger Editor's
custom watchers both use this instead of RegionSelectorWindow's rectangle
drag, since a health/mana bar is often thin, curved, or oddly shaped (a bent
arc, a diagonal sliver) that a plain rectangle can't isolate well from
whatever's around it. Ambience Mode's own "Set area"/multi-region position
pickers stay rectangle-based - those pick a screen zone for colour mood, not
a bar shape, so a rectangle is exactly right there.

Same semi-transparent, click-through overlay approach as RegionSelectorWindow
(the real desktop shows through the window's own low alpha - no screenshot
capture needed). The mask itself is a plain numpy boolean array (the actual
source of truth, sized to the full monitor while painting); the visible pink
tint is a fresh PPM-encoded render of it after each completed stroke, using
the same "no PIL, raw PPM PhotoImage" technique as colour_picker_window.py's
gradient. During an active drag, a lightweight canvas line tracks the stroke
in real time instead of re-rendering the mask on every mouse-move - only
committed (stamped into the mask, then rendered) once the stroke ends, which
keeps dragging itself smooth regardless of the mask's full-monitor size.
"""
from __future__ import annotations

import tkinter
from typing import Callable

import customtkinter as ctk
import numpy as np

from src.gui import theme

BRUSH_MIN_RADIUS = 3
BRUSH_MAX_RADIUS = 60
BRUSH_DEFAULT_RADIUS = 15
OVERLAY_ALPHA = 0.35  # a bit stronger than RegionSelectorWindow's 0.25 - the painted
                      # fill needs to read clearly against the real screen showing through
PAINT_COLOR_HEX = theme.PRIMARY[1]  # this overlay is always dark-styled, like RegionSelectorWindow's
PAINT_COLOR_RGB = (255, 45, 145)    # the same colour as PAINT_COLOR_HEX (#FF2D91), as RGB ints for the mask render


def _stamp_circle(mask: np.ndarray, cx: int, cy: int, radius: int, value: bool) -> None:
    """Mark (or clear) a filled circle in mask, clipped to its bounds. Only
    touches the circle's own small bounding box via array slicing, not the
    whole array, so this stays fast even on a full-monitor-sized mask."""
    height, width = mask.shape
    x0, x1 = max(0, cx - radius), min(width, cx + radius + 1)
    y0, y1 = max(0, cy - radius), min(height, cy + radius + 1)
    if x0 >= x1 or y0 >= y1:
        return
    ys, xs = np.ogrid[y0:y1, x0:x1]
    circle = (xs - cx) ** 2 + (ys - cy) ** 2 <= radius * radius
    mask[y0:y1, x0:x1][circle] = value


def _stamp_stroke(mask: np.ndarray, points: list[tuple[int, int]], radius: int, value: bool) -> None:
    """Stamp circles along every segment of points (one recorded drag path),
    interpolating between consecutive points so a fast mouse movement doesn't
    leave gaps in the stroke."""
    if not points:
        return
    _stamp_circle(mask, points[0][0], points[0][1], radius, value)
    step = max(1, radius // 2)
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        distance = max(abs(x1 - x0), abs(y1 - y0), 1)
        steps = max(1, distance // step)
        for i in range(1, steps + 1):
            t = i / steps
            _stamp_circle(mask, int(round(x0 + (x1 - x0) * t)), int(round(y0 + (y1 - y0) * t)), radius, value)


def _mask_to_photo_image(mask: np.ndarray) -> tkinter.PhotoImage:
    """Black everywhere, solid pink where mask is True - combined with the
    overlay window's own low alpha, this reads as a translucent pink tint over
    the real screen showing through, the filled equivalent of
    RegionSelectorWindow's rectangle outline. Raw PPM bytes, no PIL - see
    colour_picker_window.py's gradient render for the same technique."""
    height, width = mask.shape
    rgb = np.zeros((height, width, 3), dtype=np.uint8)
    rgb[mask] = PAINT_COLOR_RGB
    header = f"P6 {width} {height} 255 ".encode("ascii")
    return tkinter.PhotoImage(width=width, height=height, data=header + rgb.tobytes(), format="PPM")


class BrushSelectorWindow(ctk.CTkToplevel):
    """Paint an irregular mask anywhere on the given monitor; on confirm,
    on_select is called with (x, y, width, height, mask) - x/y/width/height
    are the tight bounding box of everything painted (relative to the
    monitor's own top-left, matching ScreenCapture/ambience_config's existing
    convention), mask is a bool array of shape (height, width) cropped to
    that same box. Escape cancels without calling on_select; Confirm does
    nothing if nothing has been painted yet."""

    def __init__(self, master: ctk.CTk, monitor: dict,
                 on_select: Callable[[int, int, int, int, np.ndarray], None]):
        super().__init__(master)
        self._on_select = on_select
        self._mask = np.zeros((monitor["height"], monitor["width"]), dtype=bool)
        self._brush_radius = BRUSH_DEFAULT_RADIUS
        self._eraser = False
        self._stroke_points: list[tuple[int, int]] = []
        self._stroke_line_id: int | None = None
        self._mask_image: tkinter.PhotoImage | None = None
        self._mask_image_id: int | None = None

        self.overrideredirect(True)
        self.geometry(f"{monitor['width']}x{monitor['height']}+{monitor['left']}+{monitor['top']}")
        self.attributes("-topmost", True)
        self.attributes("-alpha", OVERLAY_ALPHA)
        self.configure(cursor="crosshair")

        self.canvas = tkinter.Canvas(self, bg="black", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_text(
            monitor["width"] / 2, 30, text="Paint the watched area - Enter to confirm, Esc to cancel",
            fill="white", font=("", 14),
        )

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Escape>", lambda event: self._cancel())
        self.bind("<Return>", lambda event: self._confirm())

        self._build_controls()
        self.after(50, self._make_modal)

    def _make_modal(self) -> None:
        self.grab_set()
        self.focus_force()

    def _build_controls(self) -> None:
        """A small floating panel (brush size, eraser, clear, confirm) -
        created after the canvas so it stacks visually on top of it (see
        MainWindow's gear-button comment for why creation order matters for
        place()d overlay widgets)."""
        panel = ctk.CTkFrame(self, fg_color=("gray85", "gray17"))
        panel.place(relx=0.5, y=60, anchor="n")

        ctk.CTkLabel(panel, text="Brush size").grid(
            row=0, column=0, columnspan=2, padx=theme.SPACE_SM, pady=(theme.SPACE_SM, 0)
        )
        self.brush_slider = ctk.CTkSlider(
            panel, from_=BRUSH_MIN_RADIUS, to=BRUSH_MAX_RADIUS, number_of_steps=BRUSH_MAX_RADIUS - BRUSH_MIN_RADIUS,
            width=140, command=self._on_brush_size_change,
        )
        self.brush_slider.set(BRUSH_DEFAULT_RADIUS)
        self.brush_slider.grid(row=1, column=0, columnspan=2, padx=theme.SPACE_SM, pady=(0, theme.SPACE_SM))

        self.eraser_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(panel, text="Eraser", variable=self.eraser_var, command=self._on_eraser_toggle).grid(
            row=2, column=0, columnspan=2, padx=theme.SPACE_SM, pady=(0, theme.SPACE_SM)
        )

        ctk.CTkButton(
            panel, text="Clear", width=90, fg_color=theme.SECONDARY_BUTTON_COLOR,
            hover_color=theme.SECONDARY_BUTTON_HOVER_COLOR, command=self._on_clear_click,
        ).grid(row=3, column=0, padx=(theme.SPACE_SM, 4), pady=(0, theme.SPACE_SM))
        ctk.CTkButton(panel, text="Confirm", width=90, command=self._confirm).grid(
            row=3, column=1, padx=(4, theme.SPACE_SM), pady=(0, theme.SPACE_SM)
        )

    def _on_brush_size_change(self, value: float) -> None:
        self._brush_radius = int(round(value))

    def _on_eraser_toggle(self) -> None:
        self._eraser = self.eraser_var.get()

    def _on_clear_click(self) -> None:
        self._mask[:] = False
        self._redraw_mask_image()

    def _on_press(self, event: tkinter.Event) -> None:
        self._stroke_points = [(event.x, event.y)]
        colour = theme.SECONDARY_BUTTON_COLOR[1] if self._eraser else PAINT_COLOR_HEX
        self._stroke_line_id = self.canvas.create_line(
            event.x, event.y, event.x, event.y,
            fill=colour, width=self._brush_radius * 2, capstyle="round", joinstyle="round",
        )

    def _on_drag(self, event: tkinter.Event) -> None:
        if self._stroke_line_id is None:
            return
        self._stroke_points.append((event.x, event.y))
        coords = [coord for point in self._stroke_points for coord in point]
        self.canvas.coords(self._stroke_line_id, *coords)

    def _on_release(self, event: tkinter.Event) -> None:
        if self._stroke_line_id is None:
            return
        self.canvas.delete(self._stroke_line_id)
        self._stroke_line_id = None
        _stamp_stroke(self._mask, self._stroke_points, self._brush_radius, value=not self._eraser)
        self._stroke_points = []
        self._redraw_mask_image()

    def _redraw_mask_image(self) -> None:
        self._mask_image = _mask_to_photo_image(self._mask)
        if self._mask_image_id is not None:
            self.canvas.delete(self._mask_image_id)
        self._mask_image_id = self.canvas.create_image(0, 0, anchor="nw", image=self._mask_image)
        self.canvas.tag_lower(self._mask_image_id)  # stay behind the instructions text and any live stroke

    def _confirm(self) -> None:
        if not np.any(self._mask):
            return  # nothing painted yet - matches RegionSelectorWindow's MIN_SELECTION_SIZE guard
        rows = np.any(self._mask, axis=1)
        cols = np.any(self._mask, axis=0)
        y0, y1 = np.where(rows)[0][[0, -1]]
        x0, x1 = np.where(cols)[0][[0, -1]]
        cropped = self._mask[y0:y1 + 1, x0:x1 + 1]
        self.destroy()
        self._on_select(int(x0), int(y0), int(x1 - x0 + 1), int(y1 - y0 + 1), cropped)

    def _cancel(self) -> None:
        self.destroy()
