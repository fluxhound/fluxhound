"""Music-reactive mode: bass-driven brightness with a spectral-centroid-driven hue.

Runs entirely in colour mode so a single colour_data (DP 24) write can
carry both brightness (its V component) and hue in one command —
switching work_mode per update would add visible lag and an extra DP
write for no benefit.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

from src.audio.analysis import AudioEnvelope
from src.audio.loopback import BLOCK_SIZE, SAMPLE_RATE, LoopbackStream
from src.tuya.device import TuyaBulb, TuyaConnectionError

SEND_INTERVAL_SECONDS = 0.12  # caps commands sent to the bulb, independent of audio block rate
SATURATION = 1000


class MusicMode:
    """Captures system audio on a background thread and drives one bulb from it."""

    def __init__(self, bulb: TuyaBulb, on_error: Callable[[str], None] | None = None,
                 on_recovered: Callable[[], None] | None = None):
        self._bulb = bulb
        self._on_error = on_error
        self._on_recovered = on_recovered
        self._had_error = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start capturing audio and driving the bulb. No-op if already running."""
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background thread and wait for it to exit."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _run(self) -> None:
        try:
            with LoopbackStream(SAMPLE_RATE, BLOCK_SIZE) as stream:
                envelope = AudioEnvelope(SAMPLE_RATE, BLOCK_SIZE)
                last_send = 0.0
                while not self._stop_event.is_set():
                    block = stream.read_block()
                    brightness, hue = envelope.process(block)
                    now = time.monotonic()
                    if now - last_send >= SEND_INTERVAL_SECONDS:
                        last_send = now
                        self._send(int(round(hue)), brightness)
        except Exception as exc:  # audio device errors don't propagate out of a thread otherwise
            self._report_error(str(exc))

    def _send(self, hue: int, brightness: int) -> None:
        try:
            self._bulb.set_color(hue, SATURATION, brightness)
        except TuyaConnectionError as exc:
            self._had_error = True
            self._report_error(str(exc))
        else:
            if self._had_error:
                self._had_error = False
                if self._on_recovered is not None:
                    self._on_recovered()

    def _report_error(self, message: str) -> None:
        if self._on_error is not None:
            self._on_error(message)
