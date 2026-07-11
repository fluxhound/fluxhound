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

## Open
- Music mode brightness calibration is tuned against one synthesized
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
