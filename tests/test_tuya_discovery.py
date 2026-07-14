"""Unit tests for src.tuya.discovery (tinytuya.deviceScan mocked, no real network)."""
from __future__ import annotations

import tinytuya

from src.tuya.discovery import DEFAULT_SCAN_SECONDS, DiscoveredDevice, discover_devices


def test_discover_devices_extracts_id_ip_and_version(monkeypatch):
    monkeypatch.setattr(
        tinytuya, "deviceScan",
        lambda **kwargs: {
            "192.168.1.10": {
                "gwId": "abc123", "ip": "192.168.1.10", "version": "3.3",
            },
        },
    )
    devices = discover_devices()
    assert devices == [DiscoveredDevice(device_id="abc123", ip_address="192.168.1.10", protocol_version=3.3)]


def test_discover_devices_falls_back_to_id_field_when_gwid_missing(monkeypatch):
    monkeypatch.setattr(
        tinytuya, "deviceScan",
        lambda **kwargs: {"192.168.1.11": {"id": "xyz789", "ip": "192.168.1.11", "version": "3.4"}},
    )
    devices = discover_devices()
    assert devices == [DiscoveredDevice(device_id="xyz789", ip_address="192.168.1.11", protocol_version=3.4)]


def test_discover_devices_skips_entries_missing_id_or_ip(monkeypatch):
    monkeypatch.setattr(
        tinytuya, "deviceScan",
        lambda **kwargs: {
            "a": {"gwId": "abc123", "ip": "192.168.1.10", "version": "3.3"},
            "b": {"gwId": "", "ip": "192.168.1.11", "version": "3.3"},
            "c": {"gwId": "def456", "ip": "", "version": "3.3"},
        },
    )
    devices = discover_devices()
    assert len(devices) == 1
    assert devices[0].device_id == "abc123"


def test_discover_devices_defaults_to_33_on_bad_or_missing_version(monkeypatch):
    monkeypatch.setattr(
        tinytuya, "deviceScan",
        lambda **kwargs: {"a": {"gwId": "abc123", "ip": "192.168.1.10", "version": "not-a-number"}},
    )
    devices = discover_devices()
    assert devices[0].protocol_version == 3.3


def test_discover_devices_returns_empty_list_when_nothing_found(monkeypatch):
    monkeypatch.setattr(tinytuya, "deviceScan", lambda **kwargs: {})
    assert discover_devices() == []


def test_discover_devices_uses_a_long_enough_scan_window_to_catch_multiple_devices(monkeypatch):
    """Regression test: an earlier version passed maxretry=2, which tinytuya treats
    as a 2-second listening window - nowhere near long enough for every device on a
    real network to broadcast at least once, so a scan reliably missed devices on a
    live 3-bulb network. maxretry must default to tinytuya's own recommended window
    (18s, DEFAULT_SCAN_SECONDS) unless the caller overrides it."""
    captured = {}
    monkeypatch.setattr(tinytuya, "deviceScan", lambda **kwargs: captured.update(kwargs) or {})

    discover_devices()

    assert captured["maxretry"] == DEFAULT_SCAN_SECONDS == 18


def test_discover_devices_passes_through_a_custom_scan_seconds(monkeypatch):
    captured = {}
    monkeypatch.setattr(tinytuya, "deviceScan", lambda **kwargs: captured.update(kwargs) or {})

    discover_devices(scan_seconds=5)

    assert captured["maxretry"] == 5
