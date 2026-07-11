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
├── device_config.json       # legacy single-device format, kept only for migration, NOT versioned
├── devices_config.json      # every configured device + group + active selection, NOT versioned
├── audio_mode_config.json   # Audio Mode assignment/sensitivity, NOT versioned
├── custom_colour_config.json # last picked custom colour, NOT versioned
├── src/
│   ├── main.py              # entry point
│   ├── device_config.py     # DeviceConfig dataclass; legacy load/save, used for migration
│   ├── devices_config.py    # load/save every device + group + active selection
│   ├── audio_mode_config.py # load/save Audio Mode's assignment + sensitivity
│   ├── custom_colour_config.py # load/save the custom-picker's last colour
│   ├── gui/                 # customtkinter GUI components
│   │   ├── main_window.py
│   │   ├── device_config_dialog.py
│   │   ├── settings_window.py
│   │   ├── devices_window.py
│   │   └── colour_picker_window.py
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

## Manual Mode: White Circle, Custom Colour Picker, Live-State Indicator
The colour-palette row gained two circles bracketing the fixed swatches:
a plain white one on the left, and a canvas-drawn one on the right that
opens a full colour picker.

**White is now the only thing that switches `work_mode`.** Previously,
touching the brightness slider silently forced white mode (`set_brightness`
→ `set_work_mode(WHITE)` internally). That meant brightness couldn't be
adjusted while a colour was active without leaving colour mode. The
brightness slider (`MainWindow._apply_brightness`) now stays inside
whichever mode is already active - `set_colour_data_value` (hue/sat
preserved, only V changes) in colour mode, `set_brightness_value` in white
mode - and only the new White circle (`MainWindow._on_white_click`) calls
`set_work_mode(WHITE)` explicitly. The temperature/saturation dual-purpose
slider (see "Audio Mode" above) already worked this way and needed no
change; its label-switching logic was re-verified to still match the
active mode after this change.

**Custom colour picker** (`src/gui/colour_picker_window.py`,
`ColourPickerWindow(ctk.CTkToplevel)`): a non-modal, freely-movable window
opened by clicking the rightmost palette circle
(`MainWindow._on_custom_colour_swatch_click`; clicking again while it's
open just raises/focuses the existing one instead of opening a second).
Contains:
- A saturation/value gradient canvas (220x220) for the current hue,
  click-and-drag to pick, plus a separate hue slider (0-359).
- A HEX entry and three separate R/G/B entries, each committing on Enter
  or focus-out; typing a value updates the gradient/slider/indicator to
  match (`_apply_rgb` via `colorsys.rgb_to_hsv`).
Both paths are debounced (`DEBOUNCE_MS = 120`) into a single
`on_pick(hue, saturation, value)` callback so dragging doesn't flood the
bulb with sends. The gradient itself is rendered with vectorized numpy
HSV→RGB math into a raw PPM P6 byte buffer fed straight into a
`tkinter.PhotoImage(format="PPM")` - deliberately avoids adding a PIL/
Pillow dependency for what's otherwise a one-function need, and is fast
enough to re-render on every hue-slider tick.

The rightmost circle itself (`tkinter.Canvas`, drawn directly rather than
through a `CTkButton` so it can show either a picked colour or a rainbow
indicator) shows a 24-wedge rainbow radial (`_draw_rainbow_swatch`) until
the user has ever picked a colour, then switches permanently to a solid
fill of the picked colour (`_draw_solid_swatch`) - signalling "a colour
picker lives behind this" before first use, then acting as a normal
recall swatch afterward. Picking (`MainWindow._on_custom_colour_picked`)
applies the colour exactly like a palette pick (`_on_colour_pick`) and
persists it to `custom_colour_config.json`
(`src/custom_colour_config.py`, same load/save dataclass pattern as
`device_config.py`), loaded back on startup - so the custom colour
survives both mode switches and full app restarts, matching the palette
swatches' behaviour of just being static built-in choices.

