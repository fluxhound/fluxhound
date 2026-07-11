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
- Music mode: WASAPI loopback capture, FFT-driven brightness, spectral-
  flux onset detection for hard colour changes, smoothed and rate-capped
  (`src/audio/`, `src/modes/music_mode.py`)

## Open
- Music mode brightness calibration (`DB_FLOOR`/`DB_CEIL` in
  `src/audio/analysis.py`) is tuned against synthetic test signals, not
  real songs — needs a real-world listening pass
- Colour wheel (continuous HSV picker) instead of a fixed palette
- Colour temperature control in the GUI (DP 23 is wired in the wrapper
  but not exposed yet)
- Screen ambient mode
- Screen region alarm mode
- Real Lemon Squeezy license validation
- PyInstaller build config (`.spec`)
- Device discovery / multi-device support
