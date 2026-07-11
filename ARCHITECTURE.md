# FluxHound — Architecture

Technical reference for the project structure, hardware protocol, and
coding conventions used in this repository.

## Tech Stack
- Python 3.x
- GUI: customtkinter
- Tuya communication: tinytuya (local protocol, version 3.3)
- Audio (music mode): soundcard (WASAPI loopback capture) + numpy (FFT)
- Build: PyInstaller → portable .exe
- License validation: Lemon Squeezy API

## Directory Structure
```
fluxhound/
├── README.md
├── ARCHITECTURE.md         # this file
├── CHANGELOG.md
├── ROADMAP.md
├── LICENSE
├── requirements.txt
├── src/
│   ├── main.py             # entry point
│   ├── device_config.py     # load/save the configured bulb's connection details
│   ├── gui/                 # customtkinter GUI components
│   │   ├── main_window.py
│   │   └── device_config_dialog.py
│   ├── tuya/                 # device communication (tinytuya wrapper)
│   ├── audio/                 # system-audio loopback capture + FFT/onset analysis
│   │   ├── loopback.py
│   │   └── analysis.py
│   ├── modes/                # manual, music-reactive, screen ambient, etc.
│   │   └── music_mode.py
│   └── licensing/            # license check module
└── tests/
```
(Structure evolves as code is written.)

## Music Mode
Reacts to whatever the system is currently playing, captured via WASAPI
loopback (no microphone, no source-app integration needed). Runs on a
dedicated background thread while active; the status area (connected /
error) stays visible and live, same as in manual mode.
- **Brightness** watches only the bass band (20-200 Hz) of the FFT
  magnitude spectrum, mapped from a fixed dB range onto the bulb's
  10-1000 brightness scale, with light attack/release smoothing tuned
  to stay punchy on individual bass hits rather than fading them out
  (`src/audio/analysis.py`, `AudioEnvelope`). `DB_FLOOR`/`DB_CEIL` are a
  calibrated starting point, not tuned against a broad library of real
  music — adjust by ear if it reads too dim or too maxed-out.
- **Colour** tracks the spectrum's centroid (its "center of mass"
  frequency — low for bass-heavy sound, high for bright/trebly sound),
  mapped log-scale onto a warm-to-cool hue range and smoothed, so it
  drifts continuously with the sound's timbre instead of jumping hard
  on a trigger. `CENTROID_MIN_HZ`/`CENTROID_MAX_HZ` are similarly a
  starting-point calibration.
- The bulb only accepts commands so fast; sends are capped at ~8/second
  (`SEND_INTERVAL_SECONDS` in `src/modes/music_mode.py`) regardless of
  audio block rate.
- Runs entirely in Tuya colour mode: brightness rides the HSV "value"
  component of `colour_data` (DP 24) so one write updates both
  brightness and hue instead of switching work_mode back and forth.

## Device Configuration
Bulb connection details (device ID, IP address, local key) are entered
through the GUI, not hardcoded. They're persisted to `device_config.json`
next to the running app (`src/device_config.py`) — gitignored, never
committed. On startup the app checks whether a device is already
registered; if not, it asks for the three values directly. A "Change
device" button lets you re-enter them at any time.

## Tuya Devices — DP Schema (Meka A60-RGBCW model)
- DP 20 = switch (bool)
- DP 21 = work_mode ("white" / "colour")
- DP 22 = bright_value (10–1000, white mode only)
- DP 23 = temp_value
- DP 24 = colour_data (hex string, e.g. `"00ec03e803e8"` = h/s/v, each
  4-digit hex — a plain hex string, not a JSON dict)
- Protocol version: 3.3

Device credentials (IPs, device IDs, local keys) are never stored in
this repository — see "Device Configuration" above.

## Coding Conventions
- Files/modules, variables, functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- "Private" (convention only): leading underscore `_helper()`
- Docstrings for all public functions/classes
- Code, comments, docstrings, commit messages: English only
