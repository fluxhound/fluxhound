"""Custom Trigger Editor (paid-tier): lets the user add any number of extra
watched screen regions on top of Gaming Mode's built-in one, each with its own
fully custom TriggerConfig (thresholds, flash colours, multi-step glow bands)
instead of the fixed defaults every free-tier user gets.

Two windows: TriggerEditorWindow lists every custom watcher (add/remove/
configure); TriggerConfigEditorWindow is the full per-watcher editor (name,
region, sensitivity, flash colours, threshold bands). Both mutate the shared
AmbienceConfig in place and call on_change after every edit, matching
DevicesWindow's pattern - the caller (MainWindow) persists it and restarts
Ambience Mode's watchers if it's currently running.
"""
from __future__ import annotations

import colorsys
from typing import Callable

import customtkinter as ctk

from src.ambience_config import AmbienceConfig, AmbienceRegion, TriggerWatcher, new_watcher_id
from src.gui import theme
from src.gui.brush_selector_window import BrushSelectorWindow
from src.gui.colour_picker_window import ColourPickerWindow
from src.gui.devices_window import TextInputDialog
from src.screen.capture import list_monitors
from src.screen.health_bar import (
    DETECTION_MODE_AUTO,
    DETECTION_MODE_FILL_FRACTION,
    DETECTION_MODE_OCR,
    ThresholdBand,
    TriggerConfig,
    encode_region_mask,
)

_DETECTION_MODE_LABELS = {
    DETECTION_MODE_AUTO: "Auto (recommended)",
    DETECTION_MODE_FILL_FRACTION: "Fill colour",
    DETECTION_MODE_OCR: "Read number (OCR)",
}
_DETECTION_LABEL_TO_MODE = {label: mode for mode, label in _DETECTION_MODE_LABELS.items()}

ROW_PADY = 4


def _hsv1000_to_hex(hue: int, saturation: int, value: int) -> str:
    """hue 0-360, saturation/value 0-1000 (this app's usual colour_data scale) to
    a #rrggbb string, for a swatch button's fg_color."""
    r, g, b = colorsys.hsv_to_rgb((hue % 360) / 360.0, saturation / 1000.0, value / 1000.0)
    return f"#{int(round(r * 255)):02x}{int(round(g * 255)):02x}{int(round(b * 255)):02x}"


def _current_monitor(ambience_config: AmbienceConfig) -> dict | None:
    monitors = list_monitors()
    if not monitors:
        return None
    for monitor in monitors:
        if monitor["index"] == ambience_config.monitor_index:
            return monitor
    for monitor in monitors:
        if monitor.get("is_primary"):
            return monitor
    return monitors[0]


