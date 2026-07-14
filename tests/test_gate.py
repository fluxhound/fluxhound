"""Unit tests for src.licensing.gate (pure logic, license_check mocked)."""
from __future__ import annotations

from src.licensing import gate, license_check


def test_free_tier_limits_to_one_device(monkeypatch):
    monkeypatch.setattr(license_check, "is_licensed", lambda: False)

    assert gate.max_devices() == gate.FREE_MAX_DEVICES == 1
    assert gate.can_add_device(0) is True
    assert gate.can_add_device(1) is False


def test_unlocked_tier_has_no_device_limit(monkeypatch):
    monkeypatch.setattr(license_check, "is_licensed", lambda: True)

    assert gate.max_devices() is None
    assert gate.can_add_device(50) is True


def test_free_tier_blocks_audio_multi_region_and_trigger_editor(monkeypatch):
    monkeypatch.setattr(license_check, "is_licensed", lambda: False)

    assert gate.is_audio_mode_allowed() is False
    assert gate.is_multi_region_mode_allowed() is False
    assert gate.is_custom_trigger_editor_allowed() is False


def test_unlocked_tier_allows_audio_multi_region_and_trigger_editor(monkeypatch):
    monkeypatch.setattr(license_check, "is_licensed", lambda: True)

    assert gate.is_audio_mode_allowed() is True
    assert gate.is_multi_region_mode_allowed() is True
    assert gate.is_custom_trigger_editor_allowed() is True


def test_is_unlocked_mirrors_license_check(monkeypatch):
    monkeypatch.setattr(license_check, "is_licensed", lambda: True)
    assert gate.is_unlocked() is True
    monkeypatch.setattr(license_check, "is_licensed", lambda: False)
    assert gate.is_unlocked() is False
