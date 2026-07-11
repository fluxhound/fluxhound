"""Music-reactive mode: FFT-driven brightness with onset-triggered hard colour changes.

Runs entirely in colour mode so a single colour_data (DP 24) write can
carry both brightness (its V component) and the current hue in one
command — switching work_mode per update would add visible lag and an
extra DP write for no benefit.
"""
from __future__ import annotations

import random
import threading
import time
from typing import Callable

from src.audio.analysis import AudioEnvelope
from src.audio.loopback import BLOCK_SIZE, SAMPLE_RATE, LoopbackStream
from src.tuya.device import TuyaBulb, TuyaConnectionError

SEND_INTERVAL_SECONDS = 0.12  # caps commands sent to the bulb, independent of audio block rate
SATURATION = 1000
HUES = [0, 30, 60, 120, 180, 240, 280, 320]


class MusicMode:
    """Captures system audio on a background thread and drives one bulb from it."""

    def __init__(self, bulb: TuyaBulb, on_error: Callable[[str], None] | None = None):
        self._bulb = bulb
        self._on_error = on_error
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
                hue = random.choice(HUES)
                last_send = 0.0
                while not self._stop_event.is_set():
                    block = stream.read_block()
                    now = time.monotonic()
                    brightness, onset = envelope.process(block, now)
                    if onset:
                        hue = random.choice([h for h in HUES if h != hue])
                    if now - last_send >= SEND_INTERVAL_SECONDS:
                        last_send = now
                        self._send(hue, brightness)
        except Exception as exc:  # audio device errors don't propagate out of a thread otherwise
            self._report_error(str(exc))

    def _send(self, hue: int, brightness: int) -> None:
        try:
            self._bulb.set_color(hue, SATURATION, brightness)
        except TuyaConnectionError as exc:
            self._report_error(str(exc))

    def _report_error(self, message: str) -> None:
        if self._on_error is not None:
            self._on_error(message)
