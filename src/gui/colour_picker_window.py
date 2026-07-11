"""A draggable, non-modal colour-picker popup.

Lets the user pick a colour either by clicking/dragging on the
saturation/value gradient (tinted by the hue slider below it), or by
typing an exact value into the hex or R/G/B fields. Every interaction
applies live via `on_pick(hue, saturation, value)` (hue 0-360,
saturation/value 0-1000, matching the Tuya colour_data scale), debounced
the same way sliders elsewhere in this app are, so dragging doesn't
flood the bulb with requests.

The gradient is rendered with a `tkinter.PhotoImage` built from raw PPM
bytes (a numpy-vectorized HSV->RGB conversion, no per-pixel Python
loop) - fast enough to redraw on every hue-slider tick without lag, and
needs no extra dependency (PPM loading is a built-in Tk image format,
unlike CTkImage which needs Pillow - not currently a dependency here).
"""
from __future__ import annotations

import colorsys
import tkinter
from typing import Callable

import customtkinter as ctk
import numpy as np

GRADIENT_SIZE = 220
DEBOUNCE_MS = 120
INDICATOR_RADIUS = 6


def _hsv_to_rgb255(hue_deg: float, saturation: float, value: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb((hue_deg % 360) / 360.0, saturation, value)
    return int(round(r * 255)), int(round(g * 255)), int(round(b * 255))


def _rgb255_to_hsv(r: int, g: int, b: int) -> tuple[float, float, float]:
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    return h * 360.0, s, v


def _render_gradient_image(hue_deg: float, size: int) -> tkinter.PhotoImage:
    """Saturation increases left->right, value increases bottom->top, tinted by a single
    fixed hue (hue doesn't vary across the grid, only along the separate hue slider)."""
    sat = np.linspace(0.0, 1.0, size)
    val = np.linspace(1.0, 0.0, size)
    s_grid, v_grid = np.meshgrid(sat, val)

    h = (hue_deg % 360) / 360.0
    sector = int(h * 6.0) % 6
    fraction = h * 6.0 - int(h * 6.0)
    p = v_grid * (1 - s_grid)
    q = v_grid * (1 - fraction * s_grid)
    t = v_grid * (1 - (1 - fraction) * s_grid)
    # HSV->RGB sector table; hue is scalar for the whole grid so only one variant applies.
    variants = [
        (v_grid, t, p), (q, v_grid, p), (p, v_grid, t),
        (p, q, v_grid), (t, p, v_grid), (v_grid, p, q),
    ]
    r_grid, g_grid, b_grid = variants[sector]

    rgb = np.stack([r_grid, g_grid, b_grid], axis=-1)
    rgb_bytes = (np.clip(rgb, 0.0, 1.0) * 255).astype(np.uint8)
    header = f"P6 {size} {size} 255 ".encode("ascii")
    return tkinter.PhotoImage(width=size, height=size, data=header + rgb_bytes.tobytes(), format="PPM")


class ColourPickerWindow(ctk.CTkToplevel):
    """Non-modal, freely movable (standard OS title bar drag) colour picker."""

    def __init__(self, master: ctk.CTk, initial_hue: int, initial_saturation: int, initial_value: int,
                 on_pick: Callable[[int, int, int], None]):
        super().__init__(master)
        self._on_pick = on_pick
        self._hue = float(initial_hue)
        self._saturation = max(0.0, min(1.0, initial_saturation / 1000.0))
        self._value = max(0.0, min(1.0, initial_value / 1000.0))
        self._debounce_id: str | None = None
        self._gradient_image: tkinter.PhotoImage | None = None
        self._updating_entries = False  # guards against feedback loops while syncing text fields

        self.title("Colour Picker")
        self.resizable(False, False)

        self.canvas = tkinter.Canvas(
            self, width=GRADIENT_SIZE, height=GRADIENT_SIZE, highlightthickness=0, cursor="crosshair"
        )
        self.canvas.pack(padx=16, pady=(16, 8))
        self.canvas.bind("<Button-1>", self._on_canvas_interact)
        self.canvas.bind("<B1-Motion>", self._on_canvas_interact)

        self.hue_slider = ctk.CTkSlider(self, from_=0, to=359, number_of_steps=359, command=self._on_hue_slider)
        self.hue_slider.set(self._hue)
        self.hue_slider.pack(padx=16, pady=(0, 12), fill="x")

        entries_frame = ctk.CTkFrame(self, fg_color="transparent")
        entries_frame.pack(padx=16, pady=(0, 16))

        ctk.CTkLabel(entries_frame, text="Hex").grid(row=0, column=0, padx=(0, 6), pady=4, sticky="w")
        self.hex_entry = ctk.CTkEntry(entries_frame, width=90)
        self.hex_entry.grid(row=0, column=1, padx=(0, 16), pady=4)
        self.hex_entry.bind("<Return>", self._on_hex_entered)
        self.hex_entry.bind("<FocusOut>", self._on_hex_entered)

        self._rgb_entries: dict[str, ctk.CTkEntry] = {}
        for column, label in enumerate(("R", "G", "B")):
            ctk.CTkLabel(entries_frame, text=label).grid(row=0, column=2 + column * 2, padx=(0, 4), pady=4)
            entry = ctk.CTkEntry(entries_frame, width=44)
            entry.grid(row=0, column=3 + column * 2, padx=(0, 8), pady=4)
            entry.bind("<Return>", self._on_rgb_entered)
            entry.bind("<FocusOut>", self._on_rgb_entered)
            self._rgb_entries[label] = entry

        self._render_gradient()
        self._sync_entries()

    # -- Gradient + indicator -----------------------------------------------------

    def _indicator_position(self) -> tuple[float, float]:
        x = self._saturation * (GRADIENT_SIZE - 1)
        y = (1.0 - self._value) * (GRADIENT_SIZE - 1)
        return x, y

    def _indicator_outline_colour(self) -> str:
        # A dark indicator ring is hard to see over a dark (low-value) area, and vice versa.
        return "white" if self._value < 0.6 else "black"

    def _render_gradient(self) -> None:
        self._gradient_image = _render_gradient_image(self._hue, GRADIENT_SIZE)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._gradient_image)
        x, y = self._indicator_position()
        self.canvas.create_oval(
            x - INDICATOR_RADIUS, y - INDICATOR_RADIUS, x + INDICATOR_RADIUS, y + INDICATOR_RADIUS,
            outline=self._indicator_outline_colour(), width=2, tags="indicator",
        )

    def _move_indicator(self) -> None:
        x, y = self._indicator_position()
        self.canvas.coords(
            "indicator", x - INDICATOR_RADIUS, y - INDICATOR_RADIUS, x + INDICATOR_RADIUS, y + INDICATOR_RADIUS
        )
        self.canvas.itemconfigure("indicator", outline=self._indicator_outline_colour())

    # -- Interaction ---------------------------------------------------------------

    def _on_canvas_interact(self, event: tkinter.Event) -> None:
        x = max(0, min(GRADIENT_SIZE - 1, event.x))
        y = max(0, min(GRADIENT_SIZE - 1, event.y))
        self._saturation = x / (GRADIENT_SIZE - 1)
        self._value = 1.0 - y / (GRADIENT_SIZE - 1)
        self._move_indicator()
        self._sync_entries()
        self._schedule_pick()

    def _on_hue_slider(self, value: float) -> None:
        self._hue = value
        self._render_gradient()
        self._sync_entries()
        self._schedule_pick()

    def _schedule_pick(self) -> None:
        if self._debounce_id is not None:
            self.after_cancel(self._debounce_id)
        self._debounce_id = self.after(DEBOUNCE_MS, self._fire_pick)

    def _fire_pick(self) -> None:
        self._debounce_id = None
        hue = int(round(self._hue)) % 360
        saturation = int(round(self._saturation * 1000))
        value = int(round(self._value * 1000))
        self._on_pick(hue, saturation, value)

    # -- Text entries ----------------------------------------------------------------

    def _sync_entries(self) -> None:
        """Reflect the current hue/saturation/value onto the hex and R/G/B fields,
        without re-triggering their own change handlers."""
        if self._updating_entries:
            return
        self._updating_entries = True
        try:
            r, g, b = _hsv_to_rgb255(self._hue, self._saturation, self._value)
            self.hex_entry.delete(0, "end")
            self.hex_entry.insert(0, f"{r:02X}{g:02X}{b:02X}")
            for label, channel in zip(("R", "G", "B"), (r, g, b)):
                entry = self._rgb_entries[label]
                entry.delete(0, "end")
                entry.insert(0, str(channel))
        finally:
            self._updating_entries = False

    def _apply_rgb(self, r: int, g: int, b: int) -> None:
        r, g, b = max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))
        self._hue, self._saturation, self._value = _rgb255_to_hsv(r, g, b)
        self.hue_slider.set(self._hue)
        self._render_gradient()
        self._sync_entries()
        self._schedule_pick()

    def _on_hex_entered(self, event: tkinter.Event | None = None) -> None:
        if self._updating_entries:
            return
        text = self.hex_entry.get().strip().lstrip("#")
        if len(text) != 6:
            return
        try:
            r, g, b = int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
        except ValueError:
            return
        self._apply_rgb(r, g, b)

    def _on_rgb_entered(self, event: tkinter.Event | None = None) -> None:
        if self._updating_entries:
            return
        try:
            r = int(self._rgb_entries["R"].get())
            g = int(self._rgb_entries["G"].get())
            b = int(self._rgb_entries["B"].get())
        except ValueError:
            return
        self._apply_rgb(r, g, b)
