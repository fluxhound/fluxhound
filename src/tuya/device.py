"""Local Tuya communication wrapper for the Meka A60-RGBCW bulb model."""
from __future__ import annotations

import tinytuya

DP_SWITCH = "20"
DP_WORK_MODE = "21"
DP_BRIGHTNESS = "22"
DP_COLOR_TEMP = "23"
DP_COLOUR_DATA = "24"

WORK_MODE_WHITE = "white"
WORK_MODE_COLOUR = "colour"


def _build_colour_data(hue: int, saturation: int, value: int) -> str:
    """Encode HSV as the bulb's colour_data hex string (4 hex digits per component)."""
    hue = max(0, min(360, hue))
    saturation = max(0, min(1000, saturation))
    value = max(0, min(1000, value))
    return f"{hue:04x}{saturation:04x}{value:04x}"


class TuyaBulb:
    """Wrapper around tinytuya.Device for Meka A60-RGBCW bulbs (local protocol 3.3)."""

    def __init__(self, device_id: str, ip_address: str, local_key: str, version: float = 3.3):
        self._device = tinytuya.Device(device_id, ip_address, local_key, version=version)
        self._device.set_version(version)

    def status(self) -> dict:
        """Return the raw device status (DP dict) from the bulb."""
        return self._device.status()

    def turn_on(self) -> dict:
        """Switch the bulb on."""
        return self._device.set_value(DP_SWITCH, True)

    def turn_off(self) -> dict:
        """Switch the bulb off."""
        return self._device.set_value(DP_SWITCH, False)

    def set_white(self, brightness: int, temperature: int) -> dict:
        """Switch to white mode and set brightness (10-1000) and colour temperature."""
        brightness = max(10, min(1000, brightness))
        self._device.set_value(DP_WORK_MODE, WORK_MODE_WHITE)
        self._device.set_value(DP_BRIGHTNESS, brightness)
        return self._device.set_value(DP_COLOR_TEMP, temperature)

    def set_color(self, hue: int, saturation: int, value: int) -> dict:
        """Switch to colour mode and set HSV (hue 0-360, saturation/value 0-1000)."""
        colour_data = _build_colour_data(hue, saturation, value)
        self._device.set_value(DP_WORK_MODE, WORK_MODE_COLOUR)
        return self._device.set_value(DP_COLOUR_DATA, colour_data)
