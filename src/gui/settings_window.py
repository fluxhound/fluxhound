"""Settings Toplevel opened from the main window's gear button.

A launcher for the Devices and License windows, structured as a list of
entries so more settings sections can be added later without changing what the
gear button itself does. Also hosts the two standalone toggles that don't
warrant their own window: minimize-to-tray-on-close and launch-at-Windows-
login.
"""
from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from src import autostart
from src.gui import theme
from src.gui.license_window import LicenseWindow


class SettingsWindow(ctk.CTkToplevel):
    """A small modal menu; picking an entry closes this window and opens the
    corresponding one, rather than stacking windows on top of each other."""

    def __init__(self, master: ctk.CTk, on_open_devices: Callable[[], None],
                 minimize_to_tray: bool, on_minimize_to_tray_change: Callable[[bool], None]):
        super().__init__(master)
        self._on_open_devices = on_open_devices
        self._on_minimize_to_tray_change = on_minimize_to_tray_change

        self.title("Settings")
        theme.apply_icon(self)
        self.geometry("280x360")
        self.resizable(False, False)
        self.transient(master)

        ctk.CTkLabel(self, text="Settings", font=theme.font_heading()).pack(pady=(20, 16))
        ctk.CTkButton(self, text="Devices", command=self._on_devices_click).pack(padx=20, pady=(0, 8), fill="x")
        ctk.CTkButton(self, text="License", command=self._on_license_click).pack(padx=20, fill="x")

        ctk.CTkLabel(
            self, text="Startup", font=theme.font_subheading(), text_color=theme.TEXT_MUTED_COLOR,
        ).pack(pady=(theme.SPACE_SECTION, theme.SPACE_XS), padx=20, anchor="w")

        self.autostart_var = ctk.BooleanVar(value=autostart.is_enabled())
        ctk.CTkCheckBox(
            self, text="Start with Windows", variable=self.autostart_var, command=self._on_autostart_toggle,
        ).pack(padx=20, pady=(0, theme.SPACE_SM), anchor="w")

        ctk.CTkLabel(
            self, text="Window", font=theme.font_subheading(), text_color=theme.TEXT_MUTED_COLOR,
        ).pack(pady=(theme.SPACE_SECTION, theme.SPACE_XS), padx=20, anchor="w")

        self.minimize_to_tray_var = ctk.BooleanVar(value=minimize_to_tray)
        ctk.CTkCheckBox(
            self, text="Minimize to tray on close", variable=self.minimize_to_tray_var,
            command=self._on_minimize_to_tray_toggle,
        ).pack(padx=20, pady=(0, theme.SPACE_XS), anchor="w")
        ctk.CTkLabel(
            self, text="When off, closing the window quits FluxHound normally.",
            font=theme.font_small(), text_color=theme.TEXT_MUTED_COLOR, justify="left", wraplength=240,
        ).pack(padx=20, anchor="w")

        self.after(50, self._make_modal)

    def _make_modal(self) -> None:
        """Grab focus once the window is actually mapped (grab_set fails on an unmapped window)."""
        self.grab_set()

    def _on_devices_click(self) -> None:
        self.destroy()
        self._on_open_devices()

    def _on_license_click(self) -> None:
        self.destroy()
        LicenseWindow(self.master)

    def _on_autostart_toggle(self) -> None:
        if self.autostart_var.get():
            autostart.enable()
        else:
            autostart.disable()

    def _on_minimize_to_tray_toggle(self) -> None:
        self._on_minimize_to_tray_change(self.minimize_to_tray_var.get())
