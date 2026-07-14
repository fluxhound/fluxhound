"""Tests for src/autostart.py. Runs against a scratch registry subkey (not
the real Run key) so this suite never touches the machine's actual Windows
startup behaviour."""
import winreg

import pytest

from src import autostart

_TEST_KEY_PATH = r"Software\FluxHoundAutostartTest"


@pytest.fixture(autouse=True)
def _use_scratch_registry_key(monkeypatch):
    monkeypatch.setattr(autostart, "_RUN_KEY_PATH", _TEST_KEY_PATH)
    yield
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, _TEST_KEY_PATH)
    except FileNotFoundError:
        pass


def test_is_enabled_false_when_key_absent():
    assert autostart.is_enabled() is False


def test_enable_then_is_enabled_true():
    autostart.enable()
    assert autostart.is_enabled() is True


def test_disable_removes_entry():
    autostart.enable()
    autostart.disable()
    assert autostart.is_enabled() is False


def test_disable_is_a_noop_when_not_enabled():
    autostart.disable()
    assert autostart.is_enabled() is False
