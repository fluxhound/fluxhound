"""Main application window (customtkinter)."""
from __future__ import annotations

import colorsys
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import customtkinter as ctk

from src import device_config
from src.device_config import DeviceConfig
from src.gui.device_config_dialog import DeviceConfigDialog
from src.modes.music_mode import MusicMode
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

# Music mode hammers the bulb with frequent updates, so it gets its own bulb handle
# tuned to fail fast (no retry, short timeout) instead of the multi-second retry
# used for one-off manual commands - see src/modes/music_mode.py for why.
MUSIC_MODE_TIMEOUT_SECONDS = 1.5


def _hue_to_hex(hue: int) -> str:
    """Convert a hue (0-360) at full saturation/value to a #rrggbb string for swatch previews."""
    r, g, b = colorsys.hsv_to_rgb(hue / 360, 1.0, 1.0)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


class MainWindow(ctk.CTk):
    """FluxHound main window: manual control (on/off, brightness, colour) of one test bulb."""

    def __init__(self):
        super().__init__()
        self.bulb: TuyaBulb | None = None
        self._device_config: DeviceConfig | None = None
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._slider_after_id: str | None = None
        self._temperature_after_id: str | None = None
        self._music_mode: MusicMode | None = None

        self.title("FluxHound")
        self.geometry("420x520")
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

        self.brightness_label = ctk.CTkLabel(self, text="Brightness")
        self.brightness_label.pack(pady=(12, 0))
        self.brightness_slider = ctk.CTkSlider(
            self, from_=10, to=1000, number_of_steps=99, command=self._on_brightness_change
        )
        self.brightness_slider.set(1000)
        self.brightness_slider.pack(padx=24, pady=(4, 12), fill="x")

        self.temperature_label = ctk.CTkLabel(self, text="Temperature (white mode)")
        self.temperature_label.pack(pady=(4, 0))
        self.temperature_slider = ctk.CTkSlider(
            self, from_=0, to=1000, number_of_steps=100, command=self._on_temperature_change
        )
        self.temperature_slider.set(500)
        self.temperature_slider.pack(padx=24, pady=(4, 12), fill="x")

        self.colour_label = ctk.CTkLabel(self, text="Colour")
        self.colour_label.pack(pady=(4, 4))
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

        self.white_button = ctk.CTkButton(self, text="White", width=140, command=self._on_white_click)

        self.music_button = ctk.CTkButton(self, text="Music Mode", width=140, command=self._on_music_mode_click)
        self.music_button.pack(pady=(0, 12))

        self.exit_music_button = ctk.CTkButton(
            self, text="Exit Music Mode", width=160, command=self._on_exit_music_mode_click
        )

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
        self._device_config = config
        self.bulb = TuyaBulb(
            config.device_id, config.ip_address, config.local_key, version=config.protocol_version
        )
        self._set_controls_enabled(True)
        self._set_status("Connecting...")
        self._run_async(self.bulb.status, on_success=self._on_initial_status)

    def _on_initial_status(self, status: dict) -> None:
        """Sync the power switch to the bulb's actual state instead of assuming 'off'.

        tinytuya's status() occasionally returns a partial dps dict (seen
        live: a full response one poll, then just `{'22': ...}` the next).
        Only touch the switch when DP_SWITCH is actually present, so a
        partial response can't make it look like the bulb is off.
        """
        self._set_status("Connected")
        dps = status.get("dps", {})
        if DP_SWITCH in dps:
            self.power_var.set(bool(dps[DP_SWITCH]))

    # -- Controls ---------------------------------------------------------------

    def _set_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable the bulb controls, e.g. when no device is configured."""
        state = "normal" if enabled else "disabled"
        self.power_switch.configure(state=state)
        self.brightness_slider.configure(state=state)
        self.temperature_slider.configure(state=state)
        self.music_button.configure(state=state)
        self.white_button.configure(state=state)
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
                self.after(0, lambda: self._apply_manual_result(lambda: self._set_status(message, error=True)))
                return
            if on_success is not None:
                self.after(0, lambda: self._apply_manual_result(lambda: on_success(result)))

        self._executor.submit(task)

    def _apply_manual_result(self, apply: Callable[[], None]) -> None:
        """Ignore a manual-mode result that arrives after music mode has taken over the status
        area, e.g. a colour pick issued right before switching modes resolving late."""
        if self._music_mode is None:
            apply()

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

    def _on_temperature_change(self, value: float) -> None:
        """Handle a slider move: debounce so dragging doesn't flood the bulb with requests."""
        if self._temperature_after_id is not None:
            self.after_cancel(self._temperature_after_id)
        temperature = int(value)
        self._temperature_after_id = self.after(
            SLIDER_DEBOUNCE_MS, lambda: self._apply_temperature(temperature)
        )

    def _apply_temperature(self, temperature: int) -> None:
        """Send the debounced colour temperature to the bulb (switches to white mode)."""
        self._temperature_after_id = None
        self._set_status(f"Setting temperature to {temperature}...")
        self._run_async(
            self.bulb.set_temperature, temperature, on_success=lambda _: self._set_status("Connected")
        )

    def _on_colour_pick(self, hsv: tuple[int, int, int]) -> None:
        """Handle a click on a palette swatch: sets the bulb directly, or music mode's output."""
        hue, saturation, value = hsv
        if self._music_mode is not None:
            self._music_mode.set_colour(hue)
            return
        self._set_status("Setting colour...")
        self._run_async(
            self.bulb.set_color, hue, saturation, value, on_success=lambda _: self._set_status("Connected")
        )

    def _on_white_click(self) -> None:
        """Handle the 'White' button, only shown in music mode: switch its output to white."""
        if self._music_mode is not None:
            self._music_mode.set_white()

    # -- Music mode ---------------------------------------------------------------

    def _on_music_mode_click(self) -> None:
        """Enter music mode: hide manual controls, start analysing system audio."""
        if self._slider_after_id is not None:
            self.after_cancel(self._slider_after_id)
            self._slider_after_id = None
        if self._temperature_after_id is not None:
            self.after_cancel(self._temperature_after_id)
            self._temperature_after_id = None
        self._show_music_mode_controls()
        self._set_status("Music mode active")
        music_bulb = TuyaBulb(
            self._device_config.device_id, self._device_config.ip_address, self._device_config.local_key,
            version=self._device_config.protocol_version, timeout=MUSIC_MODE_TIMEOUT_SECONDS, retry_attempts=1,
            persistent=True,
        )
        self._music_mode = MusicMode(
            music_bulb, on_error=self._on_music_mode_error, on_recovered=self._on_music_mode_recovered
        )
        self._music_mode.start()

    def _on_exit_music_mode_click(self) -> None:
        """Leave music mode and go back to manual control."""
        if self._music_mode is not None:
            self._music_mode.stop()
            self._music_mode = None
        self._show_normal_controls()
        self._set_status("Connecting...")
        self._run_async(self.bulb.status, on_success=self._on_initial_status)

    def _on_music_mode_error(self, message: str) -> None:
        """Surface an audio/bulb error from the music-mode background thread. The status area
        stays visible and live in music mode, same as in manual mode."""
        self.after(0, lambda: self._set_status(f"Music mode error: {message}", error=True))

    def _on_music_mode_recovered(self) -> None:
        """Bulb commands are succeeding again after a prior error; clear the error state."""
        self.after(0, lambda: self._set_status("Music mode active"))

    def _show_normal_controls(self) -> None:
        """Layout for manual control: everything except the music-mode-only widgets."""
        self.white_button.pack_forget()
        self.exit_music_button.pack_forget()
        self.configure_button.pack(pady=(0, 12))
        self.power_switch.pack(pady=8)
        self.brightness_label.pack(pady=(12, 0))
        self.brightness_slider.pack(padx=24, pady=(4, 12), fill="x")
        self.temperature_label.pack(pady=(4, 0))
        self.temperature_slider.pack(padx=24, pady=(4, 12), fill="x")
        self.colour_label.pack(pady=(4, 4))
        self.palette_frame.pack(pady=(0, 12))
        self.music_button.pack(pady=(0, 12))

    def _show_music_mode_controls(self) -> None:
        """Layout for music mode: only colour choice (colour or white) and exit remain."""
        self.configure_button.pack_forget()
        self.power_switch.pack_forget()
        self.brightness_label.pack_forget()
        self.brightness_slider.pack_forget()
        self.temperature_label.pack_forget()
        self.temperature_slider.pack_forget()
        self.music_button.pack_forget()
        self.colour_label.pack(pady=(4, 4))
        self.palette_frame.pack(pady=(0, 12))
        self.white_button.pack(pady=(0, 12))
        self.exit_music_button.pack(pady=(8, 24))

    def _on_close(self) -> None:
        """Shut down background work before closing the window."""
        if self._music_mode is not None:
            self._music_mode.stop()
        self._executor.shutdown(wait=False)
        self.destroy()
