"""Local network discovery for Tuya devices via UDP broadcast (tinytuya.deviceScan)
- no cloud dependency, matching the rest of this app.

Only device_id, IP address, and protocol version are ever discoverable this way:
Tuya devices deliberately don't broadcast their local_key over the LAN, so that
still has to be entered by hand in DeviceConfigDialog. This just saves looking up/
typing the other two. (An earlier version could also fetch the local_key via the
user's own Tuya Cloud developer credentials - removed after a real bug in that
path and, separately, because the credentials it needed would sit in a plaintext
local JSON file, which wasn't worth it for a convenience feature.)

Best-effort by nature: a device only shows up if it happens to broadcast during the
scan window, so a device that's offline, asleep, or just unlucky with UDP packet
timing won't appear in any one scan - the caller should let the user re-scan rather
than treat an empty/partial result as final.
"""
from __future__ import annotations

from dataclasses import dataclass

import tinytuya

# tinytuya.deviceScan's "maxretry" parameter isn't a retry count despite the name -
# it flows straight through to tinytuya.scanner.devices() as scantime, the number of
# seconds to keep listening for broadcasts. An earlier version of this file passed 2
# here on the (wrong) assumption it meant retries, which cut the real listening
# window down to ~2 seconds - Tuya devices don't all broadcast within the same
# instant, so on a live 3-bulb network that was only ever long enough to reliably
# catch one of them. tinytuya's own default (tinytuya.SCANTIME) is 18 seconds; match
# it explicitly rather than relying on the None-means-default fallback chain shared
# across two different tinytuya functions.
DEFAULT_SCAN_SECONDS = 18


@dataclass
class DiscoveredDevice:
    """A Tuya device that responded to a local UDP broadcast scan."""

    device_id: str
    ip_address: str
    protocol_version: float


def discover_devices(scan_seconds: int = DEFAULT_SCAN_SECONDS) -> list[DiscoveredDevice]:
    """Listen for local Tuya UDP broadcasts for scan_seconds and return whatever
    devices responded during that window. Best-effort by nature (see module
    docstring) - a longer window catches more devices, since each only broadcasts
    periodically rather than continuously."""
    raw = tinytuya.deviceScan(verbose=False, poll=False, maxretry=scan_seconds)
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
