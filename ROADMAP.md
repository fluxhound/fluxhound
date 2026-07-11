# Roadmap

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

## Open
- Audio Mode's Energy calibration is tuned against one synthesized
  track, not a broad library of real songs — a real-world listening
  pass across genres may still need adjustment
- Verify which end of the temperature slider (0 vs. 1000) actually
  reads as warm vs. cool on the physical bulb
- Colour wheel (continuous HSV picker) instead of a fixed palette
- Screen ambient mode
- Screen region alarm mode
- Real Lemon Squeezy license validation
- PyInstaller build config (`.spec`)
- Device discovery / multi-device support
