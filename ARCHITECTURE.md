# FluxHound — Architecture

Technical reference for the project structure, hardware protocol, and
coding conventions used in this repository.

## Tech Stack
- Python 3.x
- GUI: customtkinter
- Tuya communication: tinytuya (local protocol, version 3.3)
- Audio (Audio Mode): soundcard (WASAPI loopback capture) + numpy (FFT)
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
├── device_config.json       # entered via GUI at runtime, NOT versioned
├── audio_mode_config.json   # Audio Mode assignment/sensitivity, NOT versioned
├── src/
│   ├── main.py              # entry point
│   ├── device_config.py     # load/save the configured bulb's connection details
│   ├── audio_mode_config.py # load/save Audio Mode's assignment + sensitivity
│   ├── gui/                 # customtkinter GUI components
│   │   ├── main_window.py
│   │   └── device_config_dialog.py
│   ├── tuya/                 # device communication (tinytuya wrapper)
│   ├── audio/                 # system-audio loopback capture + FFT analysis
│   │   ├── loopback.py
│   │   └── custom_show.py    # Audio Mode's three sources + target mapping
│   ├── modes/                # manual, audio-reactive, screen ambient, etc.
│   │   └── custom_mode.py
│   └── licensing/            # license check module
└── tests/
```
(Structure evolves as code is written.)

## Audio Mode
One reactive mode (formerly three separate "Music Mode 1/2/3" - merged
into a single configurable mode; see CHANGELOG for that history),
toggled with an "Activate/Deactivate Audio Mode" button that lives on
the same page as manual control, not a separate screen. Reacts to
whatever the system is currently playing, captured via WASAPI loopback
(no microphone, no source-app integration needed). Runs on a dedicated
background thread while active; the status area (connected/error)
stays visible and live, same as in manual mode.

`src/audio/custom_show.py` (`CustomShowEnvelope`) computes three
independent, always-on "sources" every block, each a normalized [0,1]
signal with its own natural smoothing:
- **Timbre** - spectral centroid (the spectrum's "center of mass"
  frequency), continuous drift, low for bass/tonal-heavy sound, high
  for bright/noisy sound.
- **Energy** - weighted bass/mid/treble band energy (0.5/0.3/0.2),
  continuous loudness pulse. Calibrated by playing and re-capturing a
  synthesized, realistically-mixed track (kick/bass/snare/hihat/melody/
  pad at typical relative levels) through real WASAPI loopback, not
  isolated tones - an early tone-based calibration read isolated sine
  waves as far louder than the same frequency range is in a real mix.
  Still just one synthesized track, not a broad library of real songs.
- **Beat** - onset/spectral-flux detection, idle at 0 and spiking to 1
  the instant a hit is detected before decaying back down - a
  0→1→0 flash envelope.

The GUI (`MainWindow`) lets the user assign each of Hue/Brightness/
Saturation to at most one source via a 3x3 button grid, enforced as a
**strict bijection**: selecting a source for one target disables that
same source's buttons in the other two categories (both visually and
in `MainWindow._on_mode3_source_click`, which also guards the
assignment dict directly in case a click ever reaches it despite the
disabled state) until deselected. A source maps onto whichever target
it's assigned to via `target_min + normalized * (target_max -
target_min)` regardless of which source is feeding it (hue 0-270,
brightness 10-1000, saturation 400-1000) - so reassigning a source
never needs new calibration. A target with nothing assigned simply
keeps sending its last value (frozen, not reset to a default).

Each source also has a per-source **sensitivity** slider (0-100, one
per grid row, tuning whichever source currently occupies that row):
an exponential curve (`_sensitivity_factor`) so 50 reproduces exactly
the calibrated default and the full range spans a 4x swing either way.
What sensitivity actually scales differs per source, since "more
sensitive" means something different for each: Timbre's smoothing time
(faster drift), Energy's gain (quieter sound reaches full brightness),
Beat's onset threshold (smaller transients trigger it).

**Manual override**: picking a palette colour deactivates Hue's
assignment; moving the brightness slider deactivates Brightness's;
moving the temperature/saturation slider (see below) deactivates
Saturation's - handing that one property back to manual control
without stopping Audio Mode for the other two
(`MainWindow._deactivate_row` for the persisted assignment,
`CustomMode.set_manual_override` to also clear it and set the value
atomically in the running mode, avoiding a race against the mode's own
next send). "Set to Default" resets the assignment and sensitivity to
a fixed starting configuration (Hue-Energy, Brightness-Beat,
Saturation-Timbre - the shape the user asked to standardize on)
without touching whether Audio Mode itself is on.

**Temperature/saturation dual-purpose slider**: the same slider
controls colour temperature (DP 23) in white mode, or saturation
directly (the S component of DP 24, keeping the current hue/value)
in colour mode - which is always the case while Audio Mode is
running, since it only knows how to drive colour_data. The label
above it (`MainWindow._update_temperature_label`) switches between
"Temperature (white mode)" and "Saturation (colour mode)" to match.

**Persistence**: the assignment and every source's sensitivity are
saved to `audio_mode_config.json` next to the app
(`src/audio_mode_config.py`, same load/save pattern as
`device_config.py`) on every change, and loaded on startup - so they
survive both switching Audio Mode on/off and restarting the app
entirely, not just staying in memory for the session.

This is free in bulb-load terms: `colour_data` (DP 24) already bundles
hue/saturation/value into one hex string, so driving all three costs
exactly one DP write per update either way. `CustomMode`
(`src/modes/custom_mode.py`) uses its own `TuyaBulb` instance built by
`MainWindow._build_reactive_mode_bulb()`: `persistent=True`,
`connection_retry_limit=2`, a short fail-fast timeout, and
`TuyaBulb.*_nowait` sends (`set_work_mode_nowait`,
`set_colour_data_value_nowait`) instead of the default multi-attempt-
retry, non-persistent, response-waiting setup used for one-off manual
commands. That combination is the result of several rounds of live
debugging against real hardware, not a design that was right the first
time:

1. An early version wrote two DPs per update (work_mode + value)
   through the default 2-attempt/1s-delay retry - up to ~14s per
   update on failure, enough sustained traffic to overwhelm the bulb's
   WiFi firmware and make it stop responding for a stretch, with the
   background thread's `stop()` (2s join timeout) not long enough to
   reliably terminate it either. Fixed by cutting the redundant DP
   write and failing fast (`retry_attempts=1`, short timeout).
2. Failing fast stopped the multi-second freezes, but errors kept
   recurring: every send was still a full TCP connect + handshake +
   close, and that per-command overhead alone intermittently
   overwhelmed the firmware - visible both as `"unexpected response:
   None"` errors and visibly jerky brightness (a dropped send reads as
   a skipped update / a jump). Fixed with `persistent=True`: one
   connection stays open for the session instead of being rebuilt
   every ~150ms. Brightness smoothing was also retuned in this pass -
   a second, independent source of the jerky look, since the original
   0.03s attack fully settled within one ~0.15s send interval, making
   the value actually sent close to a single raw, unsmoothed audio
   block each time.