class TriggerEditorWindow(ctk.CTkToplevel):
    """Lists every custom trigger watcher, with add/remove and a "Configure"
    button per watcher opening its full TriggerConfig editor."""

    def __init__(self, master: ctk.CTk, ambience_config: AmbienceConfig, on_change: Callable[[], None]):
        super().__init__(master)
        self._ambience_config = ambience_config
        self._on_change = on_change
        self._region_selector_window: BrushSelectorWindow | None = None

        self.title("Custom Trigger Editor")
        theme.apply_icon(self)
        self.geometry("420x420")
        self.transient(master)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(16, 8))
        ctk.CTkLabel(header, text="Custom Trigger Editor", font=theme.font_heading()).pack(side="left")
        ctk.CTkButton(header, text="Add watcher", width=110, command=self._on_add_watcher_click).pack(side="right")

        ctk.CTkLabel(
            self,
            text="Extra screen regions watched alongside Gaming Mode's built-in one, "
                 "each with its own thresholds and flash colours.",
            wraplength=380, text_color=theme.TEXT_MUTED_COLOR, justify="left",
        ).pack(fill="x", padx=16, pady=(0, 8))

        self.scroll_frame = ctk.CTkScrollableFrame(self, width=380, height=280)
        self.scroll_frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        self.after(50, self._make_modal)
        self._render()

    def _make_modal(self) -> None:
        self.grab_set()

    # -- Mutations ------------------------------------------------------------------

    def _on_add_watcher_click(self) -> None:
        TextInputDialog(
            self, title="New watcher", label='Watcher name (e.g. "Mana orb")',
            on_save=self._prompt_region_for_new_watcher,
        )

    def _prompt_region_for_new_watcher(self, name: str) -> None:
        monitor = _current_monitor(self._ambience_config)
        if monitor is None:
            return
        if self._region_selector_window is not None and self._region_selector_window.winfo_exists():
            self._region_selector_window.lift()
            return
        self._region_selector_window = BrushSelectorWindow(
            self, monitor, on_select=lambda x, y, w, h, mask: self._add_watcher(name, x, y, w, h, mask)
        )

    def _add_watcher(self, name: str, x: int, y: int, width: int, height: int, mask) -> None:
        watcher = TriggerWatcher(
            watcher_id=new_watcher_id(), name=name,
            region=AmbienceRegion(x=x, y=y, width=width, height=height, mask=encode_region_mask(mask)),
            config=TriggerConfig(),
        )
        self._ambience_config.trigger_watchers.append(watcher)
        self._changed()

    def _on_remove_click(self, watcher: TriggerWatcher) -> None:
        self._ambience_config.trigger_watchers.remove(watcher)
        self._changed()

    def _on_configure_click(self, watcher: TriggerWatcher) -> None:
        TriggerConfigEditorWindow(self, ambience_config=self._ambience_config, watcher=watcher, on_change=self._changed)

    def _changed(self) -> None:
        self._on_change()
        self._render()

    # -- Rendering ------------------------------------------------------------------

    def _render(self) -> None:
        for child in self.scroll_frame.winfo_children():
            child.destroy()
        if not self._ambience_config.trigger_watchers:
            ctk.CTkLabel(
                self.scroll_frame,
                text='No custom watchers yet. Click "Add watcher" to watch another screen '
                     "region with its own thresholds and colours.",
                wraplength=340, text_color=theme.TEXT_MUTED_COLOR, justify="left",
            ).pack(pady=8)
            return
        for watcher in self._ambience_config.trigger_watchers:
            self._render_watcher_row(watcher)

    def _render_watcher_row(self, watcher: TriggerWatcher) -> None:
        # Action buttons packed right first, label last with fill+expand - keeps
        # them from being pushed out of the scroll frame's fixed width by a long
        # name (see devices_window.py's DevicesWindow for the same fix and why).
        row = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        row.pack(fill="x", pady=ROW_PADY)
        ctk.CTkButton(
            row, text="Remove", width=70, fg_color=theme.SECONDARY_BUTTON_COLOR, hover_color=theme.SECONDARY_BUTTON_HOVER_COLOR, command=lambda: self._on_remove_click(watcher)
        ).pack(side="right", padx=4)
        ctk.CTkButton(
            row, text="Configure", width=90, command=lambda: self._on_configure_click(watcher)
        ).pack(side="right", padx=4)
        ctk.CTkLabel(row, text=watcher.name, anchor="w").pack(side="left", fill="x", expand=True)


