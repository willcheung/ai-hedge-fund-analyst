from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from trading_execution.config import state_root
from typing import Any, Protocol

from trading_execution.models import TradeIntent
from trading_execution.risk import evaluate_intent


@dataclass
class PaperOrderState:
    last_signal_key: str | None = None
    pending_order_until: str | None = None
    pending_signal_family: str | None = None
    last_placement_intent_id: str | None = None


class BrokerAdapter(Protocol):
    def list_positions(self) -> list[dict[str, Any]]: ...
    def list_open_orders(self) -> list[dict[str, Any]]: ...
    def place_bracket_order(self, intent: TradeIntent) -> dict[str, Any]: ...


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _root_symbol(item: dict[str, Any]) -> str:
    return str(item.get("root_symbol") or item.get("symbol") or "").upper()[:3]


def _active_mes_exposure(adapter: BrokerAdapter) -> bool:
    positions = adapter.list_positions()
    for pos in positions:
        if _root_symbol(pos) == "MES" and abs(float(pos.get("quantity") or 0)) > 0:
            return True
    orders = adapter.list_open_orders()
    for order in orders:
        status = str(order.get("status") or "").lower()
        if _root_symbol(order) == "MES" and status not in {"cancelled", "inactive", "filled"}:
            return True
    return False


def signal_key(signal: dict[str, Any]) -> str:
    material = {
        "state": signal.get("state"),
        "symbol": signal.get("symbol"),
        "side": signal.get("side"),
        "entry_price": signal.get("entry_price"),
        "stop_price": signal.get("stop_price"),
        "target_price": signal.get("target_price"),
        "reason": signal.get("reason"),
    }
    raw = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def signal_family(signal: dict[str, Any]) -> str:
    return "|".join(
        [
            str(signal.get("symbol") or "").upper(),
            str(signal.get("side") or "").upper(),
            str(signal.get("reason") or ""),
        ]
    )


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _cooldown_active(state: PaperOrderState, family: str, now: datetime) -> bool:
    until = _parse_utc(state.pending_order_until)
    if until is None or until <= now:
        state.pending_order_until = None
        state.pending_signal_family = None
        return False
    return state.pending_signal_family == family


def _max_contracts(config: dict[str, Any], symbol: str) -> int:
    spec = config.get("allowed_symbols", {}).get(symbol.upper(), {})
    symbol_cap = int(spec.get("max_contracts", 0))
    total_cap = int(config.get("risk_limits", {}).get("max_contracts_total", 0))
    return max(0, min(symbol_cap, total_cap))


def build_intent_from_signal(signal: dict[str, Any], config: dict[str, Any], *, now: datetime | None = None) -> TradeIntent:
    now = now or _now_utc()
    symbol = str(signal.get("symbol") or "MES").upper()
    contract_cap = _max_contracts(config, symbol)
    entry = float(signal["entry_price"])
    stop = float(signal["stop_price"])
    dollars_per_point = float(config.get("allowed_symbols", {}).get(symbol, {}).get("dollars_per_point", 5))
    per_contract_loss = abs(entry - stop) * dollars_per_point
    trade_loss_limit = float(config.get("risk_limits", {}).get("max_trade_loss_usd", 0))
    risk_sized_contracts = contract_cap if per_contract_loss <= 0 else math.floor(trade_loss_limit / per_contract_loss)
    contracts = max(0, min(contract_cap, risk_sized_contracts))
    if contracts <= 0:
        raise ValueError("risk_limit_allows_zero_contracts")
    max_loss = abs(entry - stop) * dollars_per_point * contracts
    intent_id = f"PAPER-{now.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    return TradeIntent(
        intent_id=intent_id,
        created_at=now.isoformat(),
        mode="paper",
        broker="ibkr",
        symbol=symbol,
        side=str(signal["side"]).upper(),  # type: ignore[arg-type]
        contracts=contracts,
        entry_type="LIMIT",
        limit_price=entry,
        stop_price=stop,
        target_price=float(signal["target_price"]) if signal.get("target_price") is not None else None,
        max_loss_usd=max_loss,
        thesis=f"{signal.get('reason') or 'strategy_entry'}; paper algo test",
        invalidation=signal.get("invalidation"),
        expires_at=(now + timedelta(minutes=5)).isoformat(),
        requires_human_approval=bool(config.get("require_human_approval", False)),
        human_approval=None,
    )


