"""Local network discovery for Tuya devices via UDP broadcast (tinytuya.deviceScan)
- no cloud dependency, matching the rest of this app.

Only device_id, IP address, and protocol version are ever discoverable this way:
Tuya devices deliberately don't broadcast their local_key over the LAN, so that
still has to come from somewhere else (manual entry, or the Tuya Cloud API - see
src/tuya/cloud_discovery.py). This just saves looking up/typing the other two.

Best-effort by nature: a device only shows up if it happens to broadcast during the
scan window, so a device that's offline, asleep, or just unlucky with UDP packet
timing won't appear in any one scan - the caller should let the user re-scan rather
than treat an empty/partial result as final.
"""
from __future__ import annotations

from dataclasses import dataclass

import tinytuya

DEFAULT_SCAN_RETRIES = 2  # tinytuya.deviceScan's maxretry - keeps a scan to a few seconds


@dataclass
class DiscoveredDevice:
    """A Tuya device that responded to a local UDP broadcast scan."""

    device_id: str
    ip_address: str
    protocol_version: float


def discover_devices(maxretry: int = DEFAULT_SCAN_RETRIES) -> list[DiscoveredDevice]:
    """Listen for local Tuya UDP broadcasts for a few seconds and return whatever
    devices responded."""
    raw = tinytuya.deviceScan(verbose=False, poll=False, maxretry=maxretry)
    devices = []
    for info in raw.values():
        device_id = info.get("gwId") or info.get("id")
        ip_address = info.get("ip")
        if not device_id or not ip_address:
            continue
        try:
            protocol_version = float(info.get("version") or 3.3)
        except (TypeError, ValueError):
            protocol_version = 3.3
        devices.append(
            DiscoveredDevice(device_id=device_id, ip_address=ip_address, protocol_version=protocol_version)
        )
    return devices
