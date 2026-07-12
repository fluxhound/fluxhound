"""Main application window (customtkinter)."""
from __future__ import annotations

import colorsys
import math
import sys
import tkinter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import customtkinter as ctk
import numpy as np

from src import audio_mode_config, custom_colour_config, devices_config
from src.audio.custom_show import SENSITIVITY_MAX, SENSITIVITY_MIN, SOURCES, TARGETS
from src.audio_mode_config import AudioModeConfig
from src.custom_colour_config import CustomColour
from src.device_config import DeviceConfig
from src.devices_config import DEVICE_SELECTION_PREFIX, GROUP_SELECTION_PREFIX, DeviceGroup, DevicesConfig
from src.gui.colour_picker_window import ColourPickerWindow
from src.gui.device_config_dialog import DeviceConfigDialog
from src.gui.devices_window import DevicesWindow
from src.gui.settings_window import SettingsWindow
from src.modes.ambience_mode import AmbienceMode
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
    split_value_across_bulbs,
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

# Audio Mode and Ambience Mode both hammer the bulb with frequent updates, so they
# get their own bulb handles tuned to fail fast (no retry, short timeout) instead of
# the multi-second retry used for one-off manual commands - see
# src/modes/custom_mode.py for why.
REACTIVE_MODE_TIMEOUT_SECONDS = 1.5

SWATCH_SIZE = 32
RAINBOW_WEDGES = 24
# Rough warm/cool anchors for the live-state indicator's white-mode colour; which end of
# the temperature scale actually reads as warm vs. cool hasn't been verified against the
# physical bulb (see ROADMAP.md) - this is only a decorative approximation.
WARM_WHITE_RGB = (255, 197, 143)
COOL_WHITE_RGB = (202, 225, 255)

LIVE_INDICATOR_WIDTH = 260
LIVE_INDICATOR_HEIGHT = 220
LOGO_FILENAME = "fluxhound_logo.png"
LOGO_DISPLAY_SIZE = 150  # target size in px; the source PNG is downscaled to roughly this


