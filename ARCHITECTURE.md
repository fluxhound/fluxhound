# FluxHound — Architecture

Technical reference for the project structure, hardware protocol, and
coding conventions used in this repository.

## Tech Stack
- Python 3.x
- GUI: customtkinter
- Tuya communication: tinytuya (local protocol, version 3.3)
- Audio (Audio Mode): soundcard (WASAPI loopback capture) + numpy (FFT)
- Screen (Ambience Mode): mss (screen capture) + numpy (colour analysis)
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
├── fluxhound_logo.png       # app logo, composited over the live-state indicator
├── device_config.json       # legacy single-device format, kept only for migration, NOT versioned
├── devices_config.json      # every configured device + group + active selection, NOT versioned
├── audio_mode_config.json   # Audio Mode assignment/sensitivity, NOT versioned
├── custom_colour_config.json # last picked custom colour, NOT versioned
├── ambience_config.json     # Ambience Mode's monitor/region/gaming-mode/trigger-watcher choice, NOT versioned
├── license_config.json      # cached license-unlocked state, NOT versioned
├── src/
│   ├── main.py              # entry point; also sets per-monitor DPI awareness
│   ├── device_config.py     # DeviceConfig dataclass; legacy load/save, used for migration
│   ├── devices_config.py    # load/save every device + group + active selection
│   ├── audio_mode_config.py # load/save Audio Mode's assignment + sensitivity
│   ├── custom_colour_config.py # load/save the custom-picker's last colour
│   ├── ambience_config.py   # load/save Ambience Mode's monitor/region/trigger-watcher choice
│   ├── license_config.py    # load/save the cached license-unlocked state
│   ├── autostart.py         # Windows Run-key toggle (launch at login)
│   ├── gui/                 # customtkinter GUI components
│   │   ├── main_window.py
│   │   ├── device_config_dialog.py
│   │   ├── settings_window.py
│   │   ├── tray.py          # system tray icon (pywin32 Shell_NotifyIcon, no PIL)
│   │   ├── devices_window.py
│   │   ├── region_selector_window.py
│   │   ├── colour_picker_window.py
│   │   ├── trigger_editor_window.py # Custom Trigger Editor (paid-tier)
│   │   ├── license_window.py # enter/manage the license key
│   │   └── upsell_dialog.py  # shown when a free-tier user hits a paid-tier feature
│   ├── tuya/                 # device communication (tinytuya wrapper)
│   │   ├── device.py
│   │   └── discovery.py      # local UDP network scan (device ID + IP, no key)
│   ├── audio/                 # system-audio loopback capture + FFT analysis
│   │   ├── loopback.py
│   │   └── custom_show.py    # Audio Mode's three sources + target mapping
│   ├── screen/                # screen capture + colour-mood analysis (Ambience Mode)
│   │   ├── capture.py
│   │   ├── ambience_show.py
│   │   └── health_bar.py     # Gaming Mode's bar/orb fill detection + TriggerConfig
│   ├── modes/                # manual, audio-reactive, screen-reactive, etc.
│   │   ├── custom_mode.py
│   │   └── ambience_mode.py
│   └── licensing/
│       ├── gate.py           # central free/paid feature gating
│       └── license_check.py  # Lemon Squeezy License API validation
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

