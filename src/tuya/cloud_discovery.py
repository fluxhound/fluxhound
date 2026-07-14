"""Optional Tuya Cloud IoT Platform lookup for a device's local_key (and friendly
name), for users willing to provide their own Tuya developer account credentials -
an alternative to typing the local_key by hand (see DeviceConfigDialog).

This is the only place in the app that ever talks to Tuya's cloud, and only when
the user explicitly opts into it and supplies their own API credentials; every
other feature (bulb control, screen/audio reactive modes) stays fully local, per
this app's own no-cloud-dependency design (see CLAUDE.md). The cloud is used here
purely as a one-time lookup - once a local_key is retrieved, everything from that
point on talks to the bulb directly over the LAN like any other configured device.

Tuya deliberately never broadcasts local_key over the local network (see
src/tuya/discovery.py), so it's genuinely unavailable any other way short of the
device's box/QR code or the official Tuya/Smart Life app's own device-sharing UI.
"""
from __future__ import annotations

from dataclasses import dataclass

import tinytuya

API_REGIONS = ["us", "eu", "cn", "in"]


@dataclass
class CloudDevice:
    """A device listed under the caller's Tuya Cloud account."""

    device_id: str
    local_key: str
    name: str
    ip_address: str | None = None  # rarely present; Tuya Cloud doesn't reliably expose LAN IPs


class CloudDiscoveryError(Exception):
    """Raised when the Tuya Cloud API call fails (bad credentials, network error,
    empty account, etc.) - str(exc) is meant to be shown directly to the user."""


def fetch_devices_from_cloud(api_region: str, api_key: str, api_secret: str) -> list[CloudDevice]:
    """Log into the Tuya Cloud IoT Platform with the caller's own developer
    credentials and list every device registered under that account, including
    each one's local_key."""
    try:
        cloud = tinytuya.Cloud(apiRegion=api_region, apiKey=api_key, apiSecret=api_secret)
        result = cloud.getdevices()
    except Exception as exc:  # network/library errors shouldn't crash the caller
        raise CloudDiscoveryError(str(exc)) from exc

    if isinstance(result, dict) and "Err" in result:
        raise CloudDiscoveryError(result.get("Error") or f"Tuya Cloud error {result['Err']}")
    if not isinstance(result, list):
        raise CloudDiscoveryError(f"unexpected response from Tuya Cloud: {result!r}")

    devices = []
    for entry in result:
        device_id = entry.get("id")
        local_key = entry.get("local_key")
        if not device_id or not local_key:
            continue
        devices.append(
            CloudDevice(
                device_id=device_id,
                local_key=local_key,
                name=entry.get("name") or device_id,
                ip_address=entry.get("ip") or None,
            )
        )
    return devices
