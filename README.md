# FluxHound

Portable Windows desktop app for local, reactive control of Tuya RGB
bulbs via the local Tuya protocol. No cloud dependency.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Your prompt should now start with `(.venv)`. If activation is blocked by
PowerShell's execution policy, run this once and retry:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## Run

```
python -m src.main
```

On first start the app asks for your bulb's device ID, IP address, and
local key, and saves them to `device_config.json` next to the app.
That file is gitignored and never leaves your machine. Use the
"Change device" button in the app any time you need to re-enter or
switch devices.

Click "Activate Audio Mode" to make the bulb react to whatever your
system is currently playing (captured via loopback, no microphone
needed). The grid below it lets you assign Hue, Brightness, and
Saturation each to one of three signals - Timbre (tonal colour),
Energy (loudness), or Beat (hit detection) - with a sensitivity slider
per row. Manually picking a colour or moving the brightness/saturation
slider hands that one property back to you without stopping Audio Mode
for the rest. "Set to Default" resets the grid to a sensible starting
configuration; your assignment and sensitivity choices are saved to
`audio_mode_config.json` and restored on the next run.

## Building the portable .exe

```powershell
pip install pyinstaller
pyinstaller fluxhound.spec
copy fluxhound_logo.png dist\
```

The build lands at `dist\FluxHound.exe` - a single portable file, no
installer, no `.venv` needed to run it. Copy `fluxhound_logo.png`
alongside it (the app looks for it next to the running `.exe`, same as
every other config file); it's optional decoration, so the app still
runs fine without it, just without the logo on the live-state
indicator.

**Windows SmartScreen will very likely flag the built `.exe`** ("Windows
protected your PC" / unrecognized publisher) the first time it's run
on another machine. This is expected, not a bug - the binary isn't
code-signed (that requires a paid certificate this project doesn't
have yet), and SmartScreen flags any unsigned executable from an
unfamiliar source by default. Click "More info" → "Run anyway" to
proceed.

## Project layout

See `ARCHITECTURE.md` for architecture, coding conventions, and the Tuya
DP schema.

## About

FluxHound is built with substantial help from AI pair-programming
(Claude Code). Architecture decisions, testing against real hardware,
and review are human-driven; a fair share of the implementation itself
is AI-assisted.
