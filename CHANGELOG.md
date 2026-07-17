# Changelog

## 2026-07-17 (53)
- Fixed auto mode's OCR give-up mechanism permanently stranding a
  perfectly correct watcher: a real report, diagnosed using the new
  debug-log image, traced a session with 0/19 successful OCR reads to the
  watcher having been activated during a loading screen - correctly
  nothing to read at that moment, but it exhausted its attempts before the
  level finished loading, then never tried again once real gameplay (and a
  real, readable HP number) resumed, even though the region/mask were
  correct the entire time. A cutscene, menu, or respawn sequence could
  trigger the identical problem. Giving up now means dropping to a much
  slower retry cadence (`AUTO_DETECTION_RETRY_COOLDOWN_SECONDS`, 30s)
  instead of stopping outright - `HealthBarTracker._gave_up_at` tracks
  when the threshold was first hit, and `_maybe_start_ocr` allows exactly
  one retry once the cooldown elapses (restarting the cooldown if that
  retry also fails, so a truly unreadable region still only costs one
  wasted inference every 30s, not the old every-1s-forever-during-the-
  first-30s-then-never-again). The instant any retry succeeds, the give-up
  gate stops applying for the rest of the session - straight back to
  full-cadence polling, no lingering slowdown. Still not applied to an
  explicit `"ocr"` mode watcher, which keeps retrying at full cadence
  indefinitely regardless. New tests
  (`test_tracker_auto_mode_retries_again_after_the_cooldown_elapses`,
  `test_tracker_auto_mode_stops_retrying_once_the_cooldown_retry_succeeds`);
  full suite: 172 tests passing.

## 2026-07-17 (52)
- Fixed a real gap in the debug-log image feature from the previous entry,
  found immediately on first real use: the saved `_first` frame showed the
  FluxHound window/Windows taskbar itself, not the game - because the very
  first OCR attempt fires under a second after activating Ambience Mode,
  before the user has had a chance to alt-tab back to the game. `_first`
  alone made a correctly-painted mask look broken for a reason that had
  nothing to do with the mask itself. `AmbienceMode._make_ocr_debug_callback`
  now also saves `_latest` (overwritten on every attempt, not just the
  first) alongside the permanent `_first`, so the two can be compared - one
  showing the activation-moment transition state, the other the actual
  steady state once real gameplay is back in focus. Live-verified:
  simulated a screen changing between the first and a later attempt and
  confirmed `_first`/`_latest` captured the two distinct moments correctly.
  Full suite: 170 tests passing.

## 2026-07-17 (51)
- Added debug-log images: a real `--debug` session came back with 30/30 OCR
  attempts failing with no way to tell *why* from the CSV alone - a wrong
  mask position, a blacked-out capture, or a genuinely unreadable font all
  look identical in text form (an empty row). `HealthBarTracker`'s
  `debug_callback` now also receives the exact (masked, if applicable)
  frame OCR received; `AmbienceMode` saves the *first* attempt's frame per
  watcher (not every one) as a PNG next to the CSV
  (`<csv-stem>_<watcher name>.png`), via `cv2.imwrite` - no new dependency,
  `opencv-python` is already bundled transitively via
  `rapidocr_onnxruntime`, imported lazily so it's never paid for outside a
  `--debug` OCR session. Best-effort, wrapped in its own broad exception
  handler so a failed screenshot can never break the actual OCR read.
- Found and fixed a second shutdown race live-testing the image save: an
  OCR attempt's background thread (never previously tracked or joined by
  anything) can still be mid-flight when `AmbienceMode.stop()` returns and
  the debug CSV's file closes - that thread's own write then hit a real
  `ValueError: I/O operation on closed file`, losing that attempt's row and
  printing an ignored-thread-exception traceback. Fixed with
  `HealthBarTracker.join_ocr_thread`, called from `AmbienceMode.
  _run_single_reading_loop`'s `finally` before closing captures - the
  in-flight attempt is now waited for while the debug log is still open,
  instead of racing the shutdown. Live-verified: reproduced the exact
  failure (three OCR rows, then a `ValueError` traceback on the third),
  confirmed gone after the fix (same three rows, clean shutdown), and
  visually confirmed the saved debug image showed exactly the expected
  content. New tests (`tests/test_ambience_mode.py`: frame-saving on first
  attempt only, watcher-name filename sanitization;
  `tests/test_health_bar.py` updated for the debug_callback's new frame
  argument). Full suite: 170 tests passing.

## 2026-07-17 (50)
- Added an "Edit" button to the Devices window for already-configured
  devices - prompted by a real-use report: re-pairing "Stehlampe unten" via
  the Tuya/Smart Life app (to recover it from an unrelated network
  problem) rotated its `local_key`, surfacing as "Unexpected Payload from
  Device"/unreachable in FluxHound - the second time this exact scenario
  has hit this project. Until now the only fix was removing the device and
  re-adding it as new, losing its `display_name` and any group membership/
  position. `DeviceConfigDialog` already supported pre-filling from an
  existing device (its own docstring already said "entering or editing") -
  only the button to actually reach it in edit mode was missing.
  `_on_device_edited` mutates the existing `DeviceConfig` in place
  (device_id/IP/local_key/protocol_version) instead of replacing the list
  entry, so `display_name` is naturally preserved; `device_id` itself is
  also editable (an occasional full re-pair issues a new one, not just a
  new key), with `group.device_ids`/`group.positions`/`active_selection`
  updated to follow it rather than silently going stale. Window widened
  400→460px for a less cramped grouped-device row. Live-verified both the
  common case (local_key-only edit preserving display_name/group/position)
  and the harder edge case (device_id itself changing, correctly re-keying
  group membership and the active selection).

## 2026-07-16 (49)
- Fixed a new, uglier traceback the previous Ctrl+C fix exposed:
  `RuntimeError: main thread is not in main loop`, printed twice (once from
  a reactive mode's background thread trying to marshal a live-state update
  onto the Tk thread, once more from the error handler trying to report
  that same failure) every time Ctrl+C interrupted a running Ambience/Audio
  Mode session. Root cause: a reactive mode's background thread runs on its
  own timing - it can still be mid-tick, about to call `self.after(0, ...)`
  to update the GUI, at the exact moment `KeyboardInterrupt` stops Tk's
  event loop from processing (before `_quit()`'s own stop signal has even
  reached the thread). Not fatal, but it cut the background thread off via
  an uncaught exception instead of letting it notice the stop signal and
  exit cleanly through its own cleanup. Fixed with `MainWindow.
  _after_if_running`, wrapping `self.after()` and silently swallowing
  exactly this `RuntimeError` (there's nothing useful left to update once
  it fires - the app is already tearing down) - used by all three
  reactive-mode callbacks that marshal onto the Tk thread
  (`_on_reactive_mode_error`/`_on_reactive_mode_recovered`/
  `_on_reactive_mode_update`), shared by both Ambience and Audio Mode since
  both hit the identical race through the same callback interface.
  Live-verified: patched `self.after` to always raise the exact production
  error and called all three callbacks directly - none propagated it.

## 2026-07-16 (48)
- Fixed both `--debug` CSV logs (Audio Mode's and the new OCR one) losing
  an entire session's data when the app is stopped via Ctrl+C in a console
  - a real report showed a fresh log staying completely empty (not even
  the header) despite `--debug` being correctly picked up. Root cause,
  confirmed from the shared traceback: Ctrl+C raises `KeyboardInterrupt`
  straight out of Tcl's `mainloop()` callback dispatch, uncaught anywhere
  in `src/main.py` - the process died immediately, before either debug
  log's `with open(...)` block ever got to exit cleanly and flush its
  write buffer. Fixed two ways: (1) both `_open_ocr_debug_log`
  (`src/modes/ambience_mode.py`) and `_open_debug_log`
  (`src/modes/custom_mode.py`) now flush to disk after every row, not just
  on close - verified by reading the file from a second, independent
  handle while the writing one is still open, proving a row is really on
  disk immediately rather than sitting in a buffer; (2) `main()` now
  wraps `app.mainloop()` in `try/except KeyboardInterrupt`, calling
  `app._quit()` - the same real-shutdown path the tray icon's own "Quit"
  entry already uses, so Ctrl+C now also cleanly stops any active reactive
  mode, shuts down the executor, and removes the tray icon, instead of
  abruptly killing everything mid-flight. New tests: `tests/test_main.py`
  (new file, mocks `MainWindow.mainloop` to raise `KeyboardInterrupt` and
  confirms `_quit()` gets called), plus flush-survives-an-unclean-close
  regression tests in `tests/test_ambience_mode.py` and
  `tests/test_custom_mode_debug_log.py`. Full suite: 168 tests passing.

## 2026-07-16 (47)
- Raised auto mode's OCR give-up threshold
  (`AUTO_DETECTION_MAX_OCR_ATTEMPTS_WITHOUT_SUCCESS`) from 10 to 30, after a
  real `--debug` session on real gameplay showed a correctly, tightly
  painted region needing 11 OCR attempts before its first success against
  that game's actual HUD font (Half-Life's health number) - the built-in
  watcher's auto mode was giving up right as OCR was about to start
  working, permanently stranding a genuinely readable region on chaotic
  fill_fraction instead. This was the actual cause of a further "wild
  flashing" report after the auto-detection feature shipped: the built-in
  watcher's mask was confirmed correctly, tightly painted around just the
  health number (screenshot-verified), not the broad/scattered region
  initially suspected. 30 attempts (~30s, still a bounded one-time cost per
  Ambience Mode activation, not truly unlimited) gives real-world OCR
  variance (lighting, font, occlusion) a much wider berth. Full suite: 165
  tests passing (the give-up test already parameterized off the constant,
  no test changes needed).

## 2026-07-16 (46)
- Made auto-detecting colour bars vs. printed numbers a free-tier
  capability, not just a paid Custom Trigger Editor one - prompted by real
  testing against a text-only HUD (Half-Life's transparent "79" health
  readout, no bar at all) showing the built-in watcher's fixed
  `fill_fraction` detection produces genuinely nonsensical, wildly
  flickering behaviour there, since colour-ratio matching has nothing
  meaningful to measure against plain text. `TriggerConfig.detection_mode`
  now defaults to a new `"auto"` (`DETECTION_MODE_AUTO`, replacing
  `"fill_fraction"` as the default) - both the built-in watcher (a bare
  `TriggerConfig()`) and any newly-created custom watcher get it. What
  stays paid-exclusive, unchanged: watching more than one region (the
  Custom Trigger Editor's extra watchers) and configuring the reaction
  (custom flash colours/thresholds/multi-step bands) - not which detection
  method is available. A custom watcher can still force `"fill_fraction"`
  or `"ocr"` explicitly via the Trigger Editor's Detection dropdown (now
  three options: "Auto (recommended)", "Fill colour", "Read number (OCR)").
- Auto mode's decision logic (`HealthBarTracker.process`/`_maybe_start_ocr`/
  `_run_ocr`, `src/screen/health_bar.py`): fill_fraction runs every capture
  tick as before; OCR polls in the background at its usual ~1s cadence in
  parallel, not a one-shot classification that could get locked into the
  wrong choice by an unlucky first frame. Once OCR has ever succeeded, its
  reading is trusted over fill_fraction's for
  `AUTO_DETECTION_OCR_FRESHNESS_SECONDS` (5x the poll interval, ~5s)
  afterward - tolerates an occasional missed poll without visibly flip-
  flopping between detection methods, while a region OCR stops succeeding
  on still falls back to fill_fraction within a few seconds. A region OCR
  has *never* succeeded on uses fill_fraction immediately, no delay.