def _app_root_dir() -> Path:
    """Directory bundled assets (like the logo) live next to - the exe's directory
    when frozen via PyInstaller, the repo root in dev."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def _render_radial_glow(width: int, height: int, center_rgb: tuple[int, int, int],
                         edge_rgb: tuple[int, int, int]) -> tkinter.PhotoImage:
    """A radial gradient from center_rgb (at the middle) fading out to edge_rgb (at
    the corners) - the live-state colour "radiating outward" behind the logo, and
    dissolving into the surrounding UI at the edges. Vectorized numpy, encoded as a
    raw PPM P6 PhotoImage, same technique as the colour picker's gradient (no PIL)."""
    cx, cy = width / 2, height / 2
    max_dist = math.hypot(cx, cy)
    yy, xx = np.mgrid[0:height, 0:width]
    fraction = np.clip(np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / max_dist, 0.0, 1.0)[..., np.newaxis]
    center = np.array(center_rgb, dtype=np.float64)
    edge = np.array(edge_rgb, dtype=np.float64)
    rgb = (center * (1 - fraction) + edge * fraction).astype(np.uint8)
    header = f"P6 {width} {height} 255 ".encode("ascii")
    return tkinter.PhotoImage(data=header + rgb.tobytes(), format="PPM")


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
    Audio Mode for whichever device or group is currently selected."""

    def __init__(self):
        super().__init__()
        self._devices_config: DevicesConfig = devices_config.load()
        # The bulbs/device entries behind the current dropdown selection - a single
        # device selects one, a group selects all its members, so every command
        # dispatch (see _run_on_all) sends to however many bulbs are active.
        self._active_bulbs: list[TuyaBulb] = []
        self._active_devices: list[DeviceConfig] = []
        self._active_selection_ids: tuple[str, ...] = ()
        self._selector_key_by_label: dict[str, str] = {}
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._slider_after_id: str | None = None
        self._temperature_after_id: str | None = None
        self._reactive_mode: CustomMode | AmbienceMode | None = None
        self._reactive_mode_status_label = ""
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
        self.geometry("460x1000")
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

        indicator_bg = self._apply_appearance_mode(ctk.ThemeManager.theme["CTk"]["fg_color"])
        self.live_indicator = tkinter.Canvas(
            self, width=LIVE_INDICATOR_WIDTH, height=LIVE_INDICATOR_HEIGHT, highlightthickness=0, bg=indicator_bg
        )
        self.live_indicator.pack(pady=(0, 12))
        self._live_indicator_bg_photo: tkinter.PhotoImage | None = None
        self._live_indicator_bg_item = self.live_indicator.create_image(
            LIVE_INDICATOR_WIDTH / 2, LIVE_INDICATOR_HEIGHT / 2
        )
        # The logo (if the bundled PNG is present) sits on top once, drawn last so it
        # stays above the gradient - its own alpha (a soft vignette fading to fully
        # transparent) blends naturally with whatever colour is glowing beneath it.
        self._logo_photo = self._load_logo()
        if self._logo_photo is not None:
            self.live_indicator.create_image(
                LIVE_INDICATOR_WIDTH / 2, LIVE_INDICATOR_HEIGHT / 2, image=self._logo_photo
            )

        self.target_selector = ctk.CTkOptionMenu(
            self, values=["No device configured"], command=self._on_target_selected
        )
        self.target_selector.pack(pady=(0, 12))

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
        # One checkbox per target (hue/brightness/saturation == TARGETS exactly),
        # default checked - only meaningful (and only shown) while the active target
        # is a merged group: whether that property gets split positionally across the
        # group's positioned members, or mirrored identically like a plain group.
        self._split_vars: dict[str, ctk.BooleanVar] = {}
        self._split_checkboxes: dict[str, ctk.CTkCheckBox] = {}
        for row, target in enumerate(TARGETS):
            split_var = ctk.BooleanVar(value=True)
            self._split_vars[target] = split_var
            checkbox = ctk.CTkCheckBox(self.mode3_frame, text="", width=20, variable=split_var)
            checkbox.grid(row=row, column=0, padx=(0, 4), pady=6)
            self._split_checkboxes[target] = checkbox
            ctk.CTkLabel(self.mode3_frame, text=TARGET_LABELS[target], width=80, anchor="w").grid(
                row=row, column=1, padx=(0, 8), pady=6, sticky="w"
            )
            for column, source in enumerate(SOURCES):
                button = ctk.CTkButton(
                    self.mode3_frame, text=SOURCE_LABELS[source], width=68,
                    command=lambda t=target, s=source: self._on_mode3_source_click(t, s),
                )
                button.grid(row=row, column=column + 2, padx=4, pady=6)
                self._mode3_buttons[(target, source)] = button
                self._mode3_default_fg_color[(target, source)] = button.cget("fg_color")
            sensitivity_slider = ctk.CTkSlider(
                self.mode3_frame, from_=SENSITIVITY_MIN, to=SENSITIVITY_MAX, number_of_steps=100, width=90,
                command=lambda value, t=target: self._on_mode3_sensitivity_change(t, value),
            )
            sensitivity_slider.grid(row=row, column=len(SOURCES) + 2, padx=(8, 0), pady=6)
            self._sensitivity_sliders[target] = sensitivity_slider
        self._refresh_audio_mode_grid()
        self._update_merge_ui_visibility()

        self.set_default_button = ctk.CTkButton(
            self, text="Set to Default", width=160, fg_color="gray40", command=self._on_set_default_click
        )
        self.set_default_button.pack(pady=(0, 20))

        self.ambience_button = ctk.CTkButton(
            self, text="Activate Ambience", width=200, command=self._on_ambience_mode_toggle_click
        )
        self.ambience_button.pack(pady=(0, 20))

        self._update_live_indicator()
        self._set_controls_enabled(False)
        self._startup_devices()

    # -- Device/group configuration -------------------------------------------------

    def _startup_devices(self) -> None:
        """On startup: connect to whatever's already configured, else ask for a first
        device (there's nothing to pick from the selector yet)."""
        if not self._devices_config.devices:
            self._set_status("No device configured", error=True)
            self.after(50, self._open_add_device_dialog)
            return
        self._refresh_target_selector()

    def _open_add_device_dialog(self) -> None:
        DeviceConfigDialog(self, on_save=self._on_device_added, existing=None)

    def _on_device_added(self, config: DeviceConfig) -> None:
        """First-run onboarding path: DevicesWindow handles adding devices afterwards."""
        if not config.display_name:
            config.display_name = config.device_id
        self._devices_config.devices.append(config)
        if not self._devices_config.active_selection:
            self._devices_config.active_selection = devices_config.device_selection_key(config.device_id)
        self._on_devices_config_changed()

    def _on_configure_click(self) -> None:
        """Handle the gear button: open the Settings menu."""
        SettingsWindow(self, on_open_devices=self._open_devices_window)

    def _open_devices_window(self) -> None:
        DevicesWindow(self, self._devices_config, on_change=self._on_devices_config_changed)

    def _on_devices_config_changed(self) -> None:
        """Called after any add/rename/group edit: persist and refresh the selector,
        reconnecting only if the active selection's actual device set changed."""
        devices_config.save(self._devices_config)
        self._refresh_target_selector()
        self._update_merge_ui_visibility()

    def _build_selector_options(self) -> list[tuple[str, str]]:
        """(label, selection key) pairs for the dropdown: every device, then every
        group, in the order they were added."""
        options = [
            (device.display_name or device.device_id, devices_config.device_selection_key(device.device_id))
            for device in self._devices_config.devices
        ]
        options += [
            (f"Group: {group.name}", devices_config.group_selection_key(group.group_id))
            for group in self._devices_config.groups
        ]
        return options

    def _find_device(self, device_id: str) -> DeviceConfig | None:
        return next((d for d in self._devices_config.devices if d.device_id == device_id), None)

    def _resolve_device_entries(self, key: str) -> list[DeviceConfig]:
        """The device(s) a selection key refers to: one for a device key, every
        current member for a group key (so removing a device from a group takes
        effect the next time that group is targeted)."""
        if key.startswith(DEVICE_SELECTION_PREFIX):
            device = self._find_device(key[len(DEVICE_SELECTION_PREFIX):])
            return [device] if device is not None else []
        if key.startswith(GROUP_SELECTION_PREFIX):
            group_id = key[len(GROUP_SELECTION_PREFIX):]
            group = next((g for g in self._devices_config.groups if g.group_id == group_id), None)
            if group is None:
                return []
            return [d for d in (self._find_device(did) for did in group.device_ids) if d is not None]
        return []

    def _refresh_target_selector(self) -> None:
        """Rebuild the dropdown's options from the current devices/groups, falling
        back to the first option if the persisted active_selection no longer resolves
        to anything (e.g. its device or group was just removed)."""
        options = self._build_selector_options()
        self._selector_key_by_label = {label: key for label, key in options}
        if not options:
            self.target_selector.configure(values=["No device configured"])
            self.target_selector.set("No device configured")
            self._active_selection_ids = ()
            self._apply_target_selection("")
            return

        valid_keys = {key for _, key in options}
        active_key = self._devices_config.active_selection
        if active_key not in valid_keys:
            active_key = options[0][1]
            self._devices_config.active_selection = active_key
            devices_config.save(self._devices_config)

        label_by_key = {key: label for label, key in options}
        self.target_selector.configure(values=[label for label, _ in options])
        self.target_selector.set(label_by_key[active_key])

        entries = self._resolve_device_entries(active_key)
        new_ids = tuple(d.device_id for d in entries)
        if new_ids != self._active_selection_ids:
            self._active_selection_ids = new_ids
            self._apply_target_selection(active_key)

    def _on_target_selected(self, label: str) -> None:
        """Handle a manual dropdown pick."""
        key = self._selector_key_by_label.get(label)
        if key is None or key == self._devices_config.active_selection:
            return
        self._devices_config.active_selection = key
        devices_config.save(self._devices_config)
        self._active_selection_ids = tuple(d.device_id for d in self._resolve_device_entries(key))
        self._apply_target_selection(key)

    def _apply_target_selection(self, key: str) -> None:
        """(Re)build the active bulb list for the given selection and reconnect -
        a group applies every subsequent command to all its member bulbs at once."""
        entries = self._resolve_device_entries(key)
        self._active_devices = entries
        self._active_bulbs = [
            TuyaBulb(d.device_id, d.ip_address, d.local_key, version=d.protocol_version) for d in entries
        ]
        self._update_merge_ui_visibility()
        if not self._active_bulbs:
            self._set_controls_enabled(False)
            self._set_status("No device configured", error=True)
            return
        self._set_controls_enabled(True)
        self._set_status("Connecting...")
        self._run_async(self._active_bulbs[0].status, on_success=self._on_initial_status)

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
        self.target_selector.configure(state=state if self._reactive_mode is None else "disabled")
        self.power_switch.configure(state=state)
        self.brightness_slider.configure(state=state)
        self.temperature_slider.configure(state=state)
        self.audio_mode_button.configure(state=state)
        self.ambience_button.configure(state=state)
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
        for checkbox in self._split_checkboxes.values():
            checkbox.configure(state=state if self._reactive_mode is None else "disabled")

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

    def _dispatch(self, calls: list[tuple[TuyaBulb, str, tuple]]) -> None:
        """Fire (bulb, method_name, args) triples from one background task. Reports
        "Connected" once every send succeeds, or the last error if any bulb failed
        (the others still received their command)."""
        def task() -> None:
            error_message: str | None = None
            for bulb, method_name, args in calls:
                try:
                    getattr(bulb, method_name)(*args)
                except TuyaConnectionError as exc:
                    error_message = str(exc)
            if error_message is not None:
                message = f"Lamp unreachable: {error_message}"
                self.after(0, lambda: self._apply_manual_result(lambda: self._set_status(message, error=True)))
            else:
                self.after(0, lambda: self._apply_manual_result(lambda: self._set_status("Connected")))

        self._executor.submit(task)

    def _run_on_all(self, method_name: str, *args: Any) -> None:
        """Call method_name(*args) identically on every bulb in the current
        device/group selection - a group applies the same command to every member at
        once. Properties that can be split across a merged group (hue, brightness,
        saturation) go through _dispatch_colour_data/_dispatch_brightness_only
        instead."""
        self._dispatch([(bulb, method_name, args) for bulb in self._active_bulbs])

    def _active_merge_group(self) -> DeviceGroup | None:
        """The active target's DeviceGroup if it's a merged group, else None (a plain
        device, an unmerged group, or nothing configured)."""
        key = self._devices_config.active_selection
        if not key.startswith(GROUP_SELECTION_PREFIX):
            return None
        group_id = key[len(GROUP_SELECTION_PREFIX):]
        group = next((g for g in self._devices_config.groups if g.group_id == group_id), None)
        return group if group is not None and group.merged else None

    def _build_split_ranks(self) -> list[int | None]:
        """Parallel to self._active_bulbs/_active_devices: each active device's rank
        (0=BASE, 1=EXT-1, ...) within the active merged group, or None if it has no
        position (or the target isn't a merged group at all) - such a device always
        gets the plain, unsplit value regardless of the split checkboxes."""
        group = self._active_merge_group()
        if group is None:
            return [None] * len(self._active_devices)
        rank_by_id = {device_id: rank for rank, device_id in enumerate(devices_config.ordered_merge_device_ids(group))}
        return [rank_by_id.get(device.device_id) for device in self._active_devices]

    def _dispatch_colour_data(self, hue: int, saturation: int, value: int, switch_mode: bool) -> None:
        """Send hue/saturation/value to every active bulb, splitting whichever of
        them has its checkbox checked positionally across a merged group's positioned
        members - see src/tuya/device.py's split_value_across_bulbs. Unpositioned
        members and non-split properties get the plain value, same as a normal
        group."""
        method = "set_color" if switch_mode else "set_colour_data_value"
        ranks = self._build_split_ranks()
        positioned_count = sum(1 for rank in ranks if rank is not None)
        if positioned_count < 2:
            self._run_on_all(method, hue, saturation, value)
            return
        hues = split_value_across_bulbs(hue, 360, positioned_count) if self._split_vars["hue"].get() else None
        saturations = (
            split_value_across_bulbs(saturation, 1000, positioned_count)
            if self._split_vars["saturation"].get() else None
        )
        values = (
            split_value_across_bulbs(value, 1000, positioned_count)
            if self._split_vars["brightness"].get() else None
        )
        calls = []
        for bulb, rank in zip(self._active_bulbs, ranks):
            h = hues[rank] if (hues is not None and rank is not None) else hue
            s = saturations[rank] if (saturations is not None and rank is not None) else saturation
            v = values[rank] if (values is not None and rank is not None) else value
            calls.append((bulb, method, (h, s, v)))
        self._dispatch(calls)

    def _dispatch_brightness_only(self, brightness: int) -> None:
        """White-mode brightness (DP 22): the only splittable property available
        there, so this is a narrower version of _dispatch_colour_data."""
        ranks = self._build_split_ranks()
        positioned_count = sum(1 for rank in ranks if rank is not None)
        if positioned_count < 2 or not self._split_vars["brightness"].get():
            self._run_on_all("set_brightness_value", brightness)
            return
        values = split_value_across_bulbs(brightness, 1000, positioned_count)
        calls = [
            (bulb, "set_brightness_value", (values[rank] if rank is not None else brightness,))
            for bulb, rank in zip(self._active_bulbs, ranks)
        ]
        self._dispatch(calls)

    def _apply_manual_result(self, apply: Callable[[], None]) -> None:
        """Ignore a manual-mode result that arrives after Audio Mode has taken over the
        status area, e.g. a colour pick issued right before switching modes resolving late."""
        if self._reactive_mode is None:
            apply()

    def _on_power_toggle(self) -> None:
        """Handle a click on the power switch."""
        on = self.power_var.get()
        self._set_status("Switching on..." if on else "Switching off...")
        self._run_on_all("turn_on" if on else "turn_off")

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
        if isinstance(self._reactive_mode, CustomMode):
            self._deactivate_row("brightness")
            self._reactive_mode.set_manual_override("brightness", brightness)
            self._current_state.value = brightness
            self._update_live_indicator()
            return
        if self._reactive_mode is not None:
            return  # Ambience Mode has no manual-override mechanism; the slider is disabled anyway
        if self._current_state.work_mode == WORK_MODE_COLOUR:
            self._current_state.value = brightness
            self._set_status(f"Setting brightness to {brightness}...")
            self._dispatch_colour_data(
                self._current_state.hue, self._current_state.saturation, brightness, switch_mode=False
            )
        else:
            self._current_state.brightness = brightness
            self._set_status(f"Setting brightness to {brightness}...")
            self._dispatch_brightness_only(brightness)
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
        if isinstance(self._reactive_mode, CustomMode):
            self._deactivate_row("saturation")
            self._reactive_mode.set_manual_override("saturation", value)
            self._current_state.saturation = value
            self._update_live_indicator()
            return
        if self._reactive_mode is not None:
            return  # Ambience Mode has no manual-override mechanism; the slider is disabled anyway
        if self._current_state.work_mode == WORK_MODE_COLOUR:
            self._current_state.saturation = value
            self._set_status(f"Setting saturation to {value}...")
            self._dispatch_colour_data(self._current_state.hue, value, self._current_state.value, switch_mode=False)
        else:
            self._current_state.temperature = value
            self._set_status(f"Setting temperature to {value}...")
            self._run_on_all("set_temperature", value)
        self._update_live_indicator()

    def _on_colour_pick(self, hsv: tuple[int, int, int]) -> None:
        """Handle a click on a palette swatch (or a live update from the colour picker
        window): sets the bulb directly, or (if Audio Mode is running) takes the Hue
        property away from whatever source was driving it."""
        hue, saturation, value = hsv
        if isinstance(self._reactive_mode, CustomMode):
            self._deactivate_row("hue")
            self._reactive_mode.set_manual_override("hue", hue)
            self._current_state.hue = hue
            self._update_live_indicator()
            return
        if self._reactive_mode is not None:
            return  # Ambience Mode has no manual-override mechanism; the palette is disabled anyway
        self._current_state.work_mode = WORK_MODE_COLOUR
        self._current_state.hue = hue
        self._current_state.saturation = saturation
        self._current_state.value = value
        self._update_temperature_label()
        self._set_saturation_slider_value(saturation)
        self.brightness_slider.set(value)
        self._set_status("Setting colour...")
        self._dispatch_colour_data(hue, saturation, value, switch_mode=True)
        self._update_live_indicator()

    def _on_white_click(self) -> None:
        """The only way to explicitly enter white mode - brightness/temperature no
        longer switch modes themselves, only operate within whichever is active."""
        if not self._active_bulbs or self._reactive_mode is not None:
            return
        self._current_state.work_mode = WORK_MODE_WHITE
        self._update_temperature_label()
        self.brightness_slider.set(self._current_state.brightness)
        self.temperature_slider.set(self._current_state.temperature)
        self._set_status("Switching to white...")
        self._run_on_all("set_work_mode", WORK_MODE_WHITE)
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
        """Reflect self._current_state's colour and brightness as a radial glow behind
        the logo, so the indicator mirrors what the physical bulb should currently
        look like - including live updates from Audio Mode via _on_reactive_mode_update."""
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
        center_rgb = tuple(round(channel * brightness_fraction) for channel in base)
        edge_color = self._apply_appearance_mode(ctk.ThemeManager.theme["CTk"]["fg_color"])
        # winfo_rgb resolves *any* valid Tk colour spec (named like "gray86" or a
        # "#rrggbb" hex string) to 16-bit-per-channel values - _hex_to_rgb alone can't
        # handle the named-colour case, which this theme colour sometimes is.
        edge_rgb = tuple(channel // 256 for channel in self.winfo_rgb(edge_color))
        self._live_indicator_bg_photo = _render_radial_glow(
            LIVE_INDICATOR_WIDTH, LIVE_INDICATOR_HEIGHT, center_rgb, edge_rgb
        )
        self.live_indicator.itemconfig(self._live_indicator_bg_item, image=self._live_indicator_bg_photo)

    def _load_logo(self) -> tkinter.PhotoImage | None:
        """Load and downscale the bundled logo for the live-state indicator, or None
        if it's missing - the logo is optional decoration, not required to run."""
        path = _app_root_dir() / LOGO_FILENAME
        if not path.exists():
            return None
        try:
            full = tkinter.PhotoImage(file=str(path))
            factor = max(1, round(full.width() / LOGO_DISPLAY_SIZE))
            return full.subsample(factor, factor)
        except tkinter.TclError:
            return None

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
        """Open the colour-picker window (or just bring it to front if already open).
        Blocked during Ambience Mode, which has no manual-override mechanism (unlike
        Audio Mode, where picking a colour is a supported override)."""
        if not self._active_bulbs or (self._reactive_mode is not None and not isinstance(self._reactive_mode, CustomMode)):
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

    # -- Audio Mode / Ambience Mode -------------------------------------------------

    def _build_reactive_mode_bulbs(self) -> list[TuyaBulb]:
        """Dedicated bulb handles for a reactive mode's hot loop (Audio Mode or
        Ambience Mode), one per active device (a group runs the same show on every
        member at once): each fails fast and keeps a persistent connection open
        instead of reconnecting for every update - see src/modes/custom_mode.py for
        why that combination matters."""
        return [
            TuyaBulb(
                device.device_id, device.ip_address, device.local_key, version=device.protocol_version,
                timeout=REACTIVE_MODE_TIMEOUT_SECONDS, retry_attempts=1, persistent=True,
            )
            for device in self._active_devices
        ]

    def _cancel_pending_slider_updates(self) -> None:
        if self._slider_after_id is not None:
            self.after_cancel(self._slider_after_id)
            self._slider_after_id = None
        if self._temperature_after_id is not None:
            self.after_cancel(self._temperature_after_id)
            self._temperature_after_id = None

    def _set_manual_override_controls_enabled(self, enabled: bool) -> None:
        """Brightness/temperature/palette stay live during Audio Mode (a manual touch
        hands that one property back from whatever source is driving it - see
        CustomMode.set_manual_override), but Ambience Mode has no per-property
        assignment to hand back, so they're disabled outright while it runs rather
        than fighting a mode that would just overwrite them again within one send
        interval."""
        state = "normal" if enabled else "disabled"
        self.brightness_slider.configure(state=state)
        self.temperature_slider.configure(state=state)
        for swatch in self.palette_frame.winfo_children():
            if isinstance(swatch, ctk.CTkButton):
                swatch.configure(state=state)

    def _on_audio_mode_toggle_click(self) -> None:
        if isinstance(self._reactive_mode, CustomMode):
            self._deactivate_reactive_mode()
        elif self._reactive_mode is None:
            self._activate_audio_mode()

    def _on_ambience_mode_toggle_click(self) -> None:
        if isinstance(self._reactive_mode, AmbienceMode):
            self._deactivate_reactive_mode()
        elif self._reactive_mode is None:
            self._activate_ambience_mode()

    def _activate_audio_mode(self) -> None:
        self._cancel_pending_slider_updates()
        self._set_status("Reading current state...")
        self._run_async(self._active_bulbs[0].status, on_success=self._start_audio_mode)

    def _activate_ambience_mode(self) -> None:
        self._cancel_pending_slider_updates()
        self._set_status("Reading current state...")
        self._run_async(self._active_bulbs[0].status, on_success=self._start_ambience_mode)

    def _begin_reactive_mode(self, snapshot: BulbSnapshot) -> int:
        """Shared setup for either reactive mode: seed state, disable the controls
        that don't apply while something else is driving the bulb(s), and return the
        initial brightness for whichever mode needs it (Audio Mode's Custom Mode)."""
        self._pre_reactive_state = snapshot
        self._current_state = snapshot
        self._current_state.work_mode = WORK_MODE_COLOUR  # both reactive modes always drive colour_data
        self._update_temperature_label()
        self.white_button.configure(state="disabled")
        self.target_selector.configure(state="disabled")
        for checkbox in self._split_checkboxes.values():
            checkbox.configure(state="disabled")
        return snapshot.brightness if snapshot.work_mode == WORK_MODE_WHITE else snapshot.value

    def _start_audio_mode(self, status: dict) -> None:
        snapshot = _snapshot_from_status(status)
        initial_brightness = self._begin_reactive_mode(snapshot)
        split_targets = {target: var.get() for target, var in self._split_vars.items()}
        self._reactive_mode = CustomMode(
            self._build_reactive_mode_bulbs(), dict(self._mode3_assignment), dict(self._sensitivity),
            initial_hue=snapshot.hue, initial_saturation=snapshot.saturation,
            initial_brightness=initial_brightness,
            on_error=self._on_reactive_mode_error, on_recovered=self._on_reactive_mode_recovered,
            on_update=self._on_reactive_mode_update,
            split_targets=split_targets, split_ranks=self._build_split_ranks(),
        )
        self.ambience_button.configure(state="disabled")
        self.audio_mode_button.configure(text="Deactivate Audio Mode")
        self._reactive_mode_status_label = "Audio mode active"
        self._set_status(self._reactive_mode_status_label)
        self._reactive_mode.start()

    def _start_ambience_mode(self, status: dict) -> None:
        snapshot = _snapshot_from_status(status)
        self._begin_reactive_mode(snapshot)
        self._set_manual_override_controls_enabled(False)
        self._reactive_mode = AmbienceMode(
            self._build_reactive_mode_bulbs(),
            on_error=self._on_reactive_mode_error, on_recovered=self._on_reactive_mode_recovered,
            on_update=self._on_reactive_mode_update,
        )
        self.audio_mode_button.configure(state="disabled")
        self.ambience_button.configure(text="Deactivate Ambience")
        self._reactive_mode_status_label = "Ambience mode active"
        self._set_status(self._reactive_mode_status_label)
        self._reactive_mode.start()

    def _deactivate_reactive_mode(self) -> None:
        was_ambience = isinstance(self._reactive_mode, AmbienceMode)
        self._reactive_mode.stop()
        self._reactive_mode = None
        self._reactive_mode_status_label = ""
        self.white_button.configure(state="normal")
        self.target_selector.configure(state="normal")
        for checkbox in self._split_checkboxes.values():
            checkbox.configure(state="normal")
        self.audio_mode_button.configure(state="normal", text="Activate Audio Mode")
        self.ambience_button.configure(state="normal", text="Activate Ambience")
        if was_ambience:
            self._set_manual_override_controls_enabled(True)
        snapshot = self._pre_reactive_state
        self._pre_reactive_state = None
        if snapshot is not None:
            self._set_status("Restoring previous settings...")
            self._run_async(self._restore_snapshot, snapshot, on_success=lambda _: self._finish_deactivate(snapshot))
        else:
            self._finish_deactivate(None)

    def _restore_snapshot(self, snapshot: BulbSnapshot) -> None:
        """Put every active bulb back exactly how it was before Audio Mode took over.
        Runs on the background executor thread - network calls only, no widget access
        here."""
        for bulb in self._active_bulbs:
            if snapshot.work_mode == WORK_MODE_WHITE:
                bulb.set_work_mode(WORK_MODE_WHITE)
                bulb.set_brightness_value(snapshot.brightness)
                bulb.set_temperature_value(snapshot.temperature)
            else:
                bulb.set_color(snapshot.hue, snapshot.saturation, snapshot.value)

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
        self._run_async(self._active_bulbs[0].status, on_success=self._on_initial_status)

    def _on_reactive_mode_error(self, message: str) -> None:
        """Surface a capture/bulb error from whichever reactive mode is running. The
        status area stays visible and live while it runs, same as in manual mode."""
        self.after(0, lambda: self._set_status(f"{self._reactive_mode_status_label} error: {message}", error=True))

    def _on_reactive_mode_recovered(self) -> None:
        """Bulb commands are succeeding again after a prior error; clear the error state."""
        self.after(0, lambda: self._set_status(self._reactive_mode_status_label))

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
        """Manually controlling a property while Audio Mode is running hands control
        away from whatever source was assigned to it - both in the persisted config
        and, via the caller's own set_manual_override call, in the running mode.
        Callers only invoke this when Audio Mode is actually active: touching a
        slider/palette in plain manual mode must not silently clear a configured
        assignment the user hasn't activated Audio Mode to use yet."""
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

    def _update_merge_ui_visibility(self) -> None:
        """Show the Hue/Brightness/Saturation split checkboxes only while the active
        target is a merged group - they're meaningless for a single bulb or a plain
        (unmerged) group, where every bulb just mirrors the same command."""
        show = self._active_merge_group() is not None
        for checkbox in self._split_checkboxes.values():
            if show:
                checkbox.grid()
            else:
                checkbox.grid_remove()

    def _on_close(self) -> None:
        """Shut down background work before closing the window."""
        if self._reactive_mode is not None:
            self._reactive_mode.stop()
        self._executor.shutdown(wait=False)
        self.destroy()
