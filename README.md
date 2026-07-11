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

## Project layout

See `ARCHITECTURE.md` for architecture, coding conventions, and the Tuya
DP schema.

## About

FluxHound is built with substantial help from AI pair-programming
(Claude Code). Architecture decisions, testing against real hardware,
and review are human-driven; a fair share of the implementation itself
is AI-assisted.
