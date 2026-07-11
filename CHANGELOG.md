# Changelog

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
