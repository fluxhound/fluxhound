"""Ambience Mode: continuously analyses the screen's dominant colour and brightness
(src/screen/ambience_show.py) and drives one or more bulbs from it.

Reuses every reliability lesson from Audio Mode's debugging history: persistent
connection, connection_retry_limit=2, fail-fast timeout, nowait sends, one DP write
per update (colour_data already bundles hue/saturation/value) - see
src/modes/custom_mode.py for the original writeup of why that combination matters.
Unlike CustomMode, there's no per-target source assignment here - the screen's
colour mood drives hue, saturation, and brightness together, all the time.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

from src.screen.ambience_show import AmbienceEnvelope
from src.screen.capture import ScreenCapture
from src.tuya.device import TuyaBulb, TuyaConnectionError, WORK_MODE_COLOUR

CAPTURE_INTERVAL_SECONDS = 0.1
SEND_INTERVAL_SECONDS = 0.2  # caps commands sent to the bulb, independent of capture rate


class AmbienceMode:
    """Captures the screen on a background thread and drives one or more bulbs from
    its dominant colour/brightness."""

    def __init__(self, bulbs: list[TuyaBulb],
                 monitor_index: int = 0, region: tuple[int, int, int, int] | None = None,
                 on_error: Callable[[str], None] | None = None,
                 on_recovered: Callable[[], None] | None = None,
                 on_update: Callable[[int, int, int], None] | None = None):
        self._bulbs = bulbs
        self._monitor_index = monitor_index
        self._region = region
        self._on_error = on_error
        self._on_recovered = on_recovered
        self._on_update = on_update
        self._had_error = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start capturing the screen and driving the bulb(s). No-op if already running."""
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background thread and wait for it to exit."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self) -> None:
        capture = ScreenCapture(monitor_index=self._monitor_index, region=self._region)
        try:
            envelope = AmbienceEnvelope()
            for bulb in self._bulbs:
                bulb.set_work_mode_nowait(WORK_MODE_COLOUR)
            time.sleep(0.15)  # give the devices a beat before the first hot-loop send
            last_send = 0.0
            while not self._stop_event.is_set():
                frame = capture.grab_rgb()
                hue, saturation, value = envelope.process(frame)
                now = time.monotonic()
                if now - last_send >= SEND_INTERVAL_SECONDS:
                    last_send = now
                    self._send(hue, saturation, value)
                self._stop_event.wait(CAPTURE_INTERVAL_SECONDS)
        except Exception as exc:  # capture/analysis errors don't propagate out of a thread otherwise
            self._report_error(str(exc))
        finally:
            capture.close()
            for bulb in self._bulbs:
                bulb.close()

    def _send(self, hue: int, saturation: int, value: int) -> None:
        if self._on_update is not None:
            self._on_update(hue, saturation, value)
        error_message: str | None = None
        for bulb in self._bulbs:
            try:
                bulb.set_colour_data_value_nowait(hue, saturation, value)
            except TuyaConnectionError as exc:
                error_message = str(exc)
        if error_message is not None:
            self._had_error = True
            self._report_error(error_message)
        else:
            if self._had_error:
                self._had_error = False
                if self._on_recovered is not None:
                    self._on_recovered()

    def _report_error(self, message: str) -> None:
        if self._on_error is not None:
            self._on_error(message)