- Efficiency: a genuine colour bar (the majority use case "normal" Gaming
  Mode was originally built for) shouldn't pay for a real OCR inference
  every second forever. In auto mode only,
  `AUTO_DETECTION_MAX_OCR_ATTEMPTS_WITHOUT_SUCCESS` (10, ~10s) consecutive
  failures with zero successes stops starting new OCR attempts for the rest
  of that watcher's session (resets fresh on the next Ambience Mode
  activation) - deliberately not applied to an explicit `"ocr"` mode
  watcher, which keeps retrying indefinitely since choosing OCR explicitly
  is presumed deliberate.
- `TriggerConfig.ocr_max_value` now defaults to `100.0` (was `None`) so a
  bare-number display (no `"/max"` or `"%"` shown, like Half-Life's raw
  "79") resolves to a usable fraction on the free tier immediately, with no
  configuration screen the built-in watcher doesn't have. Existing saved
  watchers are unaffected - the config persistence always writes the actual
  configured value, never relies on the dataclass default.
- `AmbienceMode`'s OCR `--debug` logging (added in a previous entry) now
  also covers the built-in watcher (logs under "Gaming Mode (built-in)"),
  since it can now genuinely exercise the OCR path too, not just custom
  watchers.
- New tests: 6 for auto mode's fallback/switch/give-up behaviour in
  `tests/test_health_bar.py`, plus updated existing fill_fraction tests to
  explicitly pin `detection_mode=DETECTION_MODE_FILL_FRACTION` (they'd
  otherwise silently start real background OCR attempts too, now that bare
  `TriggerConfig()`/`HealthBarTracker()` default to auto) and one existing
  `test_ambience_config.py` test updated for the new `ocr_max_value`
  default. Live-verified end to end (real `AmbienceMode` session, mocked
  OCR text, real background thread/timing): a custom trigger watcher
  correctly read "90/100" via auto mode over fill_fraction's own reading,
  and a session with *only* the built-in region (no custom watchers)
  correctly auto-detected and read "87/100", logging under "Gaming Mode
  (built-in)" - confirming the free built-in watcher's detection now
  genuinely matches the paid custom watcher's capability. Full suite: 165
  tests passing.