**Manual override**: while Audio Mode is running, picking a palette
colour deactivates Hue's assignment; moving the brightness slider
deactivates Brightness's; moving the temperature/saturation slider (see
below) deactivates Saturation's - handing that one property back to
manual control without stopping Audio Mode for the other two
(`MainWindow._deactivate_row` for the persisted assignment, gated on
`isinstance(self._reactive_mode, CustomMode)` so it only fires while
Audio Mode is actually active; `CustomMode.set_manual_override` to also
clear it and set the value atomically in the running mode, avoiding a
race against the mode's own next send). Touching those same controls
while Audio Mode is *not* running is plain manual control and leaves
the persisted assignment untouched - an earlier version cleared it
unconditionally, so e.g. picking a colour with Audio Mode off would
silently blank out a configured Hue source the user hadn't even
activated Audio Mode to use yet; fixed by moving the deactivation
inside the same `isinstance` check that gates `set_manual_override`.
"Set to Default" resets the assignment and sensitivity to a fixed
starting configuration (Hue-Energy, Brightness-Beat, Saturation-Timbre
- the shape the user asked to standardize on) without touching whether
Audio Mode itself is on.

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

**`--debug` audio logging** (`src/main.py`'s `--debug` flag): every
time Audio Mode is activated with `--debug` set, `CustomMode` writes a
CSV row per audio block (`src/modes/custom_mode.py`'s
`DEBUG_LOG_COLUMNS`) to a fresh timestamped
`audio_debug_<timestamp>.csv` next to the app
(`MainWindow._make_debug_log_path`, gitignored) - a fresh file per
activation rather than one fixed name, so several start/stop cycles in
one session don't overwrite each other. Beyond the three final
smoothed source values, it also logs the raw pre-sensitivity readings
behind them (`CustomShowEnvelope.debug_snapshot`: `centroid_hz` for
timbre, the pre-gain `energy_raw` band blend, and `flux`/
`onset_threshold` for beat) plus the sensitivity in effect at that
instant - a value pinned at 0 or 1 in the final column doesn't say
whether that's the real signal genuinely maxed out or the current
gain/threshold being off, and the raw columns do. Exists specifically
to support a calibration pass against real music: run with `--debug`,
listen for a while, then review the CSV for the same kind of
optimization opportunities the original synthesized-track calibration
(see the Energy/BANDS comments above) was tuned against, but against
real, varied material instead of one synthesized clip. Live-verified:
activating Audio Mode with `debug=True` produced a real CSV against
the actual WASAPI loopback capture, correct header, one row roughly
every ~23ms, values matching what a silent block should produce
(`energy_raw`/`flux` at 0, `centroid_hz` pinned to `CENTROID_MIN_HZ`).

## Ambience Mode
A second, independent reactive mode: continuously reads the screen's
dominant colour and brightness and drives the active target from it,
the same way Audio Mode drives it from system audio. Toggled with an
"Activate/Deactivate Ambience" button below "Set to Default"; mutually
exclusive with Audio Mode (each button disables the other while its
mode is running), since both ultimately just drive `colour_data` and
running two show generators against the same bulb(s) at once would
just have them fight each other.

**Capture** (`src/screen/capture.py`, `ScreenCapture`): grabs the
primary monitor via `mss` (chosen over `PIL.ImageGrab` specifically to
avoid a Pillow dependency, consistent with the rest of this codebase,
and because `mss`'s per-monitor/arbitrary-region grabs made analysing
several distinct screen regions at once a natural extension later - see
"Multi-region Mode" below, which is exactly that), downsampled via
simple striding to ~160px wide so repeated capture+analysis stays cheap.

**Colour analysis** (`src/screen/ambience_show.py`, `AmbienceEnvelope`):
turns one captured frame into a single smoothed (hue, saturation,
brightness) reading representing the screen's colour "mood". The
naive approach - averaging every pixel - fails in practice: most real
screen content (text, window chrome, black bars, plain backgrounds) is
low-saturation "boring" pixels that would dominate by sheer count and
wash any flat average toward a muddy grey/brown that doesn't reflect
what's actually visually happening. Two deliberate design choices work
around that:
- **Boring-pixel filtering**: a pixel only counts toward the "what
  colour" decision if its saturation clears `BORING_SATURATION_THRESHOLD`
  (0.18) and its value clears a small `BORING_VALUE_LOW` floor (0.06,
  to drop numerically-noisy near-black hues at 8-bit quantization).
  Brightness alone never disqualifies a pixel - a fully saturated pure
  colour at maximum brightness is exactly as vivid as a dim one, only
  low *saturation* makes something boring. An earlier version also
  excluded high-value pixels to catch near-white content, which was
  wrong: it was actually excluding fully-saturated bright primaries too
  (a solid blue full-screen test frame came back with saturation 0
  instead of 1000) - caught by a unit test
  (`test_pure_saturated_colour_at_full_brightness_is_not_treated_as_boring`)
  before it reached live testing.
- **Weighted-histogram dominant hue, not a flat average**: among the
  surviving "colourful" pixels, hue is bucketed into 36 10-degree bins,
  each pixel weighted by its own saturation, and the peak bin's pixels
  are averaged for the final hue/saturation. This picks *one* dominant
  colour instead of blending distinct colours together - half a screen
  red and half blue produces red or blue, never the muddy purple that
  a flat average would produce and that nothing on screen actually
  shows. If literally no pixel clears the boring threshold (e.g. a
  plain text document), the last hue is held and saturation drops to 0
  rather than resetting to a hardcoded default. Brightness always
  follows the *whole* frame's average value, not just the colourful
  subset - a bright white document should still produce a bright,
  if unsaturated, light.
- Frame-to-frame smoothing is an exponential moving average
  (`DEFAULT_SMOOTHING_FACTOR = 0.15`) with hue smoothed the short way
  around the 360° wrap (`_hue_delta`), so a hue near 350 moving toward
  10 goes through 360/0, not the long way through 180.

**Colour sensitivity / Smoothing sliders** (Ambience tab): both fixed
constants above turned out to want different values depending on
content. `BORING_SATURATION_THRESHOLD`'s default filters aggressively
enough that games look great (only genuinely vivid on-screen elements
register), but a live test while watching a film showed the same
threshold picking a small bold-coloured detail that clashed with a
scene's actual, more muted, overall mood - and separately, the fixed
smoothing factor's snappy response (tuned for games, where a colour
change is already triggered by a deliberate in-game event) read as
"jittery" for a film's more gradual scene-to-scene mood shifts. Rather
than pick one fixed compromise, both are now two 0-100 sliders (50 =
neutral, reproducing the original fixed constants exactly), using the
same exponential-curve convention as Audio Mode's per-source
sensitivity (`src/audio/custom_show.py`'s `_sensitivity_factor`) -
`src/screen/ambience_show.py`'s `colour_sensitivity_to_threshold`/
`smoothing_to_factor` do the same 4x-swing mapping. Persisted in
`AmbienceConfig.colour_sensitivity`/`smoothing`
(`src/ambience_config.py`), and - since the whole point is tuning them
while actually watching something - live-adjustable while Ambience
Mode is running: `AmbienceMode.set_colour_sensitivity`/`set_smoothing`
update a lock-protected value that `_apply_live_ambience_settings`
pushes into every active `AmbienceEnvelope` once per capture tick via
its own `set_boring_saturation_threshold`/`set_smoothing_factor`
setters, without resetting whatever hue/saturation/value state that
envelope has already smoothed so far - the same live-update contract
`CustomMode.set_sensitivity` already established for Audio Mode.

**Reactive loop** (`src/modes/ambience_mode.py`, `AmbienceMode`):
structurally identical to `CustomMode`/Audio Mode and reuses every
reliability lesson from its debugging history - persistent connection,
`connection_retry_limit=2`, fail-fast timeout, `nowait` sends, one DP
write per update - captures roughly every 0.1s, sends to the bulb(s)
at most every 0.2s. Unlike Audio Mode it has no per-target source
assignment (hue/saturation/brightness always all come from the same
screen reading together) *unless* Multi-region Mode is on - see below -
in which case each bulb can be driven from its own independent screen
region instead.

**Manual controls during Ambience Mode**: unlike Audio Mode, which
supports taking one property back via `CustomMode.set_manual_override`,
Ambience Mode has no per-property assignment to hand back - so the
brightness/temperature sliders and the colour palette (including the
custom-colour circle) are disabled outright while it runs
(`MainWindow._set_manual_override_controls_enabled`), rather than
fighting a mode that would just overwrite a manual touch again within
one send interval. The White circle, target selector, and merge-split
checkboxes stay disabled the same way they already are during Audio
Mode.

Verified live against the three real bulbs already merged into one
group on this machine: showed a solid-red full-screen test pattern,
confirmed all three bulbs converged on hue ≈0; switched to solid blue,
confirmed convergence on hue ≈240; confirmed the Activate Audio Mode
button was disabled the whole time (mutual exclusion) and the manual
controls were disabled; deactivated and confirmed a clean restore and
re-enabled controls. The group's `devices_config.json` was never
touched by any of this, since the feature just drives whatever the
already-active target is.

### Monitor and Region Selection
Below the Ambience button: a preview box shaped to the watched monitor's
aspect ratio, a monitor dropdown (only matters with more than one
monitor attached), and a "Set area"/"Delete area" button - lets Ambience
Mode watch one hand-picked rectangle of a monitor instead of the whole
thing.

**Persistence** (`src/ambience_config.py`, `AmbienceConfig`): the
chosen monitor's index (mss's own 1-based numbering; 0 means "not
chosen yet", falls back to whichever monitor mss flags primary) and an
optional `AmbienceRegion` (x, y, width, height, relative to that
monitor's own top-left) in `ambience_config.json`. If the persisted
monitor index no longer resolves to anything (e.g. a monitor that's
been unplugged since), `MainWindow._refresh_monitor_selector` falls
back the same way the device/group target selector does - adopts the
fallback monitor as the new persisted choice rather than silently
pointing at one that doesn't exist.

**Region selection** (`src/gui/region_selector_window.py`,
`RegionSelectorWindow`): clicking "Set area" opens a borderless,
topmost, semi-transparent Toplevel sized and positioned to exactly
cover the chosen monitor's physical pixel bounds. Dragging draws a
rubber-band rectangle (`<ButtonPress-1>`/`<B1-Motion>`/
`<ButtonRelease-1>` on a `tkinter.Canvas`); releasing hands the
monitor-relative `(x, y, width, height)` back to `MainWindow`, which
persists it and flips the button to "Delete area" (clicking it clears
the region and flips the button back). Switching monitors always
clears any saved region, since its pixel coordinates only make sense
relative to the monitor they were drawn on.

**Getting the overlay to land in the right place matters more than it
sounds**: Tkinter on Windows normally reports *virtualized* pixel
coordinates that Windows silently rescales whenever display scaling
isn't 100%, while mss (and the physical monitor bounds it reports)
always works in real physical pixels. Left alone, the two would drift
apart on any scaled display, and the overlay - or the rectangle drawn
on it - would land somewhere other than what actually gets captured.
Fixed once, centrally, in `src/main.py`
(`_enable_dpi_awareness`, called before any Tk window is created):
`ctypes.windll.shcore.SetProcessDpiAwareness(2)` (per-monitor DPI
aware) makes Tkinter's coordinate system match mss's physical pixels
directly, so no other code needs to think about scaling at all.

**Preview** (`MainWindow._redraw_ambience_preview`): a one-shot
snapshot of the watched monitor (via `ScreenCapture`, nearest-neighbour
resized to fit the preview box - `_resize_frame_nearest`, no PIL) with
the selected region, if any, drawn as an outlined rectangle on top,
proportionally scaled. Not a live video feed - it only redraws when the
monitor or region choice actually changes, not continuously, so it
costs nothing while Ambience Mode isn't even running.

**Wiring into capture** (`src/screen/capture.py`): `ScreenCapture`
takes `monitor_index` and an optional `region`; `list_monitors()`
exposes every monitor mss can see (each augmented with its own
1-based `index`) for the dropdown. `AmbienceMode` takes the same two
parameters and constructs its `ScreenCapture` with them inside its own
background thread. The monitor dropdown and "Set area"/"Delete area"
button are disabled while either reactive mode is running, alongside
the other manual controls, since changing the capture source
mid-session isn't supported.

Verified live: simulated a drag-select (`event_generate` on the
overlay's canvas) over a fixed region of the primary monitor and
confirmed the resulting persisted region matched the drag exactly; a
fresh `ambience_config.load()` (simulating a restart) reproduced it
identically. The strongest check: filled the whole monitor green except
for a red rectangle placed exactly at the selected region, activated
Ambience Mode, and confirmed all three real bulbs converged on red, not
green - proving the capture is genuinely restricted to the region and
not just incidentally including it within a full-monitor grab (green
covered far more of the screen and would have dominated a weighted
histogram otherwise). "Delete area" and monitor switching both
correctly cleared the region, on disk and in the UI.

### Gaming Mode
A checkbox below the monitor/"Set area" row. Checking it repurposes the
"Set area" region: instead of narrowing the *ambient* reading to that
region, ambient goes back to watching the whole monitor, and the
region becomes a dedicated health/resource-bar watcher running
alongside it - the idea being to reflect the screen's overall mood as
usual, while a game's health/mana/resource bar or orb (drag-selected
the same way as any other region) gets to briefly interrupt that with
an alert.

**Fill detection** (`src/screen/health_bar.py`): deliberately not
OCR - reading styled in-game digits reliably would need a much
heavier, more fragile dependency for a signal a simple colour-ratio
approach already gives directly, and it generalises across bar shapes
without knowing anything about them. `calibrate_bar_colour` identifies
the bar's fill colour (hue, saturation, value) once, the same
"most frequent vivid colour" idea Ambience Mode itself uses for the
whole screen, applied to the cropped region. `fill_fraction` then
measures what fraction of the region's pixels currently match that
colour - which *is* the fill percentage, regardless of orientation or
shape (horizontal bar, vertical bar, circular orb alike), as long as
the region is cropped around the bar/orb's full fixed extent (so both
"filled" and "emptied" pixels are always inside it - the container
doesn't move or resize, only the ratio of fill-to-track pixels within
it does).

**A same-hue dark "track" needed real care**: many bars' empty portion
is a *darker shade of a similar hue* to the fill (a dim maroon track
behind a bright red fill), not neutral grey - matching on hue alone
isn't enough to tell them apart, and naively including both when
identifying the fill colour drags the reference toward the track's
much duller saturation/value. Hit exactly this live in testing:
calibrating while the bar was mostly empty (track pixels vastly
outnumbering fill pixels) diluted the reference far enough that
`fill_fraction` started reading track pixels as filled too, breaking
the percentage at low health specifically - caught by a unit test
before it reached a real bulb. Fixed two ways: calibration only
considers pixels above a strict saturation floor
(`CALIBRATION_SATURATION_THRESHOLD = 0.5`, well above a typical dim
track's saturation) so a mostly-empty calibration frame can't dilute
the reference, and `fill_fraction`'s ongoing matching requires *both*
saturation and value to be a substantial fraction of the calibrated
fill's own (`FILL_SATURATION_RATIO`/`FILL_VALUE_RATIO = 0.7`), not
just close hue.

**Re-identifying the fill colour every frame, not once at startup**
(`measure_fill`): the first version calibrated once, the moment Gaming
Mode's health capture started, and reused that reference colour for
the rest of the session. Two follow-up questions from live use exposed
real problems with that: what does the region's *first* frame define
as "100%" if the game was, say, mid-fight and already damaged when
Ambience Mode started - and what happens if that one calibration frame
caught the bar fully empty? The first turned out to be a non-issue by
construction: `fill_fraction`'s denominator is always the region's
total pixel count (fixed by the drag-selected rectangle), never "what
was visible at calibration time" - calibration only ever identifies a
*colour*, not a baseline area, so healing past whatever fraction was
showing at startup was already detected correctly. The second was a
real gap: a mostly-empty region at that one moment finds no vivid
pixels, `calibrate_bar_colour` returns `None`, and the old design just
left the tracker permanently uncalibrated for the rest of the session.
There was also a related gap for bars that recolour as they deplete (a
common green→amber→red convention) - a persisted single-colour
reference can't follow that. Fixed by dropping the one-shot calibration
step entirely: `measure_fill` re-identifies the region's own dominant
vivid colour fresh from every single frame and measures against that
same frame's own reading, so there's no reference to go stale, no
single calibration moment to get unlucky on, and a colour-shifting bar
is measured correctly at every step along the way. An empty frame
simply measures as a real 0.0 rather than a failed calibration.

**Reacting to changes** (`HealthBarTracker`): compares each frame's
fraction to the last one - a drop past `CHANGE_EPSILON` (2 percentage
points, to ignore capture noise) briefly overrides the bulb with a red
flash (`BLINK_DURATION_SECONDS = 0.5`); a rise, green. Falling below
`LOW_HEALTH_THRESHOLD` (10%) holds a continuous red glow instead,
taking priority over a flash that happens to still be active, until
the fraction rises back above it. Since there's no separate
calibration step anymore, the very first `process()` call after
construction just records a baseline - if that baseline is itself
below 10% (bar starts empty), the low-health glow fires immediately,
which is the correct reading, not a bug.

**Wiring** (`src/modes/ambience_mode.py`): with `gaming_mode=True`,
`AmbienceMode` runs *two* `ScreenCapture`s from the same background
thread - one on the whole monitor for the ambient reading (unchanged),
one on the region for `HealthBarTracker`. Whichever tick a tracker
override is active, it's sent instead of the ambient reading; otherwise
the ambient reading goes out as normal. The choice and region persist
the same way as everything else (`ambience_config.json`,
`AmbienceConfig.gaming_mode`), and the checkbox is disabled while a
reactive mode is running, alongside the monitor dropdown and area
button.

Verified live against the three real merged bulbs (in two passes - the
initial feature, then the per-frame recalibration follow-up): a blue
full-screen background with a red health bar (dark same-hue track
behind a vivid fill, the exact case the calibration fix targets)
drag-selected as the area. With Gaming Mode on, all three bulbs read
the ambient blue at rest - confirming the region no longer drives
ambient once Gaming Mode is on. Shrinking the bar 100%→50% flashed all
three red, which expired back to blue; growing 50%→90% flashed green
the same way. Dropping to 5% held a continuous red glow (confirmed
still red 1.5s later, not just an expired flash), and recovering to
80% flashed green once more before ambient blue resumed. The follow-up
pass specifically targeted the two fixed gaps: starting Ambience Mode
with the bar already fully empty correctly showed the low-health glow
immediately (rather than silently never working for the rest of the
session), and healing from that empty start to 90% was still detected
as a real increase; a fill that both shrank *and* changed colour
(green → amber, simulating a game's own recolour-as-you-deplete
convention) still correctly triggered a decrease flash. Both passes
restored `ambience_config.json` (including the user's own real
in-progress Gaming Mode region, mid-session, in the second pass) to
its exact prior state afterward and turned the real bulbs off.

### Custom Trigger Editor (paid-tier)
Gaming Mode's built-in watcher always uses `TriggerConfig()`'s fixed
defaults (see above) - genuinely good presets, not a deliberately
weakened demo, since every user gets exactly this behaviour regardless
of tier. The Custom Trigger Editor is purely additive on top of it:
any number of *extra* watched regions, each with its own independently
configurable thresholds, flash colours, and multi-step glow reactions,
running alongside the built-in one.

**Generalizing `health_bar.py`** (`TriggerConfig`, `ThresholdBand`):
every value the original implementation hardcoded as a module constant
(`CHANGE_EPSILON`, `BLINK_DURATION_SECONDS`, `DECREASE_COLOUR`,
`INCREASE_COLOUR`, `LOW_HEALTH_THRESHOLD`/`LOW_HEALTH_COLOUR`) became a
field on `TriggerConfig` instead, with those exact same values as its
defaults - `HealthBarTracker(config=None)` reproduces the original
behaviour bit-for-bit, which is what both the built-in watcher and the
existing test suite rely on unchanged. `LOW_HEALTH_THRESHOLD`'s single
fixed glow became `threshold_bands: list[ThresholdBand]` - any number
of `(threshold, colour)` pairs, letting a watcher glow differently at
different severity levels (e.g. amber below 50%, red below 20%) - the
"multi-step reactions" the feature is meant to expose.
`TriggerConfig.active_band(fraction)` picks the *smallest* threshold
among those the current fraction has crossed (most severe wins),
strict less-than to match the original single-threshold check exactly.

**Watchers** (`TriggerWatcher`, `src/ambience_config.py`): a region
plus a `TriggerConfig`, persisted in `AmbienceConfig.trigger_watchers`
(a plain list, empty by default - a pre-Trigger-Editor config file
loads with an empty list, not an error). `AmbienceMode` evaluates the
built-in watcher (if a region is set) first, then every custom watcher
in list order, every tick; the *first* one with a non-`None` override
wins for that tick - documented, deterministic priority rather than
last-write-wins or some other unstated rule. Watchers whose regions
don't overlap never interact at all; the priority rule only matters
when two watchers' conditions are true at the exact same moment.

**GUI** (`src/gui/trigger_editor_window.py`): `TriggerEditorWindow`
lists every custom watcher (add/remove/"Configure"), opened via a
"Custom Trigger Editor..." button next to the Gaming Mode checkbox.
"Add watcher" prompts for a name, then reuses the same
`RegionSelectorWindow` drag-to-select overlay Ambience Mode's own "Set
area" uses. `TriggerConfigEditorWindow` is the full per-watcher editor:
rename, re-drag the region, sensitivity (`change_epsilon`) and flash
duration as plain entries, decrease/increase flash colours as small
swatch buttons that reuse `ColourPickerWindow` non-modally (matching
the main window's own custom-colour swatch), and the threshold-bands
list as its own mini add/remove/edit section, always re-sorted and
re-rendered by threshold after any edit. Editing a watcher while
Ambience Mode is already running does *not* auto-restart it - the
watcher list it started with keeps running until the next manual
Activate/Deactivate, to avoid momentarily flickering the bulb back to
its pre-reactive manual state and forth again just to pick up an edit
(see "Fragile/rushed areas" below).

Verified live against the real 3-bulb merged group: two on-screen bars
drawn as real Tk windows (not a mocked frame) at fixed screen
coordinates, one as Gaming Mode's built-in region, one as a custom
watcher with a distinctly different `TriggerConfig` (orange decrease,
cyan increase, a single magenta band at 30% - all different from the
fixed defaults). `TuyaBulb.set_colour_data_value_nowait` was wrapped
(not replaced) to log every send. Confirmed: shrinking the built-in
bar past 10% sent the fixed red glow; shrinking the custom bar past
*its* 30% band sent magenta, not red or green; growing the custom bar
back sent its custom cyan flash, not the default green; and with both
bars simultaneously below their thresholds, the built-in watcher (first
in evaluation order) won, exactly as documented. One real bug caught
and fixed *in the test itself*, not the implementation: the test's
first attempt used track colours with too-high saturation for the
"empty" portion of the synthetic bars, which `calibrate_bar_colour`
picked up as if it were part of the fill at low fill levels - the same
pitfall `health_bar.py`'s own docstring already warns about, hit again
by not reusing the existing unit test's proven-safe track colour.
`devices_config.json` was untouched throughout; `ambience_config.json`
was restored to the user's exact prior state and the real bulbs turned
off afterward.

### Multi-region Mode
A second checkbox next to Gaming Mode, mutually exclusive with it (both
give the region concept a different meaning, and running both at once
would be ambiguous about what a bulb should show). Instead of one
screen reading applied to every bulb alike, Multi-region Mode gives
each of a merged group's *positioned* bulbs (BASE, EXT-1, EXT-2, ...)
its own independent screen region - e.g. BASE watching the left third
of the screen, EXT-1 the middle, EXT-2 the right - so a merged group
can genuinely reflect *different* parts of the screen simultaneously,
not just split one shared reading positionally the way manual control
and Audio Mode's split checkboxes do (see "Merged Groups" below - that
splits *one number* across bulbs; this drives each bulb from a
*different source reading* entirely).

**UI**: checking "Multi-region mode" reveals a position dropdown and
its own "Set area"/"Delete area" button below the existing monitor/area
row (`MainWindow.multi_region_controls`); the dropdown lists whichever
positions the active target's merged group actually has assigned
(`_current_group_positions`, empty and showing a placeholder if the
active target isn't a merged group), and the area button assigns or
clears a region for whichever position is currently selected, reusing
the same drag-to-select `RegionSelectorWindow` as the single-region
flow. The plain "Set area" button (for the shared single region) is
disabled while Multi-region Mode is on, since `region` isn't used in
this mode. The preview box marks every assigned position's region at
once, each labelled with its position, instead of just one outline.

**Persistence** (`src/ambience_config.py`, `AmbienceConfig.
multi_region_mode` / `position_regions: dict[str, AmbienceRegion]`):
keyed by position *label* ("BASE", "EXT-1", ...) rather than by a
specific group id or device id - consistent with this file already
treating monitor/region as one global choice rather than per-group
state, and a reasonable simplification besides: "BASE = left third of
the screen" carries a consistent meaning regardless of which physical
group or bulb currently happens to hold that position. A pre-multi-
region `ambience_config.json` loads with both defaulting to
off/empty, matching every other config module's backward-compatible
load pattern in this codebase.

**Dispatch** (`src/modes/ambience_mode.py`, `AmbienceMode`): the send
path is unified around a list of `(hue, saturation, value)` readings
parallel to `self._bulbs` (`_send(readings)`) - normal Ambience Mode
and Gaming Mode just build a list where every entry is the same shared
reading, so a single send path serves all three modes without a
special case. In Multi-region Mode (`_run_multi_region`), one
`ScreenCapture`/`AmbienceEnvelope` pair runs per *distinct* region
(bulbs assigned the same region share one pair rather than duplicating
the capture), plus one whole-monitor fallback pair shared by any bulb
with no region assigned (no position, or a position with no region set
yet) - each bulb's entry in the final list comes from whichever pair
its assigned region maps to. `MainWindow._build_bulb_regions` builds
the per-bulb region list the same way `_build_split_ranks` already
builds per-bulb ranks for the ordinary split feature: each active
bulb's rank in the merged order looks up its position label, which
looks up that position's configured region (or `None`, meaning
"fall back to whole-monitor" for that one bulb specifically - an
unpositioned group member, or a positioned one that just hasn't had a
region assigned yet).

Verified live against the three real bulbs already merged into
"Stehlampe" (BASE/EXT-1/EXT-2): three solid-colour windows (red,
green, blue) drawn at three known, non-overlapping screen rectangles;
those exact rectangles assigned as BASE/EXT-1/EXT-2's regions; Ambience
Mode activated with Multi-region Mode on. `TuyaBulb.
set_colour_data_value_nowait` was wrapped (not replaced - the real
bulbs still received every command) to log which physical device each
send went to, without needing to watch the lamps directly: BASE
consistently received hue 0 (red), EXT-1 hue 120 (green), EXT-2 hue 240
(blue) - nine consecutive sends each, zero cross-talk between bulbs -
confirming the three bulbs were each genuinely reading their own
independent screen region rather than one shared average.
`devices_config.json` was untouched throughout (byte-identical
before/after); `ambience_config.json` was restored to the user's exact
prior state (their own real Gaming Mode region, still in daily use)
once the test finished.

### Deactivating a Reactive Mode: Restoring Manual State
Both reactive modes share the same entry/exit plumbing
(`MainWindow._begin_reactive_mode`/`_deactivate_reactive_mode`/
`_restore_snapshot`): a `BulbSnapshot` of the bulb's actual state is
taken right before the mode starts, and reapplied once it stops, so
switching back to manual control lands exactly where it left off
instead of at some hardcoded default (see "Fixed reactive modes
jumping to hardcoded defaults..." in the CHANGELOG for the original
version of this mechanism).

**A real bug found live**: `_begin_reactive_mode` kept
`self._pre_reactive_state` (the snapshot to restore *to*) and
`self._current_state` (the live-tracking copy the running mode's
`on_update` callback continuously overwrites, to drive the live-state
indicator) pointed at the *same* `BulbSnapshot` object instead of an
independent copy. Since `_on_reactive_mode_update` mutates
`self._current_state`'s fields in place on every tick, and that was
the identical object as `_pre_reactive_state`, the "restore to this"
snapshot silently drifted to match whatever the mode was currently
showing - by the time the mode was deactivated, "restoring" just
reapplied the mode's own last output, which is indistinguishable from
never restoring anything at all. Confirmed live against the real
3-bulb group: set a known white/500 baseline, ran Ambience Mode long
enough to drift onto an unrelated hue, deactivated, and polled the
bulb's actual `status()` from a completely separate connection - it
stayed on the mode's last colour indefinitely (checked out to 2s
later) instead of reverting. Fixed by making `self._current_state` an
independent `dataclasses.replace(snapshot)` copy in
`_begin_reactive_mode`, leaving `self._pre_reactive_state` untouched
for the rest of the mode's run. Re-verified with the same live setup,
for both a white-mode and a colour-mode baseline: the correct original
state (not the mode's last output) was confirmed on the physical bulb
after deactivating, both times.

Restoring a merged group of *N* bulbs takes noticeably longer than a
single device - `_restore_snapshot` issues up to 3 sequential,
confirmed (non-`nowait`) network round-trips per bulb (work_mode,
brightness, temperature - or work_mode + colour_data), one bulb after
another, since `self._active_bulbs` are plain non-persistent
connections. Observed live at roughly 400-500ms per round-trip, so a
3-bulb group's full restore realistically takes several seconds - the
"Restoring previous settings..." status message covers exactly that
window, and it's expected, not a bug.

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
`live_indicator` below the title that mirrors the bulb's current
colour+brightness. Called from every state-changing handler, including
`CustomMode.on_update` (`MainWindow._on_reactive_mode_update`) so it
keeps mirroring Audio Mode's live show instead of freezing while it
runs. The gear button no longer opens the device dialog directly - it
opens a small `SettingsWindow` (`src/gui/settings_window.py`) whose
first (currently only) entry, "Devices", closes it and opens
`DevicesWindow` - see "Devices, Groups, and the Target Selector" below.

**System tray**: `MainWindow` constructs a `TrayIcon`
(`src/gui/tray.py`) in `__init__`. Clicking the window's close button
(`WM_DELETE_WINDOW`, `MainWindow._on_close`) hides the window
(`self.withdraw()`) instead of quitting - the app keeps any active
reactive mode running in the background. A left click or "Show
FluxHound" from the tray icon's right-click menu restores it
(`_restore_from_tray`); "Quit" there is the only way to actually close
the app (`MainWindow._quit`, which then also removes the tray icon).
Built directly against `pywin32`'s `Shell_NotifyIcon`/`LoadImage` APIs
(loading `fluxhound.ico` straight from its file path) rather than
`pystray`, whose public API hard-requires a `PIL.Image.Image` - this
app has deliberately avoided Pillow everywhere else. `TrayIcon` runs
its own Win32 message pump on a dedicated daemon thread (mirroring
pywin32's own systray demo) and always calls back into Tk via
`root.after(0, ...)`, the same cross-thread handoff pattern already
used for `DeviceConfigDialog`'s background network scan. If pywin32
isn't available or the icon fails to load, `TrayIcon.is_available`
stays `False` and `_on_close` falls back to a real quit, so the window
is never stranded with no way back. `SettingsWindow` also hosts a
"Start with Windows" checkbox backed by `src/autostart.py`, which
adds/removes a per-user `HKCU\...\Run` registry entry via the stdlib
`winreg` module (no admin rights needed, no new dependency).

**Scrollable body**: every feature added to the main window pushed its
total content height up again, until it finally grew taller than a
1080p screen (`460x1160`, reported live as no longer fitting). Rather
than keep shrinking things to fit, everything except the gear button
now lives inside a `ctk.CTkScrollableFrame` (`MainWindow.scroll_container`,
packed `fill="both", expand=True`) - the window itself dropped back to a
comfortable fixed `480x820`, and any content past that scrolls instead
of the window overflowing off-screen. The gear button stays a direct
child of the window (not the scrollable frame), created *after* the
scroll container so it stacks visually on top and stays reachable at
any scroll position, instead of scrolling away or being covered by the
scrollable frame's content.

**Live indicator as a logo backdrop**: `live_indicator` is a raw
`tkinter.Canvas` (260x220, chosen over a `ctk.CTkFrame` so a PNG with
alpha can be composited on top of it - customtkinter frames can't do
that) with two layered canvas image items. The bottom one is a radial
gradient (`_render_radial_glow`, same vectorized-numpy-into-a-raw-PPM-
`PhotoImage` technique as the colour picker's gradient, no PIL) going
from the bulb's current colour at the centre out to the window's own
background colour at the edges - regenerated on every
`_update_live_indicator` call, so the "glow" is live. The top one is
the app logo (`fluxhound_logo.png`, next to the app - `_load_logo`,
downscaled once at startup via `PhotoImage.subsample`), drawn once and
never redrawn since it doesn't change; missing the file just means no
logo layer, not a crash. **Confirmed empirically before relying on
it**: modern Tk (8.6, bundled with this Python) alpha-blends a
`PhotoImage`'s transparency for real when drawn over other canvas
content via `create_image` (a synthetic 50%-alpha pixel composited over
a green background came out as an exact 50/50 blend, not an all-or-
nothing cutout) - not just documented in Tk's changelog but verified
directly, since older/other Tk builds only supported boolean
transparency. That's what lets the logo's own soft vignette (fully
transparent at the far corners, fading in toward the opaque dog-head
artwork) blend naturally into the radial glow beneath it instead of
showing a hard-edged square. One gotcha hit along the way: the theme's
background colour (`ctk.ThemeManager.theme["CTk"]["fg_color"]`) isn't
always a "#rrggbb" hex string - it can be a Tk named colour like
`"gray86"` - so resolving it to RGB for the gradient's outer colour
goes through `self.winfo_rgb(...)` (handles both forms) rather than
manual hex parsing, which crashed on the very first live run otherwise.

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
protocol has no name field to read from the bulb itself, and by
default this app doesn't talk to Tuya's cloud API either - see "Device
Discovery" below for the one, opt-in exception - so there's usually no
other source for a "real" name). `device_config.py` and its json file
are kept around only for that migration path; nothing writes to
`device_config.json` since.

**Devices window** (`src/gui/devices_window.py`, `DevicesWindow`):
lists every device under "Single devices" (ungrouped) and then every
group under "Grouped devices", each device row with a "Change name"
button. Renaming only ever touches `display_name` locally - it's never
sent to the bulb. An "Add device" button opens the existing
`DeviceConfigDialog` to register a new bulb's ID/IP/local key.

### Device Discovery
`DeviceConfigDialog` doesn't require typing all three values by hand
anymore. A "Scan local network" button covers two of them: it listens
for local Tuya UDP broadcasts for up to 18 seconds
(`src/tuya/discovery.py`, `DEFAULT_SCAN_SECONDS`, wrapping
`tinytuya.deviceScan`) and lists whatever devices responded as
buttons; picking one fills in Device ID and IP Address. Best-effort by
design - a device only shows up if it happens to broadcast during that
window, so the button can just be clicked again rather than treating
an empty or partial result as final.

**A real bug in the scan window's length**: `tinytuya.deviceScan`'s
`maxretry` parameter isn't a retry count despite the name - it flows
straight through to `tinytuya.scanner.devices()` as `scantime`, the
number of *seconds* to keep listening. The original version of this
file passed `maxretry=2` on the wrong assumption it meant retries,
cutting the real listening window down to ~2 seconds - nowhere near
long enough for every device on a real network to broadcast at least
once, since they broadcast periodically, not continuously. Reported
live: scanning the real network with three configured bulbs found only
one of them. Fixed by defaulting to tinytuya's own recommended window
(`tinytuya.SCANTIME`, 18 seconds) explicitly, and renaming the
parameter to `scan_seconds` to describe what it actually controls.
Re-verified live: the same scan now reliably finds all three known
bulbs (plus a fourth, not-yet-configured Tuya device also on the
network) in one pass.

The local key is a separate problem: Tuya devices deliberately never
broadcast it over the LAN (that's the whole point of a *local* key),
so UDP discovery can never provide it, and it's always typed in by
hand.

**Removed: fetching the local key via the user's own Tuya Cloud
developer account** (`src/tuya/cloud_discovery.py`, `src/tuya_cloud_config.py`).
An earlier version offered this as a second option next to manual
entry, using `tinytuya.Cloud` and the user's own API region/key/secret
- the only place this app ever talked to Tuya's cloud, opt-in only.
Removed after real user reports: entering correct, correctly-scoped
credentials still produced a wrong "no local key found on this
account" error (a real bug in that path, never root-caused before the
decision was made to drop it), and separately, the credentials it
needed would sit in a plaintext local JSON file
(`tuya_cloud_credentials.json`) - not worth that for a convenience
feature layered on top of an app whose whole premise is local-only
control. Local UDP scan (device ID + IP) plus manual local-key entry
is the only path now, matching this app's core design more directly
than the removed feature ever did.

Verified live against the real network: "Scan local network" found a
real bulb and correctly filled Device ID and IP Address from it,
without ever touching `devices_config.json` (the dialog was cancelled,
not saved, specifically so a real, already-configured device wouldn't
get duplicated into the list).

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

## Merged Groups: Treating Several Bulbs as One
A plain group mirrors every command to all its members identically. A
*merged* group instead treats its members as segments of one virtual
lamp: a single logical hue/brightness/saturation value is divided
positionally across them instead of copied to each.

**Positions** (`DeviceGroup.positions: dict[device_id, str]`, `src/devices_config.py`):
each grouped device can be assigned "BASE" or "EXT-1"/"EXT-2"/... (up
to member count - 1), each label unique within the group - enforced by
`available_positions` only offering a device the labels no *other*
member currently holds (its own current label stays offered to it). Set
via a `CTkOptionMenu` in `DevicesWindow`, placed between the device's
name and its "Change name" button. `position_rank`/`ordered_merge_device_ids`
turn the positions dict into an ordered BASE, EXT-1, EXT-2, ... sequence
- the order a merged group's members represent as segments of the
virtual lamp. `can_merge` is the minimum viable merge: at least a BASE
*and* an EXT-1 assigned (a lone BASE can't split anything).

**The "Merge" button** (one per group, next to its name) toggles
`DeviceGroup.merged`. Disabled until `can_merge` is true; clicking it
again un-merges. Changing a position so `can_merge` becomes false again
(e.g. clearing EXT-1, or removing its device from the group entirely)
auto-clears `merged` too, so a merged group can never reference an
invalid position set.

**The split** (`src/tuya/device.py`, `split_value_across_bulbs(value,
max_value, count)`): a pure function distributing one logical
0..max_value reading across `count` positioned bulbs, BASE first - like
pouring `value/max_value * count` "full bulbs" worth of fill into
`count` buckets of capacity 1 each, in order. A 50% request across 3
bulbs fills BASE to 100%, EXT-1 to 50%, EXT-2 to 0%; across 2 bulbs it's
100%/0% - both are the examples the feature was specified against, and
both are covered by unit tests plus a live run against two real bulbs
(see below). Devices *without* a position always get the plain,
unsplit value regardless of merge state - they're not part of the
virtual lamp, just along for the ride, exactly like an unmerged group's
member.

**The three checkboxes** (`MainWindow._split_vars`, one per target,
default checked) say which of hue/brightness/saturation actually gets
divided this way versus mirrored as-is even while merged; they live in
the Audio Mode assignment grid itself, one column added before each of
its three existing rows (grid columns shifted right by one), and are
only shown (`_update_merge_ui_visibility`, `.grid()`/`.grid_remove()`)
while the active target resolves to a merged group. Disabled, like the
target selector and White circle, while Audio Mode is running.

**Dispatch**: `MainWindow._dispatch_colour_data` (hue/saturation/value
together - palette picks, brightness/saturation slider moves in colour
mode) and `_dispatch_brightness_only` (white-mode brightness) compute
each active bulb's per-property value from `_build_split_ranks` (each
active device's rank in the merged order, or `None` if unpositioned)
before falling through to the same `_dispatch` used for everything
else, so a merged group's partial failure behaves exactly like a plain
group's (one bulb's error doesn't block the rest, and doesn't stop the
others from getting their share). Audio Mode's hot loop applies the
identical algorithm inside `CustomMode._send` via the same
`split_value_across_bulbs`, driven by a `split_targets`/`split_ranks`
pair passed in at Audio Mode start (`MainWindow._start_audio_mode`) -
so a merged group can run one reactive show split across its bulbs the
same way a manual command would.

Verified live against the user's own real two-lamp group ("Stehlampe"):
assigned BASE/EXT-1, confirmed the Merge button's disabled → enabled
transition exactly at the BASE+EXT-1 threshold, merged it, requested
50% brightness with hue/saturation unchecked and confirmed via
`status()` on both real bulbs that BASE landed at exactly 1000 and
EXT-1 at exactly 0 (colour_data's hue component confirmed unchanged,
proving the unchecked properties stayed mirrored); swapped which lamp
held which position and got the exact reverse; unmerged and confirmed
both lamps went back to receiving the identical mirrored value. The
group's original (unpositioned, unmerged) state was restored exactly
afterward.

## Licensing: Free vs. Paid Tier
FluxHound's finalization phase (packaging for a private friends-and-
family test round, not yet a public release) introduced a free/paid
split. Free: Manual Control, Ambience Mode, and Gaming Mode with its
built-in watcher - all fully functional, no artificial throttling; the
built-in watcher's fixed defaults are genuinely good presets, not a
deliberately weakened demo. A single configured device is the only
hard cap, which makes groups and Merged Groups unavailable too without
needing separate gating logic for them (both need 2+ devices). Paid
(a valid license key) additionally unlocks: more than one device,
Audio Mode, Multi-region Mode, and the Custom Trigger Editor.

**Central gate** (`src/licensing/gate.py`): every mode/feature
availability check in the GUI routes through here - `is_unlocked()`,
`max_devices()`/`can_add_device(count)`, `is_audio_mode_allowed()`,
`is_multi_region_mode_allowed()`, `is_custom_trigger_editor_allowed()`
- rather than each mode file deciding for itself, so the free/paid
boundary lives in one reviewable place instead of being scattered
across `main_window.py`, `devices_window.py`, and the mode
implementations. All of it is pure logic (`license_check.is_licensed()`
mocked in tests), no GUI dependency.

**Gating points** (where the spec asked for it): `MainWindow.
_on_audio_mode_toggle_click`, `_on_multi_region_mode_toggled`, and
`_on_trigger_editor_click`; `DevicesWindow._on_add_device_click`. Each
checks the relevant `gate` function *before* doing anything - a
blocked multi-region checkbox reverts itself back to unchecked, a
blocked action never partially applies. Every gated point shows the
same `UpsellDialog` (`src/gui/upsell_dialog.py`) instead of a dead-end
error: what's locked, what unlocking adds, an "Enter licence key"
button straight to `LicenseWindow`, and a "Not now" to dismiss.

**License validation** (`src/licensing/license_check.py`): calls Lemon
Squeezy's public License API (`POST /v1/licenses/activate` - no store/
API key needed up front, Lemon Squeezy scopes the check to whichever
product the key itself was issued for) only when the user actually
enters a key. On success, the unlocked state is cached locally
(`src/license_config.py`, `license_config.json`, gitignored - same
sensitivity as a password); `is_licensed()` is a pure local read of
that cache afterward, *never* a network call, so nothing ever blocks
app startup on connectivity - satisfying "don't hard-require network
access on every app start" by construction (there's no code path that
could make a network call at startup) rather than needing a separate
offline-fallback branch. No real license key was available while
building this (no Lemon Squeezy store/product exists yet for FluxHound)
- the success path is covered by unit tests with the network call
mocked; the *rejected-key* path was additionally confirmed against the
real, live API (`curl` against `/v1/licenses/activate` with a bogus
key returned exactly the `{"activated": false, "error": "license_key
not found."}` shape the error-parsing code expects) - the one piece
that couldn't be fully live-verified end-to-end is the success path
against a real key, which needs a real store to exist first.

**License window** (`src/gui/license_window.py`, reachable from
Settings → License, or via any `UpsellDialog`'s "Enter licence key"
button): shows current Free/Licensed status, an entry field + Activate
button (runs the network call on a background thread, matching every
other network-touching dialog in this app), and "Remove licence" to
clear the cached state back to Free tier locally (does not contact
Lemon Squeezy - there's no corresponding server-side deactivate flow
started from this side to match).

Verified live against the real 3-bulb merged group, in the actual
free-tier (no cached license) state: clicking Activate Audio Mode,
checking Multi-region mode, clicking Custom Trigger Editor, and
clicking Add device (at the real device count) each correctly showed
`UpsellDialog` and left the underlying state completely unchanged
(`_reactive_mode` stayed `None`, the checkbox reverted itself, the
Trigger Editor window never opened, the device list was unchanged) -
while Gaming Mode's checkbox, the Ambience button, and manual controls
stayed fully enabled and functional throughout. Re-verified with a
locally seeded "unlocked" cache (no real key - see above): the same
three actions succeeded normally instead. One real bug caught in the
first pass of the test itself, not the app: destroying a parent window
immediately after a click that opens a new child `Toplevel` crashed
the Tcl interpreter, because the child's own `.after(50, ...)` modal
setup fired after its parent no longer existed - fixed in the test by
not destroying a window that might have just spawned a child dialog.

## Packaging: a Single Portable .exe
`fluxhound.spec` (repo root, versioned - it's a build recipe, not a
build artifact) builds a `--onefile`-equivalent `EXE` via `pyinstaller
fluxhound.spec`, entry point `src/main.py`. `console=False` (windowed,
no console popup); no code signing (that needs a paid certificate this
project doesn't have) - see README's SmartScreen note.

**The logo is deliberately not bundled as a PyInstaller data file.**
`MainWindow._app_root_dir()` (and every `*_config.py`'s `_app_dir()`)
already resolves relative to `sys.executable` when
`getattr(sys, "frozen", False)` - the built `.exe`'s own directory -
matching every local config file's "lives next to the portable exe"
convention. PyInstaller's own `datas=` mechanism instead extracts
bundled files into a temp dir (`sys._MEIPASS`) at every launch, which
is the wrong location for this convention. `fluxhound_logo.png` is
just copied into `dist/` alongside the built exe after building
instead (documented in README) - the app already handles a missing
logo file gracefully (no crash, just no logo layer on the live-state
indicator), so this isn't a hard requirement either.

Hidden imports/data files needed almost no manual configuration:
`pyinstaller-hooks-contrib` (installed alongside PyInstaller) already
ships hooks for `customtkinter` (its theme JSON/font assets),
`soundcard`, and several of tinytuya's/cryptography's own transitive
dependencies, auto-detected during the build. Two harmless warnings
appeared (`pycparser.lextab`/`yacctab` not found - regenerable at
runtime if actually needed; a macOS-only `AppKit` import from
`darkdetect`'s OS-theme detection, irrelevant on Windows) - neither
affected the build or the smoke test below.

**Smoke test** (no separate clean VM available in this environment -
noted here rather than silently skipped): built the exe, then ran it
from an isolated directory containing only the built `FluxHound.exe`
and `fluxhound_logo.png` - no `.venv`, no source tree, nothing on
`PYTHONPATH` that could make it "work by accident" the way running
from inside the dev environment could mask a missing dependency.
Confirmed: the window opens with the correct title, the customtkinter
theme and the logo/radial-glow live-state indicator render correctly,
`ambience_config.json` gets created in that same directory (confirming
the frozen-path resolution actually works, not just the source-mode
fallback), and the "Configure device" dialog (a nested `Toplevel`,
including the local-network-scan and manual-vs-Tuya-Cloud local-key UI
added by Device Discovery) opens and renders correctly too - exercising
more than just the main window's own construction path. This is
necessarily narrower than a true clean-machine test (same OS/Python
ABI, same set of system DLLs already present) - flagged as the one
piece of this phase that couldn't be fully verified without a second
physical or virtual Windows machine.

## Design System
A visual polish pass before the friends-and-family test round - no new
app functionality, every existing capability works exactly as before,
just presented consistently and on-brand rather than customtkinter's
generic default blue theme spread unevenly across windows built up
over many separate features.

**Brand**: a single vivid pink/magenta accent (`#FF2D91` dark-mode /
`#E91E82` light-mode) against clean neutral dark chrome - chosen over
deriving a palette from the logo file itself, since the logo's
apparent background colour in any screenshot is just whatever colour
the live-state radial glow happens to be showing at that moment, not a
fixed brand colour baked into the asset.

**Central theme** (`src/gui/theme.py` + `theme.json`): a customtkinter
colour theme JSON (mirroring the structure of customtkinter's own
bundled `blue.json`) loaded once via `ctk.set_default_color_theme()`
before any widget is constructed - `theme.apply()`, called from
`src/main.py` before `MainWindow()`. This makes every widget's
*default* colour pink/branded for free, without passing `fg_color=`
explicitly at each of the hundreds of construction sites across every
window. `theme.py` also carries: named constants for the handful of
places code still needs an explicit colour instead of the global
default (`ERROR_COLOR`, `TEXT_MUTED_COLOR`, `SECONDARY_BUTTON_COLOR`
for Cancel/Remove-style buttons, `CANVAS_BORDER_COLOR`/`CANVAS_BG_COLOR`
for raw `tkinter.Canvas` widgets which don't understand CTk's
`(light, dark)` colour-tuple convention); a spacing scale
(`SPACE_XS`..`SPACE_SECTION`) so padding is consistent instead of
arbitrary numbers repeated at each call site; font factory functions
(`font_title()`/`font_heading()`/`font_subheading()`/`font_body()`/
`font_small()`/`font_badge()`) instead of ad hoc `ctk.CTkFont(...)`
calls, and `theme.json`'s own `CTkFont` section sets "Segoe UI" as the
default family on Windows (the actual native Windows UI font, chosen
over customtkinter's default "Roboto" specifically so the app reads as
a native Windows app rather than needing a bundled font). Every
hardcoded blue/gray literal that predated this pass (the Audio Mode
grid's selected-cell highlight, the region-selector's drag rectangle,
every dialog's Cancel/error/muted-status colours) now routes through
these instead.

**App icon** (`fluxhound.ico`, `theme.apply_icon()`): generated from
`fluxhound_logo.png` with no PIL dependency - Tk's own `PhotoImage`
(`subsample`/`zoom` for exact-ratio resizing, `.write(..., format=
"png")` for output, both already used elsewhere in this app's no-PIL
image work) produces 16/32/48/256px PNGs, packed into a minimal ICO
container built by hand with `struct` (modern ICO format embeds PNG
data directly per entry - no BMP conversion needed). Wired into every
window's title bar (`theme.apply_icon(window)`, one call added to each
`Toplevel` subclass's `__init__`) and into `fluxhound.spec` twice:
bundled as a data file (so the runtime `iconbitmap()` calls can find it
when frozen) and as the exe's own embedded icon resource via `icon=
'fluxhound.ico'` (Explorer/taskbar/pinned-shortcut icon, a separate
mechanism from the runtime calls). **Known limitation**: the source
logo is detailed line art (fine linework - eyes, headphone cable,
texture lines) that doesn't survive small-size downscaling - the
16x16/32x32/48x48 renditions are technically present (not the generic
Python fallback the finalization phase's own instructions called out
to avoid) but not clearly legible as "a dog head" at a glance. Confirmed
by direct inspection of each generated size, not just assumed. A
proper small-size icon needs a separately designed, simplified mark
(bold shape, no fine interior linework) - not something derivable from
the existing source art by any amount of scriptable resizing. Flagged
here rather than approximated further.

**Layout** (`src/gui/main_window.py`): the main window's constructor
used to pack every control from this app's entire feature history
(manual controls, Audio Mode's 3x3 grid, Ambience/Gaming/Multi-region/
Trigger Editor controls) into one long vertically-scrolling column.
It's now a persistent header (branding, live-state indicator, target
selector - shared context every screen needs) above a `CTkTabview`
with three tabs (Manual / Audio / Ambience), each with its own
`CTkScrollableFrame` so a tab that grows, or a cramped DPI-scaled
layout, never crops content instead of needing the window itself to
grow. Every widget kept its exact `self.xxx` attribute name through
this move - only which frame each one is packed into changed - so the
dozens of existing event handlers referencing those widgets elsewhere
in the file needed no changes; this was a deliberate constraint to keep
a large layout change low-risk to the underlying functionality.

**Free/paid visibility** (`theme.pro_badge()`): a small pink "PRO" pill
packed next to every paid-tier control (Activate Audio Mode, Multi-
region mode, Custom Trigger Editor) - shown unconditionally, not only
once a user clicks through to `UpsellDialog`, on the reasoning that
which tier a feature belongs to is a fixed product fact worth showing
at a glance, the same way many apps keep a "PRO" tag on premium menu
items even for subscribers already on that tier (so it doesn't need to
react to the current licence state, avoiding any state-sync risk).
`UpsellDialog` itself also got a matching badge treatment and now uses
`theme.font_heading()`/`theme.TEXT_MUTED_COLOR` instead of one-off
values.

**Explicit UI states** (`MainWindow._set_status`): every status message
now gets an icon and colour matching its actual nature, inferred from
the message text itself so none of the ~15 existing call sites needed
changes - an error (red, "⚠"), an in-progress action (muted, "⏳",
animated trailing dots - every in-progress message already ends with
"...", which the animation hooks off of directly), or a steady state
(muted, "●" - "Connected", an active reactive mode's own label). Zero
configured devices now shows a guided empty state
(`empty_state_frame`: "No devices yet" heading, a one-line description,
a prominent "Add Device" button, tabs hidden) instead of a blank/
disabled-looking screen behind an auto-popped dialog -
`_refresh_target_selector` was already the one place that knew "zero
devices vs. some" for every code path (startup, add, remove the last
device), so it toggles between the empty state and the normal view.

**DPI scaling**: verified at customtkinter's own simulated 100%/125%/
150% widget scaling (`ctk.set_widget_scaling()`/`set_window_scaling()`)
rather than changing the real Windows display-scaling setting, which is
a system setting this app has no business changing on someone's
machine. All three scales screenshotted cleanly on every tab - no
cropping, no overlapping controls; the window itself grows with the
scale factor (`set_window_scaling` resizes the actual window, not just
widget content), so nothing is ever squeezed into a fixed-size frame
too small for the scaled content.

Verified live against the real 3-bulb merged group at every stage of
this pass (theme + icon, the tab restructure, the explicit states, DPI
scaling) via window-specific screenshots, plus one final full
functional regression check: a real Ambience Mode activate/deactivate
cycle through the new tab layout, confirming actual bulb commands were
sent (captured via a wrapped `set_colour_data_value_nowait`, not just
widget state) and a clean restore on deactivate - the redesign changed
nothing about the underlying behaviour. `devices_config.json`/
`ambience_config.json` confirmed byte-identical before/after every
test in this pass; the real bulbs were left switched off afterward. One
mid-pass screenshotting mistake is worth recording: a full-screen
(rather than window-specific) capture briefly exposed unrelated content
on the rest of the desktop (other open browser tabs) - caught
immediately, the file was deleted without further use, and every
subsequent screenshot in this pass used the window-specific `PrintWindow`
capture method already established earlier in this project's history
specifically to avoid this.

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
Mode" above for how it switches meaning. Confirmed against the
physical bulb: 0 (left end of the slider) reads warm, 1000 (right end)
reads cool - matches the live-state indicator's warm/cool gradient
(`WARM_WHITE_RGB` at temperature 0, `COOL_WHITE_RGB` at 1000 in
`src/gui/main_window.py`).

## Coding Conventions
- Files/modules, variables, functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- "Private" (convention only): leading underscore `_helper()`
- Docstrings for all public functions/classes
- Code, comments, docstrings, commit messages: English only
