# Roadmap

**Status (2026-07-14): licensing, packaging, and a visual design pass
are all done. This build (`dist/FluxHound.exe`) is meant for a private
friends-and-family test round, not a public release** - see "Known
limitations for this test round" under Open below before sending it
further than that.

## Done
- Project skeleton (`src/gui`, `src/tuya`, `src/modes`, `src/licensing`)
- `TuyaBulb` wrapper: on/off, white mode, colour mode, timeout + retry
- Phase 2 GUI: power toggle, live brightness slider, colour palette,
  all wired directly to the bulb (no apply button)
- Basic error handling: unreachable/misbehaving bulb shows a status
  message in the GUI instead of crashing; calls run off the UI thread
- License check stub (`src/licensing/license_check.py`)
- Flexible device configuration: GUI dialog asks for device ID/IP/local
  key on first start, persists to gitignored `device_config.json`,
  "Change device" button to re-enter them later
- Power switch syncs to the bulb's actual on/off state on connect,
  instead of always starting at "off"
- Music mode: WASAPI loopback capture, bass-band FFT-driven brightness
  (punchy attack/release smoothing), user-chosen fixed colour or white
  (palette + White button stay usable in music mode), rate-capped
  single-DP-write sends, status area stays live during the mode
  including error recovery (`src/audio/`, `src/modes/music_mode.py`)
- Fixed a real freeze: music mode's old two-DP-write-per-update design
  with the default retry/timeout could overwhelm the bulb's WiFi
  firmware and stall for up to ~14s per cycle; now uses a dedicated
  fail-fast bulb handle and only writes work_mode when it changes
- Colour temperature control in the GUI (DP 23), a "Temperature" slider
  next to brightness in manual mode
- Fixed a latent bug: `status()` can return a partial dps dict; the
  power switch sync now only acts on DP 20 when it's actually present
  instead of defaulting to "off"
- Re-calibrated music mode brightness: narrowed the band to 40-150 Hz
  and recalibrated `DB_FLOOR`/`DB_CEIL` against a realistically-mixed
  synthesized track played through real loopback (not a single tone) —
  bass previously produced almost no visible brightness reaction with
  real music because the old calibration was tuned against isolated
  sine tones, which read far louder than the same band in a real mix
- Fixed recurring "unexpected response: None" errors and visibly jerky
  brightness in music mode: every send was doing a full TCP
  connect/handshake/close, which alone was enough to intermittently
  overwhelm the bulb's WiFi firmware even after the earlier fail-fast
  fix. Music mode's bulb now keeps one persistent connection open for
  the session (`TuyaBulb(persistent=True)`). Also retuned brightness
  smoothing (attack 0.03s -> 0.08s, release 0.12s -> 0.25s) since the
  old attack time fully settled within one send interval, making the
  sent value close to an unsmoothed single audio block each time
- Fixed the errors that kept happening even with a persistent
  connection: `connection_retry_limit=1` (set to force fast failure)
  turned out to also cap how many extra reads tinytuya waits through
  for a device's routine null-ack-before-real-response — at 1, a
  single slow pair got misreported as `None`. Raised to 2. Also dialed
  brightness smoothing back about halfway (0.055s / 0.185s) after a
  report that it had eaten too much visible reaction. Two 50-second
  continuous-bass sessions afterward produced zero errors; a simulated
  unreachable device still fails in ~3s
- Add Music Mode 2 ("Spectrum Mode"): fully autonomous full-spectrum
  light show — continuous spectral-centroid-driven hue, multi-band
  (bass/mid/treble) brightness, saturation "flash" dips on detected
  onsets. Reuses Music Mode's reliability setup (persistent connection,
  fail-fast retry, one DP write per update) via a shared bulb-builder,
  and its own dedicated button + the existing "Exit Music Mode" button
  (`src/audio/spectrum_show.py`, `src/modes/spectrum_mode.py`)
- Fixed dropouts that persisted in both reactive modes even after the
  persistent-connection/retry-limit fixes, found by comparing against
  a working reference script that drives 3 bulbs without the issue.
  Root cause: waiting for and parsing a response on every send is
  still too much round-trip overhead for the bulb's WiFi firmware
  under sustained traffic, regardless of retry settings — confirmed by
  the fact the reference script sends *faster* (60ms vs. 150ms) but
  never waits for a response at all. Switched both modes' hot-loop
  sends to tinytuya's `nowait=True` (`TuyaBulb.*_nowait`), which still
  detects a genuinely failed connection but skips the receive/retry
  cycle for a successful write. Verified live: two 100-second sessions
  (one per mode) with continuous varied audio produced zero errors
