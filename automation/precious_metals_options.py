#!/usr/bin/env python3
"""Format option exposure supplied by an explicit private external cache."""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, Iterable, List, Optional

from private_config import load_private_json
import math


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _fmt_money(value: Any, decimals: int = 0) -> str:
    value = _f(value)
    if decimals == 0:
        return f"${value:,.0f}"
    return f"${value:,.{decimals}f}"


def _fmt_pct(value: Any, decimals: int = 1) -> str:
    return f"{_f(value):+.{decimals}f}%"


def _parse_dt(value: str) -> Optional[dt.datetime]:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        return dt.datetime.fromisoformat(text)
    except Exception:
        return None


def load_metals_options(path: Optional[str] = None) -> Dict[str, Any]:
    """No implicit account lookup, fallback summary or invented positions."""
    return load_private_json("ANALYST_METALS_OPTIONS_FILE", path=path, optional=True)


def _days_to_expiration(expiration: str, now: Optional[dt.datetime] = None) -> Optional[int]:
    try:
        exp = dt.date.fromisoformat(expiration)
    except Exception:
        return None
    now_date = (now or dt.datetime.now(dt.timezone.utc)).date()
    return (exp - now_date).days


def _bucket_expiration(days: Optional[int]) -> str:
    if days is None:
        return "unknown duration"
    if days <= 45:
        return "near-dated theta grenade"
    if days <= 220:
        return "medium-dated tactical call"
    return "long-dated structural convexity"


def _position_sort_key(pos: Dict[str, Any]) -> tuple:
    return (str(pos.get("expiration") or "9999-99-99"), _f(pos.get("strike")))


def _summarize_fragile_legs(positions: Iterable[Dict[str, Any]], spot: Optional[float]) -> List[str]:
    out: List[str] = []
    for pos in sorted(positions, key=_position_sort_key):
        days = _days_to_expiration(str(pos.get("expiration") or ""))
        if days is not None and days > 75:
            continue
        be = _f(pos.get("break_even"))
        need = ((be / spot - 1.0) * 100.0) if spot and be else None
        label = f"{pos.get('expiration')} {_f(pos.get('strike')):g}{str(pos.get('type','call'))[0].upper()}"
        if need is not None:
            out.append(f"{label}: needs {_fmt_pct(need)} to breakeven; {_bucket_expiration(days)}")
        else:
            out.append(f"{label}: {_bucket_expiration(days)}")
    return out


def format_metals_options_section(
    metals_options: Dict[str, Any],
    underlying: str,
    *,
    spot: Optional[float] = None,
    conviction_score: Optional[int] = None,
    account_value: Optional[float] = None,
) -> List[str]:
    """Return Slack-ready lines for GLD/SLV option exposure and action framing."""
    underlying = underlying.upper()
    if not metals_options:
        return []
    if metals_options.get("error"):
        return [f"**🧾 {underlying} OPTIONS:** unavailable — {metals_options['error']}"]

    positions = [p for p in metals_options.get("positions", []) if str(p.get("symbol", "")).upper() == underlying]
    summary = (metals_options.get("summary", {}).get("by_underlying", {}) or {}).get(underlying, {})
    raw_value = summary.get("market_value")
    market_value = _f(raw_value) if raw_value is not None else None
    if not positions and (market_value is None or market_value <= 0):
        return []

    generated = metals_options.get("generated_at") or "unknown time"
    gen_dt = _parse_dt(generated)
    stale_tag = ""
    if gen_dt:
        age_hours = (dt.datetime.now(dt.timezone.utc) - gen_dt.astimezone(dt.timezone.utc)).total_seconds() / 3600.0
        if age_hours > 30:
            stale_tag = f"; cache {age_hours:.0f}h old"
    elif generated == "unknown time":
        stale_tag = "; cache timestamp unknown"

    cost_basis = _f(summary.get("cost_basis"))
    unrealized = _f(summary.get("unrealized_pl"), market_value - cost_basis if cost_basis and market_value is not None else 0.0)
    delta_notional = _f(summary.get("delta_notional"))
    theta_day = _f(summary.get("theta_per_day"))
    if account_value is None:
        account_value = metals_options.get("account_value")
    if account_value is not None:
        if isinstance(account_value, bool) or not isinstance(account_value, (int, float)) or not math.isfinite(account_value) or account_value <= 0:
            raise ValueError("account_value must be a finite positive number")
        allocation = (f"{market_value / account_value * 100.0:.1f}% of configured account value"
                      if market_value is not None else "account allocation unavailable")
    else:
        allocation = "account allocation unavailable"
    lines: List[str] = []
    value_label = _fmt_money(market_value) if market_value is not None else "value unavailable"
    lines.append(f"**🧾 {underlying} OPTIONS OVERLAY:** {value_label} premium ({allocation}{stale_tag})")
    if cost_basis or delta_notional or theta_day:
        pl = f"{_fmt_money(unrealized)} P&L" if unrealized else "$0 P&L"
        lines.append(f"   Exposure: {pl}; delta-notional approx. {_fmt_money(delta_notional)}; theta approx. {_fmt_money(theta_day)}/day")

    if positions:
        # Show at most 4 legs in the futures briefing; full detail stays in the private cache.
        leg_bits: List[str] = []
        for pos in sorted(positions, key=_position_sort_key)[:4]:
            days = _days_to_expiration(str(pos.get("expiration") or ""))
            be = _f(pos.get("break_even"))
            need = ((be / spot - 1.0) * 100.0) if spot and be else None
            qty = _f(pos.get("quantity"))
            strike = _f(pos.get("strike"))
            exp = pos.get("expiration")
            mv = _fmt_money(pos.get("market_value"))
            if need is not None:
                leg_bits.append(f"{qty:g}x {exp} {strike:g}C ({mv}, BE {be:g}, needs {_fmt_pct(need)})")
            else:
                leg_bits.append(f"{qty:g}x {exp} {strike:g}C ({mv})")
        lines.append("   Legs: " + " | ".join(leg_bits))

    fragile = _summarize_fragile_legs(positions, spot)
    action_prefix = "HOLD existing convexity / NO fresh option adds"
    if conviction_score is not None and conviction_score >= 5:
        action_prefix = "HOLD; only add calls after confirmed reclaim/pullback, not green-candle chase"
    elif conviction_score is not None and conviction_score <= -2:
        action_prefix = "DEFENSIVE HOLD / consider trimming weakest near-dated calls"

    action = f"{action_prefix}. Assess duration and risk from the configured positions."
    lines.append(f"   Action: {action}")
    if fragile:
        lines.append("   Theta watch: " + " | ".join(fragile[:2]))
    return lines
