#!/usr/bin/env python3
"""Silent buy-zone alert watchdog.

Prints only when a configured ticker changes alert state (enters buy zone,
breaks invalidation, or reclaims add trigger). Empty stdout means no alert.
"""
from __future__ import annotations
from automation_paths import configured_text

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

CONFIG_PATH = Path((os.environ.get("BUY_ZONE_ALERTS_CONFIG") or configured_text("${ANALYST_HERMES_HOME}/scripts/buy_zone_alerts.json")))
STATE_PATH = Path((os.environ.get("BUY_ZONE_ALERTS_STATE") or configured_text("${ANALYST_HERMES_HOME}/state/buy_zone_alerts_state.json")))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def in_market_check_window(ts: datetime) -> bool:
    # Weekdays, approximate U.S. regular-session window in UTC for current PDT season.
    # Schedule may fire around edges; keep the script quiet outside this window.
    if ts.weekday() >= 5:
        return False
    minutes = ts.hour * 60 + ts.minute
    return (13 * 60 + 25) <= minutes <= (20 * 60 + 15)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default
    except Exception:
        return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    tmp.replace(path)


def fetch_price_yfinance(symbol: str) -> tuple[float | None, str]:
    try:
        import yfinance as yf  # type: ignore
        ticker = yf.Ticker(symbol)
        fi = ticker.fast_info
        price = None
        for key in ("lastPrice", "regularMarketPrice", "previousClose"):
            try:
                v = fi.get(key) if hasattr(fi, "get") else getattr(fi, key, None)
            except Exception:
                v = None
            if v is not None:
                price = float(v)
                break
        if price is None or not math.isfinite(price):
            hist = ticker.history(period="1d", interval="1m")
            if not hist.empty:
                price = float(hist["Close"].dropna().iloc[-1])
        if price is None or not math.isfinite(price):
            return None, "no price returned"
        return price, "yfinance"
    except Exception as e:
        return None, f"price fetch failed: {type(e).__name__}: {e}"


def classify(price: float, cfg: dict) -> str:
    buy_low = float(cfg["buy_zone_low"])
    buy_high = float(cfg["buy_zone_high"])
    invalidation = cfg.get("invalidation")
    add_trigger = cfg.get("add_trigger")
    if invalidation is not None and price <= float(invalidation):
        return "INVALIDATION_BREAK"
    if buy_low <= price <= buy_high:
        return "BUY_ZONE"
    if add_trigger is not None and price >= float(add_trigger):
        return "ADD_TRIGGER_RECLAIM"
    return "NEUTRAL"


def format_alert(symbol: str, price: float, state: str, cfg: dict, source: str) -> str:
    thesis = cfg.get("thesis", "")
    buy_low = float(cfg["buy_zone_low"])
    buy_high = float(cfg["buy_zone_high"])
    invalidation = cfg.get("invalidation")
    add_trigger = cfg.get("add_trigger")
    if state == "BUY_ZONE":
        action = f"entered buy/scout zone ${buy_low:g}–${buy_high:g}"
        detail = f"Scout only; cut/avoid if it loses ${float(invalidation):g}." if invalidation is not None else "Scout only; define invalidation before sizing."
    elif state == "INVALIDATION_BREAK":
        action = f"broke invalidation ${float(invalidation):g}"
        detail = "Do not add; thesis/chart needs re-underwriting."
    elif state == "ADD_TRIGGER_RECLAIM":
        action = f"reclaimed add trigger ${float(add_trigger):g}"
        detail = "Momentum repaired; check volume/news before adding."
    else:
        action = "state changed"
        detail = ""
    lines = [
        f"BUY-ZONE ALERT: {symbol} {action}",
        f"Price: ${price:.2f} ({source}, {now_utc().strftime('%Y-%m-%d %H:%M UTC')})",
        f"Zone: ${buy_low:g}–${buy_high:g} | invalidation: ${float(invalidation):g}" + (f" | add trigger: ${float(add_trigger):g}" if add_trigger is not None else ""),
    ]
    if thesis:
        lines.append(f"Thesis: {thesis}")
    if detail:
        lines.append(detail)
    return "\n".join(lines)


def main() -> int:
    ts = now_utc()
    if not in_market_check_window(ts):
        return 0

    cfg = load_json(CONFIG_PATH, {"alerts": []})
    state = load_json(STATE_PATH, {})
    alerts = []

    for item in cfg.get("alerts", []):
        if not item.get("enabled", True):
            continue
        symbol = item["symbol"].upper()
        price, source = fetch_price_yfinance(symbol)
        if price is None:
            # Stay quiet on transient quote issues; no spam. Errors can be debugged manually.
            continue
        current_state = classify(price, item)
        prev_state = state.get(symbol, {}).get("state")
        state[symbol] = {
            "state": current_state,
            "price": price,
            "checked_at": ts.isoformat(),
        }
        if current_state != "NEUTRAL" and current_state != prev_state:
            alerts.append(format_alert(symbol, price, current_state, item, source))

    save_json(STATE_PATH, state)
    if alerts:
        print("\n\n".join(alerts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