- Add Music Mode 3 ("Custom Mode"): makes Music Mode 2's concept user-
  remixable — a 3x3 grid lets the user assign each of Hue/Brightness/
  Saturation to one of three sources (Timbre = spectral centroid,
  Energy = weighted bass/mid/treble, Beat = onset flash), enforced as
  a strict bijection (grayed out elsewhere once assigned). Defaults to
  Music Mode 2's original mapping; assignment persists across mode
  switches and applies live while running
  (`src/audio/custom_show.py`, `src/modes/custom_mode.py`)
- Fixed reactive modes jumping to hardcoded defaults (colour/red) on
  entry regardless of the bulb's actual state (e.g. white/50%/80%),
  and not restoring it on exit. All three reactive modes now seed
  their starting hue/saturation/brightness (and, for Music Mode,
  work_mode) from a `bulb.status()` snapshot taken right before
  starting, and `MainWindow` explicitly restores that exact snapshot
  (including the brightness/temperature slider positions) when exiting
  back to manual control
- Consolidated Music Mode 1/2/3 into a single "Audio Mode": removed the
  separate manual-colour-choice mode and the fixed-mapping mode
  (`src/modes/music_mode.py`, `src/modes/spectrum_mode.py`,
  `src/audio/analysis.py`, `src/audio/spectrum_show.py` all deleted),
  keeping only the configurable one and putting it permanently on the
  main page instead of behind a mode-switch screen. Added: a per-
  source sensitivity slider (0-100, exponential curve centred on the
  calibrated default) for each grid row; manually touching a property
  (palette pick, brightness slider, or the temperature slider now
  dual-purpose as saturation in colour mode) hands that one property
  back to manual control by deactivating its assignment, without
  stopping Audio Mode for the rest; a "Set to Default" button; and
  disk persistence for the assignment and sensitivity
  (`src/audio_mode_config.py`), so they now survive app restarts, not
  just mode switches within a session
- White circle added to the palette row: it's now the only control that
  switches `work_mode` to white. Brightness (and the existing
  temperature/saturation dual-purpose slider) now stay within whichever
  mode is already active instead of brightness silently forcing white
  mode. Added a custom-colour circle on the other end that opens a
  non-modal, freely-movable colour-picker window (click-drag on a
  saturation/value gradient + hue slider, or type an exact HEX/RGB
  value), showing a rainbow indicator until first use and persisting
  the picked colour across mode switches and restarts
  (`custom_colour_config.json`). Replaced the inline "Change device"
  button with a small gear-icon button in the corner, and added a
  "FLUXHOUND" title plus a live colour/brightness indicator rectangle
  to the header
- Multi-device support: any number of bulbs can now be configured, each
  with a locally-editable display name (never written back to the
  device), and grouped so several bulbs take the same command at once.
  A dropdown below the live-state rectangle picks the current target
  (one device or one group); the gear button now opens a small Settings
  menu whose "Devices" entry opens the device/group manager
  (`src/devices_config.py`, `src/gui/settings_window.py`,
  `src/gui/devices_window.py`). The previous single-device
  `device_config.json` is migrated in automatically as the first device
  on first run
- Merged groups: a group's members can each be assigned a position
  (BASE, EXT-1, EXT-2, ...) via a dropdown in the Devices window, and a
  "Merge" button (enabled once at least BASE and EXT-1 are assigned)
  turns the group into one virtual lamp - a single hue/brightness/
  saturation value gets divided positionally across the positioned
  members (BASE first) instead of mirrored to everyone, per-property via
  three checkboxes (default on) that appear in the Audio Mode grid
  whenever a merged group is the active target. Works for both manual
  control and Audio Mode's reactive show
  (`src/tuya/device.py`'s `split_value_across_bulbs`,
  `src/modes/custom_mode.py`, `src/gui/devices_window.py`)
- Logo overlay: the live-state indicator is now a radial glow (the
  bulb's current colour at the centre, fading to the app's background
  colour at the edges) with `fluxhound_logo.png` composited on top,
  its own soft transparency blending naturally into the glow beneath
  it - real alpha compositing via Tk's `PhotoImage`/`Canvas`, no PIL
  dependency (`MainWindow._render_radial_glow`, `_load_logo`)
