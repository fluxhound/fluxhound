"""Unit tests for src.licensing.license_check (tinytuya-style mocking of the
network call - no real Lemon Squeezy API access)."""
from __future__ import annotations

import io
import json
import urllib.error

import pytest

from src import license_config
from src.licensing import license_check


class _FakeResponse:
    def __init__(self, data: dict):
        self._data = json.dumps(data).encode("utf-8")

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_activate_persists_unlocked_state_on_success(tmp_path, monkeypatch):
    monkeypatch.setattr(license_config, "CONFIG_PATH", tmp_path / "license_config.json")
    monkeypatch.setattr(
        license_check.urllib.request, "urlopen",
        lambda request, timeout: _FakeResponse({"activated": True, "instance": {"id": "inst-1"}}),
    )

    license_check.activate("KEY-123")

    state = license_config.load()
    assert state.unlocked is True
    assert state.key == "KEY-123"
    assert state.instance_id == "inst-1"


def test_activate_raises_license_error_when_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(license_config, "CONFIG_PATH", tmp_path / "license_config.json")
    monkeypatch.setattr(
        license_check.urllib.request, "urlopen",
        lambda request, timeout: _FakeResponse({"activated": False, "error": "This licence key does not exist."}),
    )

    with pytest.raises(license_check.LicenseError, match="does not exist"):
        license_check.activate("BAD-KEY")

    assert license_config.load().unlocked is False


def test_activate_rejects_an_empty_key_without_a_network_call(tmp_path, monkeypatch):
    monkeypatch.setattr(license_config, "CONFIG_PATH", tmp_path / "license_config.json")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("should not make a network call for an empty key")

    monkeypatch.setattr(license_check.urllib.request, "urlopen", fail_if_called)

    with pytest.raises(license_check.LicenseError):
        license_check.activate("   ")


def test_activate_parses_the_error_body_of_an_http_error(tmp_path, monkeypatch):
    monkeypatch.setattr(license_config, "CONFIG_PATH", tmp_path / "license_config.json")

    def raise_http_error(request, timeout):
        body = json.dumps({"activated": False, "error": "Licence key has expired."}).encode("utf-8")
        raise urllib.error.HTTPError(
            url=license_check.ACTIVATE_URL, code=404, msg="Not Found", hdrs=None, fp=io.BytesIO(body),
        )

    monkeypatch.setattr(license_check.urllib.request, "urlopen", raise_http_error)

    with pytest.raises(license_check.LicenseError, match="expired"):
        license_check.activate("EXPIRED-KEY")


def test_activate_falls_back_to_a_generic_message_for_an_unparseable_error_body(tmp_path, monkeypatch):
    monkeypatch.setattr(license_config, "CONFIG_PATH", tmp_path / "license_config.json")

    def raise_http_error(request, timeout):
        raise urllib.error.HTTPError(
            url=license_check.ACTIVATE_URL, code=500, msg="Internal Server Error",
            hdrs=None, fp=io.BytesIO(b"not json"),
        )

    monkeypatch.setattr(license_check.urllib.request, "urlopen", raise_http_error)

    with pytest.raises(license_check.LicenseError):
        license_check.activate("SOME-KEY")


def test_deactivate_clears_the_cached_state(tmp_path, monkeypatch):
    monkeypatch.setattr(license_config, "CONFIG_PATH", tmp_path / "license_config.json")
    license_config.save(license_config.LicenseState(key="K", instance_id="i", unlocked=True))

    license_check.deactivate()

    assert license_check.is_licensed() is False
    assert license_config.load() == license_config.LicenseState()


def test_is_licensed_never_makes_a_network_call(tmp_path, monkeypatch):
    """The whole point of caching locally: app startup must never block on
    connectivity just to check the license state."""
    monkeypatch.setattr(license_config, "CONFIG_PATH", tmp_path / "license_config.json")
    license_config.save(license_config.LicenseState(key="K", instance_id="i", unlocked=True))

    def fail_if_called(*args, **kwargs):
        raise AssertionError("is_licensed() must never touch the network")

    monkeypatch.setattr(license_check.urllib.request, "urlopen", fail_if_called)

    assert license_check.is_licensed() is True
