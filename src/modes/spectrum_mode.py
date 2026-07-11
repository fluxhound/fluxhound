"""Music Mode 2 ("Spectrum Mode"): fully autonomous, full-spectrum light show.

Unlike MusicMode (manual colour choice, bass-only brightness), this mode
drives hue, saturation, and brightness entirely from the audio via
SpectrumShowEnvelope - see src/audio/spectrum_show.py for the concept.

Shares MusicMode's hard-won reliability settings: `bulb` should be a
TuyaBulb built the same way (persistent=True, fail-fast retry/timeout),
since every lesson from that mode - persistent connections, a sane
connection_retry_limit, one DP write per update, nowait sends - applies
identically here. colour_data (DP 24) already bundles hue/saturation/
value into a single write, so driving all three doesn't cost anything
extra.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

from src.audio.loopback import BLOCK_SIZE, SAMPLE_RATE, LoopbackStream
from src.audio.spectrum_show import SpectrumShowEnvelope
from src.tuya.device import TuyaBulb, TuyaConnectionError, WORK_MODE_COLOUR

SEND_INTERVAL_SECONDS = 0.15  # caps commands sent to the bulb, independent of audio block rate


class SpectrumMode:
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
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self) -> None:
        try:
            with LoopbackStream(SAMPLE_RATE, BLOCK_SIZE) as stream:
                envelope = SpectrumShowEnvelope(SAMPLE_RATE, BLOCK_SIZE)
                self._bulb.set_work_mode_nowait(WORK_MODE_COLOUR)
                time.sleep(0.15)  # give the device a beat before the first hot-loop send
                last_send = 0.0
                while not self._stop_event.is_set():
                    block = stream.read_block()
                    now = time.monotonic()
                    hue, saturation, value = envelope.process(block, now)
                    if now - last_send >= SEND_INTERVAL_SECONDS:
                        last_send = now
                        self._send(hue, saturation, value)
        except Exception as exc:  # audio device errors don't propagate out of a thread otherwise
            self._report_error(str(exc))
        finally:
            self._bulb.close()

    def _send(self, hue: int, saturation: int, value: int) -> None:
        try:
            self._bulb.set_colour_data_value_nowait(hue, saturation, value)
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
