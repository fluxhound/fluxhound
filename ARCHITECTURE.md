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
- **Colour** is fixed and user-chosen, not audio-driven: the colour
  palette and a "White" button stay visible in music mode so you can
  pick what colour the brightness pulses in; `MusicMode.set_colour`/
  `set_white` update the running session without restarting it.
- The bulb only accepts commands so fast; sends are capped at ~6-7/second
  (`SEND_INTERVAL_SECONDS` in `src/modes/music_mode.py`), and only one
  DP write happens per update (`set_colour_data_value`/
  `set_brightness_value` — no work_mode write unless the white/colour
  choice actually changed). Music mode uses its own `TuyaBulb` instance
  with `retry_attempts=1` and a short timeout instead of the default
  multi-attempt retry, so one bad cycle fails in ~1.5s instead of
  stalling for several seconds.

  This wasn't just precautionary: an earlier version wrote two DPs per
  update (work_mode + value) through the default 2-attempt/1s-delay
  retry, which is up to ~14s per update on failure. That was enough
  sustained command traffic to overwhelm the bulb's WiFi firmware in
  practice — it stopped responding for a stretch, and the background
  thread's `stop()` (2s join timeout) wasn't long enough to reliably
  terminate it either, so leaving music mode looked like it "fixed" the
  freeze by coincidence rather than by actually stopping anything. Fixed
  by cutting redundant writes, failing fast, and a longer join timeout.

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

`status()` has been observed live returning a **partial** dps dict (e.g.
just `{'22': 10}` instead of the full set) on some polls. Don't assume
a missing key means the DP is unset/off — only act on a DP that's
actually present in the response (see `MainWindow._on_initial_status`).

Manual mode exposes a "Temperature" slider (0-1000) alongside
brightness, wired to `TuyaBulb.set_temperature` (switches to white mode
and writes DP 23). Which end reads as warm vs. cool hasn't been
verified against the physical bulb yet.

## Coding Conventions
- Files/modules, variables, functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- "Private" (convention only): leading underscore `_helper()`
- Docstrings for all public functions/classes
- Code, comments, docstrings, commit messages: English only