## 2026-07-16 (45)
- Found and fixed the actual root cause of an OCR watcher silently never
  working, using the `--debug` logging added in the previous entry: a real
  `ocr_debug_*.csv` from a 130+ second live session showed `raw_text`/
  `parsed_fraction` empty on *every single row* - OCR had read nothing at
  all, the entire time, so this watcher could not have produced any of the
  reported wild flashing (a fraction that never leaves `None` never
  triggers a band or blink). Root cause, confirmed by directly reproducing
  the exact failure shape: a watcher's painted mask is always encoded at
  its region's own *un-downsampled* resolution, but `ScreenCapture`
  downsamples any captured region wider than its default ~160px threshold
  - so for any such region, the mask and the actually-captured frame
  silently stopped matching in shape. Indexing with a mismatched boolean
  mask raises a numpy `IndexError`, which `_run_ocr`'s broad
  `except Exception: pass` was swallowing completely - not a crash, just a
  watcher that silently did nothing on every poll. The same
  `_flatten_masked` maths is shared by `fill_fraction` mode, which has no
  such broad exception guard in the main capture loop - a wide masked
  fill_fraction watcher would have hit a real, visible crash instead;
  only reported for OCR so far, but the same latent bug either way.
  Fixed with `_match_mask_to_frame`/`_resize_mask_nearest`
  (`src/screen/health_bar.py`, nearest-neighbour resize, no PIL, same
  technique as `MainWindow`'s existing `_resize_frame_nearest`): the mask
  is resized to the frame's actual shape before either `_mask_frame_for_ocr`
  or `_flatten_masked` indexes with it, a no-op when shapes already match.
  Deliberately left `ScreenCapture`'s downsampling itself untouched - that
  was already tried and proven worse for OCR accuracy in an earlier entry;
  this fix keeps that benefit while correcting the actual bug. New
  regression tests (6, including one reproducing the exact real-world
  shape - a mask painted at full resolution against a downsampled frame -
  through the full `HealthBarTracker` OCR path) plus a live end-to-end
  check against the real `rapidocr` engine on a region wider than the
  downsample threshold, confirming the exact repro failed before the fix
  and correctly read "87/100" after it. Full suite: 159 tests passing.
  Added `ocr_debug_*.csv` to `.gitignore` (same pattern as
  `audio_debug_*.csv`) and cleaned up the test session's log files.

## 2026-07-16 (44)
- Added OCR `--debug` logging to troubleshoot a real-use report: wild
  red/green flashing during a live gaming session, including a spurious
  red "decrease" flash firing right before the correct green "increase"
  flash on a heal, plus inconsistent reactions across bulbs in a merged
  group. Rather than guess further at fixes, extended the existing
  `--debug` convention (already used for Audio Mode's calibration log) to
  Gaming Mode's OCR-mode watchers: `AmbienceMode` now writes an
  `ocr_debug_<timestamp>.csv` (`OCR_DEBUG_LOG_COLUMNS`) with one row per
  OCR read attempt per watcher - the raw recognized text and the fraction
  `parse_fraction` made of it, so a transient misread frame during a HUD
  number's own change animation shows up directly in the data instead of
  only being inferred from an unexplained stray blink.
  `HealthBarTracker` gained an optional `debug_callback` parameter, called
  from its own OCR background thread after every read attempt (success or
  fail); `AmbienceMode` binds one per watcher to a shared,
  lock-guarded CSV writer (`_open_ocr_debug_log`/`_make_ocr_debug_callback`)
  since several watchers' OCR threads can write concurrently. New tests
  (`tests/test_ambience_mode.py`, a new file - 3 tests for the CSV-writing
  wiring in isolation; `tests/test_health_bar.py` +1 for the callback
  itself) plus a live end-to-end check (real background thread, real
  screen capture, OCR mocked to isolate the logging wiring from OCR
  accuracy): the CSV populated correctly with the right header and one row
  per watcher per poll interval. Full suite: 153 tests passing. The lamp-
  flashing report itself is not yet fixed - this is the diagnostic tool to
  find the actual root cause from a real test session's data, not a fix.

## 2026-07-16 (43)
- Hardened `ocr_reader.parse_fraction`'s format auto-detection
  (`src/screen/ocr_reader.py`), prompted by a live-testing question: does
  it correctly tell apart a bare "already complete" number from a
  "current/max" style reading, a "%" reading, or ugly real-world
  combinations of these? Traced through a battery of realistic combined
  strings first (ratio+redundant-percent, percent-before-ratio, two
  separate ratios in one OCR'd text, `HP:`/label-prefixed text) - all of
  these were already handled correctly by the existing ratio > percent >
  bare-number priority order, regardless of where in the string each
  pattern appears. Found one genuine gap: a bare decimal already
  *is* a complete 0-1 reading on its own (e.g. "0.79" - some HUDs/mods
  show a raw progress value directly, no ratio or percent sign attached)
  and wasn't recognized at all before this. Added
  `_DECIMAL_FRACTION_PATTERN`, checked after percent and before the
  Max-value-normalized bare-integer fallback. Its integer part is
  deliberately restricted to exactly 0 or 1 (or omitted, e.g. ".79") so it
  can never accidentally swallow the tail of an unrelated number - tested
  directly against a plausible OCR misread of "79/100" where the slash
  gets confused for a period ("79.100", integer part "79") to confirm it
  correctly falls through to None instead of silently misreading it as
  0.1. New tests in `tests/test_ocr_reader.py` (6 new: the decimal
  fraction itself, the "doesn't swallow an unrelated larger number" guard,
  the misread-slash-as-period rejection, and three combined-format
  priority cases); full suite: 149 tests passing.

## 2026-07-16 (42)
- Fixed a real-use report: the lamp flashed red/green wildly with an OCR-
  mode Trigger Editor watcher running. The user's own hypothesis (the
  background around the read number being weighted in too heavily) pointed
  straight at the real bug: `HealthBarTracker._run_ocr` was handing OCR the
  raw, un-masked capture regardless of the watcher's painted brush mask -
  the mask was only ever wired into `fill_fraction`'s pixel filtering, never
  plumbed through to OCR at all, despite the docstrings saying so
  explicitly ("ignored in ocr mode"). A mask painted tightly around just the
  digits (specifically to exclude a busy/animated part of the HUD nearby)
  therefore had zero effect on what OCR actually read - the whole
  rectangular bounding box, background included, was fed in every time.
  Fixed with a new `_mask_frame_for_ocr` (`src/screen/health_bar.py`):
  everything outside the mask is now blanked to a flat colour before the
  frame reaches `ocr_reader.read_text`, leaving the painted-in digits
  themselves completely untouched; no mask (the built-in watcher, or an OCR
  watcher whose region was drawn with the plain rectangle tool) reproduces
  the exact prior behaviour. New regression test
  (`test_tracker_ocr_mode_masks_out_the_background_before_reading`)
  confirms the frame OCR actually receives is masked correctly; full suite:
  145 tests passing (4 new).
- Live-tested the fix against the real `rapidocr` engine (not mocked): a
  static "87/100" label with a constantly-repainted noisy background and a
  second, nearby "45/60"-style number crammed into the same capture. Both
  masked and unmasked reads stayed stable in this particular synthetic
  setup - rapidocr's own text-line ordering was already reliable here, so
  this specific noise pattern didn't reproduce the flicker on its own. The
  masking fix is confirmed as a real bug fix (the mask genuinely wasn't
  reaching OCR before, now it does), but not proven to be the *complete*
  explanation for the reported wild flashing - flagged in ROADMAP's Open
  list as worth re-confirming against the actual game, since a single-frame
  OCR misread of a stylized in-game digit could in principle still cause an
  isolated flash on its own, independent of background exclusion.

## 2026-07-16 (41)
- Replaced the plain rectangle drag-select with a paintable brush
  selector for Gaming Mode's built-in region and every Custom Trigger
  Editor watcher (Ambience Mode's own colour-zone region pickers are
  unchanged - a rectangle is the right tool there). Prompted by a real
  report plus a screenshot of Grounded's health bar: a curved/bent HUD
  bar can't be isolated from its surroundings inside any single
  rectangle. New `src/gui/brush_selector_window.py`
  (`BrushSelectorWindow`): same semi-transparent click-through overlay
  technique as `RegionSelectorWindow`, but paints a freeform mask via
  circular "stamps" along the drag path (interpolated between mouse-
  move samples so a fast drag doesn't leave gaps), rendered with the
  same no-PIL raw-PPM `tkinter.PhotoImage` technique the colour picker
  already uses. Confirm computes the tight bounding box of the painted
  pixels as the region's existing `(x, y, width, height)`, plus the
  mask itself cropped to that box. `AmbienceRegion` gained an optional
  `mask` field (`numpy.packbits`+base64, no separate shape stored -
  always matches the owning region's own height/width;
  `encode_region_mask`/`decode_region_mask` in `health_bar.py`); `None`
  (every pre-existing region, and every Ambience colour-zone region)
  means "the whole rectangle", reproducing prior behaviour exactly.
  `fill_fraction`/`calibrate_bar_colour`/`measure_fill` all gained an
  optional `mask` parameter applied before their existing maths;
  `HealthBarTracker`/`AmbienceMode` thread the decoded mask through
  from `MainWindow` (built-in watcher) or each watcher's own
  `region.mask` (custom watchers). Live-verified: painting a curved
  stroke rendered as a smooth filled shape matching the path exactly,
  and Confirm correctly computed the cropped mask and bounding box.
- Added OCR-based detection as a second Custom Trigger Editor watcher
  mode (paid-tier only, alongside the existing fill-fraction default;
  the built-in Gaming Mode watcher is unaffected and stays fill-
  fraction-only), for displays that show health/mana as text/digits
  rather than a fillable bar - a colour-ratio measurement has nothing
  to read there no matter how the region is shaped. New "Detection"
  dropdown and a conditionally-shown "Max value" field in
  `TriggerConfigEditorWindow`; `TriggerConfig.detection_mode`/
  `ocr_max_value` persist the choice. Chose `rapidocr_onnxruntime` for
  the new OCR dependency over `pytesseract` (no pip-only install - a
  Tesseract binary has to be separately sourced/bundled) and Windows'
  own native OCR (zero size cost, but real untested PyInstaller/COM
  packaging risk and a hard Windows-only dependency) - discussed at
  length with the user, whose own reasoning about install-simplicity
  and portability was engaged with and confirmed rather than either
  blindly agreed with or dismissed; adds ~150-190MB installed
  (measured, not estimated - mostly `opencv-python`) and this is the
  first place Pillow enters the dependency tree (transitively, via
  `rapidocr` - never imported by FluxHound's own code, which still
  avoids PIL directly everywhere else).
- A single OCR reading measured ~0.3s - too slow to run synchronously
  in the ~0.1s capture loop without stalling every other watcher.
  `HealthBarTracker` in OCR mode now starts a reading on its own
  background thread at most once per `OCR_POLL_INTERVAL_SECONDS`
  (1.0s), never letting readings pile up, and re-evaluates the last
  known fraction against thresholds every tick in between. Found and
  fixed a real bug via unit testing before it ever ran live: the
  throttle's "last started" sentinel was initialized to `0.0`, and
  since `0.0` is also a legitimate first-ever timestamp, the very
  first reading was silently skipped every time - fixed by using
  `None` as the "never started" sentinel instead.
- Found and fixed a real PyInstaller packaging bug before shipping:
  `rapidocr`'s own model loader does a dynamic bare-name
  `importlib.import_module("ch_ppocr_v3_det")` after appending its own
  package directory to `sys.path` - works from a normal pip install,
  but fails once frozen (`AttributeError: module 'ch_ppocr_v3_det' has
  no attribute 'TextDetector'`), and PyInstaller's static analysis
  can't trace the dynamic import to bundle it either. Fixed with
  `hiddenimports` in `fluxhound.spec` (forces bundling under the real
  qualified names) plus a new runtime hook
  (`pyinstaller_rthook_rapidocr.py`) that registers each qualified
  import into `sys.modules` under the bare name `rapidocr` expects, so
  Python's import system finds it there before ever touching
  `sys.path`. Verified by building both a minimal standalone frozen
  test exe and the full `FluxHound.exe`, both correctly reading a real
  "87/100" test image after the fix, having failed identically before
  it.
- Tried, then reverted, a capture change for OCR mode: skipping
  `ScreenCapture`'s default ~160px downsample for OCR watchers on the
  plausible theory that more resolution should help read small text.
  Repeated, reproducible live testing against a real on-screen
  "87/100" showed the exact opposite - the same crop read correctly
  every time at the default downsample and failed every time at full
  resolution. Reverted rather than keep an unproven change that
  measurably made real recognition worse; left a comment in
  `ambience_mode.py` recording the finding so it isn't quietly retried
  without re-testing.
- Full suite passing (142 tests) after all of the above; new/extended
  coverage: `tests/test_ocr_reader.py` (11 new), `tests/
  test_brush_selector_window.py` (6 new), plus extensions to `tests/
  test_health_bar.py` (+6, including the OCR throttle sentinel bug)
  and `tests/test_ambience_config.py` (+3).

## 2026-07-16 (40)
- Fixed a real-use report: the Settings window's "Minimize to tray on
  close" was only ever static explanatory text - there was no actual
  checkbox to turn it off, despite the text describing one. Added a
  real "Minimize to tray on close" checkbox backed by a new
  `src/app_settings.py` (`AppSettings.minimize_to_tray`, defaults to
  `True`, same load/save pattern as every other config file here).
  `MainWindow._on_close` now checks it alongside the tray icon's
  availability, and toggling the checkbox takes effect on the very
  next close - no restart needed. Live-verified both directions: with
  it on (the default), closing the window still hides to the tray;
  with it off, closing the window quits FluxHound normally.
- While testing this, caught and fixed a real (if harmless) latent bug
  in `src/gui/tray.py`: the `WM_DESTROY` handler didn't return an
  `int` like every other handler, which pywin32 surfaced as a
  "WNDPROC return value cannot be converted to LRESULT" error printed
  on every real quit (it never actually stopped the quit from
  completing, but was still a bug) - fixed with the missing `return 0`.
- Cleaned up the accumulated `audio_debug_*.csv` test logs from the
  recent Audio Mode calibration round.

## 2026-07-16 (39)
- Fixed a real follow-on bug from the Energy auto-leveling fix,
  surfaced in a second round of real-music --debug testing: a gap of
  true digital silence (before playback starts, between songs) had the
  floor's fast attack chasing it all the way down to
  `ADAPTIVE_RANGE_ABSOLUTE_MIN_DB` within a couple of seconds. When
  music resumed, the floor sat miscalibrated there and only crawled
  back up over the slow ~12s release, so Energy read inflated (pinned
  near/at 1.0) for 10-30+ seconds right after every silence gap -
  confirmed directly in the log data (two of five new sessions showed
  the floor bottoming out at the -60dB clamp, followed by Energy
  sitting at or near 1.0 for several seconds once music resumed).
  Fixed with a new `SILENCE_GATE_DB` (-70dB, `src/audio/custom_show.py`):
  a block that quiet has no real content to calibrate against, so the
  adaptive-range update is simply skipped for it - floor/ceiling stay
  exactly where they were before the gap. Verified by reproducing the
  exact failing sequence (warm up on real-ish content, 6s of true
  silence, resume) - the floor no longer moves during the gap and
  Energy is back to a sensible level within a few blocks of resuming,
  instead of pinned near-max for many seconds.
- Fixed the Audio tab's per-target sensitivity sliders being visibly
  clipped behind the scrollable frame's scrollbar (reported after
  live use). Root cause: the single-row layout (checkbox + target
  label + 3 source buttons + a narrow 90px slider) left the row's
  total width almost exactly equal to the tab's available width, with
  no margin left for the `CTkScrollableFrame`'s scrollbar - and since
  that frame only scrolls vertically, overflowing width doesn't
  reflow or get its own horizontal scrollbar, it just sits behind the
  vertical one. Fixed by moving each target's sensitivity slider to
  its own grid row, spanning the width of that target's 3 source
  buttons, instead of trimming already-tight column widths - removes
  the width pressure entirely and, as a bonus, makes the sliders
  noticeably wider and easier to drag precisely. A small "Sensitivity"
  caption was added above each slider while restructuring, since there
  previously wasn't one. Live-verified via a window screenshot: clear
  margin between the sliders and the scrollbar now.

## 2026-07-16 (38)
- Raised `BEAT_BASE_THRESHOLD_MULTIPLIER` from 1.8 to 2.2
  (`src/audio/custom_show.py`): the first --debug real-music test
  round showed onset gaps clustering heavily against
  `ONSET_MIN_INTERVAL_SECONDS` (13-24% of detected onsets within
  0.05s of the 0.15s floor) in dense/percussive passages - the
  detector was firing on nearly every eligible block rather than
  picking out distinct hits. Validated by re-simulating onset
  detection directly from the already-logged `flux` column of both
  real sessions (no new capture needed): -21% to -24% fewer onsets,
  and near-floor clustering down from 24.8%/13.9% to 18.8%/9.3%,
  while still preserving a substantial number of onsets. A first
  pass, to be re-checked against the next test round.
- Deliberately did *not* raise `BANDS`' db_ceil, the other pending
  suggestion from the same test round (Energy's raw signal pinned at
  exactly 1.0 13.4% of the time on one track). The auto-leveling fix
  added just before this already solves that dynamically - a
  sustained loud passage now raises the ceiling to match within a
  couple of seconds, so the pinning should already be far less
  frequent post-fix. Raising the static seed on top would only affect
  the brief "before adaptation catches up" window and risks fighting
  with the mechanism meant to already handle it.

## 2026-07-16 (37)
- Fixed Energy going flat/unreactive at a lower overall playback
  volume (reported after the first --debug real-music test round: a
  browser tab's own volume turned down made the lamp noticeably less
  reactive even without any loud signals otherwise). Root cause,
  confirmed analytically before touching any code: `BANDS`' db_floor/
  db_ceil in `src/audio/custom_show.py` are fixed, absolute dB
  thresholds calibrated at one reference volume - a synthetic "song"
  (alternating louder/quieter noise bursts, all scaled down 20dB)
  showed the old fixed-threshold formula clipping the quiet half of
  every cycle to a flat 0.0 exactly 50% of the time. Separately
  confirmed Timbre (a frequency/magnitude ratio) and Beat (an adaptive
  mean+std flux threshold) already cancel out a uniform volume change
  mathematically, so only Energy needed fixing.
- Fix: each band now auto-levels its own floor/ceiling live instead of
  using `BANDS`' constants directly (`CustomShowEnvelope.
  _update_adaptive_range`) - a fast ~2s "attack" toward any new
  extreme (louder or quieter) and a slower ~12s "release" back
  otherwise, so a real volume change (in either direction) is picked
  up within a few seconds without one one-off transient throwing
  everything else off. Seeded from the same fixed constants, so
  behaviour at whatever volume those were originally calibrated
  against is unchanged. Re-running the same synthetic quiet-song test
  after the fix: 0% of blocks clip to 0 at every volume level tested
  (down to -30dB), with loud/quiet separation degrading gracefully
  instead of falling off a cliff.
- The per-band floor/ceiling are also now logged via `--debug`'s CSV
  (`*_floor_db`/`*_ceiling_db` columns) so a real volume-change test
  can be confirmed after the fact, not just the three final source
  values. Live-verified against the real bulb group: the new columns
  populate correctly and visibly track over a real WASAPI capture.

## 2026-07-14 (36)
- Added a `--debug` CLI flag (`src/main.py`) so Audio Mode can log a
  calibration pass against real music: every audio block while Audio
  Mode is active gets one CSV row (`src/modes/custom_mode.py`'s
  `DEBUG_LOG_COLUMNS`) written to a fresh timestamped
  `audio_debug_<timestamp>.csv` next to the app (a new file per
  activation, gitignored). Logs the three final smoothed source values
  (timbre/energy/beat) plus the raw pre-sensitivity readings behind
  them (`CustomShowEnvelope.debug_snapshot`: centroid Hz, pre-gain
  energy, flux/onset threshold) and the sensitivity in effect at that
  instant - a value pinned at 0 or 1 in the final column doesn't say
  whether that's the real signal maxed out or the current gain/
  threshold being off, and the raw columns do. The intent: run with
  `--debug` against real, varied music for a while, then review the
  CSV for the same kind of calibration adjustments the original
  Energy/BANDS tuning was based on (see ARCHITECTURE.md), but grounded
  in real listening instead of one synthesized clip. Live-verified
  against the real bulb group: activated Audio Mode with debug=True,
  confirmed a real CSV appeared with the correct header and one row
  roughly every ~23ms, matching the expected values for a silent
  block.

## 2026-07-14 (35)
- Added two Ambience-tab sliders after live use while watching a film:
  "Colour sensitivity" (how aggressively `AmbienceEnvelope` ignores
  dull/low-saturation pixels when picking a dominant colour -
  previously a fixed constant tuned for games, where it works well,
  but for films it sometimes picked a small vivid detail that clashed
  with a scene's actual, more muted, overall mood) and "Smoothing"
  (how quickly colour transitions settle - the previous fixed EMA
  factor's snappy response suits games, where a colour change is
  already triggered by a deliberate in-game event, but read as
  "ruckelig"/choppy for a film's more gradual scene-to-scene shifts).
  Both are 0-100, 50 = the original fixed constants exactly, using the
  same exponential-curve convention as Audio Mode's per-source
  sensitivity sliders (`src/audio/custom_show.py`). Persisted in
  `ambience_config.json` (`AmbienceConfig.colour_sensitivity`/
  `smoothing`) and live-adjustable while Ambience Mode is running
  (`AmbienceMode.set_colour_sensitivity`/`set_smoothing`), since the
  whole point is tuning them by feel while actually watching content -
  no restart, no losing the running envelope's already-smoothed state.
  Live-verified against the real bulb group: activated Ambience Mode,
  dragged both sliders while it was running, confirmed the running
  mode's live values updated immediately.

## 2026-07-14 (34)
- Added a system tray icon (`src/gui/tray.py`): closing the main window
  now hides it to the tray instead of quitting, so any active reactive
  mode keeps running in the background. "Show FluxHound" / a left
  click on the tray icon restores the window; "Quit" from its
  right-click menu is now the only real way to exit. Built directly
  against pywin32's `Shell_NotifyIcon`/`LoadImage` (loading
  `fluxhound.ico` from its file path) instead of `pystray`, whose
  public API requires a `PIL.Image.Image` - this app has avoided
  Pillow everywhere else. The tray icon runs its own Win32 message
  pump on a dedicated daemon thread and calls back into Tk via
  `root.after(0, ...)`, the same cross-thread pattern already used for
  `DeviceConfigDialog`'s background network scan. If pywin32 isn't
  available or the icon fails to load, `_on_close` falls back to a
  real quit instead of stranding the window with no way back.
- Added a "Start with Windows" checkbox to Settings, backed by
  `src/autostart.py` - a `winreg`-based toggle of a per-user
  `HKCU\...\Run` entry, no admin rights or new dependency needed.
- Live-verified: tray hide/restore correctly toggles the window's Tk
  state (`normal` <-> `withdrawn`) without ending the process, and the
  Settings checkbox correctly writes/removes the registry entry
  (cleaned back up after the test, confirmed no leftover entry).

## 2026-07-14 (33)
- Fix: the gear/Settings button disappeared after the tab-restructure
  design pass. It was still created before header_frame/the tabview,
  so those later-packed siblings stacked visually above it and covered
  it even though it was still there and technically clickable if you
  knew exactly where. Fixed by moving its construction back to the end
  of `__init__` (it's `.place()`d, not packed, so creation order is
  what determines stacking) - restores the invariant the pre-redesign
  code already documented and relied on.
- Remove the Tuya Cloud local_key automation entirely
  (`src/tuya/cloud_discovery.py`, `src/tuya_cloud_config.py`, and
  their tests, all deleted). It had a real bug - correctly-entered
  credentials and region still produced a wrong "no local key found on
  this account" error - and, separately, needed the user's Tuya IoT
  API key/secret sitting in a plaintext local JSON file, which wasn't
  worth it for a convenience feature on an app whose whole premise is
  local-only control. `DeviceConfigDialog` now only offers local UDP
  scan (device ID + IP) plus manual local-key entry - no radio choice,
  no cloud section, no more entry fields whose typed text was oddly
  invisible until focused (that bug lived entirely in the now-removed
  cloud UI)

## 2026-07-14 (32)
- Visual design pass - no functional changes, every existing capability
  works exactly as before (confirmed via a live Ambience Mode activate/
  deactivate cycle sending real bulb commands through the redesigned
  UI). A single vivid pink/magenta brand accent now applies globally
  via a customtkinter colour theme (`src/gui/theme.py`/`theme.json`,
  loaded once at startup) instead of ad hoc colours scattered per
  window; a generated `fluxhound.ico` (no PIL - Tk's own PhotoImage
  resize + a hand-built ICO container) is wired into every window's
  title bar, the taskbar, and the built exe's own resources, so no
  generic Python icon ships anywhere. The main window's single long
  scrolling column is now a persistent header + Manual/Audio/Ambience
  tabs (every widget kept its exact attribute name, so no event-handler
  changes were needed). Status messages get an icon/colour matching
  their nature (error/loading-with-animated-dots/steady) instead of
  plain text; zero configured devices now shows a guided empty state
  instead of a blank screen; every paid-tier control gets a small
  "PRO" badge shown at a glance, not just on click-through. Verified at
  100/125/150% simulated DPI scaling (customtkinter's own scaling API,
  not the real Windows display setting) with no cropping on any tab.
  Known limitation, flagged rather than approximated: the source
  logo's fine line-art detail doesn't survive small-size (16-48px) icon
  downscaling legibly - needs a real, separately designed simplified
  mark

## 2026-07-14 (31)
- Add PyInstaller packaging: `fluxhound.spec` builds a single portable
  `FluxHound.exe` (`console=False`, unsigned). The logo is intentionally
  not bundled as a PyInstaller data file - copied into `dist/` alongside
  the exe instead, matching `_app_root_dir()`'s existing "resolve next
  to sys.executable when frozen" convention rather than PyInstaller's
  temp extraction dir. Smoke-tested from an isolated directory with no
  dev environment on the path: window opens, theme/logo render
  correctly, its own config file is created next to it, and a nested
  dialog (Configure device) opens correctly too. README documents the
  build command and the expected Windows SmartScreen warning.
- **Finalization phase complete**: licensing (free/paid gating + real
  Lemon Squeezy validation) and packaging are both done. This build is
  intended for a private friends-and-family test round, not a public
  release - ROADMAP's Open section lists the known limitations
  (untested real-key success path, no server-side licence release on
  "Remove licence", no periodic re-validation, Trigger Editor edits not
  live-restarting a running session, smoke test not on a separate
  machine) surfaced now rather than left for real users to hit first

## 2026-07-14 (30)
- Add licensing: free vs. paid tier gating, and real Lemon Squeezy
  license validation. Free: 1 device, Manual Control, Ambience Mode,
  Gaming Mode with its built-in watcher - fully functional. Paid:
  unlimited devices/groups/Merged Groups, Audio Mode, Multi-region
  Mode, the Custom Trigger Editor. All gating routes through one
  central module (`src/licensing/gate.py`); every gated action shows a
  non-dead-end `UpsellDialog` explaining what unlocking adds, with a
  path straight to the new `LicenseWindow` (Settings → License). Real
  Lemon Squeezy License API integration (`POST /v1/licenses/activate`)
  replaces the always-true stub; the unlocked state is cached locally
  (`src/license_config.py`) so `is_licensed()` never makes a network
  call - the app never hard-requires connectivity just to start up.
  Verified live against the real 3-bulb group in both the free (each
  gated action blocked with an upsell, underlying state unchanged) and
  a locally-seeded-unlocked state (same actions succeed normally); the
  rejected-key path was also confirmed against the real, live Lemon
  Squeezy API (no store/product exists yet to test a real valid key)

## 2026-07-14 (29)
- Add the Custom Trigger Editor: Gaming Mode's fixed-constant behaviour
  (`health_bar.py`) was generalized into a `TriggerConfig`/
  `ThresholdBand` pair (thresholds, flash colours, multi-step glow
  bands), with the original constants kept as its defaults so the
  built-in watcher stays exactly as it was. Any number of extra
  watchers (own screen region + own fully custom TriggerConfig) now run
  alongside the built-in one, added/edited via a new "Custom Trigger
  Editor..." window (`src/gui/trigger_editor_window.py`) - first
  watcher with an active override wins each tick, built-in first.
  Groundwork for the paid-tier gating in the licensing/packaging
  finalization phase. Verified live against the real 3-bulb group: a
  custom watcher's own thresholds/colours fired correctly and
  independently of the built-in one's fixed defaults, and priority
  ordering held when both fired simultaneously

## 2026-07-14 (28)
- Fix: "Scan local network" only reliably found one device on a
  network with three real bulbs. `tinytuya.deviceScan`'s `maxretry`
  argument isn't a retry count despite the name - it's the scan's
  listening duration in seconds, and the original code passed `2` on
  the wrong assumption, cutting the real window to ~2 seconds, far too
  short for every device to get a chance to broadcast. Fixed by
  defaulting to tinytuya's own recommended 18-second window
  (`DEFAULT_SCAN_SECONDS`) and renaming the parameter to `scan_seconds`
  to describe what it controls; the "Scanning local network..." status
  text now sets that expectation too. Verified live: a scan now finds
  all three known bulbs (plus one unregistered Tuya device) in one pass

## 2026-07-14 (27)
- Removed "Screen region alarm mode" from ROADMAP's Open list: its one
  concrete use case (alarm on a region's fill level rising/falling) is
  already exactly what Gaming Mode does; a broader "alarm on arbitrary
  region change" feature would be speculative without a specific need

## 2026-07-14 (26)
- Fix: deactivating Audio Mode or Ambience Mode left the bulb(s) stuck
  on the mode's last colour instead of restoring the manual state from
  before it started. `_begin_reactive_mode` aliased the "restore to
  this" snapshot and the live-tracking snapshot to the same object, so
  the mode's own continuous live-indicator updates silently corrupted
  the restore target throughout the run. Fixed by giving
  `self._current_state` an independent copy instead of sharing the
  object with `self._pre_reactive_state`. Verified live against the
  real 3-bulb group for both a white-mode and a colour-mode baseline:
  the bulb reliably settled back to the true prior state after
  deactivating, not the mode's last output

## 2026-07-14 (25)
- Add Multi-region Mode: a checkbox (mutually exclusive with Gaming
  Mode) lets a merged group's positioned bulbs (BASE, EXT-1, EXT-2,
  ...) each watch their own screen region instead of sharing one
  ambient reading, via a position dropdown + its own "Set area"/
  "Delete area" button and a preview that labels every assigned
  region at once. `AmbienceMode`'s send path was unified around a
  per-bulb reading list so normal/Gaming/Multi-region modes all share
  one send method instead of three separate ones; bulbs sharing a
  region share one capture, and a bulb with no region assigned falls
  back to the whole-monitor reading (`src/ambience_config.py`,
  `src/modes/ambience_mode.py`, `src/gui/main_window.py`). Verified
  live against the three real merged bulbs: three solid-colour screen
  regions (red/green/blue) assigned to BASE/EXT-1/EXT-2 produced
  exactly matching, non-cross-talking hues sent to each corresponding
  physical bulb

## 2026-07-11 (24)
- Add device discovery to `DeviceConfigDialog`. A "Scan local network"
  button (`src/tuya/discovery.py`, wrapping `tinytuya.deviceScan` - UDP
  broadcast, no cloud) lists whatever Tuya devices respond within a
  few seconds; picking one fills in Device ID and IP Address.
  Best-effort by design - a device that isn't currently broadcasting
  just won't show up in that particular scan, so the button can simply
  be clicked again.
- Tuya devices deliberately never broadcast their local_key over the
  LAN, so UDP discovery can never provide it. Added a radio choice next
  to "Local Key": enter it by hand (unchanged), or - for users willing
  to provide their own Tuya IoT developer account credentials - fetch
  it from the Tuya Cloud API (`src/tuya/cloud_discovery.py`, wrapping
  `tinytuya.Cloud`). This is the *only* place anywhere in the app that
  talks to Tuya's cloud, and only when the user explicitly opts in by
  entering their own API region/key/secret; it's a one-time lookup -
  once retrieved, control of that bulb stays 100% local like every
  other device. Fetched devices list their real Tuya-assigned name
  (something local-only discovery can never provide) and fill in
  Device ID, Local Key, and IP Address if the API happens to include
  one (it usually doesn't - Tuya Cloud doesn't reliably expose a
  device's LAN IP, which is why the local scan still matters even for
  Cloud users). A successful fetch's credentials are remembered
  (`src/tuya_cloud_config.py`, `tuya_cloud_credentials.json`,
  gitignored - account-level, same sensitivity as a password); a failed
  fetch (bad key/secret) is never persisted.
- Fixed a real bug caught before it reached live testing: the dialog's
  hardcoded `geometry("380x320")` was sized for the old three-field
  layout and far too small for the new content - Tk's pack geometry
  manager, when it runs out of vertical space, silently collapses
  low-priority widgets to 1x1px instead of showing them, so the manual
  Local Key field and the whole Cloud section were present but
  invisible and non-interactive. Fixed by removing the hardcoded
  geometry entirely and letting the dialog auto-size to its actual
  content, which also means it now grows correctly as scan/fetch
  results are added.
- Verified live against the real network: "Scan local network" found a
  real bulb and correctly filled Device ID and IP Address from it (the
  dialog was cancelled rather than saved, so the already-configured
  device wasn't duplicated into `devices_config.json`, which was
  confirmed byte-for-byte unchanged afterward); the manual/Cloud radio
  toggle correctly swaps which section is visible, with the dialog
  resizing accordingly. The Tuya Cloud path itself is covered by unit
  tests with `tinytuya.Cloud` mocked - not live-tested, since it needs
  a real Tuya IoT developer account's credentials, which weren't
  available. New unit tests for both discovery modules and the
  credential persistence; full suite: 76 tests passing (13 new).

## 2026-07-11 (23)
- Confirmed against the physical bulb which end of the temperature
  slider reads as warm vs. cool: 0 (left) is warm, 1000 (right) is
  cool - matching what `WARM_WHITE_RGB`/`COOL_WHITE_RGB` already
  assumed for the live-state indicator's white-mode gradient. Updated
  the code comment (previously "unverified... decorative
  approximation") and ARCHITECTURE.md to state this as confirmed
  rather than an open question; moved off ROADMAP.md's Open list.

## 2026-07-11 (22)
- Fix two real gaps in Gaming Mode's health-bar tracking (`src/screen/
  health_bar.py`), both raised as questions before being asked to fix
  them: what happens if Ambience Mode starts while the bar's already
  at some non-zero level, and what if that very first frame catches it
  fully empty? The first turned out to already work correctly by
  construction - `fill_fraction`'s denominator is always the region's
  fixed total pixel count, never "whatever the bar showed at
  calibration time", so healing past a mid-fight starting level was
  already detected correctly. The second was real: a mostly-empty
  region on that one calibration frame finds no vivid pixels,
  `calibrate_bar_colour` returns `None`, and the old design left the
  tracker permanently uncalibrated for the rest of the session.
  There's also a related gap for bars that recolour as they deplete (a
  common green→amber→red convention), which a single persisted
  reference colour can't follow.
- Fixed by dropping the one-shot calibration step entirely: the fill
  colour is now re-identified fresh from *every single frame*
  (`measure_fill`, replacing `HealthBarTracker.calibrate()` + a
  persisted `_bar_colour`) and measured against that same frame's own
  reading. No reference to go stale, no single calibration moment to
  get unlucky on, and a colour-shifting bar is measured correctly at
  every step. An empty frame now measures as a real fill fraction of
  0.0 (correctly triggering the low-health glow immediately) rather
  than a failed calibration. `AmbienceMode`'s hot loop simplified to
  match - no more `calibrated` flag/branch, just one `process()` call
  per frame.
- Verified live against the three real merged bulbs, twice: once with
  the bar starting completely empty on Ambience Mode's very first
  frame (confirmed the low-health glow fires immediately, then that
  healing to 90% is still detected as a real increase - proving
  tracking wasn't left permanently broken), and once with a bar that
  both shrank *and* changed colour (green → amber) in the same
  transition (confirmed the decrease flash still fires correctly).
  This session's `ambience_config.json` had the user's own real,
  in-progress Gaming Mode region set at the time - backed up before
  testing and restored exactly afterward, including pausing mid-test
  when their own FluxHound instance turned out to still be running, to
  avoid two processes fighting over the same real bulbs. Two new
  regression tests plus three widened existing ones (colour-shift and
  empty-start specific); full suite: 63 tests passing.

## 2026-07-11 (21)
- Add Gaming Mode: a checkbox below the monitor/"Set area" row that
  repurposes the region as a health/resource-bar (or Diablo-style orb)
  watcher instead of an ambient-colour region. With it checked, the
  ambient reading goes back to watching the whole monitor as usual,
  while the region gets scanned for the bar's fill level and can
  briefly override the bulb with an alert.
- New `src/screen/health_bar.py`: deliberately colour-ratio based, not
  OCR - reading styled in-game digits reliably would need a much
  heavier, more fragile dependency for a signal this approach already
  gives directly, and it works for any bar/orb shape without knowing
  its geometry. `calibrate_bar_colour` identifies the bar's fill colour
  (hue/saturation/value) once, the same "most frequent vivid colour"
  idea Ambience Mode itself uses for the whole screen; `fill_fraction`
  then measures what fraction of the region's pixels match it - which
  *is* the fill percentage, as long as the region is cropped around the
  bar/orb's full fixed extent. `HealthBarTracker` compares fractions
  frame to frame: a drop past a small epsilon (to ignore capture noise)
  briefly flashes the bulb red, a rise flashes green, and falling below
  10% holds a continuous red glow (taking priority over an active flash)
  until it recovers.
- Fixed a real bug caught by a unit test before it reached a live bulb:
  many bars' empty "track" is a *darker shade of a similar hue* to the
  fill (a dim maroon track behind a bright red fill), not neutral grey.
  Calibrating while the bar was mostly empty - track pixels vastly
  outnumbering fill pixels - diluted the identified reference colour
  toward the track's much duller saturation/value, which then made
  `fill_fraction` misread track pixels as filled, breaking the
  percentage specifically at low health. Fixed by requiring calibration
  pixels to clear a much stricter saturation floor (0.5, well above a
  typical dim track) so a mostly-empty calibration frame can't dilute
  the reference, and by requiring `fill_fraction`'s ongoing matches to
  be close on saturation *and* value to the calibrated fill, not just
  hue.
- `src/modes/ambience_mode.py`'s `AmbienceMode` now runs two
  `ScreenCapture`s when `gaming_mode=True` - one on the whole monitor
  for the ambient reading, one on the region for the health-bar tracker
  - both from the same background thread; whichever tick a tracker
  override is active, it's sent instead of the ambient reading.
  Persisted alongside the monitor/region choice
  (`src/ambience_config.py`, `AmbienceConfig.gaming_mode`); the
  checkbox is disabled while a reactive mode is running, like the
  monitor dropdown and area button.
- Verified live against the three real merged bulbs: a blue full-screen
  background with a red health bar (dark same-hue track behind a vivid
  fill - the exact case the calibration fix targets) drag-selected as
  the area. With Gaming Mode on, all three bulbs read ambient blue at
  rest, confirming the region no longer drives ambient once Gaming Mode
  is on. Shrinking the bar 100%→50% flashed all three red then expired
  back to blue; growing 50%→90% flashed green the same way. Dropping to
  5% held a continuous red glow (confirmed still red 1.5s later, not
  just an expired flash), and recovering to 80% flashed green once more
  before ambient blue resumed. New unit tests for `health_bar.py`
  (including a regression test for the low-fill calibration bug) and
  `ambience_config.py`'s `gaming_mode` round-trip; full suite: 60 tests
  passing (12 new).

## 2026-07-11 (20)
- Fix the main window growing taller than a 1080p screen (`460x1160`,
  reported live as no longer fitting). Everything except the gear
  button now lives inside a `ctk.CTkScrollableFrame`
  (`MainWindow.scroll_container`); the window itself dropped back to a
  fixed `480x820` and any content past that scrolls instead of the
  window overflowing off-screen. The gear button is created *after*
  the scroll container (still a direct child of the window, not the
  scrollable frame) so it stacks on top and stays reachable at any
  scroll position. Verified live: window geometry confirmed at
  `480x820`, screenshotted at the top (title/live indicator/manual
  controls, gear button visible) and scrolled to the bottom
  (Set to Default/Ambience button/preview/monitor dropdown all
  reachable, gear button still visible). Full suite: 47 tests passing
  (no logic changed, layout only).

## 2026-07-11 (19)
- Add monitor and capture-region selection to Ambience Mode. Below the
  Ambience button: a preview box shaped to the watched monitor's aspect
  ratio, a monitor dropdown (matters once more than one monitor is
  attached), and a "Set area" button that opens a drag-to-select
  overlay (`src/gui/region_selector_window.py`, `RegionSelectorWindow`)
  covering the chosen monitor - releasing the drag persists that
  rectangle and Ambience Mode watches only it from then on, instead of
  the whole monitor. The button then reads "Delete area" to revert.
  Both choices persist across mode switches and restarts
  (`src/ambience_config.py`, `ambience_config.json`), with automatic
  fallback if the saved monitor no longer resolves (e.g. unplugged).
- `src/screen/capture.py`'s `ScreenCapture` now takes `monitor_index`
  and an optional `region` (pixels relative to that monitor's own
  top-left, not the full virtual desktop), and gained `list_monitors()`
  for the dropdown. `AmbienceMode` takes the same two parameters and
  builds its `ScreenCapture` with them inside its own background
  thread.
- Made the app per-monitor DPI aware
  (`src/main.py`, `_enable_dpi_awareness`,
  `SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)`, called
  before any Tk window exists) - without it, Windows silently rescales
  Tkinter's screen coordinates whenever display scaling isn't 100%,
  while mss (and the physical monitor bounds it reports) always works
  in real physical pixels; left alone the two would drift apart and the
  selector's drag rectangle would land somewhere other than what
  actually gets captured. This machine happens to run at 100% scaling
  (checked via `GetDeviceCaps`/`LOGPIXELSX` before assuming it wasn't
  needed), so the mismatch wouldn't have been visible in this session's
  own testing - fixed anyway since it's a one-time, no-downside setting
  that prevents a whole class of bugs on any scaled display.
- The preview box (`MainWindow._redraw_ambience_preview`) is a one-shot
  snapshot of the watched monitor, nearest-neighbour resized to fit
  (`_resize_frame_nearest`, no PIL) with the selected region (if any)
  drawn as an outlined rectangle on top - not a live video feed, it only
  redraws when the monitor/region choice changes. The monitor dropdown
  and area button are disabled while either reactive mode is running,
  like the rest of the manual controls; switching monitors always
  clears any saved region, since its pixel coordinates only make sense
  relative to the monitor they were drawn on.
- Verified live: simulated a drag-select (`event_generate` on the
  overlay's canvas) and confirmed the persisted region matched the drag
  exactly, and that a fresh `ambience_config.load()` (simulating a
  restart) reproduced it identically. The strongest check: filled the
  whole primary monitor green except for a red rectangle placed exactly
  at the selected region, activated Ambience Mode, and confirmed all
  three real bulbs converged on red rather than the far more numerous
  green pixels - proving capture is genuinely restricted to the region,
  not just a full-monitor grab that happened to include it. "Delete
  area" and monitor switching both correctly cleared the region, on
  disk and in the UI. New unit tests for `ambience_config.py`'s
  round-trip/fallback behaviour and `ScreenCapture`'s monitor/region
  resolution math; full suite: 47 tests passing (9 new).

## 2026-07-11 (18)
- Fix manual touches (colour palette, brightness slider, temperature/
  saturation slider, White circle) silently clearing an Audio Mode
  source assignment even while Audio Mode wasn't running. The
  assignment is persisted configuration for the *next* time Audio Mode
  runs; touching a slider in plain manual mode shouldn't blank out a
  configured Hue/Brightness/Saturation source the user hasn't even
  activated Audio Mode to use. `MainWindow._deactivate_row` is now only
  called from inside the `isinstance(self._reactive_mode, CustomMode)`
  branch of each handler (previously called unconditionally first,
  before checking whether anything reactive was even running); the two
  calls in `_on_white_click` were removed outright, since that handler
  already refuses to run at all while any reactive mode is active, so
  they could only ever fire in plain manual mode where they never
  belonged. Manually touching a control *while Audio Mode is actually
  running* still correctly clears that target's assignment, unchanged.
- Fix the "Remove" button appearing to be missing for a grouped device
  that hasn't been renamed yet (falls back to showing its device ID,
  which is much longer than a typical name). `DevicesWindow`'s row
  layout packed the name label first with `fill="x", expand=True`,
  which claims all available width before the action buttons get a
  turn - a long enough label pushed "Remove" (and "Change name")
  straight out of the scrollable frame's fixed width, off-screen but
  still technically present in the widget tree. Fixed by packing the
  action buttons from the right first, so they always claim their
  space, with the label packed last to fill only whatever's left.
- Verified live against the real 3-lamp merged group on this machine:
  colour pick, brightness, saturation, and White click with Audio Mode
  off left the on-disk `audio_mode_config.json` assignment byte-for-byte
  unchanged; the same brightness touch during an active Audio Mode
  session still correctly cleared just that target's assignment
  (confirmed against the real bulb group throughout, then restored
  exactly). For the layout fix, located the previously-unnamed lamp's
  Remove button by its row and confirmed its on-screen X position now
  falls inside the scroll frame's visible bounds, where it previously
  would have been clipped outside them.

## 2026-07-11 (17)
- Add Ambience Mode: a second reactive mode, mutually exclusive with
  Audio Mode, that continuously matches the active target's colour and
  brightness to whatever's dominantly colourful on screen. New
  `src/screen/capture.py` (`ScreenCapture`, via `mss` - chosen over
  `PIL.ImageGrab` to avoid a Pillow dependency, and because `mss`'s
  per-monitor/region grabs leave room for a planned per-region
  follow-up) grabs and downsamples the primary monitor; new
  `src/screen/ambience_show.py` (`AmbienceEnvelope`) turns a frame into
  one smoothed hue/saturation/brightness reading, deliberately
  discounting low-saturation "boring" pixels (text, chrome, plain
  backgrounds) that would otherwise wash a flat average toward grey,
  and picking one dominant hue via a saturation-weighted histogram
  instead of averaging distinct colours into a muddy blend nothing on
  screen shows. New `src/modes/ambience_mode.py` (`AmbienceMode`)
  reuses Audio Mode's full reliability setup (persistent connection,
  fail-fast timeout, `nowait` sends, rate-capped single-DP writes).
- Caught a real bug before it reached live testing: an earlier version
  of the "boring pixel" filter also excluded high-*value* pixels
  (intended to catch near-white content), which was wrong - it
  actually excluded fully-saturated bright primaries too. A solid-blue
  test frame came back with saturation 0 instead of 1000. Fixed by
  removing the value-based upper filter entirely: brightness never
  makes a pixel boring, only low saturation does (a near-white pixel
  already has near-zero saturation by definition, so the saturation
  filter alone was always sufficient). Caught by a new unit test
  (`test_pure_saturated_colour_at_full_brightness_is_not_treated_as_boring`)
  before this ever touched a real bulb.
- New "Activate Ambience" button below "Set to Default". Since Audio
  Mode and Ambience Mode would otherwise fight over the same
  `colour_data` writes, each mode's button disables the other's while
  it's running. Ambience Mode has no per-property source assignment to
  hand back (unlike Audio Mode's `set_manual_override`), so the
  brightness/temperature sliders and colour palette are disabled
  outright while it runs instead of being silently overwritten again
  within one send interval (`MainWindow._set_manual_override_controls_enabled`).
- Verified live against the three real bulbs already merged into one
  group on this machine: a solid-red full-screen test pattern
  converged all three bulbs to hue ≈0, switching to solid blue
  converged them to hue ≈240 - confirmed via `status()` on all three
  real bulbs, not just the app's own state. Confirmed mutual exclusion
  (Activate Audio Mode disabled throughout) and manual-control
  disabling, and a clean deactivate/restore afterward. The group's
  `devices_config.json` was never touched, since the feature just
  drives whatever the already-active target is. Added `mss` to
  requirements.txt. New unit tests for the colour analysis
  (`tests/test_ambience_show.py`, 7 tests); full suite: 38 tests
  passing.

## 2026-07-11 (16)
- The live-state indicator now shows `fluxhound_logo.png` (added to the
  repo) composited over a radial glow of the bulb's current colour,
  fading out to the app's background colour at the edges - replaces
  the old flat-colour `ctk.CTkFrame` with a raw `tkinter.Canvas` (two
  layered image items: the glow, regenerated on every state change via
  the same vectorized-numpy/raw-PPM technique as the colour picker's
  gradient, no PIL; the logo, downscaled once at startup via
  `PhotoImage.subsample` and never redrawn since it doesn't change).
  Window height grown from 820 to 1000 to fit the larger 260x220
  indicator area.
- Verified empirically before relying on it, since older Tk only
  supported all-or-nothing transparency: composited a synthetic
  50%-alpha pixel over a solid background via `Canvas.create_image` and
  got back an exact 50/50 blend, confirming this Tk build (8.6, bundled
  with the project's Python) does real alpha compositing - which is
  what lets the logo's own soft vignette (opaque at the dog-head
  artwork, fully transparent at the far corners) blend naturally into
  the glow instead of showing a hard-edged square.
- Fixed a crash hit on the first live run: the theme's background
  colour (`ctk.ThemeManager.theme["CTk"]["fg_color"]`) isn't always a
  "#rrggbb" hex string - customtkinter's default theme has it as a
  named Tk colour like `"gray86"` - so parsing it with a hand-rolled
  hex parser threw `ValueError: invalid literal for int() with base 16:
  'gr'`. Switched to `self.winfo_rgb(...)`, which resolves any valid Tk
  colour spec (named or hex) to RGB.
- Verified live: launched the app, screenshotted the real window
  (`PrintWindow` via a small PowerShell/.NET snippet, since
  `SetForegroundWindow` silently failed to bring a background-launched
  window forward for a normal screen-region grab) and visually
  confirmed the radial glow (in the bulb's actual current red) and the
  logo's soft-edged vignette blending into it correctly, with the rest
  of the layout unaffected. The app is currently in real day-to-day use
  with three real bulbs merged into one virtual lamp (BASE/EXT-1/
  EXT-2) - that live `devices_config.json` state was left untouched.

## 2026-07-11 (15)
- Add merged groups: a group's members can each be assigned a position
  ("BASE" or "EXT-1"/"EXT-2"/... up to member count - 1, each label
  unique within the group) via a new dropdown in the Devices window,
  placed before each grouped device's "Change name" button
  (`DevicesWindow._on_position_changed`,
  `devices_config.available_positions` filters out labels already taken
  by another member). A "Merge" button next to each group's name
  (`DevicesWindow._on_merge_click`) toggles `DeviceGroup.merged`, only
  enabled once at least BASE and EXT-1 are assigned
  (`devices_config.can_merge`); losing that minimum (repositioning or
  removing a device) auto-clears `merged` so it can never reference an
  invalid position set.
- A merged group is treated as one virtual lamp instead of a set of
  identical mirrors: `src/tuya/device.py` gains
  `split_value_across_bulbs(value, max_value, count)`, distributing one
  logical 0..max_value reading across `count` positioned bulbs BASE
  first (a 50% request across 3 bulbs -> BASE 100%, EXT-1 50%, EXT-2
  0%; across 2 bulbs -> 100%/0%, both straight from the feature spec).
  Three checkboxes (`MainWindow._split_vars`, default checked, one per
  Hue/Brightness/Saturation) control which properties actually get
  divided this way versus mirrored as-is; they're inserted as a new
  column before the Audio Mode assignment grid's three existing rows,
  and only shown while the active target resolves to a merged group
  (`MainWindow._update_merge_ui_visibility`). Devices without a position
  always get the plain, unsplit value regardless of merge state - only
  positioned members are treated as segments of the virtual lamp.
- Wired into every relevant dispatch path: `MainWindow.
  _dispatch_colour_data`/`_dispatch_brightness_only` compute each active
  bulb's per-property share from `_build_split_ranks` before sending
  (palette picks, brightness/saturation slider moves), falling through
  to the same partial-failure-tolerant `_dispatch` used everywhere else.
  `CustomMode` (Audio Mode) gained the same `split_targets`/`split_ranks`
  parameters and applies the identical algorithm in its hot loop, so a
  merged group can run one reactive show split across its bulbs.
- Verified live against the two real bulbs already grouped together on
  this machine ("Stehlampe"): the Merge button's disabled -> enabled
  transition landed exactly at the BASE+EXT-1 threshold; a 50%
  brightness request (hue/saturation unchecked) landed BASE at exactly
  1000 and EXT-1 at exactly 0 via `status()` on both real bulbs, hue
  unchanged confirming the unchecked properties stayed mirrored;
  swapping which lamp held which position produced the exact reverse;
  unmerging brought both lamps back to receiving an identical mirrored
  value. New unit tests cover `split_value_across_bulbs` (both spec
  examples, full/zero/single-bulb edges) and the position/merge helpers
  (`position_rank`, `available_positions`, `ordered_merge_device_ids`,
  `can_merge`). Full suite: 31 tests passing.

## 2026-07-11 (14)
- Add multi-device support: any number of Tuya bulbs can now be
  configured, each with a locally-editable display name that's purely
  cosmetic in this app (the local Tuya protocol has no name field to
  write back to the device). New `src/devices_config.py`
  (`DevicesConfig`: a list of devices, a list of named groups, and
  which one is currently the active target) replaces the old
  single-device `device_config.json` as the source of truth; on first
  run after this change, the previously-configured device is migrated
  in automatically as the first entry, display name defaulting to its
  device ID (`device_config.py`/`device_config.json` are kept around
  only for that one-time migration read, nothing writes to them
  anymore).
- The gear button no longer opens the device dialog directly - it opens
  a small `SettingsWindow` (`src/gui/settings_window.py`) whose first
  entry, "Devices", closes it and opens `DevicesWindow`
  (`src/gui/devices_window.py`): lists devices under "Single devices"
  and groups under "Grouped devices", each with a "Change name" button,
  and either a "Group" button (single devices - prompts for a new
  group's name, or once groups exist, asks to create a new one or add
  to an existing one) or a "Remove" button (grouped devices - pulls it
  back out; a group that loses its last member is deleted
  automatically). An "Add device" button opens the existing device
  dialog to register a new bulb.
- Added a dropdown below the live-state rectangle
  (`MainWindow.target_selector`) listing every device and group; the
  selected one is the current target for every manual command and
  Audio Mode session. Every bulb command dispatch (`MainWindow.
  _run_on_all`) now sends to every bulb in the active target at once
  instead of a single hardcoded bulb, so a group applies the same
  command to all its members simultaneously - one member failing
  doesn't stop the command reaching the others. `CustomMode` (Audio
  Mode) now takes a list of bulbs instead of one, for the same reason.
  Switching targets only reconnects when the resolved device set
  actually changed, so renaming a device or editing a group you're not
  currently using doesn't disturb a live connection; if the active
  target is deleted out from under it, the selector falls back to the
  first available option automatically. Disabled, like the White
  circle, while Audio Mode is running.
- Verified live against the real bulb (reachable again this session -
  see entry (13)'s note; the user confirmed the lamp and its local_key
  were fine throughout, so the earlier unreachability was most likely
  transient rather than the rotated-key theory guessed at the time):
  the legacy
  `device_config.json` migrated correctly into `devices_config.json`
  with the display name defaulting to the device ID; renaming the
  device updated the selector label immediately without disturbing the
  live connection; adding a second (deliberately unreachable) test
  device and grouping it with the real one via both the "create new
  group" and "add to existing group" paths worked exactly as designed,
  including the "Single devices" heading correctly disappearing once
  every device was grouped; switching the main window's target to that
  group and toggling power sent the command to both - the real lamp
  switched on despite the fake device reporting unreachable, confirming
  a partial group failure doesn't block the rest; removing devices from
  the group one at a time correctly auto-deleted it once empty, and the
  selector correctly fell back to a valid device afterward. Full
  `pytest` suite (20 tests, including new coverage for
  `devices_config.py`'s round-trip and migration behaviour) passed
  throughout.

## 2026-07-11 (13)
- White circle added to the palette row (leftmost), the only control
  left that switches `work_mode` to white
  (`MainWindow._on_white_click`). Brightness
  (`MainWindow._apply_brightness`) no longer forces white mode as a
  side effect - it now sends `set_colour_data_value` (hue/saturation
  preserved) while in colour mode and `set_brightness_value` in white
  mode, so brightness can be adjusted without leaving whatever colour
  is active. Disabled while Audio Mode is running, since that mode only
  ever drives `colour_data`.
- Added a custom-colour circle (rightmost) opening a non-modal,
  freely-movable colour-picker window (`src/gui/colour_picker_window.py`,
  `ColourPickerWindow`): click-and-drag on a 220x220 saturation/value
  gradient plus a separate hue slider, or type an exact HEX or R/G/B
  value directly. The gradient is rendered with vectorized numpy
  HSV->RGB math into a raw PPM byte buffer fed to a
  `tkinter.PhotoImage` - no PIL/Pillow dependency added. Both input
  paths are debounced (120ms) into a single `on_pick(hue, saturation,
  value)` callback.
- The custom-colour circle itself shows a 24-wedge rainbow radial until
  the user has ever picked a colour, then a solid fill of the picked
  colour from then on. The picked colour is persisted to
  `custom_colour_config.json` (`src/custom_colour_config.py`, same
  load/save dataclass pattern as `device_config.py`) and reloaded on
  startup, so it survives both mode switches and full app restarts.
- `CustomMode` (Audio Mode) gained an `on_update(hue, saturation,
  value)` callback fired from its background thread on every send, so
  the GUI can mirror the live show without polling.
- Replaced the inline "Change device" button with a small gear-icon
  (⚙) button in the top-right corner, freeing up header space for a
  "FLUXHOUND" title label and a `live_indicator` rectangle below it
  that reflects the bulb's current colour and brightness as a fill
  colour at all times, including live updates from Audio Mode via the
  new `on_update` callback (`MainWindow._update_live_indicator`).
- Verified live against a real bulb (the usual primary test lamp,
  "Computerlicht1/Stehlampe mitte", was unexpectedly unreachable this
  session - see debugging note below; verification instead used a
  second test lamp, "Stehlampe unten", with `device_config.json`
  temporarily swapped and restored to the original afterward):
  White click set DP21 to 'white'; picking a palette colour (blue) set
  DP21 to 'colour' with the expected DP24; moving the brightness slider
  while in colour mode kept DP21 at 'colour' and changed only DP24's V
  component, hue/saturation preserved - the core fix. The picker's hex
  entry ("FF8800") and a canvas click both produced exact matching
  DP24 values and correctly-synced RGB entry fields. The persisted
  `custom_colour_config.json` matched the last pick exactly. Audio Mode
  correctly disabled/re-enabled the White circle on start/stop, and the
  live indicator's fill colour changed during a running session via the
  new callback. Deactivating Audio Mode restored the exact pre-
  activation DP24 snapshot even through the new brightness/colour-mode
  code paths.
- Debugging note (not a code defect): the primary test lamp
  ("Computerlicht1/Stehlampe mitte") was unreachable
  at the Tuya protocol level throughout this session's live-testing
  attempts (`ERR_OFFLINE` / "Device Unreachable" from tinytuya) despite
  responding to `ping` and accepting a raw TCP connection on port 6668.
  Ruled out as an app bug by reproducing the failure with fully
  hardcoded credentials bypassing all app/GUI code, confirming
  `device_config.json` was uncorrupted, and successfully connecting to
  a second, different test lamp with identical code. Most likely cause:
  the lamp's `local_key` was rotated by a re-pairing via the official
  Tuya/Smart Life app, which invalidates the previous local key
  permanently. This needs to be resolved on the device side (re-pair
  and obtain a fresh local key, then re-enter it via the app's gear-
  icon button) - it isn't something the app or this codebase can fix.
- Also hit two false "hang" appearances in test scripts written during
  this session's live verification, both caused by an unhandled
  exception inside a Tkinter `.after()` callback silently stopping a
  test's step-chain before it could schedule its next step (Tkinter
  logs the traceback but doesn't propagate it) - a Windows console
  `UnicodeEncodeError` printing the gear button's "⚙" glyph under the
  default cp1252 encoding, and an unwrapped `TuyaConnectionError` from
  a separate verification-only bulb probe. Neither was an application
  bug; noted here since the same pattern could easily be mistaken for a
  real freeze again in future test scripts.

## 2026-07-11 (12)
- Consolidate Music Mode 1/2/3 into a single "Audio Mode", removed the
  manual-colour-choice mode and the fixed-mapping mode entirely
  (deleted `src/modes/music_mode.py`, `src/modes/spectrum_mode.py`,
  `src/audio/analysis.py`, `src/audio/spectrum_show.py`, their tests,
  and their buttons). Only the configurable mode (formerly "Music Mode
  3") remains, moved from its own mode-switch screen onto the main
  page permanently as an "Activate/Deactivate Audio Mode" toggle;
  status shows "Audio mode active" at the top while running.
- Manually touching a property now hands it back from Audio Mode
  without stopping the rest of it: picking a palette colour
  deactivates Hue's assignment, moving the brightness slider
  deactivates Brightness's, moving the temperature slider deactivates
  Saturation's (`MainWindow._deactivate_row` for the persisted
  assignment, `CustomMode.set_manual_override` to also clear it and
  set the value atomically in the running mode).
- The temperature slider is now dual-purpose: colour temperature (DP
  23) in white mode, or saturation directly (DP 24's S component,
  hue/value preserved) in colour mode - which Audio Mode is always in.
  Its label switches between "Temperature (white mode)" and
  "Saturation (colour mode)" to match.
- Added a per-source sensitivity slider (0-100) to each grid row,
  tuning whichever source currently occupies that row via an
  exponential curve centred on the calibrated default at 50: Timbre's
  smoothing time, Energy's gain, or Beat's onset threshold, depending
  on which source it is.
- Added a "Set to Default" button: resets the assignment (Hue-Energy,
  Brightness-Beat, Saturation-Timbre) and all sensitivities without
  touching whether Audio Mode itself is active.
- The assignment and sensitivity now persist to `audio_mode_config.json`
  (`src/audio_mode_config.py`, same pattern as `device_config.py`) on
  every change and load on startup, surviving app restarts - not just
  in-memory across mode switches within a session as before.
- Fixed a bug found while verifying the above live: `_on_initial_status`
  unconditionally wrote the fetched colour-mode saturation onto the
  temperature/saturation slider on every status refresh, even in white
  mode, silently overwriting a just-restored temperature value (e.g.
  600) with a stale saturation reading (e.g. 1000) moments later.
- Verified live: bijection enforcement via real button `.invoke()` calls;
  manual overrides deactivating the correct row (colour pick -> Hue,
  brightness slider -> Brightness, temperature slider -> Saturation,
  each confirmed against the bulb's actual DP state); the dual-purpose
  slider correctly targeting DP 23 or DP 24's saturation depending on
  mode; a full white/450/600 -> activate -> deactivate round trip
  restoring exactly, sliders included, after the fix above; Set to
  Default resetting without touching Audio Mode's on/off state; a
  30-second live session with real bass audio and the default mapping
  producing zero errors with genuine hue/saturation/brightness
  movement; and `audio_mode_config.json`'s contents matching every
  change made along the way.

## 2026-07-11 (11)
- Add Music Mode 3 ("Custom Mode"): makes Music Mode 2's fixed hue/
  brightness/saturation mapping user-configurable. `CustomShowEnvelope`
  (`src/audio/custom_show.py`) computes three always-on sources every
  block (Timbre = spectral centroid, Energy = weighted bass/mid/treble
  band energy, Beat = onset/flux flash envelope), each a normalized
  0-1 signal reusing Music Mode 2's exact calibration. The GUI's 3x3
  button grid assigns each of Hue/Brightness/Saturation to at most one
  source, enforced as a strict bijection (a source's buttons in the
  other two rows disable once it's assigned somewhere, both visually
  and via a direct guard in `MainWindow._on_mode3_source_click`).
  Defaults to Music Mode 2's original mapping; the assignment persists
  across mode switches for the session and updates live while running
  (`CustomMode.set_assignment`). `CustomMode`
  (`src/modes/custom_mode.py`) reuses Music Mode's full reliability
  setup (persistent connection, fail-fast retry, nowait sends, one DP
  write per update via the shared `MainWindow._build_reactive_mode_bulb`).
- Fix reactive modes snapping to hardcoded defaults on entry regardless
  of the bulb's actual state - e.g. entering any Music Mode while the
  bulb was white at 50% brightness / 80% temperature used to jump
  straight to colour mode red. `AudioEnvelope`, `SpectrumShowEnvelope`,
  and `CustomMode` now accept initial hue/saturation/brightness (and
  Music Mode specifically an initial work_mode, since it can stay
  white) seeded from a `bulb.status()` snapshot taken right before a
  reactive mode starts, so the first updates drift from the bulb's
  actual state instead of snapping away from it.
- On exiting back to manual control, that same snapshot is now
  explicitly restored (`MainWindow._restore_snapshot`) - work_mode,
  brightness, and temperature, or colour/saturation/value - instead of
  just re-reading whatever the reactive mode left behind, and the
  brightness/temperature slider widgets are synced to match so the
  manual screen visibly shows the same values as before.
- Verified live: set the bulb to white/500/800 manually, entered Music
  Mode and confirmed it stayed white with brightness drifting from
  ~500 rather than snapping to the floor, exited and confirmed an
  exact restore (dps and both sliders); repeated the same round trip
  through Music Mode 3. Verified Music Mode 3's bijection through real
  `CTkButton.invoke()` calls (a disabled button does nothing) and a
  30-second live session with real bass audio showing genuine
  hue/saturation/brightness movement with zero errors.

## 2026-07-11 (10)
- Fix connection dropouts that persisted in both reactive modes even
  after the persistent-connection and connection_retry_limit fixes.
  Found by comparing against a working reference script (3 Tuya bulbs
  driven off separate FFT frequency bands) that doesn't have the
  problem: every send here still called tinytuya's default
  `set_value()`, which waits for and parses a response even at
  `retry_attempts=1` - a blocking receive cycle per update that's
  still too much for the bulb's WiFi firmware under sustained traffic.
  The reference script never waits for a response at all
  (`nowait=True`), despite sending faster (60ms vs. this app's 150ms),
  which rules out raw request rate as the cause. Splitting load across
  3 bulbs wasn't the explanation either - each bulb there gets its own
  full update stream at the same rate a single bulb would.
- `TuyaBulb` gains `set_work_mode_nowait`/`set_brightness_value_nowait`/
  `set_colour_data_value_nowait`: fire-and-forget writes that still
  detect a genuinely failed connection (tinytuya returns an error dict
  immediately if it can't open the socket) but skip the receive/retry
  cycle for a successful write. Both `MusicMode` and `SpectrumMode`
  switched their hot-loop sends to these; manual controls keep the
  waiting path, appropriately, since a user action should be confirmed
  or reported as failed.
- Verified live: two 100-second sessions (Music Mode and Music Mode 2
  separately) with continuous varied audio produced zero errors in
  either - the earlier 50-second tests weren't long enough to reliably
  surface this. Manual-mode controls re-verified unaffected.

## 2026-07-11 (9)
- Add Music Mode 2 ("Spectrum Mode"): a second, fully autonomous
  reactive mode with no user colour choice, aimed at getting the
  richest light show a single RGBCW bulb can do out of whatever's
  playing.
  - `src/audio/spectrum_show.py` (`SpectrumShowEnvelope`) drives hue
    (continuous spectral-centroid drift, warm for bass/tonal sound,
    cool for bright/noisy sound), brightness (weighted bass/mid/treble
    band blend, 0.5/0.3/0.2, so it stays alive during melodic or
    cymbal-heavy passages with little bass), and saturation (brief
    dips toward white on detected onsets, then recovering - a "flash"
    accent instead of a hard hue jump) every update.
  - `src/modes/spectrum_mode.py` (`SpectrumMode`) reuses Music Mode's
    hard-won reliability setup as-is (persistent connection,
    `connection_retry_limit=2`, fail-fast timeout, one DP write per
    update) via a new shared `MainWindow._build_reactive_mode_bulb()`.
    Driving all three HSV components costs nothing extra: `colour_data`
    (DP 24) already bundles them into one write.
  - Mid/treble band dB calibration measured the same way as Music
    Mode's bass band: the same synthesized, realistically-mixed track
    played and re-captured via real WASAPI loopback.
  - GUI: a "Music Mode 2" button next to "Music Mode"; both share the
    existing "Exit Music Mode" button back to manual control
    (`MainWindow._reactive_mode` now holds whichever mode is running).
  - Verified live against the real bulb with a 30-second realistic
    track: zero errors, and all three HSV components showed genuine
    variation (hue across 27 distinct values, saturation dipping on
    onsets and recovering, brightness spanning 189-746). Also verified
    clean switching Music Mode -> normal -> Music Mode 2 -> normal via
    the shared Exit button.

## 2026-07-11 (8)
- Fix the "unexpected response: None" errors that kept happening even
  with music mode's new persistent connection. Root cause:
  `connection_retry_limit=1` (set in the previous fix to force fast
  failure on a genuinely unreachable bulb) turned out to also cap how
  many extra reads tinytuya waits through when the device sends a
  routine null "ack" before its real response - normal Tuya protocol
  behaviour, not a failure. At 1, a single slow ack+payload pair was
  enough to exhaust that budget and come back as a bare `None`,
  misreported as an error even though the command had landed.
- Raised `connection_retry_limit` to 2 (exposed as a `TuyaBulb`
  constructor parameter). Chose 2 over tinytuya's default of 5 to keep
  genuine-failure detection fast: verified a simulated unreachable
  device still errors in ~3s and `MusicMode.stop()` still returns in
  well under a second, versus ~4.6s/~3s at a retry limit of 3.
- Dialed brightness smoothing back about halfway after a report that
  it had eaten too much of the visible reaction:
  `BRIGHTNESS_ATTACK_SECONDS` 0.08s -> 0.055s, `BRIGHTNESS_RELEASE_SECONDS`
  0.25s -> 0.185s (halfway back to the original 0.03s/0.12s).
- Verified live against the real bulb: two separate 50-second sessions
  with continuous synthesized bass audio produced zero errors, versus
  errors recurring within seconds before this fix and one lingering
  connection-warmup error per session at a retry limit of 3.

## 2026-07-11 (7)
- Fix recurring "unexpected response: None" errors and visibly jerky
  brightness in music mode, reported live after the previous fail-fast
  fix. Root cause: every send opened a brand new TCP connection
  (connect + handshake + close) instead of reusing one; at ~6-7
  sends/second that overhead alone was enough to intermittently
  overwhelm the bulb's WiFi firmware, and a dropped send read as a
  visible jump/skip in brightness.
- Music mode's bulb now uses `persistent=True` (one connection kept
  open for the whole session; `TuyaBulb.close()` releases it when the
  mode stops), instead of the connect-per-command default used for
  one-off manual commands. Verified live: a 22-second stress test with
  continuous bass audio produced zero errors, versus errors recurring
  within seconds before.
- Also retuned brightness smoothing (`BRIGHTNESS_ATTACK_SECONDS`
  0.03s -> 0.08s, `BRIGHTNESS_RELEASE_SECONDS` 0.12s -> 0.25s): the old
  attack time fully settled well within one ~0.15s send interval, so
  the value actually sent was close to a single raw, unsmoothed audio
  block each time - a second, independent source of the jerky look on
  top of the dropped-send issue.

## 2026-07-11 (6)
- Re-calibrate music mode brightness after a user report that bass
  produced almost no visible reaction with real music. Root cause:
  the previous calibration (20-200 Hz, floor 10 dB, ceil 40 dB) was
  tuned against isolated synthetic sine tones, which concentrate all
  their energy into 1-2 FFT bins and read far louder than the same
  frequency range does in an actual mix.
- Measured this properly instead of guessing again: built a
  synthesized, realistically-mixed track (kick + bassline + snare +
  hihat + pad at typical relative mix levels, 0.85 peak, 120 BPM),
  played it through the real speaker and re-captured it via real
  WASAPI loopback, and logged per-block energy across ten candidate
  frequency bands to see which one actually had usable dynamic range.
  The bass band had by far the highest absolute energy of all bands
  (as expected), but the old 40 dB ceiling meant real kick hits
  (~16-18 dB) never reached even half the brightness range.
- New calibration: band narrowed to 40-150 Hz (kick/bass fundamental,
  dropping sub-40 Hz content most systems barely reproduce and
  150-200 Hz content diluted by non-bass material), `DB_FLOOR=-5.0`,
  `DB_CEIL=22.0` from the measured percentiles.
- Verified live against the real bulb with the same track: brightness
  now swings 10-812 (mean ~388) in time with the kick pattern, versus
  being effectively pinned near the floor before.

## 2026-07-11 (5)
- Fix a real freeze reported live: music mode wrote two DPs per update
  (work_mode + value) through the default 2-attempt/1s-delay retry —
  up to ~14s per update on failure, enough sustained traffic to
  overwhelm the bulb's WiFi firmware and make it stop responding for a
  stretch. Music mode now uses a dedicated `TuyaBulb` with
  `retry_attempts=1` and a short timeout (fails in ~1.5s), and only
  writes work_mode when the white/colour choice actually changes.
  `MusicMode.stop()`'s join timeout raised from 2s to 5s so it reliably
  terminates the thread instead of potentially leaving it running.
- Music mode no longer changes colour automatically: brightness stays
  FFT/bass-driven, but colour is a fixed choice the user makes via the
  colour palette or a new "White" button, both of which stay visible
  and usable while music mode is running (`MusicMode.set_colour`/
  `set_white`, applied on the next cycle without restarting capture).
- Add a "Temperature" slider (DP 23) next to Brightness in manual mode.
- Fix a latent bug found via live testing: `TuyaBulb.status()` can
  return a partial dps dict (observed live: `{'22': 10}` with nothing
  else). The power-switch sync on connect now only touches the switch
  when DP 20 is actually present, instead of defaulting to "off".
- Fix a status-label race: a manual-mode command issued just before
  entering music mode could resolve after the mode switch and
  overwrite "Music mode active" with a stale "Connected".
- Verified live: unreachable-bulb test showed the first error at
  ~1.6s (previously up to ~14s) and confirmed `stop()` actually joins
  the thread in ~0.2s; a 10-second music-mode session with real bass
  audio produced zero errors and visibly pulsing brightness; picking a
  palette colour and clicking White while music mode was running were
  both confirmed against the real bulb's DP state.

## 2026-07-11 (4)
- Rework music mode's brightness/colour logic: brightness now watches
  only the bass band (20-200 Hz) with lighter, punchier smoothing
  instead of the full audible range; colour is now driven continuously
  by the spectrum's centroid (warm for bass-heavy, cool for treble-
  heavy sound) instead of jumping hard on detected onsets. Removed the
  now-unused onset detector.
- The status area (connected / unreachable) stays live during music
  mode instead of freezing on "Music mode active" — `MusicMode` reports
  both errors and recovery back to the GUI.
- Verified live: bass-heavy test audio kept hue low/warm and brightness
  pulsing with the bass hits; switching to broadband treble content
  moved the hue up smoothly over ~1-2 seconds rather than snapping;
  simulated a bulb connection failure mid-session and confirmed the
  status area showed the error and then recovered once the connection
  was restored.

## 2026-07-11 (3)
- Add music mode: WASAPI loopback capture of system audio
  (`src/audio/loopback.py`), FFT band-energy brightness with
  attack/release smoothing, and spectral-flux onset detection for hard
  colour jumps (`src/audio/analysis.py`), tied together in
  `src/modes/music_mode.py`. Bulb commands are rate-capped independent
  of audio block rate.
- GUI: "Music Mode" button hides all manual controls except a single
  "Exit Music Mode" button while active.
- Verified live: real loopback capture of a played test signal,
  confirmed hue jumps on onsets and brightness tracking loudness on the
  real test bulb; initial dB-based brightness normalization design was
  wrong (self-referential AGC snapped to near-max on any sound) and was
  replaced with a fixed, documented-as-tunable dB calibration before
  this was caught by a unit test comparing quiet vs. loud signals.

## 2026-07-11 (2)
- Replace the static `local_config.py` with a GUI-driven device config:
  first start asks for device ID/IP/local key if none is registered
  yet, "Change device" button to re-enter them, values persisted to
  gitignored `device_config.json` next to the app.
- Power switch now reflects the bulb's actual on/off state on connect
  instead of always starting deselected.
- README: added a short, honest note that the project is built with
  AI pair-programming assistance.

## 2026-07-11
- Phase 2 GUI: brightness slider and colour-palette swatches wired live
  to the bulb (no apply button), debounced slider input, power toggle.
- `TuyaBulb` hardened: socket timeout, retry on transient failures, and
  `TuyaConnectionError` for unreachable/misbehaving devices; GUI calls
  now run off the Tk main thread and show connection errors instead of
  crashing.
- Fix README venv activation command for PowerShell (`Activate.ps1`
  instead of the extensionless `activate`, which PowerShell won't
  resolve) — cause of a `ModuleNotFoundError: customtkinter` when
  running `python -m src.main` outside the venv.

## 2026-07-10
- Initial project skeleton: folder structure, `TuyaBulb` wrapper around
  tinytuya (DP schema for the Meka A60-RGBCW model), minimal
  customtkinter GUI with on/off control, licensing stub, and a
  `local_config.py` template for test device credentials.