- Ambience Mode: a second reactive mode (mutually exclusive with Audio
  Mode) that continuously matches the active target to the screen's
  dominant colour and brightness, captured via `mss`. Deliberately
  discounts low-saturation "boring" pixels (text, UI chrome, plain
  backgrounds) so a comparatively small vivid area still produces a
  clearly visible, mood-appropriate colour instead of being averaged
  into grey; picks one dominant hue via a saturation-weighted histogram
  rather than a flat average, so mixed distinct colours don't blur into
  a muddy blend nothing on screen actually shows
  (`src/screen/capture.py`, `src/screen/ambience_show.py`,
  `src/modes/ambience_mode.py`)
- Ambience Mode monitor + region selection: a dropdown picks which
  monitor gets watched (persisted, with automatic fallback if a
  monitor's since been unplugged), and a "Set area" button opens a
  drag-to-select overlay to watch just one rectangle of it instead of
  the whole screen - "Delete area" reverts to the whole monitor. A
  preview box shaped to the monitor's aspect ratio shows a snapshot
  with the selected region marked. Required making the app per-monitor
  DPI aware (`src/main.py`) so the overlay's drawn rectangle lines up
  exactly with what mss actually captures on a scaled display
  (`src/ambience_config.py`, `src/gui/region_selector_window.py`)
- Gaming Mode: a checkbox that repurposes the "Set area" region as a
  health/resource-bar (or Diablo-style orb) watcher instead of an
  ambient-colour region - ambient goes back to watching the whole
  monitor, and the region gets scanned via a colour-ratio fill
  estimate (no OCR) that briefly flashes the bulb red/green on a
  meaningful decrease/increase, or holds a continuous red glow below
  10% - all overriding the ambient reading for as long as they're
  active (`src/screen/health_bar.py`, `src/modes/ambience_mode.py`)
- Confirmed which end of the temperature slider reads as warm vs. cool
  on the physical bulb: 0 (left) is warm, 1000 (right) is cool -
  matches what the live-state indicator's gradient already assumed;
  updated the code comment and ARCHITECTURE.md from "unverified
  decorative approximation" to confirmed
- Device discovery: "Scan local network" (UDP broadcast, no cloud)
  fills in Device ID and IP Address from whatever Tuya devices respond;
  the local key still can't come from there (Tuya never broadcasts it),
  so a manual-vs-Tuya-Cloud choice was added for that one field - typed
  by hand as before, or fetched via the user's own Tuya IoT developer
  account credentials, the only place this app ever talks to Tuya's
  cloud and only when explicitly opted into
  (`src/tuya/discovery.py`, `src/tuya/cloud_discovery.py`,
  `src/tuya_cloud_config.py`)
- Multi-region screen analysis: a "Multi-region mode" checkbox
  (mutually exclusive with Gaming Mode) lets a merged group's
  positioned bulbs (BASE, EXT-1, EXT-2, ...) each watch their own
  screen region instead of sharing one reading - a position dropdown
  plus its own "Set area"/"Delete area" button assigns a region per
  position, and the preview marks all of them at once, each labelled.
  `AmbienceMode`'s send path was unified around a per-bulb reading list
  so normal/Gaming/Multi-region modes all share one send method; bulbs
  sharing a region share one capture, and any bulb without an assigned
  region falls back to the whole-monitor reading
  (`src/ambience_config.py`, `src/modes/ambience_mode.py`,
  `MainWindow._build_bulb_regions`)
- Fixed a real bug: deactivating Audio Mode or Ambience Mode left the
  bulb(s) stuck on whatever colour the mode had last shown instead of
  restoring the manual state from before it started. Root cause:
  `_begin_reactive_mode` pointed the "restore to this" snapshot and the
  live-tracking snapshot at the *same* object, so the mode's continuous
  live-indicator updates silently overwrote the restore target too -
  by deactivation time it just matched the mode's own last output.
  Fixed by giving `self._current_state` an independent copy
  (`dataclasses.replace`); confirmed live for both a white-mode and a
  colour-mode baseline against the real 3-bulb group
- Removed "Screen region alarm mode" from Open: its one concrete use
  case (alarm on a watched region's fill level dropping/rising) is
  already exactly what Gaming Mode does - a separate, more general
  "alarm on arbitrary region change" feature would be speculative
  without a specific need driving it
- Fixed a real bug: "Scan local network" only ever reliably found one
  device on a network with three real bulbs. `tinytuya.deviceScan`'s
  `maxretry` argument isn't a retry count despite the name - it's
  actually the scan's *listening duration in seconds*, and the
  original code passed `2` on the wrong assumption, cutting the real
  window down to ~2 seconds - far too short for every device to get a
  chance to broadcast. Fixed by defaulting to tinytuya's own
  recommended 18-second window (`DEFAULT_SCAN_SECONDS`); confirmed
  live that a scan now finds all three known bulbs in one pass
  (`src/tuya/discovery.py`)
- Custom Trigger Editor (paid-tier groundwork for the licensing/
  packaging finalization phase): Gaming Mode's fixed-constant behaviour
  was generalized into a `TriggerConfig`/`ThresholdBand` pair, with the
  original constants as its defaults so the built-in watcher is
  unchanged. Any number of extra watchers (own region + own
  thresholds/flash colours/multi-step glow bands) can now run alongside
  the built-in one via a new "Custom Trigger Editor..." window; the
  first watcher with an active override wins each tick, built-in first.
  Verified live against the real 3-bulb group: a custom watcher's own
  thresholds/colours fired correctly and independently of the built-in
  one's fixed defaults, and priority ordering held when both fired at
  once (`src/screen/health_bar.py`, `src/ambience_config.py`,
  `src/modes/ambience_mode.py`, `src/gui/trigger_editor_window.py`)
- Licensing: free vs. paid tier gating, and real Lemon Squeezy license
  validation (finalization phase, private friends-and-family test
  round). Free tier: 1 device, Manual Control, Ambience Mode, Gaming
  Mode with its built-in watcher - fully functional, no throttling.
  Paid (a valid license key): unlimited devices/groups/Merged Groups,
  Audio Mode, Multi-region Mode, the Custom Trigger Editor. All gating
  routes through one central module (`src/licensing/gate.py`) rather
  than being scattered across mode files; every gated action shows a
  non-dead-end `UpsellDialog` explaining what unlocking adds. Real
  Lemon Squeezy License API integration (`src/licensing/license_check.py`,
  `POST /v1/licenses/activate`) replaces the always-true stub; the
  unlocked state is cached locally (`src/license_config.py`) so
  `is_licensed()` never makes a network call, satisfying "don't hard-
  require network access on every app start" by construction. No real
  Lemon Squeezy store/product exists yet, so the success path is unit-
  tested with the network call mocked; the rejected-key path was
  additionally confirmed against the real, live API. Verified live
  against the real 3-bulb group in both the free (blocked + upsell
  shown, underlying state unchanged) and a locally-seeded-unlocked
  (allowed) state
- PyInstaller packaging: `fluxhound.spec` builds a single portable
  `FluxHound.exe` (`console=False`, unsigned). The logo is deliberately
  not bundled as a PyInstaller data file - it's copied into `dist/`
  alongside the exe instead, since `_app_root_dir()` already resolves
  paths relative to `sys.executable` (the exe's own directory) when
  frozen, not PyInstaller's temp extraction dir. Almost no manual
  hidden-import configuration was needed (`pyinstaller-hooks-contrib`
  already covers customtkinter/soundcard/etc.). Smoke-tested by running
  the built exe from an isolated directory with no `.venv`/source tree
  on the path - window opens correctly, theme and logo render, its own
  config file gets created next to it (confirming frozen-path
  resolution), and a nested dialog (Configure device, including the
  network-scan UI) opens and renders correctly too. README documents
  the build command and warns that Windows SmartScreen will flag the
  unsigned binary (expected, not a bug)
- Visual design pass (no functional changes - every existing capability
  works exactly as before, see the live functional regression check
  below): a single vivid pink/magenta brand accent applied globally via
  a customtkinter colour theme (`src/gui/theme.py`/`theme.json`) instead
  of ad hoc colours per window; a generated app icon (`fluxhound.ico`,
  no PIL) wired into every window's title bar, the taskbar, and the
  built exe's own resources; the main window's single long scrolling
  column reorganized into a persistent header + Manual/Audio/Ambience
  tabs (every widget kept its exact attribute name, so existing event
  handlers needed no changes); explicit icon/colour treatment for
  error/loading/steady status states plus an animated loading indicator
  instead of plain text; a guided empty state ("No devices yet" + an
  Add Device button) instead of a blank screen when nothing's
  configured yet; a small "PRO" badge next to every paid-tier control.
  Verified at 100/125/150% simulated DPI scaling (customtkinter's own
  scaling API, not the real Windows display setting) with no cropping
  on any tab, and with a real Ambience Mode activate/deactivate cycle
  through the new layout confirming actual bulb commands still go out
  correctly. Known limitation, flagged rather than approximated: the
  source logo's fine line-art detail doesn't survive small-size
  (16-48px) icon downscaling legibly - a proper small-size mark needs
  real design work, not something derivable from the existing source
  art
- Fixed a real regression from the design pass: the gear/Settings
  button disappeared, covered by the new header/tabview stacking above
  it (creation order changed during the restructure, breaking an
  invariant the original code depended on) - moved back to the end of
  `__init__`
- Removed the Tuya Cloud local_key automation added under "Device
  discovery" above (`src/tuya/cloud_discovery.py`,
  `src/tuya_cloud_config.py`, deleted along with their tests): a real
  bug (correct credentials still produced a wrong "no local key found"
  error) plus, separately, not wanting the user's Tuya API key/secret
  sitting in a plaintext local file for what was only ever a
  convenience layered on an otherwise fully local-only app. Local UDP
  scan + manual local-key entry is the only path now
- System tray: closing the main window now hides it to a tray icon
  instead of quitting (`src/gui/tray.py`, pywin32's `Shell_NotifyIcon`/
  `LoadImage` directly - no `pystray`, to avoid a transitive PIL
  dependency); "Show FluxHound" or a left click restores it, "Quit"
  from the tray menu is the only real exit now. Falls back to a real
  quit if the tray icon isn't available so the window can't get
  stranded. Added a "Start with Windows" checkbox in Settings
  (`src/autostart.py`, a `winreg`-based per-user Run key toggle, no
  admin rights needed)
- Ambience Mode: two new Ambience-tab sliders, "Colour sensitivity" and
  "Smoothing" (both 0-100, 50 = today's fixed behaviour, unchanged
  unless touched), after live use during a film showed the game-tuned
  defaults picking colours too aggressively bold/detached from a
  scene's actual mood, and transitioning between them too abruptly.
  Live-adjustable while Ambience Mode is running (the point is tuning
  by eye/feel while actually watching something), persisted in
  `ambience_config.json`
- Audio Mode: a `--debug` CLI flag logs every audio block's raw
  timbre/energy/beat signal (plus the pre-sensitivity readings behind
  them - raw centroid Hz, pre-gain energy, flux/onset threshold) to a
  timestamped CSV, to support a calibration pass against real music
  instead of just the one synthesized track the original calibration
  used
- Fixed a real reactivity problem reported after the first --debug
  test round: at a lower overall playback volume, Energy read as
  noticeably flatter/less reactive even with the song's own loud/quiet
  dynamics unchanged. Root cause: BANDS' db_floor/db_ceil were fixed,
  absolute dB thresholds from one reference volume - a synthetic test
  confirmed a uniformly quieter signal clipped the quiet half of every
  cycle to a flat 0.0 under the old formula. Fixed with per-band
  auto-leveling (`CustomShowEnvelope._update_adaptive_range`): floor/
  ceiling now track the recently observed dB range live (fast attack
  toward a new extreme, slow release otherwise), seeded from the same
  fixed constants so behaviour at the original reference volume is
  unchanged. Timbre and Beat were checked and don't have this problem -
  both already cancel out a uniform volume change mathematically
- Raised `BEAT_BASE_THRESHOLD_MULTIPLIER` 1.8 → 2.2: the same test
  round's logs showed onset gaps clustering against the 0.15s minimum
  interval during dense passages (13-24% of onsets landing within
  0.05s of it) - the detector was firing on nearly every eligible
  block. Re-simulated from the already-logged flux data (no new
  capture needed): -21% to -24% fewer onsets, -6 percentage points
  near-floor clustering, on both real sessions. First pass, to
  re-check against the next test round. Deliberately did *not* also
  raise `BANDS`' db_ceil (the other pending suggestion) - the
  auto-leveling fix above already addresses the pinned-at-ceiling
  finding that prompted it, dynamically and more directly; raising the
  static seed on top risks fighting with it for a problem it's meant
  to already solve
- Fixed a real follow-on bug from the auto-leveling fix, surfaced in a
  second real-music --debug round: a gap of true silence (before
  playback starts, between songs) had the floor chasing it all the way
  down to the safety clamp, then Energy read inflated (pinned near/at
  1.0) for 10-30+ seconds once music resumed while the floor slowly
  crawled back up. Fixed with `SILENCE_GATE_DB` (-70dB): a block that
  quiet has nothing real to calibrate against, so floor/ceiling simply
  freeze instead of chasing it. Verified against the exact failing
  scenario (real music, 6s silence, resume) - floor now stays put
  through the gap and Energy returns to normal within a few blocks of
  resuming
- Fixed the Audio tab's per-target sensitivity sliders being clipped
  behind the scrollable frame's scrollbar (a real-use report) - the
  single-row layout (checkbox + label + 3 source buttons + a narrow
  slider) left almost no width margin inside the tab's
  `CTkScrollableFrame`, which only scrolls vertically, so the
  overflowing slider column sat behind the vertical scrollbar rather
  than reflowing. Moved each slider to its own row spanning its 3
  source buttons' width instead of trimming already-tight columns -
  also makes the sliders themselves wider and easier to drag. Live-
  verified via screenshot: comfortable margin before the scrollbar now.
- Fixed a real-use report: Settings' "Minimize to tray on close" was
  only ever static explanatory text, never an actual checkbox - so
  there was no way to turn the behaviour off. Added a real checkbox
  backed by a new `src/app_settings.py`, wired live into
  `MainWindow._on_close` (takes effect on the next close, no restart).
  While testing this, also caught and fixed a real (if harmless) bug
  in `src/gui/tray.py`: the `WM_DESTROY` handler didn't return an
  `int`, which pywin32 surfaced as a `WNDPROC return value cannot be
  converted to LRESULT` error on every real quit
- Brush-based region selection for Gaming Mode/Custom Trigger Editor
  watchers, replacing the plain rectangle drag-select for those (not
  for Ambience Mode's own colour-zone regions, which stay rectangular):
  a real-use report showed a rectangle can't isolate a curved/oddly-
  shaped bar (e.g. Grounded's bent HUD health bar) from its
  surroundings. `BrushSelectorWindow` paints a freeform mask over the
  same semi-transparent click-through overlay `RegionSelectorWindow`
  already used; the tight bounding box of the painted pixels becomes
  the region's `(x, y, width, height)` as before, plus a new optional
  `mask` (packed/base64, `AmbienceRegion.mask`) that every fill-
  measuring function now respects (`None` reproduces prior whole-
  rectangle behaviour exactly)
  (`src/gui/brush_selector_window.py`, `src/screen/health_bar.py`,
  `src/ambience_config.py`)
- OCR-based detection for Custom Trigger Editor watchers (paid-tier),
  for health/mana displays shown as text/digits rather than a fillable
  bar - a colour-ratio fill measurement has nothing to read there.
  `TriggerConfig.detection_mode` picks "fill_fraction" (default,
  unchanged) or "ocr"; `rapidocr_onnxruntime` was chosen over
  `pytesseract` (no pip-only Tesseract install) and Windows' native OCR
  (untested PyInstaller/COM packaging risk) for its pip-only install
  and portability, following through on this project's discussion with
  the user of the size/dependency tradeoffs involved. Runs on its own
  throttled (`OCR_POLL_INTERVAL_SECONDS`) background thread per watcher
  rather than blocking the capture loop, since a single reading takes
  far longer than one capture tick. Required a real PyInstaller
  packaging fix (`hiddenimports` + a runtime hook,
  `pyinstaller_rthook_rapidocr.py`) for a dynamic bare-name import
  `rapidocr` itself does that only works unfrozen. A plausible-seeming
  "full resolution helps OCR" capture change was tried, proven wrong by
  repeated live testing, and reverted rather than kept on theory alone
  (`src/screen/ocr_reader.py`, `src/screen/health_bar.py`,
  `src/gui/trigger_editor_window.py`)
- Fixed a real-use report of the lamp flashing wildly with an OCR watcher
  running: the painted brush mask never actually reached OCR - only
  `fill_fraction` honoured it, so a mask painted around just the digits to
  exclude nearby HUD clutter had zero real effect. Fixed with
  `_mask_frame_for_ocr` (`src/screen/health_bar.py`), blanking everything
  outside the mask before the frame reaches OCR. Live-tested against the
  real `rapidocr` engine with a synthetically noisy background - stable in
  that particular test, though not proven to fully explain the reported
  flicker on its own (see Open below)
- Hardened `ocr_reader.parse_fraction`'s format auto-detection: verified
  against a battery of realistic combined-format strings (ratio+redundant-
  percent, percent-before-ratio, two ratios in one text) that the existing
  ratio > percent > bare-number priority already handles them correctly,
  and added a genuinely missing 4th pattern - a bare decimal between 0 and
  1 (e.g. "0.79") is now recognized as already a complete reading, for
  HUDs/mods that show a raw progress value with no ratio or percent sign
  attached. Its integer part is restricted to exactly 0 or 1 so it can't
  accidentally misread a garbled ratio's tail as a fraction
- Added OCR `--debug` logging (`AmbienceMode.debug_log_path`, an
  `ocr_debug_<timestamp>.csv` alongside Audio Mode's existing calibration
  log) to troubleshoot a real-use report of continued wild flashing - one
  row per OCR read attempt per watcher, raw recognized text plus the
  parsed fraction, so a misread shows up directly in the data
- Found and fixed the actual bug the debug log revealed: a watcher's
  painted mask is encoded at its region's own un-downsampled resolution,
  but `ScreenCapture` downsamples any region wider than ~160px - so the
  mask silently stopped matching the actual captured frame's shape for any
  such region, raising an `IndexError` on every OCR attempt that
  `_run_ocr`'s broad exception handler swallowed completely (a watcher
  that silently never worked, not a visible crash). Same root cause
  affects `fill_fraction` mode's masking too (no such guard there, so it
  would crash visibly instead). Fixed with `_match_mask_to_frame`/
  `_resize_mask_nearest` (`src/screen/health_bar.py`) resizing the mask to
  the frame's actual shape before either detection mode indexes with it -
  deliberately leaves `ScreenCapture`'s own downsampling untouched, since
  disabling that was already tried and proven worse for OCR accuracy.
  Live-verified against the real `rapidocr` engine on a region wider than
  the downsample threshold
- Made colour-bar/printed-number auto-detection a free-tier capability:
  `TriggerConfig.detection_mode` now defaults to a new `"auto"` (both
  fill_fraction and OCR run in parallel, whichever is actually working for
  the region wins) instead of `"fill_fraction"` - both the built-in Gaming
  Mode watcher and any new custom watcher get it. Prompted by real testing
  against a text-only HUD (Half-Life's transparent health number, no bar)
  showing the built-in watcher's old fixed fill_fraction detection
  genuinely can't work there. What stays paid-exclusive: watching more than
  one region, and configuring the reaction - not which detection is
  available. Includes a give-up mechanism (`AUTO_DETECTION_MAX_OCR_
  ATTEMPTS_WITHOUT_SUCCESS`) so a genuine colour bar doesn't pay for a real
  OCR inference every second forever, and a freshness window
  (`AUTO_DETECTION_OCR_FRESHNESS_SECONDS`) so a working OCR reading isn't
  abandoned on one missed poll. `ocr_max_value` now defaults to 100 so a
  bare-number display works out of the box on the free tier. Detection
  dropdown in the Trigger Editor gained a third "Auto (recommended)"
  option. Live-verified end to end: both a custom watcher and the built-in
  watcher (with no custom watchers at all) correctly auto-detected and read
  a real OCR value in a live `AmbienceMode` session
- Raised the auto-detection give-up threshold 10 → 30 attempts (~10s →
  ~30s), after a real `--debug` session showed OCR needing 11 attempts to
  first succeed against one real game's HUD font - a correctly, tightly
  painted (screenshot-confirmed) region was giving up right as OCR was
  about to start working, permanently stranding it on chaotic fill_fraction
- Fixed both `--debug` CSV logs losing an entire session's data on Ctrl+C:
  Ctrl+C in a console raises `KeyboardInterrupt` straight out of Tcl's
  mainloop callback, uncaught anywhere - the process died before either
  log's file ever got flushed. Both logs now flush after every row, and
  `main()` catches the KeyboardInterrupt and calls the app's real
  shutdown path (same one the tray icon's "Quit" uses), instead of the
  whole app dying abruptly mid-session
- Fixed a follow-on `RuntimeError: main thread is not in main loop`
  traceback the fix above exposed: a reactive mode's background thread can
  still be mid-tick, calling `self.after(...)` to update the GUI, right as
  Ctrl+C stops Tk's event loop from processing. `MainWindow.
  _after_if_running` now wraps every such cross-thread `self.after()` call
  and silently swallows exactly this error, letting the background thread
  notice the stop signal and exit cleanly instead of being cut off
- Added an "Edit" button to the Devices window for updating an already-
  configured device's ID/IP/local key in place, without losing its display
  name or group membership/position - prompted by a real re-pair (needed
  to recover "Stehlampe unten" from an unrelated WiFi problem) rotating
  its local_key, the second time this exact scenario has hit this project.
  `device_id` changing mid-edit is also handled, re-keying group
  membership/position/active-selection to follow it
- Added debug-log images: every OCR attempt's frame per watcher (masked,
  if applicable) is saved as a PNG next to the `--debug` CSV - `_first`
  (kept permanently) and `_latest` (overwritten every attempt), so a "why
  is OCR reading nothing" report can be diagnosed by literally looking at
  what OCR saw, instead of guessing between a misplaced mask/wrong monitor/
  unreadable font. Found and fixed a second shutdown-race traceback while
  live-testing it (an in-flight OCR thread writing to an already-closed
  debug log file) - `HealthBarTracker.join_ocr_thread`, joined before the
  log closes. On first real use, `_first` alone turned out to reliably show
  the FluxHound window/Windows taskbar rather than the game (the first
  attempt fires before the user switches focus back) - `_latest` was added
  right after to show the actual steady state instead
- Fixed auto mode's OCR give-up mechanism permanently stranding a
  perfectly correct watcher: diagnosed via the new debug-log image, a real
  0/19-successful-reads session traced to the watcher being activated
  during a loading screen (correctly nothing to read at that moment) -
  it exhausted its attempts before the level finished loading and then
  never tried again once real gameplay resumed, even though the region/
  mask were correct throughout. Giving up now means a much slower retry
  cadence (once every 30s) instead of stopping outright, so a temporarily-
  obscured watcher (loading screen, cutscene, menu) gets real second
  chances instead of being abandoned for the rest of the session
- Fixed the actual root cause behind the last several "wild flashing"
  reports: OCR reading nothing from a real, fully legible, correctly-
  masked HUD number, at any resolution (tested native through 6x upscale
  directly against the real failing frame). Grayscale + a min-max contrast
  stretch (`ocr_reader._normalize_for_ocr`, applied to every frame before
  OCR) fixed it, reproducibly, with no regression on already-working
  cases - found by testing several preprocessing approaches directly
  against the real frame rather than guessing

## Open
- Audio Mode's Energy calibration is tuned against one synthesized
  track, not a broad library of real songs — a real-world listening
  pass across genres may still need adjustment
- OCR watchers: a real multi-session investigation turned up several
  distinct, now-fixed causes of "wild flashing" (mask/downsample mismatch,
  the give-up threshold being too low then not resuming after giving up,
  the built-in watcher being fill_fraction-only, and finally OCR genuinely
  failing to read a legible, correctly-masked HUD number until grayscale +
  contrast normalization was added) plus one confirmed non-FluxHound cause
  (one lamp intermittently roaming onto a same-SSID WiFi repeater with a
  much weaker signal at its current physical location - not a code issue
  at all). Next step: a clean end-to-end re-test now that every identified
  cause has a fix, to confirm the flashing is actually gone in real
  gameplay rather than assuming the latest fix was the last one needed.
  Still separately unexplained and unconfirmed: bulbs in a merged group
  reacting differently from each other (`_send` dispatches the identical
  colour to every bulb in Gaming Mode, so this isn't a dispatch-logic bug
  as far as the code shows - possibly a downstream WiFi-timing effect of
  frequent spurious overrides, though the WiFi-repeater finding above may
  turn out to fully explain this too)
- **Known limitations for this test round** (surfaced per the
  finalization-phase request to flag anything fragile or rushed,
  rather than let real users hit it first):
  - The License success path (`activate()` against a *real*, valid
    key) has never been live-tested end-to-end - no Lemon Squeezy
    store/product exists yet for FluxHound. Only the rejected-key path
    was confirmed against the real, live API; the success path is
    covered by unit tests with the network call mocked. This needs a
    real store set up and a real test purchase before it can be
    trusted in front of real users.
  - "Remove licence" only clears the local cache - it does not tell
    Lemon Squeezy to release the activation slot server-side. Repeated
    activate/deactivate cycles (e.g. testing on multiple machines)
    could exhaust a real key's activation limit without the server
    ever finding out a slot was freed.
  - Once unlocked, the app trusts the cached state indefinitely - there
    is no periodic re-validation against Lemon Squeezy. A revoked or
    refunded key would keep showing "Licensed" locally forever. This
    was a deliberate, scoped-down choice appropriate for a small
    private test round (see `src/licensing/license_check.py`'s
    docstring) but would need revisiting before a public release.
  - Editing a Custom Trigger Editor watcher while Ambience Mode is
    already running does not restart it live - the watcher list it
    started with keeps running until the next manual Deactivate/
    Activate. Deliberate (avoids a live-restart flickering the bulb
    back to its pre-reactive state and forth again), but worth knowing
    before a tester wonders why their edit "didn't do anything" yet.
  - The PyInstaller smoke test ran on the same machine the app was
    built on (same OS build, same system DLLs already present) - not a
    truly separate clean machine/VM, which this environment doesn't
    have access to. A genuinely different Windows install could still
    surface a missing-dependency issue this test wouldn't catch.
  - `fluxhound.ico`'s 16/32/48px sizes are technically FluxHound's own
    icon (not the generic Python fallback) but not clearly legible as
    "a dog head" - the source logo is detailed line art that doesn't
    survive small-size downscaling. A real, separately designed
    simplified small-size mark would fix this; no amount of further
    scripted resizing of the existing source art will.
