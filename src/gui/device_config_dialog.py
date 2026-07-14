"""Modal dialog for entering or editing a bulb's connection details.

Device ID and IP address can be filled in by hand or picked from a local network
scan (src/tuya/discovery.py, UDP broadcast - no cloud). The local key has two
paths: type it in directly, or - for users willing to provide their own Tuya IoT
developer account credentials - fetch it from the Tuya Cloud API
(src/tuya/cloud_discovery.py), the only place this app ever talks to Tuya's cloud,
and only when the user explicitly opts into it.
"""
from __future__ import annotations

import threading
from typing import Callable

import customtkinter as ctk

from src import tuya_cloud_config
from src.device_config import DeviceConfig
from src.tuya.cloud_discovery import API_REGIONS, CloudDevice, CloudDiscoveryError, fetch_devices_from_cloud
from src.tuya.discovery import DiscoveredDevice, discover_devices

ERROR_TEXT_COLOR = ("#b91c1c", "#f87171")
STATUS_TEXT_COLOR = ("gray30", "gray70")


class DeviceConfigDialog(ctk.CTkToplevel):
    """Modal dialog asking for device ID, IP address and local key."""

    def __init__(self, master: ctk.CTk, on_save: Callable[[DeviceConfig], None],
                 existing: DeviceConfig | None = None):
        super().__init__(master)
        self._on_save = on_save

        self.title("Configure device")
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
        self.scan_status_label = ctk.CTkLabel(self, text="", text_color=STATUS_TEXT_COLOR)
        self.scan_status_label.pack()
        self.scan_results_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.scan_results_frame.pack(pady=(0, 8))

        self.key_source_var = ctk.StringVar(value="manual")
        key_source_row = ctk.CTkFrame(self, fg_color="transparent")
        key_source_row.pack(pady=(4, 4))
        ctk.CTkRadioButton(
            key_source_row, text="Enter local key manually", variable=self.key_source_var, value="manual",
            command=self._on_key_source_changed,
        ).pack(side="left", padx=6)
        ctk.CTkRadioButton(
            key_source_row, text="Fetch via Tuya Cloud", variable=self.key_source_var, value="cloud",
            command=self._on_key_source_changed,
        ).pack(side="left", padx=6)

        self.manual_key_frame = ctk.CTkFrame(self, fg_color="transparent")
        ctk.CTkLabel(self.manual_key_frame, text="Local Key").pack()
        self.local_key_entry = ctk.CTkEntry(self.manual_key_frame, width=300, show="*")
        self.local_key_entry.pack(pady=(2, 8))

        self.cloud_frame = ctk.CTkFrame(self, fg_color="transparent")
        saved_credentials = tuya_cloud_config.load()
        region_row = ctk.CTkFrame(self.cloud_frame, fg_color="transparent")
        region_row.pack(pady=(4, 4))
        ctk.CTkLabel(region_row, text="API Region").pack(side="left", padx=(0, 8))
        self.api_region_menu = ctk.CTkOptionMenu(region_row, values=API_REGIONS, width=100)
        self.api_region_menu.set(saved_credentials.api_region)
        self.api_region_menu.pack(side="left")
        self.api_key_entry = ctk.CTkEntry(self.cloud_frame, width=300, placeholder_text="API Key")
        self.api_key_entry.insert(0, saved_credentials.api_key)
        self.api_key_entry.pack(pady=(2, 4))
        self.api_secret_entry = ctk.CTkEntry(self.cloud_frame, width=300, show="*", placeholder_text="API Secret")
        self.api_secret_entry.insert(0, saved_credentials.api_secret)
        self.api_secret_entry.pack(pady=(2, 4))
        self.fetch_button = ctk.CTkButton(self.cloud_frame, text="Fetch from Tuya Cloud", width=180,
                                           command=self._on_fetch_click)
        self.fetch_button.pack(pady=(2, 4))
        self.cloud_status_label = ctk.CTkLabel(self.cloud_frame, text="", text_color=STATUS_TEXT_COLOR)
        self.cloud_status_label.pack()
        self.cloud_results_frame = ctk.CTkFrame(self.cloud_frame, fg_color="transparent")
        self.cloud_results_frame.pack(pady=(0, 4))

        self.manual_key_frame.pack(pady=(0, 4))

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

    def _on_key_source_changed(self) -> None:
        """Swap which local-key input is visible - the underlying local_key_entry
        widget is always what Save actually reads, whichever path filled it."""
        if self.key_source_var.get() == "manual":
            self.cloud_frame.pack_forget()
            self.manual_key_frame.pack(pady=(0, 4))
        else:
            self.manual_key_frame.pack_forget()
            self.cloud_frame.pack(pady=(0, 4))

    # -- Local network scan (device ID + IP, no key) -----------------------------------

    def _on_scan_click(self) -> None:
        self.scan_button.configure(state="disabled")
        self.scan_status_label.configure(text="Scanning local network...")
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
                fg_color="gray30", command=lambda d=device: self._apply_discovered_device(d),
            ).pack(pady=2)

    def _on_scan_failed(self, message: str) -> None:
        self.scan_button.configure(state="normal")
        self.scan_status_label.configure(text=f"Scan failed: {message}", text_color=ERROR_TEXT_COLOR)

    def _apply_discovered_device(self, device: DiscoveredDevice) -> None:
        self.device_id_entry.delete(0, "end")
        self.device_id_entry.insert(0, device.device_id)
        self.ip_entry.delete(0, "end")
        self.ip_entry.insert(0, device.ip_address)

    # -- Tuya Cloud fetch (device ID + local key, region-dependent) ---------------------

    def _on_fetch_click(self) -> None:
        api_region = self.api_region_menu.get()
        api_key = self.api_key_entry.get().strip()
        api_secret = self.api_secret_entry.get().strip()
        if not api_key or not api_secret:
            self.cloud_status_label.configure(text="API Key and Secret are required.", text_color=ERROR_TEXT_COLOR)
            return
        self.fetch_button.configure(state="disabled")
        self.cloud_status_label.configure(text="Fetching from Tuya Cloud...", text_color=STATUS_TEXT_COLOR)
        for child in self.cloud_results_frame.winfo_children():
            child.destroy()
        threading.Thread(target=self._run_fetch, args=(api_region, api_key, api_secret), daemon=True).start()

    def _run_fetch(self, api_region: str, api_key: str, api_secret: str) -> None:
        try:
            devices = fetch_devices_from_cloud(api_region, api_key, api_secret)
        except CloudDiscoveryError as exc:
            self.after(0, lambda: self._on_fetch_failed(str(exc)))
            return
        self.after(0, lambda: self._on_fetch_done(devices, api_region, api_key, api_secret))

    def _on_fetch_done(self, devices: list[CloudDevice], api_region: str, api_key: str, api_secret: str) -> None:
        self.fetch_button.configure(state="normal")
        # Only remembered once a fetch actually succeeds, so a typo'd key/secret
        # never gets persisted.
        tuya_cloud_config.save(
            tuya_cloud_config.CloudCredentials(api_region=api_region, api_key=api_key, api_secret=api_secret)
        )
        if not devices:
            self.cloud_status_label.configure(text="No devices with a local key found on this account.")
            return
        self.cloud_status_label.configure(text=f"Found {len(devices)} device(s):")
        for device in devices:
            ctk.CTkButton(
                self.cloud_results_frame, text=f"{device.name}  ({device.device_id})", width=300,
                fg_color="gray30", command=lambda d=device: self._apply_cloud_device(d),
            ).pack(pady=2)

    def _on_fetch_failed(self, message: str) -> None:
        self.fetch_button.configure(state="normal")
        self.cloud_status_label.configure(text=f"Fetch failed: {message}", text_color=ERROR_TEXT_COLOR)

    def _apply_cloud_device(self, device: CloudDevice) -> None:
        self.device_id_entry.delete(0, "end")
        self.device_id_entry.insert(0, device.device_id)
        self.local_key_entry.delete(0, "end")
        self.local_key_entry.insert(0, device.local_key)
        if device.ip_address:
            self.ip_entry.delete(0, "end")
            self.ip_entry.insert(0, device.ip_address)
        self.cloud_status_label.configure(text=f"Local key retrieved for {device.name}.")

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
