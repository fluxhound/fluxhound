"""Unit tests for src.tuya.cloud_discovery (tinytuya.Cloud mocked, no real network
or Tuya account needed)."""
from __future__ import annotations

import pytest
import tinytuya

from src.tuya.cloud_discovery import CloudDevice, CloudDiscoveryError, fetch_devices_from_cloud


class _FakeCloud:
    """Stands in for tinytuya.Cloud - records the constructor args it was called
    with and returns whatever getdevices_result the test configured."""

    last_instance = None

    def __init__(self, apiRegion=None, apiKey=None, apiSecret=None):
        self.apiRegion = apiRegion
        self.apiKey = apiKey
        self.apiSecret = apiSecret
        _FakeCloud.last_instance = self

    def getdevices(self):
        return self.getdevices_result


def test_fetch_devices_from_cloud_extracts_id_key_and_name(monkeypatch):
    fake = type("F", (_FakeCloud,), {"getdevices_result": [
        {"id": "abc123", "local_key": "s3cr3t", "name": "Living Room Lamp"},
    ]})
    monkeypatch.setattr(tinytuya, "Cloud", fake)

    devices = fetch_devices_from_cloud("us", "key", "secret")

    assert devices == [CloudDevice(device_id="abc123", local_key="s3cr3t", name="Living Room Lamp")]
    assert fake.last_instance.apiRegion == "us"
    assert fake.last_instance.apiKey == "key"
    assert fake.last_instance.apiSecret == "secret"


def test_fetch_devices_from_cloud_includes_ip_when_present(monkeypatch):
    fake = type("F", (_FakeCloud,), {"getdevices_result": [
        {"id": "abc123", "local_key": "s3cr3t", "name": "Lamp", "ip": "192.168.1.20"},
    ]})
    monkeypatch.setattr(tinytuya, "Cloud", fake)

    devices = fetch_devices_from_cloud("us", "key", "secret")

    assert devices[0].ip_address == "192.168.1.20"


def test_fetch_devices_from_cloud_falls_back_to_id_when_name_missing(monkeypatch):
    fake = type("F", (_FakeCloud,), {"getdevices_result": [{"id": "abc123", "local_key": "s3cr3t"}]})
    monkeypatch.setattr(tinytuya, "Cloud", fake)

    devices = fetch_devices_from_cloud("us", "key", "secret")

    assert devices[0].name == "abc123"


def test_fetch_devices_from_cloud_skips_devices_without_a_local_key(monkeypatch):
    fake = type("F", (_FakeCloud,), {"getdevices_result": [
        {"id": "abc123", "local_key": "s3cr3t", "name": "Has Key"},
        {"id": "def456", "local_key": "", "name": "No Key"},
    ]})
    monkeypatch.setattr(tinytuya, "Cloud", fake)

    devices = fetch_devices_from_cloud("us", "key", "secret")

    assert len(devices) == 1
    assert devices[0].device_id == "abc123"


def test_fetch_devices_from_cloud_raises_on_error_response(monkeypatch):
    fake = type("F", (_FakeCloud,), {
        "getdevices_result": {"Error": "Invalid access_token", "Err": "1010"}
    })
    monkeypatch.setattr(tinytuya, "Cloud", fake)

    with pytest.raises(CloudDiscoveryError, match="Invalid access_token"):
        fetch_devices_from_cloud("us", "bad-key", "bad-secret")


def test_fetch_devices_from_cloud_wraps_unexpected_exceptions(monkeypatch):
    def _raise(*args, **kwargs):
        raise ConnectionError("network unreachable")

    monkeypatch.setattr(tinytuya, "Cloud", _raise)

    with pytest.raises(CloudDiscoveryError, match="network unreachable"):
        fetch_devices_from_cloud("us", "key", "secret")