class TriggerConfigEditorWindow(ctk.CTkToplevel):
    """Full editor for one custom watcher: name, region, sensitivity, flash
    colours, and its threshold_bands list (the "multi-step reactions")."""

    def __init__(self, master: ctk.CTk, ambience_config: AmbienceConfig, watcher: TriggerWatcher,
                 on_change: Callable[[], None]):
        super().__init__(master)
        self._ambience_config = ambience_config
        self._watcher = watcher
        self._on_change = on_change
        self._region_selector_window: BrushSelectorWindow | None = None

        self.title(f"Configure: {watcher.name}")
        theme.apply_icon(self)
        self.resizable(False, False)
        self.transient(master)

        name_row = ctk.CTkFrame(self, fg_color="transparent")
        name_row.pack(fill="x", padx=16, pady=(16, 4))
        self.name_label = ctk.CTkLabel(name_row, text=watcher.name, font=theme.font_subheading())
        self.name_label.pack(side="left")
        ctk.CTkButton(name_row, text="Rename", width=80, command=self._on_rename_click).pack(side="right")

        region_row = ctk.CTkFrame(self, fg_color="transparent")
        region_row.pack(fill="x", padx=16, pady=4)
        self.region_label = ctk.CTkLabel(region_row, text=self._region_text())
        self.region_label.pack(side="left")
        ctk.CTkButton(region_row, text="Change area", width=100, command=self._on_change_area_click).pack(side="right")

        detection_row = ctk.CTkFrame(self, fg_color="transparent")
        detection_row.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(detection_row, text="Detection").pack(side="left")
        self.detection_mode_menu = ctk.CTkOptionMenu(
            detection_row, values=list(_DETECTION_MODE_LABELS.values()), width=170,
            command=self._on_detection_mode_selected,
        )
        self.detection_mode_menu.set(
            _DETECTION_MODE_LABELS.get(watcher.config.detection_mode, _DETECTION_MODE_LABELS[DETECTION_MODE_AUTO])
        )
        self.detection_mode_menu.pack(side="right")

        # Shown in OCR and Auto modes (auto still needs it for its OCR side) -
        # used when the recognized text is a bare number with no "/max" or "%"
        # alongside it (see ocr_reader.parse_fraction). Defaults to 100 (see
        # TriggerConfig.ocr_max_value), so this is prefilled rather than blank.
        self.max_value_row = ctk.CTkFrame(self, fg_color="transparent")
        ctk.CTkLabel(self.max_value_row, text='Max value (if no "/max" shown)').pack(side="left")
        self.max_value_entry = ctk.CTkEntry(self.max_value_row, width=60)
        if watcher.config.ocr_max_value is not None:
            self.max_value_entry.insert(0, str(watcher.config.ocr_max_value))
        self.max_value_entry.bind("<Return>", self._on_max_value_entered)
        self.max_value_entry.bind("<FocusOut>", self._on_max_value_entered)
        self.max_value_entry.pack(side="right")

        self.epsilon_row = ctk.CTkFrame(self, fg_color="transparent")
        self.epsilon_row.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(self.epsilon_row, text="Change needed to trigger a flash (%)").pack(side="left")
        self.epsilon_entry = ctk.CTkEntry(self.epsilon_row, width=60)
        self.epsilon_entry.insert(0, str(round(watcher.config.change_epsilon * 100, 1)))
        self.epsilon_entry.bind("<Return>", self._on_epsilon_entered)
        self.epsilon_entry.bind("<FocusOut>", self._on_epsilon_entered)
        self.epsilon_entry.pack(side="right")

        duration_row = ctk.CTkFrame(self, fg_color="transparent")
        duration_row.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(duration_row, text="Flash duration (seconds)").pack(side="left")
        self.duration_entry = ctk.CTkEntry(duration_row, width=60)
        self.duration_entry.insert(0, str(watcher.config.blink_duration_seconds))
        self.duration_entry.bind("<Return>", self._on_duration_entered)
        self.duration_entry.bind("<FocusOut>", self._on_duration_entered)
        self.duration_entry.pack(side="right")

        decrease_row = ctk.CTkFrame(self, fg_color="transparent")
        decrease_row.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(decrease_row, text="Flash colour on decrease").pack(side="left")
        self.decrease_swatch = ctk.CTkButton(
            decrease_row, text="", width=32, height=24,
            fg_color=_hsv1000_to_hex(*watcher.config.decrease_colour),
            command=lambda: self._open_colour_picker("decrease_colour"),
        )
        self.decrease_swatch.pack(side="right")

        increase_row = ctk.CTkFrame(self, fg_color="transparent")
        increase_row.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(increase_row, text="Flash colour on increase").pack(side="left")
        self.increase_swatch = ctk.CTkButton(
            increase_row, text="", width=32, height=24,
            fg_color=_hsv1000_to_hex(*watcher.config.increase_colour),
            command=lambda: self._open_colour_picker("increase_colour"),
        )
        self.increase_swatch.pack(side="right")

        ctk.CTkLabel(
            self,
            text="Threshold bands (multi-step glow): hold a colour continuously while the "
                 "fill stays at or below a threshold. The lowest matching threshold wins.",
            wraplength=340, text_color=theme.TEXT_MUTED_COLOR, justify="left",
        ).pack(fill="x", padx=16, pady=(16, 4))

        self.bands_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.bands_frame.pack(fill="x", padx=16, pady=(0, 4))

        ctk.CTkButton(self, text="Add band", width=100, command=self._on_add_band_click).pack(
            padx=16, pady=(0, 8), anchor="w"
        )

        ctk.CTkButton(self, text="Done", command=self.destroy).pack(pady=(4, 16))

        self._render_bands()
        self._update_max_value_visibility()
        self.after(50, self._make_modal)

    def _make_modal(self) -> None:
        self.grab_set()

    def _region_text(self) -> str:
        region = self._watcher.region
        shape = " (painted shape)" if region.mask else ""
        return f"Region: {region.width}x{region.height} at ({region.x}, {region.y}){shape}"

    # -- Detection mode -----------------------------------------------------------------

    def _on_detection_mode_selected(self, choice: str) -> None:
        self._watcher.config.detection_mode = _DETECTION_LABEL_TO_MODE[choice]
        self._update_max_value_visibility()
        self._on_change()

    def _update_max_value_visibility(self) -> None:
        if self._watcher.config.detection_mode in (DETECTION_MODE_OCR, DETECTION_MODE_AUTO):
            self.max_value_row.pack(fill="x", padx=16, pady=(0, 4), before=self.epsilon_row)
        else:
            self.max_value_row.pack_forget()

    def _on_max_value_entered(self, event: object = None) -> None:
        text = self.max_value_entry.get().strip()
        if not text:
            self._watcher.config.ocr_max_value = None
            self._on_change()
            return
        try:
            value = float(text)
        except ValueError:
            return
        self._watcher.config.ocr_max_value = value if value > 0 else None
        self._on_change()

    # -- Name / region ----------------------------------------------------------------

    def _on_rename_click(self) -> None:
        TextInputDialog(
            self, title="Rename watcher", label="Watcher name", initial=self._watcher.name, on_save=self._rename
        )

    def _rename(self, name: str) -> None:
        self._watcher.name = name
        self.name_label.configure(text=name)
        self.title(f"Configure: {name}")
        self._on_change()

    def _on_change_area_click(self) -> None:
        monitor = _current_monitor(self._ambience_config)
        if monitor is None:
            return
        if self._region_selector_window is not None and self._region_selector_window.winfo_exists():
            self._region_selector_window.lift()
            return
        self._region_selector_window = BrushSelectorWindow(self, monitor, on_select=self._set_region)

    def _set_region(self, x: int, y: int, width: int, height: int, mask) -> None:
        self._watcher.region = AmbienceRegion(x=x, y=y, width=width, height=height, mask=encode_region_mask(mask))
        self.region_label.configure(text=self._region_text())
        self._on_change()

    # -- Sensitivity / duration ---------------------------------------------------------

    def _on_epsilon_entered(self, event: object = None) -> None:
        try:
            percent = float(self.epsilon_entry.get())
        except ValueError:
            return
        self._watcher.config.change_epsilon = max(0.0, min(100.0, percent)) / 100.0
        self._on_change()

    def _on_duration_entered(self, event: object = None) -> None:
        try:
            seconds = float(self.duration_entry.get())
        except ValueError:
            return
        self._watcher.config.blink_duration_seconds = max(0.0, seconds)
        self._on_change()

    # -- Flash colours ------------------------------------------------------------------

    def _open_colour_picker(self, field_name: str) -> None:
        hue, saturation, value = getattr(self._watcher.config, field_name)

        def on_pick(h: int, s: int, v: int) -> None:
            setattr(self._watcher.config, field_name, (h, s, v))
            swatch = self.decrease_swatch if field_name == "decrease_colour" else self.increase_swatch
            swatch.configure(fg_color=_hsv1000_to_hex(h, s, v))
            self._on_change()

        ColourPickerWindow(self, initial_hue=hue, initial_saturation=saturation, initial_value=value, on_pick=on_pick)

    # -- Threshold bands ------------------------------------------------------------------

    def _on_add_band_click(self) -> None:
        self._watcher.config.threshold_bands.append(ThresholdBand(threshold=0.1, colour=(0, 1000, 1000)))
        self._on_change()
        self._render_bands()

    def _on_remove_band_click(self, band: ThresholdBand) -> None:
        self._watcher.config.threshold_bands.remove(band)
        self._on_change()
        self._render_bands()

    def _on_band_threshold_entered(self, band: ThresholdBand, entry: ctk.CTkEntry, event: object = None) -> None:
        try:
            percent = float(entry.get())
        except ValueError:
            return
        band.threshold = max(0.0, min(100.0, percent)) / 100.0
        self._on_change()
        self._render_bands()

    def _open_band_colour_picker(self, band: ThresholdBand, swatch: ctk.CTkButton) -> None:
        def on_pick(h: int, s: int, v: int) -> None:
            band.colour = (h, s, v)
            swatch.configure(fg_color=_hsv1000_to_hex(h, s, v))
            self._on_change()

        ColourPickerWindow(
            self, initial_hue=band.colour[0], initial_saturation=band.colour[1], initial_value=band.colour[2],
            on_pick=on_pick,
        )

    def _render_bands(self) -> None:
        for child in self.bands_frame.winfo_children():
            child.destroy()
        if not self._watcher.config.threshold_bands:
            ctk.CTkLabel(
                self.bands_frame, text="No bands - no continuous glow reaction.", text_color=theme.TEXT_MUTED_COLOR
            ).pack(anchor="w")
            return
        for band in sorted(self._watcher.config.threshold_bands, key=lambda b: b.threshold):
            row = ctk.CTkFrame(self.bands_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkButton(
                row, text="x", width=24, fg_color=theme.SECONDARY_BUTTON_COLOR, hover_color=theme.SECONDARY_BUTTON_HOVER_COLOR, command=lambda b=band: self._on_remove_band_click(b)
            ).pack(side="right", padx=(4, 0))
            swatch = ctk.CTkButton(row, text="", width=32, height=24, fg_color=_hsv1000_to_hex(*band.colour))
            swatch.configure(command=lambda b=band, s=swatch: self._open_band_colour_picker(b, s))
            swatch.pack(side="right", padx=4)
            ctk.CTkLabel(row, text="at or below").pack(side="left")
            entry = ctk.CTkEntry(row, width=50)
            entry.insert(0, str(round(band.threshold * 100, 1)))
            entry.pack(side="left", padx=4)
            entry.bind("<Return>", lambda e, b=band, en=entry: self._on_band_threshold_entered(b, en, e))
            entry.bind("<FocusOut>", lambda e, b=band, en=entry: self._on_band_threshold_entered(b, en, e))
            ctk.CTkLabel(row, text="%").pack(side="left")
