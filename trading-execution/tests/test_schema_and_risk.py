from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from trading_execution.config import load_config as load_staging_config

def load_config():
    # Synthetic risk-math fixture only; never used with a real broker.
    config = load_staging_config()
    config["kill_switch"] = False
    return config
from trading_execution.models import TradeIntent
from trading_execution.risk import evaluate_intent
from trading_execution.schema import validate_trade_intent_payload

EXAMPLE = json.loads((Path(__file__).resolve().parents[1] / "examples/mes_paper_intent.json").read_text())


def intent(overrides=None):
    payload = copy.deepcopy(EXAMPLE)
    if overrides:
        payload.update(overrides)
    validate_trade_intent_payload(payload)
    return TradeIntent.from_dict(payload)


def test_example_mes_intent_passes_risk_gate():
    decision = evaluate_intent(intent(), load_config())
    assert decision.approved, decision.reasons
    assert decision.computed_loss_usd == pytest.approx(50.0)


def test_live_mode_requires_explicit_live_config():
    payload = copy.deepcopy(EXAMPLE)
    payload["mode"] = "live"
    validate_trade_intent_payload(payload)
    config = load_config()
    config["mode"] = "live"
    config["allow_live_orders"] = False
    decision = evaluate_intent(TradeIntent.from_dict(payload), config)
    assert not decision.approved
    assert "live_orders_not_enabled" in decision.reasons


def test_live_mes_two_contract_cap_can_be_approved_with_explicit_live_config():
    payload = copy.deepcopy(EXAMPLE)
    payload.update({"mode": "live", "contracts": 2, "max_loss_usd": 100.0})
    validate_trade_intent_payload(payload)
    config = load_config()
    config["mode"] = "live"
    config["allow_live_orders"] = True
    config["allowed_symbols"]["MES"]["max_contracts"] = 2
    config["risk_limits"]["max_contracts_total"] = 2
    config["risk_limits"]["max_trade_loss_usd"] = 100

    decision = evaluate_intent(TradeIntent.from_dict(payload), config)

    assert decision.approved, decision.reasons
    assert decision.computed_loss_usd == pytest.approx(100.0)


def test_missing_human_approval_is_rejected_when_config_requires_manual_approval():
    approved_intent = intent({"human_approval": None})
    config = load_config()
    config["require_human_approval"] = True
    decision = evaluate_intent(approved_intent, config)
    assert not decision.approved
    assert "human_approval_missing" in decision.reasons


def test_full_size_es_contracts_are_disabled_initially():
    decision = evaluate_intent(intent({"symbol": "ES", "max_loss_usd": 50.0}), load_config())
    assert not decision.approved
    assert "symbol_contract_limit_exceeded" in decision.reasons


def test_gold_is_not_allowed_for_initial_mes_execution():
    decision = evaluate_intent(intent({"symbol": "MGC", "max_loss_usd": 50.0}), load_config())
    assert not decision.approved
    assert "symbol_contract_limit_exceeded" in decision.reasons


def test_excess_stop_loss_is_rejected():
    too_wide = intent({"stop_price": 5100.0, "max_loss_usd": 1500.0})
    decision = evaluate_intent(too_wide, load_config())
    assert not decision.approved
    assert "computed_stop_loss_exceeds_trade_limit" in decision.reasons
