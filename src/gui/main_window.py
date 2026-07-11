"""Main application window (customtkinter)."""
from __future__ import annotations

import colorsys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

import customtkinter as ctk

from src import device_config
from src.audio.custom_show import SOURCES, TARGETS
from src.device_config import DeviceConfig
from src.gui.device_config_dialog import DeviceConfigDialog
from src.modes.custom_mode import CustomMode
from src.modes.music_mode import MusicMode
from src.modes.spectrum_mode import SpectrumMode
from src.tuya.device import (
    DP_BRIGHTNESS,
    DP_COLOR_TEMP,
    DP_COLOUR_DATA,
    DP_SWITCH,
    DP_WORK_MODE,
    TuyaBulb,
    TuyaConnectionError,
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
MODE3_SELECTED_COLOR = ("#2563eb", "#1d4ed8")
MODE3_DISABLED_COLOR = ("gray80", "gray22")

SOURCE_LABELS = {"timbre": "Timbre", "energy": "Energy", "beat": "Beat"}
TARGET_LABELS = {"hue": "Hue", "brightness": "Brightness", "saturation": "Saturation"}
DEFAULT_MODE3_ASSIGNMENT: dict[str, str | None] = {"hue": "timbre", "brightness": "energy", "saturation": "beat"}

# Music mode hammers the bulb with frequent updates, so it gets its own bulb handle
# tuned to fail fast (no retry, short timeout) instead of the multi-second retry
# used for one-off manual commands - see src/modes/music_mode.py for why.
MUSIC_MODE_TIMEOUT_SECONDS = 1.5


def _hue_to_hex(hue: int) -> str:
    """Convert a hue (0-360) at full saturation/value to a #rrggbb string for swatch previews."""
    r, g, b = colorsys.hsv_to_rgb(hue / 360, 1.0, 1.0)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


@dataclass
class BulbSnapshot:
    """The bulb's manual-mode state at the moment a reactive mode takes over, so it can
    be restored exactly on exit instead of being left at whatever the reactive mode did."""

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
    """FluxHound main window: manual control (on/off, brightness, colour) of one test bulb."""

    def __init__(self):
        super().__init__()
        self.bulb: TuyaBulb | None = None
        self._device_config: DeviceConfig | None = None
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._slider_after_id: str | None = None
        self._temperature_after_id: str | None = None
        self._reactive_mode: MusicMode | SpectrumMode | CustomMode | None = None
        self._pre_reactive_state: BulbSnapshot | None = None
        self._mode3_assignment: dict[str, str | None] = dict(DEFAULT_MODE3_ASSIGNMENT)

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
        self.music_button.pack(pady=(0, 8))

        self.music_button_2 = ctk.CTkButton(
            self, text="Music Mode 2", width=140, command=self._on_music_mode_2_click
        )
        self.music_button_2.pack(pady=(0, 8))

        self.music_button_3 = ctk.CTkButton(
            self, text="Music Mode 3", width=140, command=self._on_music_mode_3_click
        )
        self.music_button_3.pack(pady=(0, 12))

        self.mode3_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._mode3_buttons: dict[tuple[str, str], ctk.CTkButton] = {}
        self._mode3_default_fg_color: dict[tuple[str, str], Any] = {}
        for row, target in enumerate(TARGETS):
            ctk.CTkLabel(self.mode3_frame, text=TARGET_LABELS[target], width=80, anchor="w").grid(
                row=row, column=0, padx=(0, 8), pady=6, sticky="w"
            )
            for column, source in enumerate(SOURCES):
                button = ctk.CTkButton(
                    self.mode3_frame, text=SOURCE_LABELS[source], width=76,
                    command=lambda t=target, s=source: self._on_mode3_source_click(t, s),
                )
                button.grid(row=row, column=column + 1, padx=4, pady=6)
                self._mode3_buttons[(target, source)] = button
                self._mode3_default_fg_color[(target, source)] = button.cget("fg_color")
        self._refresh_mode3_buttons()

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
        self.music_button_2.configure(state=state)
        self.music_button_3.configure(state=state)
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
        """Ignore a manual-mode result that arrives after a reactive mode has taken over the
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
        """Handle a click on a palette swatch: sets the bulb directly, or Music Mode's output.

        Only Music Mode (not Music Mode 2/3, which are fully audio-driven) exposes this -
        the palette isn't shown in their layouts, but the isinstance check keeps this
        correct even if that ever changes.
        """
        hue, saturation, value = hsv
        if isinstance(self._reactive_mode, MusicMode):
            self._reactive_mode.set_colour(hue)
            return
        self._set_status("Setting colour...")
        self._run_async(
            self.bulb.set_color, hue, saturation, value, on_success=lambda _: self._set_status("Connected")
        )

    def _on_white_click(self) -> None:
        """Handle the 'White' button, only shown in Music Mode: switch its output to white."""
        if isinstance(self._reactive_mode, MusicMode):
            self._reactive_mode.set_white()

    # -- Reactive modes (Music Mode / 2 / 3) --------------------------------

    def _build_reactive_mode_bulb(self) -> TuyaBulb:
        """A dedicated bulb handle for a reactive mode's hot loop: fails fast and keeps one
        persistent connection open instead of reconnecting for every update - see
        src/modes/music_mode.py for why that combination matters."""
        return TuyaBulb(
            self._device_config.device_id, self._device_config.ip_address, self._device_config.local_key,
            version=self._device_config.protocol_version, timeout=MUSIC_MODE_TIMEOUT_SECONDS, retry_attempts=1,
            persistent=True,
        )

    def _cancel_pending_slider_updates(self) -> None:
        if self._slider_after_id is not None:
            self.after_cancel(self._slider_after_id)
            self._slider_after_id = None
        if self._temperature_after_id is not None:
            self.after_cancel(self._temperature_after_id)
            self._temperature_after_id = None

    def _reactive_mode_label(self) -> str:
        """Short name of the currently-running reactive mode, for status messages."""
        if isinstance(self._reactive_mode, SpectrumMode):
            return "Music mode 2"
        if isinstance(self._reactive_mode, CustomMode):
            return "Music mode 3"
        return "Music mode"

    def _on_music_mode_click(self) -> None:
        """Enter Music Mode: hide manual controls, start analysing system audio."""
        self._cancel_pending_slider_updates()
        self._set_status("Reading current state...")
        self._run_async(self.bulb.status, on_success=self._start_music_mode)

    def _start_music_mode(self, status: dict) -> None:
        snapshot = _snapshot_from_status(status)
        self._pre_reactive_state = snapshot
        self._show_music_mode_controls()
        initial_brightness = snapshot.brightness if snapshot.work_mode == WORK_MODE_WHITE else snapshot.value
        self._reactive_mode = MusicMode(
            self._build_reactive_mode_bulb(),
            initial_output_mode=snapshot.work_mode, initial_hue=snapshot.hue,
            initial_brightness=initial_brightness,
            on_error=self._on_reactive_mode_error, on_recovered=self._on_reactive_mode_recovered,
        )
        self._set_status(f"{self._reactive_mode_label()} active")
        self._reactive_mode.start()

    def _on_music_mode_2_click(self) -> None:
        """Enter Music Mode 2 (Spectrum Mode): fully autonomous full-spectrum light show."""
        self._cancel_pending_slider_updates()
        self._set_status("Reading current state...")
        self._run_async(self.bulb.status, on_success=self._start_spectrum_mode)

    def _start_spectrum_mode(self, status: dict) -> None:
        snapshot = _snapshot_from_status(status)
        self._pre_reactive_state = snapshot
        self._show_spectrum_mode_controls()
        initial_brightness = snapshot.brightness if snapshot.work_mode == WORK_MODE_WHITE else snapshot.value
        self._reactive_mode = SpectrumMode(
            self._build_reactive_mode_bulb(),
            initial_hue=snapshot.hue, initial_saturation=snapshot.saturation,
            initial_brightness=initial_brightness,
            on_error=self._on_reactive_mode_error, on_recovered=self._on_reactive_mode_recovered,
        )
        self._set_status(f"{self._reactive_mode_label()} active")
        self._reactive_mode.start()

    def _on_music_mode_3_click(self) -> None:
        """Enter Music Mode 3 (Custom Mode): user-assigned source-to-target mapping."""
        self._cancel_pending_slider_updates()
        self._set_status("Reading current state...")
        self._run_async(self.bulb.status, on_success=self._start_custom_mode)

    def _start_custom_mode(self, status: dict) -> None:
        snapshot = _snapshot_from_status(status)
        self._pre_reactive_state = snapshot
        self._show_mode3_controls()
        initial_brightness = snapshot.brightness if snapshot.work_mode == WORK_MODE_WHITE else snapshot.value
        self._reactive_mode = CustomMode(
            self._build_reactive_mode_bulb(), dict(self._mode3_assignment),
            initial_hue=snapshot.hue, initial_saturation=snapshot.saturation,
            initial_brightness=initial_brightness,
            on_error=self._on_reactive_mode_error, on_recovered=self._on_reactive_mode_recovered,
        )
        self._set_status(f"{self._reactive_mode_label()} active")
        self._reactive_mode.start()

    def _on_exit_music_mode_click(self) -> None:
        """Leave whichever reactive mode is running, restore the settings from before it
        took over, and go back to manual control."""
        if self._reactive_mode is not None:
            self._reactive_mode.stop()
            self._reactive_mode = None
        self._show_normal_controls()
        snapshot = self._pre_reactive_state
        self._pre_reactive_state = None
        if snapshot is not None:
            self._set_status("Restoring previous settings...")
            self._run_async(self._restore_snapshot, snapshot, on_success=lambda _: self._finish_exit(snapshot))
        else:
            self._finish_exit(None)

    def _restore_snapshot(self, snapshot: BulbSnapshot) -> None:
        """Put the bulb back exactly how it was before a reactive mode took over. Runs on
        the background executor thread - network calls only, no widget access here."""
        if snapshot.work_mode == WORK_MODE_WHITE:
            self.bulb.set_work_mode(WORK_MODE_WHITE)
            self.bulb.set_brightness_value(snapshot.brightness)
            self.bulb.set_temperature_value(snapshot.temperature)
        else:
            self.bulb.set_color(snapshot.hue, snapshot.saturation, snapshot.value)

    def _finish_exit(self, snapshot: BulbSnapshot | None) -> None:
        """Sync the slider widgets to the restored values (main thread) and re-sync status."""
        if snapshot is not None:
            self.brightness_slider.set(snapshot.brightness)
            self.temperature_slider.set(snapshot.temperature)
        self._run_async(self.bulb.status, on_success=self._on_initial_status)

    def _on_reactive_mode_error(self, message: str) -> None:
        """Surface an audio/bulb error from a reactive mode's background thread. The status
        area stays visible and live in these modes, same as in manual mode."""
        label = self._reactive_mode_label()
        self.after(0, lambda: self._set_status(f"{label} error: {message}", error=True))

    def _on_reactive_mode_recovered(self) -> None:
        """Bulb commands are succeeding again after a prior error; clear the error state."""
        label = self._reactive_mode_label()
        self.after(0, lambda: self._set_status(f"{label} active"))

    # -- Music Mode 3 assignment grid ----------------------------------------------

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
        self._refresh_mode3_buttons()
        if isinstance(self._reactive_mode, CustomMode):
            self._reactive_mode.set_assignment(target, self._mode3_assignment[target])

    def _refresh_mode3_buttons(self) -> None:
        """Update the assignment grid's selected/disabled visuals to match
        self._mode3_assignment, which persists across mode switches by design."""
        assigned_sources = {source for source in self._mode3_assignment.values() if source is not None}
        for (target, source), button in self._mode3_buttons.items():
            selected = self._mode3_assignment.get(target) == source
            taken_elsewhere = source in assigned_sources and not selected
            if selected:
                button.configure(state="normal", fg_color=MODE3_SELECTED_COLOR)
            elif taken_elsewhere:
                button.configure(state="disabled", fg_color=MODE3_DISABLED_COLOR)
            else:
                button.configure(state="normal", fg_color=self._mode3_default_fg_color[(target, source)])

    # -- Layouts ---------------------------------------------------------------

    def _show_normal_controls(self) -> None:
        """Layout for manual control: everything except the reactive-mode-only widgets."""
        self.white_button.pack_forget()
        self.mode3_frame.pack_forget()
        self.exit_music_button.pack_forget()
        self.configure_button.pack(pady=(0, 12))
        self.power_switch.pack(pady=8)
        self.brightness_label.pack(pady=(12, 0))
        self.brightness_slider.pack(padx=24, pady=(4, 12), fill="x")
        self.temperature_label.pack(pady=(4, 0))
        self.temperature_slider.pack(padx=24, pady=(4, 12), fill="x")
        self.colour_label.pack(pady=(4, 4))
        self.palette_frame.pack(pady=(0, 12))
        self.music_button.pack(pady=(0, 8))
        self.music_button_2.pack(pady=(0, 8))
        self.music_button_3.pack(pady=(0, 12))

    def _show_music_mode_controls(self) -> None:
        """Layout for Music Mode: only colour choice (colour or white) and exit remain."""
        self.configure_button.pack_forget()
        self.power_switch.pack_forget()
        self.brightness_label.pack_forget()
        self.brightness_slider.pack_forget()
        self.temperature_label.pack_forget()
        self.temperature_slider.pack_forget()
        self.music_button.pack_forget()
        self.music_button_2.pack_forget()
        self.music_button_3.pack_forget()
        self.mode3_frame.pack_forget()
        self.colour_label.pack(pady=(4, 4))
        self.palette_frame.pack(pady=(0, 12))
        self.white_button.pack(pady=(0, 12))
        self.exit_music_button.pack(pady=(8, 24))

    def _show_spectrum_mode_controls(self) -> None:
        """Layout for Music Mode 2: nothing to pick, it's fully audio-driven - just exit."""
        self.configure_button.pack_forget()
        self.power_switch.pack_forget()
        self.brightness_label.pack_forget()
        self.brightness_slider.pack_forget()
        self.temperature_label.pack_forget()
        self.temperature_slider.pack_forget()
        self.colour_label.pack_forget()
        self.palette_frame.pack_forget()
        self.white_button.pack_forget()
        self.music_button.pack_forget()
        self.music_button_2.pack_forget()
        self.music_button_3.pack_forget()
        self.mode3_frame.pack_forget()
        self.exit_music_button.pack(pady=(24, 24))

    def _show_mode3_controls(self) -> None:
        """Layout for Music Mode 3: the source/target assignment grid, plus exit."""
        self.configure_button.pack_forget()
        self.power_switch.pack_forget()
        self.brightness_label.pack_forget()
        self.brightness_slider.pack_forget()
        self.temperature_label.pack_forget()
        self.temperature_slider.pack_forget()
        self.colour_label.pack_forget()
        self.palette_frame.pack_forget()
        self.white_button.pack_forget()
        self.music_button.pack_forget()
        self.music_button_2.pack_forget()
        self.music_button_3.pack_forget()
        self._refresh_mode3_buttons()
        self.mode3_frame.pack(pady=(12, 12))
        self.exit_music_button.pack(pady=(8, 24))

    def _on_close(self) -> None:
        """Shut down background work before closing the window."""
        if self._reactive_mode is not None:
            self._reactive_mode.stop()
        self._executor.shutdown(wait=False)
        self.destroy()
