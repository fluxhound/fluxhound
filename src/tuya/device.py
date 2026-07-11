"""Local Tuya communication wrapper for the Meka A60-RGBCW bulb model."""
from __future__ import annotations

import time
from typing import Any, Callable

import tinytuya

DP_SWITCH = "20"
DP_WORK_MODE = "21"
DP_BRIGHTNESS = "22"
DP_COLOR_TEMP = "23"
DP_COLOUR_DATA = "24"

WORK_MODE_WHITE = "white"
WORK_MODE_COLOUR = "colour"

DEFAULT_TIMEOUT_SECONDS = 3
RETRY_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 1


class TuyaConnectionError(Exception):
    """Raised when a bulb is unreachable or returns an error response."""


def _build_colour_data(hue: int, saturation: int, value: int) -> str:
    """Encode HSV as the bulb's colour_data hex string (4 hex digits per component)."""
    hue = max(0, min(360, hue))
    saturation = max(0, min(1000, saturation))
    value = max(0, min(1000, value))
    return f"{hue:04x}{saturation:04x}{value:04x}"


class TuyaBulb:
    """Wrapper around tinytuya.Device for Meka A60-RGBCW bulbs (local protocol 3.3).

    `retry_attempts`/`retry_delay` are configurable per instance: the
    default (2 attempts, 1s apart) suits one-off interactive commands
    from the GUI, but a hot loop like music mode should use
    `retry_attempts=1` so a bad cycle fails in one timeout instead of
    retrying for several seconds while sends pile up.

    `persistent=True` keeps one TCP connection open across calls instead
    of doing a full connect/handshake/close per command. A hot loop
    (music mode) sending several times a second was enough of that
    per-call overhead, live, to make the bulb's WiFi firmware stop
    responding intermittently - a persistent connection avoids repeating
    it. One-off manual commands are fine without it.
    """

    def __init__(self, device_id: str, ip_address: str, local_key: str,
                 version: float = 3.3, timeout: int = DEFAULT_TIMEOUT_SECONDS,
                 retry_attempts: int = RETRY_ATTEMPTS, retry_delay: float = RETRY_DELAY_SECONDS,
                 persistent: bool = False):
        self._device = tinytuya.Device(
            device_id, ip_address, local_key, version=version,
            connection_timeout=timeout, connection_retry_limit=1, connection_retry_delay=0,
        )
        self._device.set_version(version)
        self._device.set_socketPersistent(persistent)
        self._retry_attempts = retry_attempts
        self._retry_delay = retry_delay

    def _send(self, fn: Callable[..., Any], *args: Any) -> dict:
        """Run a tinytuya call, retrying transient failures, and raise on persistent errors.

        tinytuya reports failures as a dict with an "Err" key instead of
        raising, so both that case and socket-level exceptions are folded
        into TuyaConnectionError here.
        """
        last_error: str | None = None
        for attempt in range(self._retry_attempts):
            try:
                result = fn(*args)
            except OSError as exc:
                last_error = str(exc)
            else:
                if isinstance(result, dict) and "Err" not in result:
                    return result
                last_error = (
                    result.get("Error", f"error {result['Err']}")
                    if isinstance(result, dict)
                    else f"unexpected response: {result!r}"
                )
            if attempt < self._retry_attempts - 1:
                time.sleep(self._retry_delay)
        raise TuyaConnectionError(last_error or "unknown error")

    def close(self) -> None:
        """Close a lingering persistent connection, if any."""
        self._device.close()

    def status(self) -> dict:
        """Return the raw device status (DP dict) from the bulb."""
        return self._send(self._device.status)

    def turn_on(self) -> dict:
        """Switch the bulb on."""
        return self._send(self._device.set_value, DP_SWITCH, True)

    def turn_off(self) -> dict:
        """Switch the bulb off."""
        return self._send(self._device.set_value, DP_SWITCH, False)

    def set_work_mode(self, mode: str) -> dict:
        """Explicitly switch work_mode (white/colour) without touching any other DP."""
        return self._send(self._device.set_value, DP_WORK_MODE, mode)

    def set_brightness_value(self, brightness: int) -> dict:
        """Set bright_value (DP 22) only, without touching work_mode. Assumes white mode."""
        brightness = max(10, min(1000, brightness))
        return self._send(self._device.set_value, DP_BRIGHTNESS, brightness)

    def set_brightness(self, brightness: int) -> dict:
        """Switch to white mode and set brightness (10-1000)."""
        self.set_work_mode(WORK_MODE_WHITE)
        return self.set_brightness_value(brightness)

    def set_temperature(self, temperature: int) -> dict:
        """Switch to white mode and set colour temperature (0-1000)."""
        temperature = max(0, min(1000, temperature))
        self.set_work_mode(WORK_MODE_WHITE)
        return self._send(self._device.set_value, DP_COLOR_TEMP, temperature)

    def set_colour_data_value(self, hue: int, saturation: int, value: int) -> dict:
        """Set colour_data (DP 24) only, without touching work_mode. Assumes colour mode."""
        colour_data = _build_colour_data(hue, saturation, value)
        return self._send(self._device.set_value, DP_COLOUR_DATA, colour_data)

    def set_color(self, hue: int, saturation: int, value: int) -> dict:
        """Switch to colour mode and set HSV (hue 0-360, saturation/value 0-1000)."""
        self.set_work_mode(WORK_MODE_COLOUR)
        return self.set_colour_data_value(hue, saturation, value)
