"""Audio Mode: user-configurable full-spectrum light show.

Wraps CustomShowEnvelope (src/audio/custom_show.py) - hue/brightness/
saturation are each driven by whichever source (or none) the caller
assigned via `set_assignment`. A target with no source assigned keeps
sending its last value - see src/audio/custom_show.py for the assignment
scheme. `set_manual_override` deactivates a target's assignment and sets
its value directly in one atomic step, for when the user takes manual
control of a property (a palette pick, or the brightness/saturation
slider) while this mode is running.

Reuses every reliability lesson from the mode's debugging history:
persistent connection, connection_retry_limit=2, fail-fast timeout,
nowait sends, one DP write per update (colour_data already bundles
hue/saturation/value).
"""
from __future__ import annotations

import threading
import time
from typing import Callable

from src.audio.custom_show import (
    SOURCE_ENERGY,
    SOURCE_TIMBRE,
    SOURCES,
    TARGET_RANGES,
    TARGETS,
    CustomShowEnvelope,
    target_value,
)
from src.audio.loopback import BLOCK_SIZE, SAMPLE_RATE, LoopbackStream
from src.tuya.device import TuyaBulb, TuyaConnectionError, WORK_MODE_COLOUR

SEND_INTERVAL_SECONDS = 0.15  # caps commands sent to the bulb, independent of audio block rate


class CustomMode:
    """Captures system audio on a background thread and drives one bulb from it, using
    a user-configurable source-to-target assignment."""

    def __init__(self, bulb: TuyaBulb, assignment: dict[str, str | None], sensitivity: dict[str, float],
                 initial_hue: int = 0, initial_saturation: int = 1000, initial_brightness: int = 10,
                 on_error: Callable[[str], None] | None = None,
                 on_recovered: Callable[[], None] | None = None):
        self._bulb = bulb
        self._on_error = on_error
        self._on_recovered = on_recovered
        self._had_error = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._lock = threading.Lock()
        self._assignment: dict[str, str | None] = dict(assignment)
        self._sensitivity: dict[str, float] = dict(sensitivity)
        # Seeded from the bulb's actual state at mode entry (see MainWindow). A target
        # keeps this value for the whole session if nothing is assigned to it.
        self._current = {
            "hue": initial_hue, "saturation": initial_saturation, "brightness": initial_brightness,
        }

    def set_assignment(self, target: str, source: str | None) -> None:
        """Change which source drives a target (or clear it) while running."""
        with self._lock:
            self._assignment[target] = source

    def set_manual_override(self, target: str, value: int) -> None:
        """Deactivate a target's source assignment and set its value directly, for when
        the user manually takes control of a property (palette pick, brightness or
        saturation slider) while this mode is running."""
        with self._lock:
            self._assignment[target] = None
            self._current[target] = value

    def set_sensitivity(self, source: str, value: float) -> None:
        """Change one source's sensitivity (0-100) while running."""
        with self._lock:
            self._sensitivity[source] = value

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
                with self._lock:
                    sensitivity = dict(self._sensitivity)
                envelope = CustomShowEnvelope(SAMPLE_RATE, BLOCK_SIZE, sensitivity=sensitivity)
                self._seed_envelope(envelope)
                self._bulb.set_work_mode_nowait(WORK_MODE_COLOUR)
                time.sleep(0.15)  # give the device a beat before the first hot-loop send
                last_send = 0.0
                while not self._stop_event.is_set():
                    block = stream.read_block()
                    now = time.monotonic()
                    with self._lock:
                        for source in SOURCES:
                            envelope.set_sensitivity(source, self._sensitivity[source])
                    source_values = envelope.process(block, now)
                    with self._lock:
                        assignment = dict(self._assignment)
                    for target in TARGETS:
                        source = assignment.get(target)
                        if source is not None:
                            self._current[target] = target_value(target, source_values[source])
                    if now - last_send >= SEND_INTERVAL_SECONDS:
                        last_send = now
                        self._send()
        except Exception as exc:  # audio device errors don't propagate out of a thread otherwise
            self._report_error(str(exc))
        finally:
            self._bulb.close()

    def _seed_envelope(self, envelope: CustomShowEnvelope) -> None:
        """Translate the bulb's current per-target values back through whichever source
        is currently assigned to them, so a continuous source starts drifting from the
        bulb's actual state instead of a hardcoded default."""
        seeds: dict[str, float] = {}
        for target, source in self._assignment.items():
            if source not in (SOURCE_TIMBRE, SOURCE_ENERGY):
                continue
            lo, hi = TARGET_RANGES[target]
            current = self._current.get(target, lo)
            normalized = (current - lo) / (hi - lo) if hi != lo else 0.0
            seeds[source] = normalized
        envelope.set_initial(**seeds)

    def _send(self) -> None:
        try:
            self._bulb.set_colour_data_value_nowait(
                self._current["hue"], self._current["saturation"], self._current["brightness"]
            )
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
