"""Main application window (customtkinter)."""
from __future__ import annotations

import colorsys
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import customtkinter as ctk

from src import device_config
from src.device_config import DeviceConfig
from src.gui.device_config_dialog import DeviceConfigDialog
from src.tuya.device import DP_SWITCH, TuyaBulb, TuyaConnectionError

# Predefined colour palette: name -> (hue 0-360, saturation 0-1000, value 0-1000)
COLOUR_PALETTE: list[tuple[str, tuple[int, int, int]]] = [
    ("Red", (0, 1000, 1000)),
    ("Orange", (30, 1000, 1000)),
    ("Yellow", (60, 1000, 1000)),
    ("Green", (120, 1000, 1000)),
    ("Cyan", (180, 1000, 1000)),
    ("Blue", (240, 1000, 1000)),
    ("Purple", (280, 1000, 1000)),
    ("Pink", (320, 1000, 1000)),
]

SLIDER_DEBOUNCE_MS = 150
NORMAL_TEXT_COLOR = ("gray10", "gray90")
ERROR_TEXT_COLOR = ("#b91c1c", "#f87171")


def _hue_to_hex(hue: int) -> str:
    """Convert a hue (0-360) at full saturation/value to a #rrggbb string for swatch previews."""
    r, g, b = colorsys.hsv_to_rgb(hue / 360, 1.0, 1.0)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


class MainWindow(ctk.CTk):
    """FluxHound main window: manual control (on/off, brightness, colour) of one test bulb."""

    def __init__(self):
        super().__init__()
        self.bulb: TuyaBulb | None = None
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._slider_after_id: str | None = None

        self.title("FluxHound")
        self.geometry("420x420")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.status_label = ctk.CTkLabel(self, text="", wraplength=380)
        self.status_label.pack(pady=(16, 4))

        self.configure_button = ctk.CTkButton(
            self, text="Change device", width=140, command=self._on_configure_click
        )
        self.configure_button.pack(pady=(0, 12))

        self.power_var = ctk.BooleanVar(value=False)
        self.power_switch = ctk.CTkSwitch(
            self, text="Power", variable=self.power_var, command=self._on_power_toggle
        )
        self.power_switch.pack(pady=8)

        ctk.CTkLabel(self, text="Brightness").pack(pady=(12, 0))
        self.brightness_slider = ctk.CTkSlider(
            self, from_=10, to=1000, number_of_steps=99, command=self._on_brightness_change
        )
        self.brightness_slider.set(1000)
        self.brightness_slider.pack(padx=24, pady=(4, 12), fill="x")

        ctk.CTkLabel(self, text="Colour").pack(pady=(4, 4))
        self.palette_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.palette_frame.pack(pady=(0, 12))
        for column, (name, hsv) in enumerate(COLOUR_PALETTE):
            hue = hsv[0]
            swatch_color = _hue_to_hex(hue)
            swatch = ctk.CTkButton(
                self.palette_frame, text="", width=32, height=32, corner_radius=16,
                fg_color=swatch_color, hover_color=swatch_color,
                command=lambda hsv=hsv: self._on_colour_pick(hsv),
            )
            swatch.grid(row=0, column=column, padx=4)

        self._set_controls_enabled(False)
        self._load_or_prompt_device_config()

    # -- Device configuration -------------------------------------------------

    def _load_or_prompt_device_config(self) -> None:
        """On startup: connect if a device is already registered, else ask for it."""
        config = device_config.load()
        if config is None:
            self._set_status("No device configured", error=True)
            self.after(50, lambda: self._open_config_dialog(existing=None))
        else:
            self._apply_config(config)

    def _on_configure_click(self) -> None:
        """Handle the 'Change device' button: reopen the dialog, pre-filled if possible."""
        self._open_config_dialog(existing=device_config.load())

    def _open_config_dialog(self, existing: DeviceConfig | None) -> None:
        DeviceConfigDialog(self, on_save=self._apply_config, existing=existing)

    def _apply_config(self, config: DeviceConfig) -> None:
        """Persist a (new or edited) device config and (re)connect to it."""
        device_config.save(config)
        self.bulb = TuyaBulb(
            config.device_id, config.ip_address, config.local_key, version=config.protocol_version
        )
        self._set_controls_enabled(True)
        self._set_status("Connecting...")
        self._run_async(self.bulb.status, on_success=self._on_initial_status)

    def _on_initial_status(self, status: dict) -> None:
        """Sync the power switch to the bulb's actual state instead of assuming 'off'."""
        self._set_status("Connected")
        is_on = bool(status.get("dps", {}).get(DP_SWITCH, False))
        self.power_var.set(is_on)

    # -- Controls ---------------------------------------------------------------

    def _set_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable the bulb controls, e.g. when no device is configured."""
        state = "normal" if enabled else "disabled"
        self.power_switch.configure(state=state)
        self.brightness_slider.configure(state=state)
        for swatch in self.palette_frame.winfo_children():
            swatch.configure(state=state)

    def _set_status(self, text: str, error: bool = False) -> None:
        """Update the status label, in the error colour if `error` is set."""
        self.status_label.configure(text=text, text_color=ERROR_TEXT_COLOR if error else NORMAL_TEXT_COLOR)

    def _run_async(self, fn: Callable[..., Any], *args: Any,
                    on_success: Callable[[Any], None] | None = None) -> None:
        """Run a (possibly slow, network-blocking) bulb call off the UI thread.

        Results and errors are marshalled back onto the Tk main thread via
        `after(0, ...)`, since customtkinter widgets aren't thread-safe.
        """
        def task() -> None:
            try:
                result = fn(*args)
            except TuyaConnectionError as exc:
                message = f"Lamp unreachable: {exc}"
                self.after(0, lambda: self._set_status(message, error=True))
                return
            if on_success is not None:
                self.after(0, lambda: on_success(result))

        self._executor.submit(task)

    def _on_power_toggle(self) -> None:
        """Handle a click on the power switch."""
        on = self.power_var.get()
        action = self.bulb.turn_on if on else self.bulb.turn_off
        self._set_status("Switching on..." if on else "Switching off...")
        self._run_async(action, on_success=lambda _: self._set_status("Connected"))

    def _on_brightness_change(self, value: float) -> None:
        """Handle a slider move: debounce so dragging doesn't flood the bulb with requests."""
        if self._slider_after_id is not None:
            self.after_cancel(self._slider_after_id)
        brightness = int(value)
        self._slider_after_id = self.after(SLIDER_DEBOUNCE_MS, lambda: self._apply_brightness(brightness))

    def _apply_brightness(self, brightness: int) -> None:
        """Send the debounced brightness value to the bulb."""
        self._slider_after_id = None
        self._set_status(f"Setting brightness to {brightness}...")
        self._run_async(self.bulb.set_brightness, brightness, on_success=lambda _: self._set_status("Connected"))

    def _on_colour_pick(self, hsv: tuple[int, int, int]) -> None:
        """Handle a click on a palette swatch."""
        hue, saturation, value = hsv
        self._set_status("Setting colour...")
        self._run_async(
            self.bulb.set_color, hue, saturation, value, on_success=lambda _: self._set_status("Connected")
        )

    def _on_close(self) -> None:
        """Shut down the background worker before closing the window."""
        self._executor.shutdown(wait=False)
        self.destroy()
