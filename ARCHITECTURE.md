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
- **Brightness** watches only the bass band (40-150 Hz — kick drum and
  bassline fundamental range) of the FFT magnitude spectrum, mapped
  from a fixed dB range onto the bulb's 10-1000 brightness scale, with
  light attack/release smoothing tuned to stay punchy on individual
  bass hits rather than fading them out (`src/audio/analysis.py`,
  `AudioEnvelope`). Calibrated by playing and re-capturing a
  synthesized, realistically-mixed track (kick/bass/snare/hihat/pad at
  typical relative levels) through real WASAPI loopback, not a single
  pure tone — an earlier tone-based calibration read isolated sine
  waves as far louder than the same frequency range is in a real mix,
  so bass barely moved brightness in practice. See the module docstring
  for the measured numbers behind `DB_FLOOR`/`DB_CEIL`. Still just one
  synthesized track, not a broad library of real songs — adjust by ear
  if a given genre reads too dim or too maxed-out.
- **Colour** is fixed and user-chosen, not audio-driven: the colour
  palette and a "White" button stay visible in music mode so you can
  pick what colour the brightness pulses in; `MusicMode.set_colour`/
  `set_white` update the running session without restarting it.
- The bulb only accepts commands so fast; sends are capped at ~6-7/second
  (`SEND_INTERVAL_SECONDS` in `src/modes/music_mode.py`), and only one
  DP write happens per update (`set_colour_data_value`/
  `set_brightness_value` — no work_mode write unless the white/colour
  choice actually changed). Music mode uses its own `TuyaBulb` instance
  with `retry_attempts=1`, a short timeout, and `persistent=True`
  (`TuyaBulb.close()` releases it when the mode stops) instead of the
  default multi-attempt-retry, non-persistent setup used for one-off
  manual commands.

  This went through two rounds of live debugging, not one:
  1. An earlier version wrote two DPs per update (work_mode + value)
     through the default 2-attempt/1s-delay retry — up to ~14s per
     update on failure. That was enough sustained command traffic to
     overwhelm the bulb's WiFi firmware; it stopped responding for a
     stretch, and the background thread's `stop()` (2s join timeout)
     wasn't long enough to reliably terminate it either, so leaving
     music mode looked like it "fixed" the freeze by coincidence.
     Fixed by cutting the redundant DP write and failing fast
     (`retry_attempts=1`, short timeout) instead of retrying for
     several seconds.
  2. Failing fast stopped the multi-second freezes, but errors kept
     recurring: every send was still doing a full TCP connect +
     handshake + close, and that per-command overhead alone was
     enough to intermittently overwhelm the firmware — visible both
     as `"unexpected response: None"` errors and as visibly jerky
     brightness (a send silently dropped mid-cycle is a skipped
     update, which reads as a jump). Fixed with `persistent=True`: one
     connection stays open for the whole session instead of being
     rebuilt every ~150ms. A 22-second stress test with continuous
     bass afterward produced zero errors.

  Brightness smoothing (`BRIGHTNESS_ATTACK_SECONDS`/
  `BRIGHTNESS_RELEASE_SECONDS` in `src/audio/analysis.py`) was also
  retuned in the same pass: the original 0.03s attack fully settles
  well within one ~0.15s send interval, so the value actually sent was
  close to a single raw, unsmoothed audio block each time — a second,
  independent source of the jerky look, on top of the dropped-send
  issue above. Raised to 0.08s attack / 0.25s release so consecutive
  sent values are correlated instead of each being close to an
  independent instantaneous sample, while staying fast enough that a
  hit still reads as punchy rather than a fade.

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
