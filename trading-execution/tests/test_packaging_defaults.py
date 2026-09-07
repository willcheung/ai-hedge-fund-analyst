"""Synthetic staging tests; no broker imports/connections required."""
import json
from pathlib import Path

import pytest

from trading_execution.config import load_config, state_root
from trading_execution.schema import SCHEMA_PATH, validate_trade_intent_payload
from trading_execution.paper_order_router import route_entry_signal, PaperOrderState


def test_packaged_defaults_block_routing_without_touching_adapter(monkeypatch):
    monkeypatch.delenv("TRADING_EXECUTION_CONFIG", raising=False)
    config = load_config()
    assert config["kill_switch"] is True
    for key in ("allow_live_orders", "allow_paper_orders", "allow_market_orders",
                "auto_order_routing_enabled", "live_money_risk_acknowledged"):
        assert config[key] is False
    assert config["ibkr"]["trading_enabled"] is False
    assert config["ibkr"]["readonly"] is True
    assert "account" not in config["ibkr"]
    class UntouchableAdapter:
        def list_positions(self):
            pytest.fail("disabled routing queried positions")
        def list_open_orders(self):
            pytest.fail("disabled routing queried orders")
        def place_bracket_order(self, intent):
            pytest.fail("disabled routing attempted placement")
    result = route_entry_signal({"state": "ENTRY_READY"}, config,
                                adapter=UntouchableAdapter(), state=PaperOrderState())
    assert result["reason"] == "auto_order_routing_disabled"


def test_config_and_state_overrides_are_temporary(tmp_path, monkeypatch):
    config_path = tmp_path / "synthetic.yaml"
    config_path.write_text("mode: paper\nkill_switch: true\n")
    monkeypatch.setenv("TRADING_EXECUTION_CONFIG", str(config_path))
    monkeypatch.setenv("TRADING_EXECUTION_STATE_DIR", str(tmp_path / "state"))
    assert state_root() == tmp_path / "state"
    assert load_config()["paths"]["audit_log"] == str(tmp_path / "state/audit.jsonl")
    config_path.write_text("[]")
    with pytest.raises(ValueError):
        load_config()


def test_explicit_state_override_never_resolves_default_home(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADING_EXECUTION_STATE_DIR", str(tmp_path / "state with spaces"))
    def forbidden_home():
        raise AssertionError("unselected HOME fallback evaluated")
    monkeypatch.setattr(Path, "home", forbidden_home)
    assert state_root() == tmp_path / "state with spaces"


def test_schema_resource_is_packaged_and_matches_contract():
    root = Path(__file__).resolve().parents[1]
    assert json.loads(SCHEMA_PATH.read_text()) == json.loads((root / "schemas/trade_intent.schema.json").read_text())
    validate_trade_intent_payload(json.loads((root / "examples/mes_paper_intent.json").read_text()))
