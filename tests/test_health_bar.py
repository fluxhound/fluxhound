"""Unit tests for src.screen.health_bar (synthetic frames, no screen capture)."""
from __future__ import annotations

import time

import numpy as np
import pytest

from src.screen import health_bar
from src.screen.health_bar import (
    AUTO_DETECTION_MAX_OCR_ATTEMPTS_WITHOUT_SUCCESS,
    AUTO_DETECTION_OCR_FRESHNESS_SECONDS,
    DECREASE_COLOUR,
    DETECTION_MODE_AUTO,
    DETECTION_MODE_FILL_FRACTION,
    DETECTION_MODE_OCR,
    INCREASE_COLOUR,
    LOW_HEALTH_COLOUR,
    OCR_MASK_FILL_COLOUR,
    OCR_POLL_INTERVAL_SECONDS,
    HealthBarTracker,
    ThresholdBand,
    TriggerConfig,
    _mask_frame_for_ocr,
    _match_mask_to_frame,
    _resize_mask_nearest,
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
    tracker = HealthBarTracker(config=TriggerConfig(detection_mode=DETECTION_MODE_FILL_FRACTION))
    assert tracker.process(_bar_frame(1.0), now=0.0) is None  # baseline, no change yet
    assert tracker.process(_bar_frame(0.5), now=0.2) == DECREASE_COLOUR


def test_tracker_flashes_green_on_a_meaningful_increase():
    tracker = HealthBarTracker(config=TriggerConfig(detection_mode=DETECTION_MODE_FILL_FRACTION))
    tracker.process(_bar_frame(0.3), now=0.0)
    assert tracker.process(_bar_frame(0.8), now=0.2) == INCREASE_COLOUR


def test_tracker_ignores_tiny_jitter_below_the_change_epsilon():
    tracker = HealthBarTracker(config=TriggerConfig(detection_mode=DETECTION_MODE_FILL_FRACTION))
    tracker.process(_bar_frame(0.5), now=0.0)
    assert tracker.process(_bar_frame(0.505), now=0.2) is None


def test_tracker_flash_expires_after_the_blink_duration():
    tracker = HealthBarTracker(config=TriggerConfig(detection_mode=DETECTION_MODE_FILL_FRACTION))
    tracker.process(_bar_frame(1.0), now=0.0)
    assert tracker.process(_bar_frame(0.5), now=0.2) == DECREASE_COLOUR
    assert tracker.process(_bar_frame(0.5), now=0.3) == DECREASE_COLOUR  # still within the window
    assert tracker.process(_bar_frame(0.5), now=1.0) is None  # blink window has elapsed


def test_tracker_holds_low_health_glow_continuously():
    tracker = HealthBarTracker(config=TriggerConfig(detection_mode=DETECTION_MODE_FILL_FRACTION))
    tracker.process(_bar_frame(1.0), now=0.0)
    assert tracker.process(_bar_frame(0.05), now=0.2) == LOW_HEALTH_COLOUR
    assert tracker.process(_bar_frame(0.05), now=5.0) == LOW_HEALTH_COLOUR  # long after any flash would expire


def test_low_health_glow_takes_priority_over_a_simultaneous_flash():
    tracker = HealthBarTracker(config=TriggerConfig(detection_mode=DETECTION_MODE_FILL_FRACTION))
    tracker.process(_bar_frame(0.5), now=0.0)
    # A drop straight into low-health territory would normally also qualify as a
    # "decrease" flash - low health should win.
    assert tracker.process(_bar_frame(0.05), now=0.2) == LOW_HEALTH_COLOUR


def test_recovering_above_the_low_health_threshold_resumes_normal_flash_behaviour():
    tracker = HealthBarTracker(config=TriggerConfig(detection_mode=DETECTION_MODE_FILL_FRACTION))
    tracker.process(_bar_frame(0.05), now=0.0)
    assert tracker.process(_bar_frame(0.05), now=0.2) == LOW_HEALTH_COLOUR
    assert tracker.process(_bar_frame(0.9), now=0.4) == INCREASE_COLOUR


def test_tracker_first_call_establishes_a_baseline_without_a_false_trigger():
    tracker = HealthBarTracker(config=TriggerConfig(detection_mode=DETECTION_MODE_FILL_FRACTION))
    assert tracker.process(_bar_frame(0.5), now=0.0) is None


def test_tracker_survives_starting_on_a_fully_empty_bar():
    """Regression guard: the old design calibrated once, at startup - if that one
    attempt landed on a fully empty bar, tracking silently never worked again for
    the rest of the session. Recalibrating every frame means an empty first frame
    is just read as a real, meaningful fraction of 0.0 (correctly triggering the
    low-health glow immediately, same as any other sub-10% reading would), and a
    later refill is still detected normally from that baseline."""
    tracker = HealthBarTracker(config=TriggerConfig(detection_mode=DETECTION_MODE_FILL_FRACTION))
    assert tracker.process(_bar_frame(0.0), now=0.0) == LOW_HEALTH_COLOUR
    assert tracker.process(_bar_frame(0.9), now=0.2) == INCREASE_COLOUR


def test_default_trigger_config_matches_the_original_fixed_constants():
    """Gaming Mode's built-in, free-tier watcher relies on TriggerConfig()'s
    reaction defaults being exactly the values Gaming Mode always used - a
    paid-tier Custom Trigger Editor changes nothing about the free
    experience by existing. detection_mode defaults to "auto" - the same
    detection capability (colour bar or printed number, auto-recognized) is
    available on both tiers; what stays paid-exclusive is configuring the
    reaction and watching more than one region, not which detection is used."""
    config = TriggerConfig()
    assert config.change_epsilon == pytest.approx(0.02)
    assert config.blink_duration_seconds == pytest.approx(0.5)
    assert config.decrease_colour == DECREASE_COLOUR
    assert config.increase_colour == INCREASE_COLOUR
    assert config.threshold_bands == [ThresholdBand(threshold=0.10, colour=LOW_HEALTH_COLOUR)]
    assert config.detection_mode == DETECTION_MODE_AUTO
    assert config.ocr_max_value == pytest.approx(100.0)


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
    config = TriggerConfig(detection_mode=DETECTION_MODE_FILL_FRACTION, threshold_bands=[
        ThresholdBand(threshold=0.5, colour=(40, 1000, 1000)),   # amber below 50%
        ThresholdBand(threshold=0.2, colour=(0, 1000, 1000)),    # red below 20%
    ])
    tracker = HealthBarTracker(config=config)
    tracker.process(_bar_frame(1.0), now=0.0)
    assert tracker.process(_bar_frame(0.4), now=0.2) == (40, 1000, 1000)
    assert tracker.process(_bar_frame(0.1), now=0.4) == (0, 1000, 1000)


def test_tracker_uses_a_custom_config_instead_of_the_fixed_defaults():
    config = TriggerConfig(
        detection_mode=DETECTION_MODE_FILL_FRACTION,
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

    config = TriggerConfig(
        detection_mode=DETECTION_MODE_FILL_FRACTION,
        threshold_bands=[ThresholdBand(threshold=0.5, colour=(40, 1000, 1000))],
    )
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


def _wait_for_ocr_attempt(tracker: HealthBarTracker) -> None:
    deadline = time.monotonic() + 2.0
    while tracker._ocr_thread_running and time.monotonic() < deadline:
        time.sleep(0.005)


def test_tracker_auto_mode_uses_fill_fraction_before_ocr_ever_succeeds(monkeypatch):
    """auto is TriggerConfig()'s new default - before OCR has ever produced a
    usable reading for this region, a real colour bar must still work exactly
    like plain fill_fraction mode, with zero extra configuration."""
    monkeypatch.setattr(health_bar.ocr_reader, "read_text", lambda frame: "")  # nothing readable here
    tracker = HealthBarTracker()  # bare - auto is the default
    assert tracker.process(_bar_frame(1.0), now=0.0) is None  # baseline
    assert tracker.process(_bar_frame(0.5), now=0.2) == DECREASE_COLOUR


def test_tracker_auto_mode_prefers_ocr_once_it_succeeds(monkeypatch):
    """Once OCR starts successfully reading this region, auto mode trusts it
    over fill_fraction's own (potentially nonsensical, for a text-only
    display) measurement - the real-use case this whole feature exists for."""
    monkeypatch.setattr(health_bar.ocr_reader, "read_text", lambda frame: "90/100")
    tracker = HealthBarTracker()
    frame = np.zeros((10, 10, 3), dtype=np.uint8)  # not a real bar - fill_fraction would read this as empty

    tracker.process(frame, now=0.0)
    _wait_for_ocr_attempt(tracker)
    assert tracker._ocr_fraction == pytest.approx(0.9)
    # the *next* tick picks up the now-fresh OCR fraction instead of
    # fill_fraction's own (0.0, since the raw frame has no vivid pixels at all)
    assert tracker.process(frame, now=0.1) is None  # 0.9 baseline recorded, no change yet to flash on


def test_tracker_auto_mode_falls_back_to_fill_fraction_once_ocr_goes_stale(monkeypatch):
    """A single long-past OCR success shouldn't be trusted forever - once
    AUTO_DETECTION_OCR_FRESHNESS_SECONDS has elapsed with no further success,
    auto mode goes back to trusting fill_fraction's fresh-every-frame read."""
    monkeypatch.setattr(health_bar.ocr_reader, "read_text", lambda frame: "90/100")
    tracker = HealthBarTracker()
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    tracker.process(frame, now=0.0)
    _wait_for_ocr_attempt(tracker)
    assert tracker._ocr_fraction == pytest.approx(0.9)

    # OCR stops succeeding from here on, and enough time passes that the one
    # earlier success is no longer "fresh" - auto should fall back to
    # fill_fraction (0.0 for this blank frame) rather than keep trusting a
    # stale 0.9 reading forever.
    health_bar.ocr_reader.read_text = lambda frame: "unreadable garbage"
    stale_now = OCR_POLL_INTERVAL_SECONDS + AUTO_DETECTION_OCR_FRESHNESS_SECONDS + 1.0
    tracker.process(frame, now=stale_now)
    _wait_for_ocr_attempt(tracker)
    # a drop straight to fill_fraction's 0.0 from the 0.9 baseline is a real,
    # meaningful decrease - confirms fill_fraction's value is what's driving
    # this tick, not the stale OCR fraction
    assert tracker.process(frame, now=stale_now + 0.1) == DECREASE_COLOUR


def test_tracker_auto_mode_gives_up_retrying_ocr_after_max_failed_attempts(monkeypatch):
    """A genuine colour bar (OCR never once succeeds) shouldn't pay the cost
    of a real OCR inference every poll interval for the rest of a long
    session - auto mode stops trying after
    AUTO_DETECTION_MAX_OCR_ATTEMPTS_WITHOUT_SUCCESS consecutive failures."""
    call_count = {"n": 0}

    def fake_read_text(frame):
        call_count["n"] += 1
        return "unreadable garbage"

    monkeypatch.setattr(health_bar.ocr_reader, "read_text", fake_read_text)
    tracker = HealthBarTracker()
    frame = _bar_frame(0.5)

    now = 0.0
    for _ in range(AUTO_DETECTION_MAX_OCR_ATTEMPTS_WITHOUT_SUCCESS + 3):
        tracker.process(frame, now=now)
        _wait_for_ocr_attempt(tracker)
        now += OCR_POLL_INTERVAL_SECONDS

    assert call_count["n"] == AUTO_DETECTION_MAX_OCR_ATTEMPTS_WITHOUT_SUCCESS


def test_tracker_explicit_ocr_mode_never_gives_up_unlike_auto(monkeypatch):
    """The give-up behaviour is auto-mode-only - a custom watcher that
    deliberately chose "Read number (OCR)" is presumed to know what it's
    watching, and keeps retrying indefinitely even past the auto threshold."""
    call_count = {"n": 0}

    def fake_read_text(frame):
        call_count["n"] += 1
        return "unreadable garbage"

    monkeypatch.setattr(health_bar.ocr_reader, "read_text", fake_read_text)
    tracker = HealthBarTracker(config=TriggerConfig(detection_mode=DETECTION_MODE_OCR))
    frame = np.zeros((10, 10, 3), dtype=np.uint8)

    now = 0.0
    for _ in range(AUTO_DETECTION_MAX_OCR_ATTEMPTS_WITHOUT_SUCCESS + 3):
        tracker.process(frame, now=now)
        _wait_for_ocr_attempt(tracker)
        now += OCR_POLL_INTERVAL_SECONDS

    assert call_count["n"] == AUTO_DETECTION_MAX_OCR_ATTEMPTS_WITHOUT_SUCCESS + 3


def test_default_ocr_max_value_lets_a_bare_number_resolve_without_configuration(monkeypatch):
    """TriggerConfig()'s new ocr_max_value=100.0 default lets a bare-number
    display (e.g. Half-Life's transparent "79", no "/max" shown) resolve to a
    usable fraction on the free tier out of the box, no configuration screen
    needed."""
    monkeypatch.setattr(health_bar.ocr_reader, "read_text", lambda frame: "79")
    tracker = HealthBarTracker()
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    tracker.process(frame, now=0.0)
    _wait_for_ocr_attempt(tracker)
    assert tracker._ocr_fraction == pytest.approx(0.79)


def test_mask_frame_for_ocr_blanks_everything_outside_the_mask():
    frame = np.full((10, 10, 3), 255, dtype=np.uint8)
    mask = np.zeros((10, 10), dtype=bool)
    mask[2:5, 2:5] = True

    masked = _mask_frame_for_ocr(frame, mask)

    assert np.all(masked[mask] == 255)  # painted-in pixels untouched
    assert np.all(masked[~mask] == OCR_MASK_FILL_COLOUR)  # everything else blanked
    assert np.all(frame == 255)  # the original frame must not be mutated in place


def test_match_mask_to_frame_resizes_a_mismatched_mask():
    """Regression test for a real bug found via a live --debug session: a
    mask is always encoded/decoded at the region's own, un-downsampled
    resolution, but ScreenCapture downsamples any captured region wider than
    ~160px (see capture.py's DEFAULT_DOWNSAMPLE_WIDTH) - so the mask and the
    actual captured frame silently stopped matching in shape for any such
    region. Before this fix, applying a mismatched mask raised an IndexError
    that _run_ocr's broad except swallowed, producing an empty OCR read on
    every single poll for the watcher's entire session - exactly what a real
    ocr_debug_*.csv from a live test showed (raw_text/parsed_fraction empty
    on every row, for over two minutes)."""
    mask = np.zeros((200, 400), dtype=bool)
    mask[50:150, 50:350] = True  # the painted digits' area, at full resolution

    resized = _match_mask_to_frame(mask, 80, 160)  # ScreenCapture's actual, downsampled frame shape

    assert resized.shape == (80, 160)
    # the painted region's relative position/proportion survives the resize -
    # scaled by the same ~2x factor as the frame itself was downsampled
    assert np.all(resized[20:60, 20:140])
    assert not np.any(resized[:20, :])
    assert not np.any(resized[60:, :])


def test_match_mask_to_frame_is_a_no_op_when_shapes_already_match():
    mask = np.zeros((80, 160), dtype=bool)
    mask[10:20, 10:20] = True
    assert _match_mask_to_frame(mask, 80, 160) is mask


def test_match_mask_to_frame_passes_none_through_unchanged():
    assert _match_mask_to_frame(None, 80, 160) is None


def test_mask_frame_for_ocr_resizes_a_mismatched_mask_instead_of_crashing():
    """The regression test at HealthBarTracker's actual entry point (see
    test_match_mask_to_frame_resizes_a_mismatched_mask for the underlying
    helper) - a mask painted at the region's full resolution must still work
    against a downsampled captured frame, not raise."""
    mask = np.zeros((200, 400), dtype=bool)
    mask[50:150, 50:350] = True
    frame = np.full((80, 160, 3), 255, dtype=np.uint8)

    masked = _mask_frame_for_ocr(frame, mask)  # must not raise IndexError

    assert masked.shape == frame.shape
    assert np.any(masked == 255)  # some painted-in pixels survived untouched
    assert np.any(masked == OCR_MASK_FILL_COLOUR)  # some pixels were blanked


def test_fill_fraction_and_calibrate_bar_colour_handle_a_mismatched_mask_shape():
    """Same root cause, same fix (_match_mask_to_frame is shared via
    _flatten_masked) - fill_fraction mode with a painted mask on a region
    wider than the downsample threshold has the identical latent crash risk,
    even though only the OCR path was actually reported broken."""
    mask = np.zeros((200, 400), dtype=bool)
    mask[50:150, 50:350] = True
    frame = _bar_frame(fill_fraction_pct=0.5, size=80)  # a smaller, downsampled-sized frame

    colour = calibrate_bar_colour(frame, mask)  # must not raise IndexError
    assert colour is not None
    fraction = fill_fraction(frame, colour, mask)  # must not raise IndexError
    assert 0.0 <= fraction <= 1.0


def test_tracker_ocr_mode_reads_correctly_through_a_downsampled_mask_mismatch(monkeypatch):
    """End-to-end regression test at the HealthBarTracker level, mirroring
    the exact real-world shape of the bug: a mask painted at the region's
    full resolution, fed a frame at ScreenCapture's actual downsampled size.
    Before the fix, this silently produced an empty OCR read (text="",
    fraction=None) forever - never a crash the user would notice, just a
    watcher that never did anything."""
    monkeypatch.setattr(health_bar.ocr_reader, "read_text", lambda frame: "87/100")
    mask = np.zeros((200, 400), dtype=bool)
    mask[50:150, 50:350] = True
    downsampled_frame = np.zeros((80, 160, 3), dtype=np.uint8)

    tracker = HealthBarTracker(config=TriggerConfig(detection_mode=DETECTION_MODE_OCR), mask=mask)
    tracker.process(downsampled_frame, now=0.0)
    deadline = time.monotonic() + 2.0
    while tracker._ocr_fraction is None and time.monotonic() < deadline:
        time.sleep(0.01)

    assert tracker._ocr_fraction == pytest.approx(0.87)


def test_tracker_ocr_mode_masks_out_the_background_before_reading(monkeypatch):
    """A real-use report: a busy/animated background around a tightly-painted
    number flipped the OCR read frame to frame even though the number itself
    never changed - because the mask was only ever applied to fill_fraction,
    never plumbed through to OCR at all. This is the regression test for the
    fix: HealthBarTracker must blank out everything outside the mask before
    the frame reaches ocr_reader.read_text."""
    seen_frames = []

    def fake_read_text(frame):
        seen_frames.append(frame.copy())
        return "50/100"

    monkeypatch.setattr(health_bar.ocr_reader, "read_text", fake_read_text)
    frame = np.full((10, 10, 3), 255, dtype=np.uint8)  # a "busy" all-white background
    mask = np.zeros((10, 10), dtype=bool)
    mask[3:7, 3:7] = True  # only the digits' own small area is painted in

    tracker = HealthBarTracker(config=TriggerConfig(detection_mode=DETECTION_MODE_OCR), mask=mask)
    tracker.process(frame, now=0.0)
    deadline = time.monotonic() + 2.0
    while not seen_frames and time.monotonic() < deadline:
        time.sleep(0.01)

    assert len(seen_frames) == 1
    received = seen_frames[0]
    assert np.all(received[mask] == 255)          # the digits' own area reached OCR unchanged
    assert np.all(received[~mask] == OCR_MASK_FILL_COLOUR)  # the surrounding "noise" did not


def test_tracker_ocr_mode_without_a_mask_passes_the_frame_unchanged(monkeypatch):
    """No mask (the built-in Gaming Mode watcher, or an OCR watcher whose
    region was drawn with the plain rectangle tool) must reproduce the
    original behaviour exactly - the whole region's raw frame goes to OCR."""
    seen_frames = []

    def fake_read_text(frame):
        seen_frames.append(frame)
        return "50/100"

    monkeypatch.setattr(health_bar.ocr_reader, "read_text", fake_read_text)
    frame = np.full((10, 10, 3), 123, dtype=np.uint8)
    tracker = HealthBarTracker(config=TriggerConfig(detection_mode=DETECTION_MODE_OCR))
    tracker.process(frame, now=0.0)
    deadline = time.monotonic() + 2.0
    while not seen_frames and time.monotonic() < deadline:
        time.sleep(0.01)

    assert len(seen_frames) == 1
    assert seen_frames[0] is frame


def test_tracker_ocr_debug_callback_receives_raw_text_and_parsed_fraction(monkeypatch):
    """Powers AmbienceMode's --debug OCR log (see test_ambience_mode.py) -
    every OCR attempt, success or fail, must be reported so a transient
    misread frame shows up in the data instead of only being inferred from
    an unexplained stray blink."""
    monkeypatch.setattr(health_bar.ocr_reader, "read_text", lambda frame: "87/100")
    calls = []
    tracker = HealthBarTracker(
        config=TriggerConfig(detection_mode=DETECTION_MODE_OCR),
        debug_callback=lambda text, fraction, frame: calls.append((text, fraction, frame)),
    )
    frame = np.zeros((10, 10, 3), dtype=np.uint8)

    tracker.process(frame, now=0.0)
    deadline = time.monotonic() + 2.0
    while not calls and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(calls) == 1
    assert calls[0][:2] == ("87/100", pytest.approx(0.87))
    assert calls[0][2] is frame  # the exact frame OCR received, for saving/inspection

    health_bar.ocr_reader.read_text = lambda frame: "unreadable garbage"
    tracker.process(frame, now=10.0)  # past the poll interval - forces a new OCR attempt
    deadline = time.monotonic() + 2.0
    while len(calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert calls[1][:2] == ("unreadable garbage", None)


def test_tracker_detects_a_decrease_even_when_the_fill_colour_shifts():
    """Regression guard: some games recolour the bar as it depletes (green -> amber
    -> red is a common health-bar convention). Since the fill colour is
    re-identified fresh every frame, a decrease must still register correctly even
    though the hue itself has also changed between frames."""
    tracker = HealthBarTracker(config=TriggerConfig(detection_mode=DETECTION_MODE_FILL_FRACTION))
    green_frame = _bar_frame(0.9, fill_rgb=(20, 200, 20), track_rgb=(15, 30, 15))
    amber_frame = _bar_frame(0.4, fill_rgb=(220, 150, 20), track_rgb=(30, 25, 22))
    tracker.process(green_frame, now=0.0)
    assert tracker.process(amber_frame, now=0.2) == DECREASE_COLOUR
