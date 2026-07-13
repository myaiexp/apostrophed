"""Config resolves layout/device from env with the documented precedence.

``config`` reads the environment at import time, so each case sets env then
reloads the module. The autouse fixture reloads once more afterwards (monkeypatch
having restored the real env) so a later test never sees a stale reload.
"""

from __future__ import annotations

import importlib

import pytest

from apostrophed import config


@pytest.fixture(autouse=True)
def _restore_config():  # pyright: ignore[reportUnusedFunction]  # used by pytest, not called
    yield
    importlib.reload(config)


def test_layout_prefers_explicit_override(monkeypatch):
    monkeypatch.setenv("APOSTROPHED_LAYOUT", "de")
    monkeypatch.setenv("XKB_DEFAULT_LAYOUT", "us")  # loses to the explicit var
    importlib.reload(config)
    assert config.LAYOUT == "de"


def test_layout_falls_back_to_xkb_default(monkeypatch):
    monkeypatch.delenv("APOSTROPHED_LAYOUT", raising=False)
    monkeypatch.setenv("XKB_DEFAULT_LAYOUT", "fr")
    importlib.reload(config)
    assert config.LAYOUT == "fr"


def test_layout_defaults_to_us(monkeypatch):
    monkeypatch.delenv("APOSTROPHED_LAYOUT", raising=False)
    monkeypatch.delenv("XKB_DEFAULT_LAYOUT", raising=False)
    importlib.reload(config)
    assert config.LAYOUT == "us"  # never "fi" — that was the non-portable bug


def test_variant_tracks_the_same_chain(monkeypatch):
    monkeypatch.delenv("APOSTROPHED_VARIANT", raising=False)
    monkeypatch.setenv("XKB_DEFAULT_VARIANT", "nodeadkeys")
    importlib.reload(config)
    assert config.VARIANT == "nodeadkeys"


def test_device_and_pointer_names_are_overridable(monkeypatch):
    monkeypatch.setenv("APOSTROPHED_DEVICE_NAME", "my virtual kbd")
    monkeypatch.setenv("APOSTROPHED_POINTER_NAME", "my virtual ptr")
    importlib.reload(config)
    assert config.DEVICE_NAME == "my virtual kbd"
    assert config.POINTER_NAME == "my virtual ptr"


def test_device_name_defaults_to_keyd(monkeypatch):
    monkeypatch.delenv("APOSTROPHED_DEVICE_NAME", raising=False)
    importlib.reload(config)
    assert config.DEVICE_NAME == "keyd virtual keyboard"
