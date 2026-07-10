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

Copy `src/local_config.py.example` to `src/local_config.py` and fill
in the device ID, IP address, and local key of your test bulb.
`src/local_config.py` is gitignored and must never be committed.

## Run

```
python -m src.main
```

## Project layout

See `ARCHITECTURE.md` for architecture, coding conventions, and the Tuya
DP schema.
