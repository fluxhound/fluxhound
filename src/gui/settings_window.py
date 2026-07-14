"""Settings Toplevel opened from the main window's gear button.

A launcher for the Devices and License windows, structured as a list of
entries so more settings sections can be added later without changing what the
gear button itself does.
"""
from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from src.gui.license_window import LicenseWindow


class SettingsWindow(ctk.CTkToplevel):
    """A small modal menu; picking an entry closes this window and opens the
    corresponding one, rather than stacking windows on top of each other."""

    def __init__(self, master: ctk.CTk, on_open_devices: Callable[[], None]):
        super().__init__(master)
        self._on_open_devices = on_open_devices

        self.title("Settings")
        self.geometry("260x220")
        self.resizable(False, False)
        self.transient(master)

        ctk.CTkLabel(self, text="Settings", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(20, 16))
        ctk.CTkButton(self, text="Devices", command=self._on_devices_click).pack(padx=20, pady=(0, 8), fill="x")
        ctk.CTkButton(self, text="License", command=self._on_license_click).pack(padx=20, fill="x")

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
