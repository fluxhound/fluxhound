"""Modal dialog for entering or editing a bulb's connection details."""
from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from src.device_config import DeviceConfig

ERROR_TEXT_COLOR = ("#b91c1c", "#f87171")


class DeviceConfigDialog(ctk.CTkToplevel):
    """Modal dialog asking for device ID, IP address and local key."""

    def __init__(self, master: ctk.CTk, on_save: Callable[[DeviceConfig], None],
                 existing: DeviceConfig | None = None):
        super().__init__(master)
        self._on_save = on_save

        self.title("Configure device")
        self.geometry("360x300")
        self.resizable(False, False)
        self.transient(master)

        ctk.CTkLabel(self, text="Device ID").pack(pady=(16, 0))
        self.device_id_entry = ctk.CTkEntry(self, width=280)
        self.device_id_entry.pack(pady=(2, 8))

        ctk.CTkLabel(self, text="IP Address").pack()
        self.ip_entry = ctk.CTkEntry(self, width=280)
        self.ip_entry.pack(pady=(2, 8))

        ctk.CTkLabel(self, text="Local Key").pack()
        self.local_key_entry = ctk.CTkEntry(self, width=280, show="*")
        self.local_key_entry.pack(pady=(2, 8))

        if existing is not None:
            self.device_id_entry.insert(0, existing.device_id)
            self.ip_entry.insert(0, existing.ip_address)
            self.local_key_entry.insert(0, existing.local_key)

        self.error_label = ctk.CTkLabel(self, text="", text_color=ERROR_TEXT_COLOR)
        self.error_label.pack(pady=(4, 0))

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack(pady=16)
        ctk.CTkButton(button_row, text="Save", command=self._on_save_click).pack(side="left", padx=6)
        ctk.CTkButton(button_row, text="Cancel", fg_color="gray40", command=self.destroy).pack(side="left", padx=6)

        self.after(50, self._make_modal)

    def _make_modal(self) -> None:
        """Grab focus once the window is actually mapped (grab_set fails on an unmapped window)."""
        self.grab_set()
        self.device_id_entry.focus()

    def _on_save_click(self) -> None:
        """Validate the three required fields and hand them off to the caller."""
        device_id = self.device_id_entry.get().strip()
        ip_address = self.ip_entry.get().strip()
        local_key = self.local_key_entry.get().strip()
        if not device_id or not ip_address or not local_key:
            self.error_label.configure(text="All three fields are required.")
            return
        self._on_save(DeviceConfig(device_id=device_id, ip_address=ip_address, local_key=local_key))
        self.destroy()
