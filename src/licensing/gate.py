"""Central feature gating: free vs. paid tier.

Every mode/feature availability check in the GUI routes through here, rather
than each mode file deciding for itself, so the free/paid boundary lives in
one reviewable place.

Free tier: Manual Control, Ambience Mode, and Gaming Mode with its built-in,
fixed-default watcher (src/screen/health_bar.py's TriggerConfig()) - all
fully functional, no artificial throttling. A single configured device means
groups and Merged Groups are naturally unavailable too (both need 2+ devices),
without needing separate gating logic for them.

Paid tier (a valid license key - see src/licensing/license_check.py)
additionally unlocks: more than one configured device, Audio Mode,
Multi-region Mode, and the Custom Trigger Editor (src/gui/trigger_editor_window.py).
"""
from __future__ import annotations

from src.licensing import license_check

FREE_MAX_DEVICES = 1


def is_unlocked() -> bool:
    """Whether the app currently has a valid, active license."""
    return license_check.is_licensed()


def max_devices() -> int | None:
    """The most devices the current tier allows configuring at once, or None
    for unlimited."""
    return None if is_unlocked() else FREE_MAX_DEVICES


def can_add_device(current_count: int) -> bool:
    """Whether one more device can be configured given how many already are."""
    limit = max_devices()
    return limit is None or current_count < limit


def is_audio_mode_allowed() -> bool:
    return is_unlocked()


def is_multi_region_mode_allowed() -> bool:
    return is_unlocked()


def is_custom_trigger_editor_allowed() -> bool:
    return is_unlocked()
