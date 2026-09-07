from __future__ import annotations

import copy
from datetime import datetime, timezone, timedelta

from trading_execution.paper_order_router import PaperOrderState, build_intent_from_signal, route_entry_signal


def entry_signal(side="BUY"):
    return {
        "state": "ENTRY_READY",
        "symbol": "MES",
        "side": side,
        "reason": "breakout_above_or15_and_vwap" if side == "BUY" else "breakdown_below_or15_and_vwap",
        "entry_price": 5400.0,
        "stop_price": 5390.0 if side == "BUY" else 5410.0,
        "target_price": 5420.0 if side == "BUY" else 5380.0,
        "invalidation": "lose level",
        "quote": {"spread": 0.25},
    }


def config(*, live_money_risk_acknowledged=True, auto_order_routing_enabled=True):
    return {
        "mode": "paper",
        "broker": "ibkr",
        "allow_live_orders": False,
        "require_human_approval": False,
        "require_stop": True,
        "allow_market_orders": False,
        "synthetic_brackets_required": True,
        "kill_switch": False,
        "auto_order_routing_enabled": auto_order_routing_enabled,
        "live_money_risk_acknowledged": live_money_risk_acknowledged,
        "allowed_symbols": {"MES": {"dollars_per_point": 5, "max_contracts": 5}},
        "risk_limits": {"max_contracts_total": 5, "max_trade_loss_usd": 250, "max_daily_loss_usd": 750, "max_open_positions": 1},
    }


class FakeAdapter:
    def __init__(self, positions=None, orders=None):
        self.positions = positions or []
        self.orders = orders or []
        self.placed = []

    def list_positions(self):
        return copy.deepcopy(self.positions)

    def list_open_orders(self):
        return copy.deepcopy(self.orders)

    def place_bracket_order(self, intent):
        self.placed.append(intent)
        return {"placed": True, "symbol": intent.symbol, "orders": [{"role": "entry"}, {"role": "stop"}, {"role": "target"}]}


def test_build_intent_from_signal_sizes_to_configured_contract_cap():
    intent = build_intent_from_signal(entry_signal(), config(), now=datetime(2026, 6, 10, tzinfo=timezone.utc))

    assert intent.mode == "paper"
    assert intent.symbol == "MES"
    assert intent.side == "BUY"
    assert intent.contracts == 5
    assert intent.entry_type == "LIMIT"
    assert intent.limit_price == 5400.0
    assert intent.stop_price == 5390.0
    assert intent.target_price == 5420.0
    assert intent.max_loss_usd == 250.0
    assert intent.requires_human_approval is False


def test_build_intent_from_signal_sizes_down_to_trade_risk_limit():
    wide_stop = entry_signal()
    wide_stop["stop_price"] = 5380.0

    intent = build_intent_from_signal(wide_stop, config(), now=datetime(2026, 6, 10, tzinfo=timezone.utc))

    assert intent.contracts == 2
    assert intent.max_loss_usd == 200.0


def test_route_entry_signal_blocks_when_broker_already_has_position():
    adapter = FakeAdapter(positions=[{"root_symbol": "MES", "quantity": 1}])
    state = PaperOrderState()

    result = route_entry_signal(entry_signal(), config(), adapter=adapter, state=state)

    assert result["action"] == "blocked"
    assert result["reason"] == "broker_position_or_order_already_open"
    assert adapter.placed == []


def test_route_entry_signal_blocks_without_live_money_acknowledgement():
    adapter = FakeAdapter()
    state = PaperOrderState()

    result = route_entry_signal(entry_signal(), config(live_money_risk_acknowledged=False), adapter=adapter, state=state)

    assert result["action"] == "blocked"
    assert result["reason"] == "auto_order_routing_disabled"
    assert "real-money" in result["detail"]
    assert adapter.placed == []


def test_route_entry_signal_blocks_when_auto_order_routing_disabled():
    adapter = FakeAdapter()
    state = PaperOrderState()

    result = route_entry_signal(entry_signal(), config(auto_order_routing_enabled=False), adapter=adapter, state=state)

    assert result["action"] == "blocked"
    assert result["reason"] == "auto_order_routing_disabled"
    assert adapter.placed == []


def test_route_entry_signal_places_paper_bracket_when_armed_and_flat():
    adapter = FakeAdapter()
    state = PaperOrderState()

    result = route_entry_signal(entry_signal("SELL"), config(), adapter=adapter, state=state)

    assert result["action"] == "placed"
    assert result["side"] == "SELL"
    assert result["contracts"] == 5
    assert len(adapter.placed) == 1
    assert adapter.placed[0].side == "SELL"


def test_route_entry_signal_dedupes_same_signal():
    adapter = FakeAdapter()
    state = PaperOrderState()

    first = route_entry_signal(entry_signal(), config(), adapter=adapter, state=state)
    second = route_entry_signal(entry_signal(), config(), adapter=adapter, state=state)

    assert first["action"] == "placed"
    assert second["action"] == "skipped"
    assert second["reason"] == "duplicate_signal"
    assert len(adapter.placed) == 1


def test_route_entry_signal_blocks_same_family_during_pending_order_cooldown():
    adapter = FakeAdapter()
    state = PaperOrderState()

    first = route_entry_signal(entry_signal(), config(), adapter=adapter, state=state)
    shifted = entry_signal()
    shifted["entry_price"] = 5400.25
    shifted["stop_price"] = 5390.25
    shifted["target_price"] = 5420.25
    second = route_entry_signal(shifted, config(), adapter=adapter, state=state)

    assert first["action"] == "placed"
    assert second["action"] == "blocked"
    assert second["reason"] == "pending_order_cooldown"
    assert len(adapter.placed) == 1


def test_route_entry_signal_allows_same_family_after_pending_order_cooldown_expires():
    adapter = FakeAdapter()
    state = PaperOrderState(
        pending_order_until=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        pending_signal_family="MES|BUY|breakout_above_or15_and_vwap",
    )

    result = route_entry_signal(entry_signal(), config(), adapter=adapter, state=state)

    assert result["action"] == "placed"
    assert len(adapter.placed) == 1


def test_route_entry_signal_blocks_negative_macro_gate():
    adapter = FakeAdapter()
    state = PaperOrderState()

    result = route_entry_signal(entry_signal(), config(), adapter=adapter, state=state, macro_gate={"allow_new_entries": False, "reason": "risk_off"})

    assert result["action"] == "blocked"
    assert result["reason"] == "macro_gate_blocked"
    assert adapter.placed == []
