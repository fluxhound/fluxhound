# FluxHound — Architecture

Technical reference for the project structure, hardware protocol, and
coding conventions used in this repository.

## Tech Stack
- Python 3.x
- GUI: customtkinter
- Tuya communication: tinytuya (local protocol, version 3.3)
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
│   ├── modes/                # manual, screen ambient, screen region alarm, etc.
│   └── licensing/            # license check module
└── tests/
```
(Structure evolves as code is written.)

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
