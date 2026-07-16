"""Ambience Mode: continuously analyses the screen's dominant colour and brightness
(src/screen/ambience_show.py) and drives one or more bulbs from it.

Reuses every reliability lesson from Audio Mode's debugging history: persistent
connection, connection_retry_limit=2, fail-fast timeout, nowait sends, one DP write
per update (colour_data already bundles hue/saturation/value) - see
src/modes/custom_mode.py for the original writeup of why that combination matters.
Unlike CustomMode, there's no per-target source assignment here - the screen's
colour mood drives hue, saturation, and brightness together, all the time.

Gaming Mode (gaming_mode=True) repurposes the "Set area" region: instead of
narrowing the *ambient* reading to just that region, the ambient reading always
watches the whole monitor again, and the region becomes a dedicated health/resource
-bar watcher (src/screen/health_bar.py) running alongside it, using
HealthBarTracker's fixed default TriggerConfig - a decrease/increase briefly
overrides the bulb with a red/green flash, and a low reading holds a continuous
red glow, both taking priority over the ambient colour for as long as they're
active. This built-in watcher is what every user gets, free or paid.

trigger_watchers (paid-tier, via the Custom Trigger Editor) adds any number of
further watchers on top of that one, each with its own screen region *and* its
own TriggerConfig - custom thresholds, flash colours, and multi-step glow bands,
instead of the fixed defaults. All active watchers (the built-in one, if any,
first, then trigger_watchers in order) are evaluated every tick; the first one
with a non-None override wins for that tick. Purely additive - trigger_watchers
being empty reproduces the exact original Gaming Mode behaviour.

Both the built-in watcher and every custom watcher may also carry a painted,
non-rectangular mask (BrushSelectorWindow, region_mask/watcher.region.mask -
see health_bar.py's encode_region_mask/decode_region_mask) narrowing
fill_fraction detection to just the painted pixels within their region - for a
bar that isn't a plain rectangle (a bent arc, a thin diagonal sliver) - or use
TriggerConfig.detection_mode="ocr" to read a printed number instead of a
colour fill, for health/mana shown as text/digits.

colour_sensitivity/smoothing (0-100 each, 50 = neutral) tune every ambient-
reading AmbienceEnvelope in play - see src/screen/ambience_show.py for what
each one scales. Live-adjustable via set_colour_sensitivity/set_smoothing
while running (same pattern as CustomMode.set_sensitivity for Audio Mode):
_apply_live_ambience_settings reads the current values under a lock once per
capture tick and pushes them into whichever envelope(s) are active that tick,
so a slider dragged mid-scene takes effect on the very next frame.

Multi-region mode (multi_region_mode=True, mutually exclusive with Gaming Mode) is
a different way of using several regions: instead of one ambient reading applied to
every bulb alike, bulb_regions gives each bulb (by position in the list, parallel to
bulbs) its own screen region to watch, so a merged group's positioned bulbs can each
reflect a genuinely different part of the screen instead of a shared average. A bulb
whose entry in bulb_regions is None (no position, or no region assigned to its
position) falls back to the ordinary whole-monitor ambient reading. Bulbs sharing
the same region share one ScreenCapture/AmbienceEnvelope pair rather than
duplicating the capture.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

import numpy as np

from src.ambience_config import TriggerWatcher
from src.screen.ambience_show import (
    AMBIENCE_SLIDER_DEFAULT,
    AmbienceEnvelope,
    colour_sensitivity_to_threshold,
    smoothing_to_factor,
)
from src.screen.capture import ScreenCapture
from src.screen.health_bar import HealthBarTracker, decode_region_mask
from src.tuya.device import TuyaBulb, TuyaConnectionError, WORK_MODE_COLOUR

CAPTURE_INTERVAL_SECONDS = 0.1
SEND_INTERVAL_SECONDS = 0.2  # caps commands sent to the bulb, independent of capture rate

# A live test tried giving OCR-mode watchers a much larger (effectively
# disabled) downsample_width than fill_fraction's usual ~160px default, on
# the assumption that full resolution would help rapidocr read small in-game
# text. Repeated, reproducible testing against a real on-screen "87/100"
# showed the *opposite*: the same crop read correctly every time at the
# default ~160px-wide downsample, and failed every time at full native
# resolution - rapidocr's text *detector* step appears to want text at a
# certain relative scale within the frame, not "as sharp as possible", so
# ScreenCapture's existing default downsample is left untouched for OCR mode
# too rather than guessing further at an untested "fix".

class AmbienceMode:
    """Captures the screen on a background thread and drives one or more bulbs from
    its dominant colour/brightness (and, in Gaming Mode, a watched bar/orb's fill
    level)."""

    def __init__(self, bulbs: list[TuyaBulb],
                 monitor_index: int = 0, region: tuple[int, int, int, int] | None = None,
                 region_mask: np.ndarray | None = None,
                 gaming_mode: bool = False,
                 multi_region_mode: bool = False,
                 bulb_regions: list[tuple[int, int, int, int] | None] | None = None,
                 trigger_watchers: list[TriggerWatcher] | None = None,
                 colour_sensitivity: float = AMBIENCE_SLIDER_DEFAULT,
                 smoothing: float = AMBIENCE_SLIDER_DEFAULT,
                 on_error: Callable[[str], None] | None = None,
                 on_recovered: Callable[[], None] | None = None,
                 on_update: Callable[[int, int, int], None] | None = None):
        self._bulbs = bulbs
        self._monitor_index = monitor_index
        self._region = region
        # Only meaningful for Gaming Mode's built-in watcher (fill_fraction mode) -
        # a painted, non-rectangular mask within self._region, from BrushSelectorWindow
        # (see MainWindow._on_region_painted). None means "the whole region counts",
        # exactly today's behaviour. Each custom trigger_watcher carries its own mask
        # directly on its own region (AmbienceRegion.mask), decoded below instead.
        self._region_mask = region_mask
        self._gaming_mode = gaming_mode
        self._trigger_watchers = trigger_watchers or []
        self._settings_lock = threading.Lock()
        self._colour_sensitivity = colour_sensitivity
        self._smoothing = smoothing
        # Only actually used when there's a region assigned to at least one bulb -
        # otherwise every bulb falls back to the plain whole-monitor reading anyway,
        # same as multi-region mode being off.
        self._multi_region_mode = multi_region_mode and bulb_regions is not None and any(
            r is not None for r in bulb_regions
        )
        self._bulb_regions = bulb_regions if self._multi_region_mode else None
        self._on_error = on_error
        self._on_recovered = on_recovered
        self._on_update = on_update
        self._had_error = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def set_colour_sensitivity(self, value: float) -> None:
        """Change the "boring colour" filter strength (0-100) while running -
        see src/screen/ambience_show.py for what this scales."""
        with self._settings_lock:
            self._colour_sensitivity = value

    def set_smoothing(self, value: float) -> None:
        """Change the colour-transition smoothing (0-100) while running, same
        live-update contract as set_colour_sensitivity."""
        with self._settings_lock:
            self._smoothing = value

    def _apply_live_ambience_settings(self, *envelopes: AmbienceEnvelope) -> None:
        """Read the current slider values once (under the lock) and push them
        into every ambient-reading envelope currently in use - called once per
        capture tick, so a slider dragged mid-scene takes effect on the very
        next frame without losing the envelope's already-smoothed state."""
        with self._settings_lock:
            colour_sensitivity = self._colour_sensitivity
            smoothing = self._smoothing
        threshold = colour_sensitivity_to_threshold(colour_sensitivity)
        factor = smoothing_to_factor(smoothing)
        for envelope in envelopes:
            envelope.set_boring_saturation_threshold(threshold)
            envelope.set_smoothing_factor(factor)

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
        try:
            self._prepare_bulbs()
            if self._multi_region_mode:
                self._run_multi_region()
            else:
                self._run_single_reading()
        except Exception as exc:  # capture/analysis errors don't propagate out of a thread otherwise
            self._report_error(str(exc))
        finally:
            for bulb in self._bulbs:
                bulb.close()

    def _prepare_bulbs(self) -> None:
        for bulb in self._bulbs:
            bulb.set_work_mode_nowait(WORK_MODE_COLOUR)
        time.sleep(0.15)  # give the devices a beat before the first hot-loop send

    def _run_single_reading(self) -> None:
        """Normal ambient mode, and Gaming Mode: one reading, sent to every bulb
        alike (a watcher's override replaces it for all of them too)."""
        # Gaming Mode always watches the *whole* monitor for the ambient reading -
        # the region is repurposed as the built-in watcher below instead of
        # narrowing the ambient reading to it.
        ambient_capture = ScreenCapture(
            monitor_index=self._monitor_index, region=None if self._gaming_mode else self._region
        )
        # The built-in watcher (fixed defaults, from the "Set area" region) comes
        # first, then any paid-tier custom watchers - first non-None override wins
        # each tick, evaluated in this order.
        watcher_captures: list[tuple[ScreenCapture, HealthBarTracker]] = []
        if self._gaming_mode:
            if self._region is not None:
                watcher_captures.append((
                    ScreenCapture(monitor_index=self._monitor_index, region=self._region),
                    HealthBarTracker(mask=self._region_mask),
                ))
            for watcher in self._trigger_watchers:
                watcher_region = (watcher.region.x, watcher.region.y, watcher.region.width, watcher.region.height)
                watcher_mask = (
                    decode_region_mask(watcher.region.mask, watcher.region.height, watcher.region.width)
                    if watcher.region.mask else None
                )
                watcher_captures.append((
                    ScreenCapture(monitor_index=self._monitor_index, region=watcher_region),
                    HealthBarTracker(config=watcher.config, mask=watcher_mask),
                ))
        try:
            envelope = AmbienceEnvelope()
            last_send = 0.0
            while not self._stop_event.is_set():
                self._apply_live_ambience_settings(envelope)
                frame = ambient_capture.grab_rgb()
                reading = envelope.process(frame)

                override: tuple[int, int, int] | None = None
                now = time.monotonic()
                for capture, tracker in watcher_captures:
                    result = tracker.process(capture.grab_rgb(), now)
                    if override is None and result is not None:
                        override = result

                if now - last_send >= SEND_INTERVAL_SECONDS:
                    last_send = now
                    sent = override if override is not None else reading
                    self._send([sent] * len(self._bulbs))
                self._stop_event.wait(CAPTURE_INTERVAL_SECONDS)
        finally:
            ambient_capture.close()
            for capture, _ in watcher_captures:
                capture.close()

    def _run_multi_region(self) -> None:
        """Each bulb gets its own region's reading (self._bulb_regions, parallel to
        self._bulbs); bulbs sharing a region share one capture/envelope pair, and
        bulbs with no region assigned share one whole-monitor fallback pair."""
        needs_fallback = any(region is None for region in self._bulb_regions)
        whole_capture = ScreenCapture(monitor_index=self._monitor_index) if needs_fallback else None
        whole_envelope = AmbienceEnvelope() if needs_fallback else None
        region_captures: dict[tuple[int, int, int, int], ScreenCapture] = {}
        region_envelopes: dict[tuple[int, int, int, int], AmbienceEnvelope] = {}
        for region in self._bulb_regions:
            if region is not None and region not in region_captures:
                region_captures[region] = ScreenCapture(monitor_index=self._monitor_index, region=region)
                region_envelopes[region] = AmbienceEnvelope()
        all_envelopes = list(region_envelopes.values()) + ([whole_envelope] if whole_envelope is not None else [])
        try:
            last_send = 0.0
            while not self._stop_event.is_set():
                self._apply_live_ambience_settings(*all_envelopes)
                whole_reading = None
                if whole_capture is not None and whole_envelope is not None:
                    whole_reading = whole_envelope.process(whole_capture.grab_rgb())
                region_readings = {
                    region: region_envelopes[region].process(capture.grab_rgb())
                    for region, capture in region_captures.items()
                }
                readings = [
                    region_readings[region] if region is not None else whole_reading
                    for region in self._bulb_regions
                ]

                now = time.monotonic()
                if now - last_send >= SEND_INTERVAL_SECONDS:
                    last_send = now
                    self._send(readings)
                self._stop_event.wait(CAPTURE_INTERVAL_SECONDS)
        finally:
            if whole_capture is not None:
                whole_capture.close()
            for capture in region_captures.values():
                capture.close()

    def _send(self, readings: list[tuple[int, int, int]]) -> None:
        """readings is parallel to self._bulbs - one (hue, saturation, value) per
        bulb. The live-state indicator (on_update) only shows one colour, so it
        mirrors the first bulb's reading."""
        if self._on_update is not None and readings:
            self._on_update(*readings[0])
        error_message: str | None = None
        for bulb, (hue, saturation, value) in zip(self._bulbs, readings):
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
