from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import TradeIntent


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reasons: list[str]
    computed_loss_usd: float | None


def _prefix_symbol(symbol: str) -> str:
    upper = symbol.upper()
    if upper.startswith("MGC"):
        return "MGC"
    if upper.startswith("GC"):
        return "GC"
    if upper.startswith("MES"):
        return "MES"
    if upper.startswith("MNQ"):
        return "MNQ"
    return upper


def estimate_stop_loss(intent: TradeIntent, config: dict[str, Any]) -> float | None:
    symbol_key = _prefix_symbol(intent.symbol)
    spec = config.get("allowed_symbols", {}).get(symbol_key)
    if not spec or intent.limit_price is None:
        return None
    dollars_per_point = float(spec["dollars_per_point"])
    return abs(float(intent.limit_price) - float(intent.stop_price)) * dollars_per_point * intent.contracts


def evaluate_intent(intent: TradeIntent, config: dict[str, Any]) -> RiskDecision:
    reasons: list[str] = []
    limits = config["risk_limits"]
    symbol_key = _prefix_symbol(intent.symbol)
    symbol_spec = config.get("allowed_symbols", {}).get(symbol_key)

    if config.get("kill_switch"):
        reasons.append("kill_switch_enabled")
    config_mode = str(config.get("mode") or "paper")
    live_enabled = bool(config.get("allow_live_orders"))
    if intent.mode not in {"paper", "live"} or config_mode not in {"paper", "live"}:
        reasons.append("unknown_trading_mode")
    elif intent.mode != config_mode:
        reasons.append("intent_mode_must_match_config_mode")
    elif intent.mode == "live" and not live_enabled:
        reasons.append("live_orders_not_enabled")
    elif intent.mode == "paper" and live_enabled:
        reasons.append("live_orders_enabled_for_paper_intent")
    if intent.entry_type == "MARKET" or not config.get("allow_market_orders", False) and intent.entry_type not in {"LIMIT", "STOP_LIMIT"}:
        reasons.append("market_orders_forbidden")
    if not symbol_spec:
        reasons.append("symbol_not_allowed")
    elif intent.contracts > int(symbol_spec.get("max_contracts", 0)):
        reasons.append("symbol_contract_limit_exceeded")
    if intent.contracts > int(limits["max_contracts_total"]):
        reasons.append("total_contract_limit_exceeded")
    if config.get("require_stop") and intent.stop_price is None:
        reasons.append("stop_required")
    if config.get("require_human_approval"):
        if not intent.requires_human_approval:
            reasons.append("human_approval_flag_required")
        if not intent.human_approval or not intent.human_approval.approved:
            reasons.append("human_approval_missing")
    if intent.is_expired():
        reasons.append("intent_expired")

    computed_loss = estimate_stop_loss(intent, config)
    if computed_loss is None:
        reasons.append("unable_to_compute_stop_loss")
    else:
        if computed_loss > float(limits["max_trade_loss_usd"]):
            reasons.append("computed_stop_loss_exceeds_trade_limit")
        if computed_loss > float(intent.max_loss_usd) + 1e-9:
            reasons.append("computed_stop_loss_exceeds_intent_max_loss")
        if intent.max_loss_usd > float(limits["max_trade_loss_usd"]):
            reasons.append("intent_max_loss_exceeds_trade_limit")

    if config.get("synthetic_brackets_required") and intent.target_price is None:
        reasons.append("target_required_for_synthetic_bracket_plan")

    return RiskDecision(approved=not reasons, reasons=reasons, computed_loss_usd=computed_loss)
