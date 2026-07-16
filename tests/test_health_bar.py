"""Unit tests for src.screen.health_bar (synthetic frames, no screen capture)."""
from __future__ import annotations

import time

import numpy as np
import pytest

from src.screen import health_bar
from src.screen.health_bar import (
    DECREASE_COLOUR,
    DETECTION_MODE_OCR,
    INCREASE_COLOUR,
    LOW_HEALTH_COLOUR,
    HealthBarTracker,
    ThresholdBand,
    TriggerConfig,
    calibrate_bar_colour,
    decode_region_mask,
    encode_region_mask,
    fill_fraction,
    measure_fill,
)


def _bar_frame(fill_fraction_pct: float, size: int = 100,
                fill_rgb: tuple[int, int, int] = (220, 20, 20),
                track_rgb: tuple[int, int, int] = (40, 30, 30)) -> np.ndarray:
    """A horizontal bar: vivid fill, dark same-hue "empty track" by default - the
    realistic case that requires matching on more than just hue."""
    frame = np.zeros((20, size, 3), dtype=np.uint8)
    filled_width = int(size * fill_fraction_pct)
    frame[:, :filled_width] = fill_rgb
    frame[:, filled_width:] = track_rgb
    return frame


def test_calibrate_bar_colour_picks_up_the_fill_hue_not_the_dark_track():
    colour = calibrate_bar_colour(_bar_frame(1.0))
    assert colour is not None
    hue, saturation, value = colour
    assert hue == 0.0
    assert saturation > 0.8  # the vivid fill, not the dark ~0.25-saturation track


def test_fill_fraction_tracks_the_bar_precisely_despite_a_same_hue_dark_track():
    colour = calibrate_bar_colour(_bar_frame(1.0))
    for pct in (1.0, 0.75, 0.5, 0.25, 0.05, 0.0):
        assert fill_fraction(_bar_frame(pct), colour) == pytest.approx(pct, abs=0.02)


def test_calibrate_returns_none_for_a_frame_with_no_vivid_colour():
    grey_frame = np.full((10, 10, 3), 128, dtype=np.uint8)
    assert calibrate_bar_colour(grey_frame) is None


def test_calibrating_at_a_low_fill_level_is_not_diluted_by_the_dominant_dark_track():
    """Regression guard: identifying the fill colour while the bar is mostly empty
    must still pick out the vivid fill's true colour, not an average dragged
    toward the much more numerous dark "track" pixels that happen to share its
    hue."""
    low_fill_colour = calibrate_bar_colour(_bar_frame(0.05))
    full_colour = calibrate_bar_colour(_bar_frame(1.0))
    assert low_fill_colour is not None
    assert low_fill_colour == pytest.approx(full_colour, abs=0.01)


def test_measure_fill_reads_zero_for_a_fully_empty_bar():
    assert measure_fill(_bar_frame(0.0)) == 0.0


def test_tracker_flashes_red_on_a_meaningful_decrease():
    tracker = HealthBarTracker()
    assert tracker.process(_bar_frame(1.0), now=0.0) is None  # baseline, no change yet
    assert tracker.process(_bar_frame(0.5), now=0.2) == DECREASE_COLOUR


def test_tracker_flashes_green_on_a_meaningful_increase():
    tracker = HealthBarTracker()
    tracker.process(_bar_frame(0.3), now=0.0)
    assert tracker.process(_bar_frame(0.8), now=0.2) == INCREASE_COLOUR


def test_tracker_ignores_tiny_jitter_below_the_change_epsilon():
    tracker = HealthBarTracker()
    tracker.process(_bar_frame(0.5), now=0.0)
    assert tracker.process(_bar_frame(0.505), now=0.2) is None


def test_tracker_flash_expires_after_the_blink_duration():
    tracker = HealthBarTracker()
    tracker.process(_bar_frame(1.0), now=0.0)
    assert tracker.process(_bar_frame(0.5), now=0.2) == DECREASE_COLOUR
    assert tracker.process(_bar_frame(0.5), now=0.3) == DECREASE_COLOUR  # still within the window
    assert tracker.process(_bar_frame(0.5), now=1.0) is None  # blink window has elapsed


def test_tracker_holds_low_health_glow_continuously():
    tracker = HealthBarTracker()
    tracker.process(_bar_frame(1.0), now=0.0)
    assert tracker.process(_bar_frame(0.05), now=0.2) == LOW_HEALTH_COLOUR
    assert tracker.process(_bar_frame(0.05), now=5.0) == LOW_HEALTH_COLOUR  # long after any flash would expire


def test_low_health_glow_takes_priority_over_a_simultaneous_flash():
    tracker = HealthBarTracker()
    tracker.process(_bar_frame(0.5), now=0.0)
    # A drop straight into low-health territory would normally also qualify as a
    # "decrease" flash - low health should win.
    assert tracker.process(_bar_frame(0.05), now=0.2) == LOW_HEALTH_COLOUR


