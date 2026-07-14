"""Modal dialog for entering or editing a bulb's connection details.

Device ID and IP address can be filled in by hand or picked from a local network
scan (src/tuya/discovery.py, UDP broadcast - no cloud). The local key is always
typed in by hand: an earlier version also offered fetching it via the user's own
Tuya Cloud developer account credentials, but that path is gone - it had a real
bug (a wrong "no local key on this account" message even with correct, correctly-
scoped credentials) and, separately, meant an API key/secret sitting in a
plaintext local JSON file, which wasn't worth it for a convenience feature. Local-
only control stays the only way this app ever talks to a bulb.
"""
from __future__ import annotations

import threading
from typing import Callable

import customtkinter as ctk

from src.device_config import DeviceConfig
from src.gui import theme
from src.tuya.discovery import DiscoveredDevice, discover_devices


class DeviceConfigDialog(ctk.CTkToplevel):
    """Modal dialog asking for device ID, IP address and local key."""

    def __init__(self, master: ctk.CTk, on_save: Callable[[DeviceConfig], None],
                 existing: DeviceConfig | None = None):
        super().__init__(master)
        self._on_save = on_save

        self.title("Configure device")
        theme.apply_icon(self)
        self.resizable(False, False)
        self.transient(master)

        ctk.CTkLabel(self, text="Device ID").pack(pady=(16, 0))
        self.device_id_entry = ctk.CTkEntry(self, width=300)
        self.device_id_entry.pack(pady=(2, 8))

        ctk.CTkLabel(self, text="IP Address").pack()
        self.ip_entry = ctk.CTkEntry(self, width=300)
        self.ip_entry.pack(pady=(2, 4))

        self.scan_button = ctk.CTkButton(self, text="Scan local network", width=180,
                                          command=self._on_scan_click)
        self.scan_button.pack(pady=(2, 4))
        self.scan_status_label = ctk.CTkLabel(self, text="", text_color=theme.TEXT_MUTED_COLOR)
        self.scan_status_label.pack()
        self.scan_results_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.scan_results_frame.pack(pady=(0, 8))

        ctk.CTkLabel(self, text="Local Key").pack()
        self.local_key_entry = ctk.CTkEntry(self, width=300, show="*")
        self.local_key_entry.pack(pady=(2, 8))

        if existing is not None:
            self.device_id_entry.insert(0, existing.device_id)
            self.ip_entry.insert(0, existing.ip_address)
            self.local_key_entry.insert(0, existing.local_key)

        self.error_label = ctk.CTkLabel(self, text="", text_color=theme.ERROR_COLOR)
        self.error_label.pack(pady=(4, 0))

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack(pady=16)
        ctk.CTkButton(button_row, text="Save", command=self._on_save_click).pack(side="left", padx=6)
        ctk.CTkButton(
            button_row, text="Cancel", fg_color=theme.SECONDARY_BUTTON_COLOR,
            hover_color=theme.SECONDARY_BUTTON_HOVER_COLOR, command=self.destroy,
        ).pack(side="left", padx=6)

        self.after(50, self._make_modal)

    def _make_modal(self) -> None:
        """Grab focus once the window is actually mapped (grab_set fails on an unmapped window)."""
        self.grab_set()
        self.device_id_entry.focus()

    # -- Local network scan (device ID + IP, no key) -----------------------------------

    def _on_scan_click(self) -> None:
        self.scan_button.configure(state="disabled")
        self.scan_status_label.configure(text="Scanning local network (up to 18s, to catch every device)...")
        for child in self.scan_results_frame.winfo_children():
            child.destroy()
        threading.Thread(target=self._run_scan, daemon=True).start()

    def _run_scan(self) -> None:
        try:
            devices = discover_devices()
        except Exception as exc:  # network/library errors shouldn't crash the dialog
            self.after(0, lambda: self._on_scan_failed(str(exc)))
            return
        self.after(0, lambda: self._on_scan_done(devices))

    def _on_scan_done(self, devices: list[DiscoveredDevice]) -> None:
        self.scan_button.configure(state="normal")
        if not devices:
            self.scan_status_label.configure(text="No devices found - try again, or enter details manually.")
            return
        self.scan_status_label.configure(text=f"Found {len(devices)} device(s):")
        for device in devices:
            ctk.CTkButton(
                self.scan_results_frame, text=f"{device.device_id}  ({device.ip_address})", width=300,
                fg_color=theme.SECONDARY_BUTTON_COLOR, hover_color=theme.SECONDARY_BUTTON_HOVER_COLOR,
                command=lambda d=device: self._apply_discovered_device(d),
            ).pack(pady=2)

    def _on_scan_failed(self, message: str) -> None:
        self.scan_button.configure(state="normal")
        self.scan_status_label.configure(text=f"Scan failed: {message}", text_color=theme.ERROR_COLOR)

    def _apply_discovered_device(self, device: DiscoveredDevice) -> None:
        self.device_id_entry.delete(0, "end")
        self.device_id_entry.insert(0, device.device_id)
        self.ip_entry.delete(0, "end")
        self.ip_entry.insert(0, device.ip_address)

    # -- Save ---------------------------------------------------------------------------

    def _on_save_click(self) -> None:
        """Validate the three required fields and hand them off to the caller."""
        device_id = self.device_id_entry.get().strip()
        ip_address = self.ip_entry.get().strip()
        local_key = self.local_key_entry.get().strip()
        if not device_id or not ip_address or not local_key:
            self.error_label.configure(text="Device ID, IP address, and local key are all required.")
            return
        self._on_save(DeviceConfig(device_id=device_id, ip_address=ip_address, local_key=local_key))
        self.destroy()
