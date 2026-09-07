from __future__ import annotations

import importlib.util
from unittest.mock import patch
from pathlib import Path


def load_watchdog_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "mes_external_failure_watchdog.py"
    spec = importlib.util.spec_from_file_location("mes_external_failure_watchdog", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    with patch.dict("os.environ", {"ANALYST_EXECUTION_ROOT": "/tmp/synthetic-execution", "ANALYST_HERMES_HOME": "/tmp/synthetic-hermes"}):
        spec.loader.exec_module(module)
    return module


def test_invalid_bid_ask_quote_quality_is_unhealthy():
    mod = load_watchdog_module()
    status = {
        "broker_health_ok": True,
        "monitor_ok": True,
        "market_snapshot_connected": True,
        "stream_ok": True,
        "quote_quality_ok": False,
        "quote_quality_reason": "invalid_bid_ask",
        "monitor_alerts": [],
    }

    assert mod.is_unhealthy(status, None) is True
    assert "quote_quality=False" in mod.health_key(status, None)


def test_auto_heal_restarts_streamer_for_invalid_book_after_cooldown(monkeypatch):
    mod = load_watchdog_module()
    calls = []
    monkeypatch.setattr(mod, "run_systemctl", lambda *args: calls.append(args) or True)
    status = {
        "broker_health_ok": True,
        "monitor_ok": True,
        "market_snapshot_connected": True,
        "stream_ok": True,
        "quote_quality_ok": False,
        "quote_quality_reason": "invalid_bid_ask",
        "monitor_alerts": [],
    }

    actions = mod.auto_heal(status, None, now=1_000, prior={})

    assert actions == ["restart_mes_streamer:invalid_bid_ask"]
    assert calls == [("restart", "mes-streamer.service")]


def test_auto_heal_does_not_restart_when_login_required(monkeypatch):
    mod = load_watchdog_module()
    calls = []
    monkeypatch.setattr(mod, "run_systemctl", lambda *args: calls.append(args) or True)
    status = {"broker_health_ok": False, "broker_health_error": "ConnectionRefusedError", "ibkr_port": 4001}

    actions = mod.auto_heal(status, None, now=1_000, prior={})

    assert actions == []
    assert calls == []
