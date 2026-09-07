from __future__ import annotations

from trading_execution.monitor import evaluate_monitor_state, monitor_once


class FakeAdapter:
    def __init__(self, health, positions, orders):
        self._health = health
        self._positions = positions
        self._orders = orders

    def health(self):
        return self._health

    def list_positions(self):
        return self._positions

    def list_open_orders(self):
        return self._orders


def test_monitor_alerts_on_broker_disconnect():
    alerts = evaluate_monitor_state(
        health={"connected": False, "broker": "ibkr"},
        positions=[],
        orders=[],
        config={"risk_limits": {"max_open_positions": 1}, "allowed_symbols": {"MES": {}}},
    )
    assert "broker_disconnected" in alerts


def test_monitor_flags_live_position_without_stop_order():
    alerts = evaluate_monitor_state(
        health={"connected": True, "broker": "ibkr"},
        positions=[{"symbol": "MESM6", "quantity": 1}],
        orders=[],
        config={"risk_limits": {"max_open_positions": 1}, "allowed_symbols": {"MES": {}}},
    )
    assert "position_present" in alerts
    assert "position_without_open_protective_order" in alerts


def test_monitor_blocks_full_size_es_position():
    alerts = evaluate_monitor_state(
        health={"connected": True, "broker": "ibkr"},
        positions=[{"symbol": "ESM6", "quantity": 1}],
        orders=[{"symbol": "ESM6", "order_type": "STOP"}],
        config={"risk_limits": {"max_open_positions": 1}, "allowed_symbols": {"MES": {}}},
    )
    assert "non_whitelisted_position" in alerts


def test_monitor_once_accepts_adapter_for_ibkr_supervision():
    result = monitor_once(
        adapter=FakeAdapter(
            health={"connected": True, "broker": "ibkr"},
            positions=[{"symbol": "MESM6", "quantity": 1}],
            orders=[{"symbol": "MESM6", "order_type": "STOP"}],
        ),
        config={"risk_limits": {"max_open_positions": 1}, "allowed_symbols": {"MES": {}}},
    )
    assert result["health"]["connected"] is True
    assert result["positions"][0]["symbol"] == "MESM6"
    assert "position_present" in result["alerts"]
    assert "position_without_open_protective_order" not in result["alerts"]