def test_recovering_above_the_low_health_threshold_resumes_normal_flash_behaviour():
    tracker = HealthBarTracker()
    tracker.process(_bar_frame(0.05), now=0.0)
    assert tracker.process(_bar_frame(0.05), now=0.2) == LOW_HEALTH_COLOUR
    assert tracker.process(_bar_frame(0.9), now=0.4) == INCREASE_COLOUR


def test_tracker_first_call_establishes_a_baseline_without_a_false_trigger():
    tracker = HealthBarTracker()
    assert tracker.process(_bar_frame(0.5), now=0.0) is None


def test_tracker_survives_starting_on_a_fully_empty_bar():
    """Regression guard: the old design calibrated once, at startup - if that one
    attempt landed on a fully empty bar, tracking silently never worked again for
    the rest of the session. Recalibrating every frame means an empty first frame
    is just read as a real, meaningful fraction of 0.0 (correctly triggering the
    low-health glow immediately, same as any other sub-10% reading would), and a
    later refill is still detected normally from that baseline."""
    tracker = HealthBarTracker()
    assert tracker.process(_bar_frame(0.0), now=0.0) == LOW_HEALTH_COLOUR
    assert tracker.process(_bar_frame(0.9), now=0.2) == INCREASE_COLOUR


def test_default_trigger_config_matches_the_original_fixed_constants():
    """Gaming Mode's built-in, free-tier watcher relies on TriggerConfig()'s
    defaults being exactly the values Gaming Mode always used - a paid-tier
    Custom Trigger Editor changes nothing about the free experience by existing."""
    config = TriggerConfig()
    assert config.change_epsilon == pytest.approx(0.02)
    assert config.blink_duration_seconds == pytest.approx(0.5)
    assert config.decrease_colour == DECREASE_COLOUR
    assert config.increase_colour == INCREASE_COLOUR
    assert config.threshold_bands == [ThresholdBand(threshold=0.10, colour=LOW_HEALTH_COLOUR)]


def test_active_band_picks_the_most_severe_satisfied_band():
    config = TriggerConfig(threshold_bands=[
        ThresholdBand(threshold=0.5, colour=(40, 1000, 1000)),   # amber
        ThresholdBand(threshold=0.2, colour=(0, 1000, 1000)),    # red
    ])
    assert config.active_band(0.45) == ThresholdBand(threshold=0.5, colour=(40, 1000, 1000))
    assert config.active_band(0.15) == ThresholdBand(threshold=0.2, colour=(0, 1000, 1000))
    assert config.active_band(0.9) is None


def test_tracker_supports_multi_step_threshold_bands():
    """A custom watcher can glow a different colour at different severity levels,
    not just one fixed low-health threshold."""
    config = TriggerConfig(threshold_bands=[
        ThresholdBand(threshold=0.5, colour=(40, 1000, 1000)),   # amber below 50%
        ThresholdBand(threshold=0.2, colour=(0, 1000, 1000)),    # red below 20%
    ])
    tracker = HealthBarTracker(config=config)
    tracker.process(_bar_frame(1.0), now=0.0)
    assert tracker.process(_bar_frame(0.4), now=0.2) == (40, 1000, 1000)
    assert tracker.process(_bar_frame(0.1), now=0.4) == (0, 1000, 1000)


def test_tracker_uses_a_custom_config_instead_of_the_fixed_defaults():
    config = TriggerConfig(
        change_epsilon=0.3, decrease_colour=(200, 1000, 1000), increase_colour=(60, 1000, 1000),
        threshold_bands=[],
    )
    tracker = HealthBarTracker(config=config)
    tracker.process(_bar_frame(1.0), now=0.0)
    # A drop that would trip the default epsilon (0.02) must NOT trigger with a
    # much looser custom epsilon (0.3).
    assert tracker.process(_bar_frame(0.9), now=0.2) is None
    assert tracker.process(_bar_frame(0.5), now=0.4) == (200, 1000, 1000)


def test_encode_decode_region_mask_round_trips():
    mask = np.zeros((13, 27), dtype=bool)
    mask[2:8, 5:20] = True
    encoded = encode_region_mask(mask)
    decoded = decode_region_mask(encoded, height=13, width=27)
    assert decoded.shape == mask.shape
    assert np.array_equal(decoded, mask)


def test_mask_restricts_calibration_and_fill_fraction_to_the_painted_pixels():
    """A region might contain the bar plus some unrelated vivid content within
    the same bounding rectangle (e.g. a nearby colourful icon) - the mask must
    make that irrelevant to both identifying the fill colour and measuring it."""
    frame = np.zeros((20, 100, 3), dtype=np.uint8)
    frame[:, :50] = (220, 20, 20)   # the actual bar, fully filled - vivid red
    frame[:, 50:] = (20, 20, 220)   # unrelated vivid blue content, NOT part of the bar
    mask = np.zeros((20, 100), dtype=bool)
    mask[:, :50] = True  # only the red half is the watched bar

    colour = calibrate_bar_colour(frame, mask)
    assert colour is not None
    hue, saturation, value = colour
    assert hue == 0.0  # red, not blue
    assert measure_fill(frame, mask) == pytest.approx(1.0, abs=0.02)


