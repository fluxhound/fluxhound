"""Shown whenever a free-tier user hits a paid-tier feature (src/licensing/gate.py) -
explains what unlocking gets them and offers to go straight to the license
entry screen, rather than a dead-end error message.
"""
from __future__ import annotations

import customtkinter as ctk

from src.gui.license_window import LicenseWindow


class UpsellDialog(ctk.CTkToplevel):
    """feature_name is a short label ("Audio Mode", "a second device", ...);
    description explains what unlocking adds, in the same voice as the rest of
    the app's copy."""

    def __init__(self, master: ctk.CTk, feature_name: str, description: str):
        super().__init__(master)

        self.title("Unlock FluxHound")
        self.geometry("360x220")
        self.resizable(False, False)
        self.transient(master)

        ctk.CTkLabel(
            self, text=f"{feature_name} is a paid-tier feature", font=ctk.CTkFont(size=15, weight="bold"),
            wraplength=320, justify="left",
        ).pack(pady=(20, 8), padx=20)
        ctk.CTkLabel(self, text=description, wraplength=320, justify="left").pack(pady=(0, 16), padx=20)

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack(pady=(0, 16))
        ctk.CTkButton(button_row, text="Enter licence key", command=self._open_license_window).pack(
            side="left", padx=6
        )
        ctk.CTkButton(button_row, text="Not now", fg_color="gray40", command=self.destroy).pack(side="left", padx=6)

        self.after(50, self._make_modal)

    def _make_modal(self) -> None:
        self.grab_set()

    def _open_license_window(self) -> None:
        master = self.master
        self.destroy()
        LicenseWindow(master)
