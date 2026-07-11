"""Main application window (customtkinter)."""
from __future__ import annotations

import colorsys
import tkinter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

import customtkinter as ctk

from src import audio_mode_config, custom_colour_config, device_config
from src.audio.custom_show import SENSITIVITY_MAX, SENSITIVITY_MIN, SOURCES, TARGETS
from src.audio_mode_config import AudioModeConfig
from src.custom_colour_config import CustomColour
from src.device_config import DeviceConfig
from src.gui.colour_picker_window import ColourPickerWindow
from src.gui.device_config_dialog import DeviceConfigDialog
from src.modes.custom_mode import CustomMode
from src.tuya.device import (
    DP_BRIGHTNESS,
    DP_COLOR_TEMP,
    DP_COLOUR_DATA,
    DP_SWITCH,
    DP_WORK_MODE,
    TuyaBulb,
    TuyaConnectionError,
    WORK_MODE_COLOUR,
    WORK_MODE_WHITE,
)

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
GRID_SELECTED_COLOR = ("#2563eb", "#1d4ed8")
GRID_DISABLED_COLOR = ("gray80", "gray22")

SOURCE_LABELS = {"timbre": "Timbre", "energy": "Energy", "beat": "Beat"}
TARGET_LABELS = {"hue": "Hue", "brightness": "Brightness", "saturation": "Saturation"}

# Audio Mode hammers the bulb with frequent updates, so it gets its own bulb handle
# tuned to fail fast (no retry, short timeout) instead of the multi-second retry
# used for one-off manual commands - see src/modes/custom_mode.py for why.
AUDIO_MODE_TIMEOUT_SECONDS = 1.5

SWATCH_SIZE = 32
RAINBOW_WEDGES = 24
# Rough warm/cool anchors for the live-state indicator's white-mode colour; which end of
# the temperature scale actually reads as warm vs. cool hasn't been verified against the
# physical bulb (see ROADMAP.md) - this is only a decorative approximation.
WARM_WHITE_RGB = (255, 197, 143)
COOL_WHITE_RGB = (202, 225, 255)


def _hue_to_hex(hue: int) -> str:
    """Convert a hue (0-360) at full saturation/value to a #rrggbb string for swatch previews."""
    r, g, b = colorsys.hsv_to_rgb(hue / 360, 1.0, 1.0)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def _draw_rainbow_swatch(canvas: tkinter.Canvas, size: int) -> None:
    """Fill the canvas with hue wedges - shown before the user has ever picked a custom
    colour, signalling 'a colour picker lives behind this circle'."""
    canvas.delete("all")
    center = size / 2
    radius = size / 2 - 1
    wedge_degrees = 360 / RAINBOW_WEDGES
    for i in range(RAINBOW_WEDGES):
        start_angle = i * wedge_degrees
        color = _hue_to_hex(int(start_angle))
        canvas.create_arc(
            center - radius, center - radius, center + radius, center + radius,
            start=start_angle, extent=wedge_degrees + 1, fill=color, outline=color,
        )


def _draw_solid_swatch(canvas: tkinter.Canvas, size: int, hex_color: str) -> None:
    """Fill the canvas with the user's picked colour, once they've chosen one."""
    canvas.delete("all")
    canvas.create_oval(1, 1, size - 1, size - 1, fill=hex_color, outline=hex_color)


@dataclass
class BulbSnapshot:
    """The bulb's manual state at some point in time - used both to seed Audio Mode when
    it starts and to restore exactly what was there before it, once it stops."""

    work_mode: str
    brightness: int
    temperature: int
    hue: int
    saturation: int
    value: int


def _snapshot_from_status(status: dict) -> BulbSnapshot:
    """Parse a bulb.status() response into a BulbSnapshot, with sensible defaults for any
    DP missing from a partial response (tinytuya has been observed returning those live)."""
    dps = status.get("dps", {})
    colour_data = dps.get(DP_COLOUR_DATA, "")
    if len(colour_data) >= 12:
        hue = int(colour_data[0:4], 16)
        saturation = int(colour_data[4:8], 16)
        value = int(colour_data[8:12], 16)
    else:
        hue, saturation, value = 0, 1000, 1000
    return BulbSnapshot(
        work_mode=dps.get(DP_WORK_MODE, WORK_MODE_WHITE),
        brightness=dps.get(DP_BRIGHTNESS, 1000),
        temperature=dps.get(DP_COLOR_TEMP, 500),
        hue=hue, saturation=saturation, value=value,
    )