3. Persistent connections stopped most of the recurring errors, but
   not all - the same `connection_retry_limit` used to force fast
   failure in step 1 turned out to gate a second, unrelated thing:
   tinytuya reuses that counter for how many extra reads it waits
   through when the device sends a routine null "ack" before its real
   response, not a failure. At 1, a single slow ack+payload pair was
   enough to exhaust that budget and come back as a bare `None`,
   misreported as an error even though the command had landed. Raised
   to 2 (not tinytuya's default of 5, to keep genuine-failure
   detection reasonably fast: ~3s instead of ~1.5s at 1 or ~4.6s at 3).
4. Even with 1-3 applied, longer real sessions still hit dropouts.
   Found by comparing against a working reference script that drives
   3 bulbs off separate FFT frequency bands without this problem:
   every send here still called tinytuya's default `set_value()`,
   which *waits for and parses a response* even at `retry_attempts=1`
   - one blocking receive cycle per update, which is exactly the kind
   of round trip the bulb's WiFi firmware struggles with under
   sustained traffic. The reference script never waits for a response
   at all, despite sending *faster* (60ms vs. this app's 150ms) -
   ruling out raw request rate as the cause; splitting load across 3
   bulbs wasn't the explanation either, since each bulb there gets its
   own full, independent update stream at the same rate a single bulb
   would. Fixed by switching to `TuyaBulb.*_nowait`: tinytuya still
   detects a genuinely failed connection attempt (an error dict
   returned immediately), but skips the receive/retry cycle for a
   successful write. Manual controls keep the waiting path, since a
   one-off user action should be confirmed or reported as failed.

Verified live at various points: two 100-second sessions with
continuous varied audio produced zero errors after step 4 (versus
errors recurring within seconds before step 2, a lingering connection-
warmup error per session before step 3, and dropouts still recurring
over longer sessions before step 4); a simulated unreachable device
still fails in ~3s and `stop()` still returns in well under a second.

Bijection enforcement was verified through real button `.invoke()`
calls (a disabled button does nothing; a direct call to the handler
for an already-assigned source is also rejected). The manual-override
behaviour, the dual-purpose slider, and disk persistence were verified
by setting the bulb to white/450/600 manually, activating Audio Mode
(confirmed it stayed white-ish and drifted from there rather than
snapping to a hardcoded default), deactivating (confirmed an exact
restore of dps *and* both slider widgets, fixing a bug where the
saturation/temperature slider was being overwritten with a stale
colour-mode value on every status refresh), and confirming
`audio_mode_config.json`'s contents matched every assignment/
sensitivity change made along the way.

## Device Configuration
Bulb connection details (device ID, IP address, local key) are entered
through the GUI, not hardcoded. They're persisted to `device_config.json`
next to the running app (`src/device_config.py`) — gitignored, never
committed. On startup the app checks whether a device is already
registered; if not, it asks for the three values directly. A "Change
device" button lets you re-enter them at any time.

Audio Mode's assignment and sensitivity are persisted the same way, in
a separate `audio_mode_config.json` (`src/audio_mode_config.py`) — see
"Audio Mode" above.

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

Manual mode exposes a "Temperature (white mode)" / "Saturation (colour
mode)" dual-purpose slider (0-1000) alongside brightness - see "Audio
Mode" above for how it switches meaning. Which end of the temperature
range reads as warm vs. cool hasn't been verified against the physical
bulb yet.

## Coding Conventions
- Files/modules, variables, functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- "Private" (convention only): leading underscore `_helper()`
- Docstrings for all public functions/classes
- Code, comments, docstrings, commit messages: English only
