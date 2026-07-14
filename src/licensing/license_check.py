"""License validation via Lemon Squeezy's License API.

activate() is the only thing that ever needs network access - it validates a
key against https://api.lemonsqueezy.com/v1/licenses/activate (a public
endpoint: no store/API key needed up front, Lemon Squeezy scopes the check to
whichever product the key itself was issued for) and, if accepted, persists
the unlocked state locally (src/license_config.py). is_licensed() is a pure
local read of that cached state afterward - never a network call - so nothing
here ever blocks app startup on connectivity, satisfying the "don't hard-
require network access on every app start" requirement by construction rather
than needing a separate offline-fallback code path.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from src import license_config

ACTIVATE_URL = "https://api.lemonsqueezy.com/v1/licenses/activate"
INSTANCE_NAME = "FluxHound"
REQUEST_TIMEOUT_SECONDS = 8


class LicenseError(Exception):
    """A license key was explicitly rejected by Lemon Squeezy (invalid,
    expired, activation-limit reached, etc.) - distinct from a connectivity
    failure (urllib.error.URLError/OSError), which callers should surface
    differently ("check your connection" rather than "invalid key")."""


def _post(url: str, data: dict) -> dict:
    body = json.dumps(data).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Lemon Squeezy returns a JSON body with an "error" field even on 4xx/5xx
        # responses (e.g. an invalid key) - only fall back to a generic message
        # if that body genuinely isn't parseable.
        try:
            return json.loads(exc.read().decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise LicenseError("The licence server returned an unexpected response.") from exc


def activate(key: str) -> None:
    """Activate a licence key against Lemon Squeezy and, if accepted, persist
    the unlocked state locally. Raises LicenseError for a rejected key;
    connectivity failures (urllib.error.URLError, socket.timeout, etc.)
    propagate as-is for the caller to distinguish from a genuinely bad key."""
    key = key.strip()
    if not key:
        raise LicenseError("Enter a licence key.")
    result = _post(ACTIVATE_URL, {"license_key": key, "instance_name": INSTANCE_NAME})
    if not result.get("activated", False):
        raise LicenseError(result.get("error") or "Licence key was rejected.")
    instance_id = (result.get("instance") or {}).get("id")
    license_config.save(license_config.LicenseState(key=key, instance_id=instance_id, unlocked=True))


def deactivate() -> None:
    """Clear the locally cached unlocked state. A local "log out" only - does
    not contact Lemon Squeezy to release the activation slot, since the app
    has no corresponding "deactivate" flow started from this side to match."""
    license_config.save(license_config.LicenseState())


def is_licensed() -> bool:
    """Whether the app is currently unlocked - a pure local read, never a
    network call, so this can be called freely (including at startup) without
    ever blocking on connectivity."""
    return license_config.load().unlocked