def test_tracker_accepts_a_mask_and_ignores_unmasked_pixels():
    bar = _bar_frame(1.0)  # 100px wide, fully filled
    wide_frame = np.zeros((20, 150, 3), dtype=np.uint8)
    wide_frame[:, :100] = bar
    wide_frame[:, 100:] = (20, 20, 220)  # unrelated vivid blob outside the mask
    mask = np.zeros((20, 150), dtype=bool)
    mask[:, :100] = True

    config = TriggerConfig(threshold_bands=[ThresholdBand(threshold=0.5, colour=(40, 1000, 1000))])
    tracker = HealthBarTracker(config=config, mask=mask)
    tracker.process(wide_frame, now=0.0)
    # the bar itself is fully filled (1.0), well above the 0.5 threshold band -
    # must not glow, even though half the *rectangle* (unmasked) is a different
    # vivid colour that would otherwise dilute/skew the reading
    assert tracker.process(wide_frame, now=0.2) is None


def test_tracker_ocr_mode_feeds_the_same_threshold_band_state_machine(monkeypatch):
    """OCR mode's background-thread polling is exercised end to end (a fake,
    instant read_text stands in for the real ~0.3s model) - the resulting
    fraction must drive the exact same threshold_bands/blink logic
    fill_fraction mode uses, just fed from a different source."""
    monkeypatch.setattr(health_bar.ocr_reader, "read_text", lambda frame: "50/100")
    config = TriggerConfig(
        detection_mode=DETECTION_MODE_OCR,
        threshold_bands=[ThresholdBand(threshold=0.6, colour=(40, 1000, 1000))],
    )
    tracker = HealthBarTracker(config=config)
    frame = np.zeros((10, 10, 3), dtype=np.uint8)  # content is irrelevant - read_text is faked

    tracker.process(frame, now=0.0)
    deadline = time.monotonic() + 2.0
    while tracker._ocr_fraction is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert tracker._ocr_fraction == pytest.approx(0.5)
    assert tracker.process(frame, now=0.1) == (40, 1000, 1000)  # 0.5 < 0.6 threshold - should glow


def test_tracker_ocr_mode_does_not_start_a_new_read_before_the_poll_interval(monkeypatch):
    call_count = {"n": 0}

    def fake_read_text(frame):
        call_count["n"] += 1
        return "50/100"

    monkeypatch.setattr(health_bar.ocr_reader, "read_text", fake_read_text)
    tracker = HealthBarTracker(config=TriggerConfig(detection_mode=DETECTION_MODE_OCR))
    frame = np.zeros((10, 10, 3), dtype=np.uint8)

    tracker.process(frame, now=0.0)
    deadline = time.monotonic() + 2.0
    while tracker._ocr_fraction is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert call_count["n"] == 1

    tracker.process(frame, now=0.1)  # well within OCR_POLL_INTERVAL_SECONDS (1.0s)
    tracker.process(frame, now=0.5)
    time.sleep(0.05)
    assert call_count["n"] == 1  # no new read started yet


def test_tracker_ocr_mode_holds_the_last_reading_when_ocr_finds_nothing(monkeypatch):
    """A missed OCR read (unrecognizable text this cycle) must not reset the
    tracker back to "no baseline" - it should keep evaluating against the last
    good reading, the same way a fill_fraction tick would with an unchanged
    frame."""
    monkeypatch.setattr(health_bar.ocr_reader, "read_text", lambda frame: "50/100")
    config = TriggerConfig(detection_mode=DETECTION_MODE_OCR)
    tracker = HealthBarTracker(config=config)
    frame = np.zeros((10, 10, 3), dtype=np.uint8)

    tracker.process(frame, now=0.0)
    deadline = time.monotonic() + 2.0
    while tracker._ocr_fraction is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert tracker._ocr_fraction == pytest.approx(0.5)

    health_bar.ocr_reader.read_text = lambda frame: "unreadable garbage"
    tracker.process(frame, now=10.0)  # forces a new OCR attempt (past the poll interval)
    time.sleep(0.1)
    assert tracker._ocr_fraction == pytest.approx(0.5)  # unchanged - the bad read was ignored


def test_tracker_detects_a_decrease_even_when_the_fill_colour_shifts():
    """Regression guard: some games recolour the bar as it depletes (green -> amber
    -> red is a common health-bar convention). Since the fill colour is
    re-identified fresh every frame, a decrease must still register correctly even
    though the hue itself has also changed between frames."""
    tracker = HealthBarTracker()
    green_frame = _bar_frame(0.9, fill_rgb=(20, 200, 20), track_rgb=(15, 30, 15))
    amber_frame = _bar_frame(0.4, fill_rgb=(220, 150, 20), track_rgb=(30, 25, 22))
    tracker.process(green_frame, now=0.0)
    assert tracker.process(amber_frame, now=0.2) == DECREASE_COLOUR