class MainWindow(ctk.CTk):
    """FluxHound main window: manual control plus an always-visible, configurable
    Audio Mode for one test bulb."""

    def __init__(self):
        super().__init__()
        self.bulb: TuyaBulb | None = None
        self._device_config: DeviceConfig | None = None
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._slider_after_id: str | None = None
        self._temperature_after_id: str | None = None
        self._reactive_mode: CustomMode | None = None
        self._pre_reactive_state: BulbSnapshot | None = None
        self._current_state = BulbSnapshot(
            work_mode=WORK_MODE_WHITE, brightness=1000, temperature=500, hue=0, saturation=1000, value=1000
        )
        self._colour_picker_window: ColourPickerWindow | None = None

        saved_config = audio_mode_config.load()
        self._mode3_assignment: dict[str, str | None] = dict(saved_config.assignment)
        self._sensitivity: dict[str, float] = dict(saved_config.sensitivity)
        saved_custom_colour = custom_colour_config.load()
        self._custom_colour: tuple[int, int, int] | None = (
            (saved_custom_colour.hue, saved_custom_colour.saturation, saved_custom_colour.value)
            if saved_custom_colour is not None else None
        )

        self.title("FluxHound")
        self.geometry("460x820")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.status_label = ctk.CTkLabel(self, text="", wraplength=420)
        self.status_label.pack(pady=(16, 4))

        self.configure_button = ctk.CTkButton(
            self, text="⚙", width=32, height=32, corner_radius=16, command=self._on_configure_click
        )
        self.configure_button.place(relx=1.0, x=-16, y=16, anchor="ne")

        self.title_label = ctk.CTkLabel(self, text="FLUXHOUND", font=ctk.CTkFont(size=26, weight="bold"))
        self.title_label.pack(pady=(4, 8))

        self.live_indicator = ctk.CTkFrame(self, width=380, height=48, corner_radius=8, fg_color="gray30")
        self.live_indicator.pack(pady=(0, 12))
        self.live_indicator.pack_propagate(False)

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

        self.white_button = ctk.CTkButton(
            self.palette_frame, text="", width=SWATCH_SIZE, height=SWATCH_SIZE, corner_radius=SWATCH_SIZE // 2,
            fg_color="#ffffff", hover_color="#e6e6e6", border_width=1, border_color="gray50",
            command=self._on_white_click,
        )
        self.white_button.grid(row=0, column=0, padx=4)

        for column, (name, hsv) in enumerate(COLOUR_PALETTE, start=1):
            hue = hsv[0]
            swatch_color = _hue_to_hex(hue)
            swatch = ctk.CTkButton(
                self.palette_frame, text="", width=SWATCH_SIZE, height=SWATCH_SIZE, corner_radius=SWATCH_SIZE // 2,
                fg_color=swatch_color, hover_color=swatch_color,
                command=lambda hsv=hsv: self._on_colour_pick(hsv),
            )
            swatch.grid(row=0, column=column, padx=4)

        canvas_bg = self._apply_appearance_mode(ctk.ThemeManager.theme["CTk"]["fg_color"])
        self.custom_colour_canvas = tkinter.Canvas(
            self.palette_frame, width=SWATCH_SIZE, height=SWATCH_SIZE, highlightthickness=0,
            bg=canvas_bg, cursor="hand2",
        )
        self.custom_colour_canvas.grid(row=0, column=len(COLOUR_PALETTE) + 1, padx=4)
        self.custom_colour_canvas.bind("<Button-1>", lambda event: self._on_custom_colour_swatch_click())
        self._redraw_custom_colour_swatch()

        self.audio_mode_button = ctk.CTkButton(
            self, text="Activate Audio Mode", width=200, command=self._on_audio_mode_toggle_click
        )
        self.audio_mode_button.pack(pady=(4, 12))

        self.mode3_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.mode3_frame.pack(pady=(0, 12))
        self._mode3_buttons: dict[tuple[str, str], ctk.CTkButton] = {}
        self._mode3_default_fg_color: dict[tuple[str, str], Any] = {}
        self._sensitivity_sliders: dict[str, ctk.CTkSlider] = {}
        for row, target in enumerate(TARGETS):
            ctk.CTkLabel(self.mode3_frame, text=TARGET_LABELS[target], width=80, anchor="w").grid(
                row=row, column=0, padx=(0, 8), pady=6, sticky="w"
            )
            for column, source in enumerate(SOURCES):
                button = ctk.CTkButton(
                    self.mode3_frame, text=SOURCE_LABELS[source], width=68,
                    command=lambda t=target, s=source: self._on_mode3_source_click(t, s),
                )
                button.grid(row=row, column=column + 1, padx=4, pady=6)
                self._mode3_buttons[(target, source)] = button
                self._mode3_default_fg_color[(target, source)] = button.cget("fg_color")
            sensitivity_slider = ctk.CTkSlider(
                self.mode3_frame, from_=SENSITIVITY_MIN, to=SENSITIVITY_MAX, number_of_steps=100, width=90,
                command=lambda value, t=target: self._on_mode3_sensitivity_change(t, value),
            )
            sensitivity_slider.grid(row=row, column=len(SOURCES) + 1, padx=(8, 0), pady=6)
            self._sensitivity_sliders[target] = sensitivity_slider
        self._refresh_audio_mode_grid()

        self.set_default_button = ctk.CTkButton(
            self, text="Set to Default", width=160, fg_color="gray40", command=self._on_set_default_click
        )
        self.set_default_button.pack(pady=(0, 20))

        self._update_live_indicator()
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
        """Handle the gear button: reopen the device dialog, pre-filled if possible."""
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
        """Sync the power switch and the brightness/temperature sliders to the bulb's
        actual state instead of assuming defaults.

        tinytuya's status() occasionally returns a partial dps dict (seen
        live: a full response one poll, then just `{'22': ...}` the next).
        Only touch the switch when DP_SWITCH is actually present, so a
        partial response can't make it look like the bulb is off.
        """
        self._set_status("Connected")
        dps = status.get("dps", {})
        if DP_SWITCH in dps:
            self.power_var.set(bool(dps[DP_SWITCH]))
        self._current_state = _snapshot_from_status(status)
        self._update_temperature_label()
        self.brightness_slider.set(
            self._current_state.brightness if self._current_state.work_mode == WORK_MODE_WHITE
            else self._current_state.value
        )
        if self._current_state.work_mode == WORK_MODE_WHITE:
            self.temperature_slider.set(self._current_state.temperature)
        else:
            self._set_saturation_slider_value(self._current_state.saturation)
        self._update_live_indicator()

    # -- Controls ---------------------------------------------------------------

    def _set_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable the bulb controls, e.g. when no device is configured."""
        state = "normal" if enabled else "disabled"
        self.power_switch.configure(state=state)
        self.brightness_slider.configure(state=state)
        self.temperature_slider.configure(state=state)
        self.audio_mode_button.configure(state=state)
        self.set_default_button.configure(state=state)
        self.white_button.configure(state=state if self._reactive_mode is None else "disabled")
        for swatch in self.palette_frame.winfo_children():
            if swatch is not self.white_button and isinstance(swatch, ctk.CTkButton):
                swatch.configure(state=state)
        if enabled:
            self._refresh_audio_mode_grid()
        else:
            for button in self._mode3_buttons.values():
                button.configure(state="disabled")
            for slider in self._sensitivity_sliders.values():
                slider.configure(state="disabled")

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
        """Ignore a manual-mode result that arrives after Audio Mode has taken over the
        status area, e.g. a colour pick issued right before switching modes resolving late."""
        if self._reactive_mode is None:
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
        """Send the debounced brightness value, operating within whichever mode is
        currently active instead of forcing white mode - the White circle is the only
        thing that switches modes now, so brightness can be adjusted while a colour is
        active too. To Audio Mode if it's running (taking that property away from
        whatever source was driving it), otherwise straight to the bulb."""
        self._slider_after_id = None
        self._deactivate_row("brightness")
        if self._reactive_mode is not None:
            self._reactive_mode.set_manual_override("brightness", brightness)
            self._current_state.value = brightness
            self._update_live_indicator()
            return
        if self._current_state.work_mode == WORK_MODE_COLOUR:
            self._current_state.value = brightness
            self._set_status(f"Setting brightness to {brightness}...")
            self._run_async(
                self.bulb.set_colour_data_value,
                self._current_state.hue, self._current_state.saturation, brightness,
                on_success=lambda _: self._set_status("Connected"),
            )
        else:
            self._current_state.brightness = brightness
            self._set_status(f"Setting brightness to {brightness}...")
            self._run_async(
                self.bulb.set_brightness_value, brightness, on_success=lambda _: self._set_status("Connected")
            )
        self._update_live_indicator()

    def _on_temperature_change(self, value: float) -> None:
        """Handle a slider move: debounce so dragging doesn't flood the bulb with requests."""
        if self._temperature_after_id is not None:
            self.after_cancel(self._temperature_after_id)
        value = int(value)
        self._temperature_after_id = self.after(
            SLIDER_DEBOUNCE_MS, lambda: self._apply_temperature_or_saturation(value)
        )

    def _apply_temperature_or_saturation(self, value: int) -> None:
        """This slider is dual-purpose: colour temperature in white mode, saturation in
        colour mode (including whenever Audio Mode is running, which is always colour
        mode) - see _update_temperature_label for the label that tracks which."""
        self._temperature_after_id = None
        self._deactivate_row("saturation")
        if self._reactive_mode is not None:
            self._reactive_mode.set_manual_override("saturation", value)
            self._current_state.saturation = value
            self._update_live_indicator()
            return
        if self._current_state.work_mode == WORK_MODE_COLOUR:
            self._current_state.saturation = value
            self._set_status(f"Setting saturation to {value}...")
            self._run_async(
                self.bulb.set_colour_data_value, self._current_state.hue, value, self._current_state.value,
                on_success=lambda _: self._set_status("Connected"),
            )
        else:
            self._current_state.temperature = value
            self._set_status(f"Setting temperature to {value}...")
            self._run_async(
                self.bulb.set_temperature, value, on_success=lambda _: self._set_status("Connected")
            )
        self._update_live_indicator()

    def _on_colour_pick(self, hsv: tuple[int, int, int]) -> None:
        """Handle a click on a palette swatch (or a live update from the colour picker
        window): sets the bulb directly, or (if Audio Mode is running) takes the Hue
        property away from whatever source was driving it."""
        hue, saturation, value = hsv
        self._deactivate_row("hue")
        if self._reactive_mode is not None:
            self._reactive_mode.set_manual_override("hue", hue)
            self._current_state.hue = hue
            self._update_live_indicator()
            return
        self._current_state.work_mode = WORK_MODE_COLOUR
        self._current_state.hue = hue
        self._current_state.saturation = saturation
        self._current_state.value = value
        self._update_temperature_label()
        self._set_saturation_slider_value(saturation)
        self.brightness_slider.set(value)
        self._set_status("Setting colour...")
        self._run_async(
            self.bulb.set_color, hue, saturation, value, on_success=lambda _: self._set_status("Connected")
        )
        self._update_live_indicator()

    def _on_white_click(self) -> None:
        """The only way to explicitly enter white mode - brightness/temperature no
        longer switch modes themselves, only operate within whichever is active."""
        if self.bulb is None or self._reactive_mode is not None:
            return
        self._deactivate_row("hue")
        self._deactivate_row("saturation")
        self._current_state.work_mode = WORK_MODE_WHITE
        self._update_temperature_label()
        self.brightness_slider.set(self._current_state.brightness)
        self.temperature_slider.set(self._current_state.temperature)
        self._set_status("Switching to white...")
        self._run_async(
            self.bulb.set_work_mode, WORK_MODE_WHITE, on_success=lambda _: self._set_status("Connected")
        )
        self._update_live_indicator()

    def _update_temperature_label(self) -> None:
        """The temperature/saturation slider's label follows the bulb's current mode."""
        if self._current_state.work_mode == WORK_MODE_COLOUR:
            self.temperature_label.configure(text="Saturation (colour mode)")
        else:
            self.temperature_label.configure(text="Temperature (white mode)")

    def _set_saturation_slider_value(self, saturation: int) -> None:
        """Reflect a colour-mode saturation onto the shared slider without touching its
        command callback (matches the .set() pattern used elsewhere in this file)."""
        self.temperature_slider.set(saturation)

    def _update_live_indicator(self) -> None:
        """Reflect self._current_state's colour and brightness as a fill colour, so the
        rectangle under the title mirrors what the physical bulb should currently look
        like - including live updates from Audio Mode via _on_reactive_mode_update."""
        state = self._current_state
        if state.work_mode == WORK_MODE_WHITE:
            t = max(0.0, min(1.0, state.temperature / 1000.0))
            base = tuple(
                round(WARM_WHITE_RGB[i] + (COOL_WHITE_RGB[i] - WARM_WHITE_RGB[i]) * t) for i in range(3)
            )
            brightness_fraction = max(0.0, min(1.0, (state.brightness - 10) / (1000 - 10)))
        else:
            r, g, b = colorsys.hsv_to_rgb(state.hue / 360.0, max(0.0, min(1.0, state.saturation / 1000.0)), 1.0)
            base = (round(r * 255), round(g * 255), round(b * 255))
            brightness_fraction = max(0.0, min(1.0, state.value / 1000.0))
        scaled = tuple(round(channel * brightness_fraction) for channel in base)
        hex_color = f"#{scaled[0]:02x}{scaled[1]:02x}{scaled[2]:02x}"
        self.live_indicator.configure(fg_color=hex_color)

    # -- Custom colour picker ----------------------------------------------------------

    def _redraw_custom_colour_swatch(self) -> None:
        """Rainbow wedges until a colour has ever been picked, then that colour's fill -
        the circle itself communicates 'a picker lives here' before first use."""
        if self._custom_colour is None:
            _draw_rainbow_swatch(self.custom_colour_canvas, SWATCH_SIZE)
        else:
            hue, saturation, value = self._custom_colour
            r, g, b = colorsys.hsv_to_rgb(hue / 360.0, saturation / 1000.0, value / 1000.0)
            hex_color = f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"
            _draw_solid_swatch(self.custom_colour_canvas, SWATCH_SIZE, hex_color)

    def _on_custom_colour_swatch_click(self) -> None:
        """Open the colour-picker window (or just bring it to front if already open)."""
        if self.bulb is None:
            return
        if self._colour_picker_window is not None and self._colour_picker_window.winfo_exists():
            self._colour_picker_window.lift()
            self._colour_picker_window.focus()
            return
        hue, saturation, value = self._custom_colour or (0, 1000, 1000)
        self._colour_picker_window = ColourPickerWindow(
            self, initial_hue=hue, initial_saturation=saturation, initial_value=value,
            on_pick=self._on_custom_colour_picked,
        )

    def _on_custom_colour_picked(self, hue: int, saturation: int, value: int) -> None:
        """Live callback from the colour-picker window: persist, redraw the swatch, and
        apply it exactly like a palette pick."""
        self._custom_colour = (hue, saturation, value)
        custom_colour_config.save(CustomColour(hue=hue, saturation=saturation, value=value))
        self._redraw_custom_colour_swatch()
        self._on_colour_pick((hue, saturation, value))

    # -- Audio Mode ---------------------------------------------------------------

    def _build_reactive_mode_bulb(self) -> TuyaBulb:
        """A dedicated bulb handle for Audio Mode's hot loop: fails fast and keeps one
        persistent connection open instead of reconnecting for every update - see
        src/modes/custom_mode.py for why that combination matters."""
        return TuyaBulb(
            self._device_config.device_id, self._device_config.ip_address, self._device_config.local_key,
            version=self._device_config.protocol_version, timeout=AUDIO_MODE_TIMEOUT_SECONDS, retry_attempts=1,
            persistent=True,
        )

    def _cancel_pending_slider_updates(self) -> None:
        if self._slider_after_id is not None:
            self.after_cancel(self._slider_after_id)
            self._slider_after_id = None
        if self._temperature_after_id is not None:
            self.after_cancel(self._temperature_after_id)
            self._temperature_after_id = None

    def _on_audio_mode_toggle_click(self) -> None:
        if self._reactive_mode is not None:
            self._deactivate_audio_mode()
        else:
            self._activate_audio_mode()

    def _activate_audio_mode(self) -> None:
        self._cancel_pending_slider_updates()
        self._set_status("Reading current state...")
        self._run_async(self.bulb.status, on_success=self._start_audio_mode)

    def _start_audio_mode(self, status: dict) -> None:
        snapshot = _snapshot_from_status(status)
        self._pre_reactive_state = snapshot
        self._current_state = snapshot
        self._current_state.work_mode = WORK_MODE_COLOUR  # Audio Mode always drives colour_data
        self._update_temperature_label()
        initial_brightness = snapshot.brightness if snapshot.work_mode == WORK_MODE_WHITE else snapshot.value
        self._reactive_mode = CustomMode(
            self._build_reactive_mode_bulb(), dict(self._mode3_assignment), dict(self._sensitivity),
            initial_hue=snapshot.hue, initial_saturation=snapshot.saturation,
            initial_brightness=initial_brightness,
            on_error=self._on_reactive_mode_error, on_recovered=self._on_reactive_mode_recovered,
            on_update=self._on_reactive_mode_update,
        )
        self.white_button.configure(state="disabled")
        self.audio_mode_button.configure(text="Deactivate Audio Mode")
        self._set_status("Audio mode active")
        self._reactive_mode.start()

    def _deactivate_audio_mode(self) -> None:
        self._reactive_mode.stop()
        self._reactive_mode = None
        self.white_button.configure(state="normal")
        self.audio_mode_button.configure(text="Activate Audio Mode")
        snapshot = self._pre_reactive_state
        self._pre_reactive_state = None
        if snapshot is not None:
            self._set_status("Restoring previous settings...")
            self._run_async(self._restore_snapshot, snapshot, on_success=lambda _: self._finish_deactivate(snapshot))
        else:
            self._finish_deactivate(None)

    def _restore_snapshot(self, snapshot: BulbSnapshot) -> None:
        """Put the bulb back exactly how it was before Audio Mode took over. Runs on the
        background executor thread - network calls only, no widget access here."""
        if snapshot.work_mode == WORK_MODE_WHITE:
            self.bulb.set_work_mode(WORK_MODE_WHITE)
            self.bulb.set_brightness_value(snapshot.brightness)
            self.bulb.set_temperature_value(snapshot.temperature)
        else:
            self.bulb.set_color(snapshot.hue, snapshot.saturation, snapshot.value)

    def _finish_deactivate(self, snapshot: BulbSnapshot | None) -> None:
        """Sync the widgets to the restored values (main thread) and re-sync status."""
        if snapshot is not None:
            self._current_state = snapshot
            self._update_temperature_label()
            if snapshot.work_mode == WORK_MODE_WHITE:
                self.brightness_slider.set(snapshot.brightness)
                self.temperature_slider.set(snapshot.temperature)
            else:
                self.brightness_slider.set(snapshot.value)
                self._set_saturation_slider_value(snapshot.saturation)
            self._update_live_indicator()
        self._run_async(self.bulb.status, on_success=self._on_initial_status)

    def _on_reactive_mode_error(self, message: str) -> None:
        """Surface an audio/bulb error from Audio Mode's background thread. The status
        area stays visible and live while it runs, same as in manual mode."""
        self.after(0, lambda: self._set_status(f"Audio mode error: {message}", error=True))

    def _on_reactive_mode_recovered(self) -> None:
        """Bulb commands are succeeding again after a prior error; clear the error state."""
        self.after(0, lambda: self._set_status("Audio mode active"))

    def _on_reactive_mode_update(self, hue: int, saturation: int, value: int) -> None:
        """Called from Audio Mode's background thread on every update; marshal onto the
        Tk main thread so the live-state rectangle mirrors the running show."""
        def apply() -> None:
            self._current_state.hue = hue
            self._current_state.saturation = saturation
            self._current_state.value = value
            self._update_live_indicator()

        self.after(0, apply)

    # -- Audio Mode assignment/sensitivity grid --------------------------------------

    def _deactivate_row(self, target: str) -> None:
        """Manually controlling a property hands control away from whatever source was
        assigned to it - both in the persisted config and, if Audio Mode is running, via
        the caller's own set_manual_override call."""
        if self._mode3_assignment.get(target) is not None:
            self._mode3_assignment[target] = None
            self._save_audio_mode_config()
            self._refresh_audio_mode_grid()

    def _save_audio_mode_config(self) -> None:
        audio_mode_config.save(
            AudioModeConfig(assignment=dict(self._mode3_assignment), sensitivity=dict(self._sensitivity))
        )

    def _on_mode3_source_click(self, target: str, source: str) -> None:
        """Toggle a source on/off for a target. A source already assigned to another
        target is disabled there until deselected, enforcing a strict one-to-one mapping
        so all three targets can always be driven by a distinct signal. The button should
        already be disabled in that case, but this guards the assignment dict directly too."""
        if self._mode3_assignment.get(target) == source:
            self._mode3_assignment[target] = None
        elif source in self._mode3_assignment.values():
            return
        else:
            self._mode3_assignment[target] = source
        self._save_audio_mode_config()
        self._refresh_audio_mode_grid()
        if isinstance(self._reactive_mode, CustomMode):
            self._reactive_mode.set_assignment(target, self._mode3_assignment[target])

    def _on_mode3_sensitivity_change(self, target: str, value: float) -> None:
        """A row's sensitivity slider tunes whichever source currently occupies that row."""
        source = self._mode3_assignment.get(target)
        if source is None:
            return
        self._sensitivity[source] = value
        self._save_audio_mode_config()
        if isinstance(self._reactive_mode, CustomMode):
            self._reactive_mode.set_sensitivity(source, value)

    def _on_set_default_click(self) -> None:
        """Reset the assignment and sensitivity to their defaults, without changing
        whether Audio Mode itself is active."""
        self._mode3_assignment = dict(audio_mode_config.DEFAULT_ASSIGNMENT)
        self._sensitivity = dict(audio_mode_config.DEFAULT_SENSITIVITY)
        self._save_audio_mode_config()
        self._refresh_audio_mode_grid()
        if isinstance(self._reactive_mode, CustomMode):
            for target, source in self._mode3_assignment.items():
                self._reactive_mode.set_assignment(target, source)
            for source, value in self._sensitivity.items():
                self._reactive_mode.set_sensitivity(source, value)

    def _refresh_audio_mode_grid(self) -> None:
        """Update the assignment grid's selected/disabled visuals and the sensitivity
        sliders to match self._mode3_assignment / self._sensitivity, which persist
        across mode switches and app restarts by design."""
        assigned_sources = {source for source in self._mode3_assignment.values() if source is not None}
        for (target, source), button in self._mode3_buttons.items():
            selected = self._mode3_assignment.get(target) == source
            taken_elsewhere = source in assigned_sources and not selected
            if selected:
                button.configure(state="normal", fg_color=GRID_SELECTED_COLOR)
            elif taken_elsewhere:
                button.configure(state="disabled", fg_color=GRID_DISABLED_COLOR)
            else:
                button.configure(state="normal", fg_color=self._mode3_default_fg_color[(target, source)])

        for target, slider in self._sensitivity_sliders.items():
            source = self._mode3_assignment.get(target)
            if source is None:
                slider.configure(state="disabled")
            else:
                slider.configure(state="normal")
                slider.set(self._sensitivity[source])

    def _on_close(self) -> None:
        """Shut down background work before closing the window."""
        if self._reactive_mode is not None:
            self._reactive_mode.stop()
        self._executor.shutdown(wait=False)
        self.destroy()
