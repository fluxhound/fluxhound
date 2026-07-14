"""Windows autostart toggle: adds/removes a per-user Run key entry so
FluxHound can optionally launch automatically at login.

Uses the stdlib winreg module against HKEY_CURRENT_USER (no admin rights
needed, unlike HKEY_LOCAL_MACHINE) - matches how most consumer Windows apps
implement this, and needs no new dependency.
"""
from __future__ import annotations

import sys
import winreg

_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "FluxHound"


def _startup_command() -> str:
    """The command line Windows should run at login. Only meaningful for the
    packaged .exe - a dev run from source has no reason to autostart - but
    resolves to something runnable either way, for testability."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" -m src.main'


def is_enabled() -> bool:
    """Whether the FluxHound Run key entry currently exists."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, _VALUE_NAME)
            return True
    except FileNotFoundError:
        return False


def enable() -> None:
    """Add the Run key entry so FluxHound launches on Windows login."""
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_WRITE) as key:
        winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, _startup_command())


def disable() -> None:
    """Remove the Run key entry, if present."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_WRITE) as key:
            winreg.DeleteValue(key, _VALUE_NAME)
    except FileNotFoundError:
        pass