**Header layout**: the old inline "Change device" button was replaced
with a small gear-icon button (`text="⚙"`, `.place(relx=1.0, x=-16,
y=16, anchor="ne")` in the top-right corner, coexisting with the rest of
the layout's `.pack()` calls) to free up space for a "FLUXHOUND" title
label placed between the status line and the power switch, and a
`live_indicator` (`ctk.CTkFrame`, fixed 380x48 via `pack_propagate(False)`)
below the title that mirrors the bulb's current colour+brightness as a
fill colour (`MainWindow._update_live_indicator`, converting either
HSV(colour mode) or a warm/cool-white interpolation(white mode) times the
brightness fraction into a hex colour). Called from every state-changing
handler, including a new `CustomMode.on_update` callback
(`MainWindow._on_reactive_mode_update`) so the rectangle keeps mirroring
Audio Mode's live show instead of freezing while it runs. The gear
button no longer opens the device dialog directly - it opens a small
`SettingsWindow` (`src/gui/settings_window.py`) whose first (currently
only) entry, "Devices", closes it and opens `DevicesWindow` - see
"Devices, Groups, and the Target Selector" below.

## Devices, Groups, and the Target Selector
FluxHound controls however many bulbs are configured, not just one.
Below the live-state rectangle, a dropdown (`MainWindow.target_selector`)
lists every configured device plus every group; whichever one is
selected is the current *target* - every manual command and Audio Mode
session goes to all of its bulbs at once (a single device is just a
one-bulb target).

**Persistence** (`src/devices_config.py`, `DevicesConfig`): a list of
devices (`DeviceConfig` - device ID, IP, local key, protocol version,
plus a `display_name`), a list of groups (`DeviceGroup` - an id, a name,
and a list of member device IDs), and which target is currently active
(`"device:<id>"` or `"group:<id>"`), all in `devices_config.json` next
to the app. On first run after this feature was added, if that file
doesn't exist yet but the older single-device `device_config.json`
does, the one configured bulb is migrated in automatically as the first
device (`display_name` defaults to its device ID, since the local Tuya
protocol has no name field to read from the bulb itself - this app
never talks to Tuya's cloud API, so there's no other source for a
"real" name). `device_config.py` and its json file are kept around only
for that migration path; nothing writes to `device_config.json` since.

**Devices window** (`src/gui/devices_window.py`, `DevicesWindow`):
lists every device under "Single devices" (ungrouped) and then every
group under "Grouped devices", each device row with a "Change name"
button. Renaming only ever touches `display_name` locally - it's never
sent to the bulb. An "Add device" button opens the existing
`DeviceConfigDialog` to register a new bulb's ID/IP/local key.

A single device's row also has a "Group" button: with no groups yet, it
prompts for a new group's name directly; once at least one group
exists, it instead asks "Create new group" or "Add to existing group"
(`GroupChoiceDialog`) - the latter opens `GroupPickerDialog` listing the
existing groups to add into. A grouped device's row gets "Remove"
instead of "Group", pulling it back out to "Single devices"; a group
that loses its last member is deleted automatically. If every device
ends up in a group, the "Single devices" heading is hidden entirely
rather than showing an empty section.

**Target dispatch** (`MainWindow._run_on_all`): every manual command
(power, brightness, colour, white, temperature/saturation) that used to
call a single `self.bulb.<method>` now calls
`getattr(bulb, method_name)(*args)` for every bulb in
`self._active_bulbs` from one background-executor task, so a group's
members all receive the same command together. One bulb failing doesn't
stop the others from getting the command - verified live by grouping
the real test lamp with a second, unreachable fake device and toggling
power: the status area reported the fake device's failure, but the real
lamp still switched on. Audio Mode follows the same idea one level
down: `CustomMode` now takes a list of bulbs
(`MainWindow._build_reactive_mode_bulbs`) instead of one, and sends
every update to all of them, so a group can run one reactive show
across every bulb in it simultaneously.

Switching the selector reconnects to the new target's bulb(s)
(`MainWindow._apply_target_selection`) and reads its status the same
way as the old single-device connect flow did, but *not* on every
`DevicesWindow` edit - `_refresh_target_selector` only reconnects when
the resolved device set behind the active selection actually changed
(comparing device-id tuples), so renaming a device, or editing a group
you're not currently targeting, doesn't disturb a live connection. If
the active selection's device or group is deleted out from under it
(e.g. a group emptied via repeated "Remove" clicks), the selector falls
back to the first available device or group automatically. The selector
is disabled while Audio Mode is running, alongside the White circle,
since swapping bulbs mid-show isn't supported.

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
