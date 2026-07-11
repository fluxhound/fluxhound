# Changelog

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
