"""Window for entering/managing the FluxHound license key: shows current
Free/Licensed status, activates a pasted key against Lemon Squeezy
(src/licensing/license_check.py), or clears a locally cached unlock.
"""
from __future__ import annotations

import threading
from typing import Callable

import customtkinter as ctk

from src.gui import theme
from src.licensing import license_check


class LicenseWindow(ctk.CTkToplevel):
    """on_change, if given, is called after every successful activate/remove -
    lets the caller (MainWindow) refresh anything gated by license state
    without needing to poll it."""

    def __init__(self, master: ctk.CTk, on_change: Callable[[], None] | None = None):
        super().__init__(master)
        self._on_change = on_change

        self.title("License")
        theme.apply_icon(self)
        self.geometry("360x280")
        self.resizable(False, False)
        self.transient(master)

        self.status_label = ctk.CTkLabel(self, font=ctk.CTkFont(size=16, weight="bold"))
        self.status_label.pack(pady=(20, 12))

        ctk.CTkLabel(self, text="Licence key").pack()
        self.key_entry = ctk.CTkEntry(self, width=280, placeholder_text="Paste your licence key")
        self.key_entry.pack(pady=(2, 8))

        self.activate_button = ctk.CTkButton(self, text="Activate", command=self._on_activate_click)
        self.activate_button.pack(pady=(0, 4))

        self.message_label = ctk.CTkLabel(self, text="", text_color=theme.TEXT_MUTED_COLOR, wraplength=300)
        self.message_label.pack(pady=(4, 4))

        self.deactivate_button = ctk.CTkButton(
            self, text="Remove licence (use Free tier)", fg_color=theme.SECONDARY_BUTTON_COLOR,
            hover_color=theme.SECONDARY_BUTTON_HOVER_COLOR, command=self._on_deactivate_click,
        )
        self.deactivate_button.pack(pady=(16, 4))

        self._refresh_status()
        self.after(50, self._make_modal)

    def _make_modal(self) -> None:
        self.grab_set()

    def _refresh_status(self) -> None:
        unlocked = license_check.is_licensed()
        self.status_label.configure(text="Licensed" if unlocked else "Free tier")
        self.deactivate_button.configure(state="normal" if unlocked else "disabled")

    # -- Activate -------------------------------------------------------------------

    def _on_activate_click(self) -> None:
        key = self.key_entry.get().strip()
        if not key:
            self.message_label.configure(text="Enter a licence key.", text_color=theme.ERROR_COLOR)
            return
        self.activate_button.configure(state="disabled")
        self.message_label.configure(text="Activating...", text_color=theme.TEXT_MUTED_COLOR)
        threading.Thread(target=self._run_activate, args=(key,), daemon=True).start()

    def _run_activate(self, key: str) -> None:
        try:
            license_check.activate(key)
        except license_check.LicenseError as exc:
            self.after(0, lambda: self._on_activate_failed(str(exc)))
            return
        except OSError as exc:  # network/connectivity failure, not a rejected key
            self.after(0, lambda: self._on_activate_failed(f"Couldn't reach the licence server: {exc}"))
            return
        self.after(0, self._on_activate_succeeded)

    def _on_activate_succeeded(self) -> None:
        self.activate_button.configure(state="normal")
        self.message_label.configure(text="Licence activated - unlocked!", text_color=theme.TEXT_MUTED_COLOR)
        self._refresh_status()
        if self._on_change is not None:
            self._on_change()

    def _on_activate_failed(self, message: str) -> None:
        self.activate_button.configure(state="normal")
        self.message_label.configure(text=message, text_color=theme.ERROR_COLOR)

    # -- Remove -----------------------------------------------------------------------

    def _on_deactivate_click(self) -> None:
        license_check.deactivate()
        self.message_label.configure(text="Licence removed - back to Free tier.", text_color=theme.TEXT_MUTED_COLOR)
        self._refresh_status()
        if self._on_change is not None:
            self._on_change()
