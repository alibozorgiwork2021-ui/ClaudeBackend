import os

import anthropic
import pytest

import claudebackend.core.client as client_mod
from claudebackend.core.client import Client, SubscriptionAuthError


def _fake_anthropic_factory(captured):
    def _fake(*args, **kwargs):
        captured["kwargs"] = kwargs
        captured["api_key_env"] = os.environ.get("ANTHROPIC_API_KEY")
        return object()

    return _fake


def test_subscription_mode_drops_env_api_key_before_constructing(monkeypatch):
    captured = {}
    monkeypatch.setattr(anthropic, "Anthropic", _fake_anthropic_factory(captured))
    monkeypatch.setattr(client_mod, "_subscription_available", lambda: True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-be-ignored")

    Client(use_subscription=True)

    # the stray key must be removed so it doesn't shadow the subscription login
    assert captured["api_key_env"] is None
    assert "api_key" not in captured["kwargs"]


def test_subscription_mode_errors_when_not_logged_in(monkeypatch):
    monkeypatch.setattr(client_mod, "_subscription_available", lambda: False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(anthropic, "Anthropic", _fake_anthropic_factory({}))

    with pytest.raises(SubscriptionAuthError):
        Client(use_subscription=True)


def test_default_mode_keeps_env_api_key(monkeypatch):
    captured = {}
    monkeypatch.setattr(anthropic, "Anthropic", _fake_anthropic_factory(captured))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-keep")

    Client()  # default (api-key) mode

    assert os.environ.get("ANTHROPIC_API_KEY") == "sk-keep"  # not popped
    assert "kwargs" in captured  # SDK constructed


def test_injected_sdk_skips_auth_resolution():
    sentinel = object()
    c = Client(sdk=sentinel, use_subscription=True)  # injected SDK wins, no auth logic
    assert c._sdk is sentinel
