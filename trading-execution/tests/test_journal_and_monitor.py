from __future__ import annotations

import json
from pathlib import Path

from trading_execution.config import load_config
from trading_execution.journal import write_trade_journal
from trading_execution.models import TradeIntent
from trading_execution.monitor import monitor_once
from trading_execution.risk import evaluate_intent
from trading_execution.schema import load_trade_intent_json


def test_journal_write_creates_auditable_file(tmp_path):
    payload = load_trade_intent_json(Path(__file__).resolve().parents[1] / "examples/mes_paper_intent.json")
    intent = TradeIntent.from_dict(payload)
    decision = evaluate_intent(intent, load_config())
    out = write_trade_journal(intent, decision, tmp_path)
    data = json.loads(out.read_text())
    assert data["intent"]["intent_id"] == "TI-20990101-synth1"
    assert data["risk_decision"]["approved"] is False
    assert "kill_switch_enabled" in data["risk_decision"]["reasons"]
    assert data["postmortem"] is None


def test_monitor_once_is_stubbed_safe():
    result = monitor_once()
    assert result["health"]["mode"] == "safe"
    assert result["positions"] == []
    assert result["open_orders"] == []
