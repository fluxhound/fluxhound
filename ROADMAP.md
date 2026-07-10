# Roadmap

## Done
- Project skeleton (`src/gui`, `src/tuya`, `src/modes`, `src/licensing`)
- `TuyaBulb` wrapper: on/off, white mode, colour mode, timeout + retry
- Phase 2 GUI: power toggle, live brightness slider, colour palette,
  all wired directly to the bulb (no apply button)
- Basic error handling: unreachable/misbehaving bulb shows a status
  message in the GUI instead of crashing; calls run off the UI thread
- License check stub (`src/licensing/license_check.py`)

## Open
- Colour wheel (continuous HSV picker) instead of a fixed palette
- Colour temperature control in the GUI (DP 23 is wired in the wrapper
  but not exposed yet)
- Screen ambient mode
- Screen region alarm mode
- Real Lemon Squeezy license validation
- PyInstaller build config (`.spec`)
- Device discovery / multi-device support
