"""Music-reactive mode: bass-driven brightness in a colour or white output the user picks.

Runs on a dedicated background thread. Colour choice (a fixed hue, or
white) is set from the GUI thread via `set_colour`/`set_white` and read
by the loop on its next cycle — no restart needed to change it.

Only one DP write happens per update (colour_data, or bright_value).
work_mode (DP 21) is written once when the output category actually
changes, not on every cycle: earlier this wrote two DPs per update with
a multi-second retry+timeout on failure, which was enough command
traffic to overwhelm the bulb's WiFi firmware and made it stop
responding for a long stretch. `bulb` should be a TuyaBulb configured
to fail fast (few/no retries, short timeout) so one bad cycle doesn't
stall the loop for long.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

from src.audio.analysis import AudioEnvelope
from src.audio.loopback import BLOCK_SIZE, SAMPLE_RATE, LoopbackStream
from src.tuya.device import TuyaBulb, TuyaConnectionError, WORK_MODE_COLOUR, WORK_MODE_WHITE

SEND_INTERVAL_SECONDS = 0.15  # caps commands sent to the bulb, independent of audio block rate
SATURATION = 1000


class MusicMode:
    """Captures system audio on a background thread and drives one bulb from it."""

    def __init__(self, bulb: TuyaBulb, on_error: Callable[[str], None] | None = None,
                 on_recovered: Callable[[], None] | None = None, initial_hue: int = 0):
        self._bulb = bulb
        self._on_error = on_error
        self._on_recovered = on_recovered
        self._had_error = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._lock = threading.Lock()
        self._output_mode = WORK_MODE_COLOUR
        self._hue = initial_hue
        self._sent_work_mode: str | None = None  # what we've actually written to DP21 so far

    def set_colour(self, hue: int) -> None:
        """Switch the running session's output to a fixed colour."""
        with self._lock:
            self._output_mode = WORK_MODE_COLOUR
            self._hue = hue

    def set_white(self) -> None:
        """Switch the running session's output to white."""
        with self._lock:
            self._output_mode = WORK_MODE_WHITE

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
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self) -> None:
        try:
            with LoopbackStream(SAMPLE_RATE, BLOCK_SIZE) as stream:
                envelope = AudioEnvelope(SAMPLE_RATE, BLOCK_SIZE)
                last_send = 0.0
                while not self._stop_event.is_set():
                    block = stream.read_block()
                    brightness = envelope.process(block)
                    now = time.monotonic()
                    if now - last_send >= SEND_INTERVAL_SECONDS:
                        last_send = now
                        self._send(brightness)
        except Exception as exc:  # audio device errors don't propagate out of a thread otherwise
            self._report_error(str(exc))
        finally:
            self._bulb.close()

    def _send(self, brightness: int) -> None:
        with self._lock:
            mode, hue = self._output_mode, self._hue
        try:
            if mode != self._sent_work_mode:
                self._bulb.set_work_mode(mode)
                self._sent_work_mode = mode
            if mode == WORK_MODE_COLOUR:
                self._bulb.set_colour_data_value(hue, SATURATION, brightness)
            else:
                self._bulb.set_brightness_value(brightness)
        except TuyaConnectionError as exc:
            self._had_error = True
            self._sent_work_mode = None  # unsure whether the mode write above actually landed
            self._report_error(str(exc))
        else:
            if self._had_error:
                self._had_error = False
                if self._on_recovered is not None:
                    self._on_recovered()

    def _report_error(self, message: str) -> None:
        if self._on_error is not None:
            self._on_error(message)
