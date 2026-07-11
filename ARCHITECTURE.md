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
│   ├── audio/                 # system-audio loopback capture + FFT analysis
│   │   ├── loopback.py
│   │   ├── analysis.py       # Music Mode: bass-band brightness envelope
│   │   └── spectrum_show.py  # Music Mode 2: full HSV audio-driven show
│   ├── modes/                # manual, music-reactive, screen ambient, etc.
│   │   ├── music_mode.py
│   │   └── spectrum_mode.py
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
     rebuilt every ~150ms.

     Also retuned brightness smoothing in this pass, a second and
     independent source of the jerky look: the original 0.03s attack
     fully settled well within one ~0.15s send interval, so the value
     actually sent was close to a single raw, unsmoothed audio block
     each time. Raised to 0.08s attack / 0.25s release.
  3. Persistent connections stopped the recurring errors, but not all
     of them — the same `connection_retry_limit` used to force fast
     failure in step 1 turned out to gate a second, unrelated thing:
     tinytuya reuses that same counter for how many extra reads it
     waits through when the device sends a null "ack" before its real
     response (routine Tuya behaviour, not a failure). At 1, a single
     slow ack+payload pair was enough to exhaust that budget and come
     back as a bare `None`, misreported as an error even though the
     command had landed. Raised to 2 (not the tinytuya default of 5,
     to keep genuine-failure detection reasonably fast: ~3s instead of
     ~1.5s at 1, or ~4.6s at 3) - fixes the false errors without
     reintroducing a slow failure path. `BRIGHTNESS_ATTACK_SECONDS`/
     `BRIGHTNESS_RELEASE_SECONDS` were also dialed back about halfway
     from step 2's values (0.055s / 0.185s) after a report that the
     smoothing had eaten too much of the visible reaction.

  Verified live at each step: two 50-second continuous-bass sessions
  with the current settings produced zero errors (versus errors
  recurring within seconds before step 2, and one lingering
  connection-warmup error per session before step 3); a simulated
  unreachable device still fails in ~3s and `stop()` still returns
  in well under a second.

## Music Mode 2 ("Spectrum Mode")
Fully autonomous - unlike Music Mode, there's nothing to pick; the
whole point is getting the richest show a single RGBCW bulb can do out
of whatever's playing. `src/audio/spectrum_show.py` drives all three
HSV components from the audio every update:
- **Hue** drifts continuously with the spectral centroid (warm for
  bass/tonal-heavy sound, cool for bright/noisy sound like cymbals),
  the idea from an earlier Music Mode prototype that got replaced there
  by a fixed user colour but fits naturally here.
- **Brightness** blends bass/mid/treble band energy (weighted 0.5/0.3/
  0.2 toward bass) instead of Music Mode's bass-only signal, so it
  stays alive during melodic or cymbal-heavy passages with little bass.
  Each band calibrated the same way as Music Mode's bass band - the
  same synthesized track played and re-captured via real loopback, not
  isolated tones.
- **Saturation** dips briefly toward white on a detected onset (beat/
  hit) and recovers, instead of a hard hue jump - reads as a "flash"
  accent without competing with the continuous hue drift or risking a
  jarring instant colour swap.

This is free in bulb-load terms: `colour_data` (DP 24) already bundles
hue/saturation/value into one hex string, so driving all three costs
exactly the same single DP write per update as Music Mode's fixed-hue
path. `SpectrumMode` (`src/modes/spectrum_mode.py`) reuses every
reliability lesson from Music Mode's debugging - persistent connection,
`connection_retry_limit=2`, fail-fast timeout, one DP write per update
- via the same `MainWindow._build_reactive_mode_bulb()` bulb
construction shared between both modes.

Verified live against the real bulb with a 30-second realistic test
track: zero errors, and all three HSV components showed real variation
(hue 0-159° across 27 distinct values, saturation 400-1000 across 12
values from the onset flashes, brightness 189-746 with a mean of 410)
- confirming it behaves as a genuine multi-dimensional show rather than
a flat pulse.

Both Music Mode and Music Mode 2 are entered from their own buttons in
manual mode and share one "Exit Music Mode" button back to it
(`MainWindow._reactive_mode` holds whichever is currently running).

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