def append_learning_event(event: dict[str, Any], path: str | Path = state_root() / "learning/events.jsonl") -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")


def route_entry_signal(
    signal: dict[str, Any],
    config: dict[str, Any],
    *,
    adapter: BrokerAdapter,
    state: PaperOrderState,
    macro_gate: dict[str, Any] | None = None,
    learning_path: str | Path | None = None,
) -> dict[str, Any]:
    now = _now_utc()
    if signal.get("state") != "ENTRY_READY":
        result = {"action": "skipped", "reason": "not_entry_ready", "state": signal.get("state")}
    elif macro_gate and macro_gate.get("allow_new_entries") is False:
        result = {"action": "blocked", "reason": "macro_gate_blocked", "macro_gate": macro_gate}
    elif not config.get("auto_order_routing_enabled", False) or not config.get("live_money_risk_acknowledged", False):
        result = {
            "action": "blocked",
            "reason": "auto_order_routing_disabled",
            "detail": "real-money MES auto order routing requires auto_order_routing_enabled=true and live_money_risk_acknowledged=true",
        }
    else:
        key = signal_key(signal)
        family = signal_family(signal)
        if state.last_signal_key == key:
            result = {"action": "skipped", "reason": "duplicate_signal", "signal_key": key}
        elif _cooldown_active(state, family, now):
            result = {
                "action": "blocked",
                "reason": "pending_order_cooldown",
                "signal_key": key,
                "signal_family": family,
                "pending_order_until": state.pending_order_until,
                "last_placement_intent_id": state.last_placement_intent_id,
            }
        elif _active_mes_exposure(adapter):
            result = {"action": "blocked", "reason": "broker_position_or_order_already_open", "signal_key": key}
        else:
            intent = build_intent_from_signal(signal, config, now=now)
            decision = evaluate_intent(intent, config)
            if not decision.approved:
                result = {"action": "blocked", "reason": "risk_rejected", "risk_reasons": decision.reasons, "computed_loss_usd": decision.computed_loss_usd, "signal_key": key}
            else:
                try:
                    placement = adapter.place_bracket_order(intent)
                except Exception as exc:
                    state.last_signal_key = key
                    state.pending_order_until = (now + timedelta(seconds=int(config.get("paper_order_cooldown_seconds", 120)))).isoformat()
                    state.pending_signal_family = family
                    state.last_placement_intent_id = intent.intent_id
                    result = {
                        "action": "blocked",
                        "reason": "order_placement_failed",
                        "error": str(exc),
                        "signal_key": key,
                        "intent_id": intent.intent_id,
                        "side": intent.side,
                        "symbol": intent.symbol,
                        "contracts": intent.contracts,
                        "entry_price": intent.limit_price,
                        "stop_price": intent.stop_price,
                        "target_price": intent.target_price,
                        "computed_loss_usd": decision.computed_loss_usd,
                    }
                else:
                    state.last_signal_key = key
                    state.pending_order_until = (now + timedelta(seconds=int(config.get("paper_order_cooldown_seconds", 120)))).isoformat()
                    state.pending_signal_family = family
                    state.last_placement_intent_id = intent.intent_id
                    result = {
                        "action": "placed",
                        "signal_key": key,
                        "intent_id": intent.intent_id,
                        "side": intent.side,
                        "symbol": intent.symbol,
                        "contracts": intent.contracts,
                        "entry_price": intent.limit_price,
                        "stop_price": intent.stop_price,
                        "target_price": intent.target_price,
                        "computed_loss_usd": decision.computed_loss_usd,
                        "placement": placement,
                    }
    event = {"ts": now.isoformat(), "type": "paper_order_router", "signal": {k: signal.get(k) for k in ["state", "symbol", "side", "reason", "entry_price", "stop_price", "target_price"]}, "result": result}
    if macro_gate:
        event["macro_gate"] = macro_gate
    if learning_path:
        append_learning_event(event, learning_path)
    return result
