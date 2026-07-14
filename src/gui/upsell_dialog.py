"""Shown whenever a free-tier user hits a paid-tier feature (src/licensing/gate.py) -
explains what unlocking gets them and offers to go straight to the license
entry screen, rather than a dead-end error message.
"""
from __future__ import annotations

import customtkinter as ctk

from src.gui import theme
from src.gui.license_window import LicenseWindow


class UpsellDialog(ctk.CTkToplevel):
    """feature_name is a short label ("Audio Mode", "a second device", ...);
    description explains what unlocking adds, in the same voice as the rest of
    the app's copy."""

    def __init__(self, master: ctk.CTk, feature_name: str, description: str):
        super().__init__(master)

        self.title("Unlock FluxHound")
        theme.apply_icon(self)
        self.geometry("360x240")
        self.resizable(False, False)
        self.transient(master)

        badge = ctk.CTkLabel(
            self, text="PRO", font=theme.font_badge(), text_color=theme.PRO_BADGE_TEXT_COLOR,
            fg_color=theme.PRO_BADGE_COLOR, corner_radius=6, width=40, height=20,
        )
        badge.pack(pady=(20, 8))
        ctk.CTkLabel(
            self, text=f"{feature_name} is a paid-tier feature", font=theme.font_heading(),
            wraplength=320, justify="left",
        ).pack(pady=(0, 8), padx=20)
        ctk.CTkLabel(
            self, text=description, font=theme.font_body(), text_color=theme.TEXT_MUTED_COLOR,
            wraplength=320, justify="left",
        ).pack(pady=(0, 16), padx=20)

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack(pady=(0, 16))
        ctk.CTkButton(button_row, text="Enter licence key", command=self._open_license_window).pack(
            side="left", padx=6
        )
        ctk.CTkButton(
            button_row, text="Not now", fg_color=theme.SECONDARY_BUTTON_COLOR,
            hover_color=theme.SECONDARY_BUTTON_HOVER_COLOR, command=self.destroy,
        ).pack(side="left", padx=6)

        self.after(50, self._make_modal)

    def _make_modal(self) -> None:
        self.grab_set()

    def _open_license_window(self) -> None:
        master = self.master
        self.destroy()
        LicenseWindow(master)
