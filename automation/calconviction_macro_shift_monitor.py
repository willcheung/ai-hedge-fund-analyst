#!/usr/bin/env python3
"""Stable change detector for the CalConviction macro-shift agent job.

Output changes only when an upstream macro artifact changes or a cross-asset
proxy crosses a material daily-move band. No timestamps are emitted, so an
unchanged regime suppresses the LLM run in Hermes monitor mode.
"""

from __future__ import annotations
from automation_paths import configured_text

import hashlib
import json
import math
from pathlib import Path

import yfinance as yf

ROOT = Path(configured_text("${ANALYST_WIKI_ROOT}"))
UPSTREAM_GLOBS = (
    "raw/briefings/tradermonty/**/macro_regime_*.json",
    "raw/briefings/tradermonty/**/macro_regime_*.md",
    "daily/fastmoney/*.md",
    "daily/meetkevin/*.md",
    "daily/feeds/last30days*.md",
)
PROXIES = (
    "SPY", "QQQ", "IWM", "TLT", "HYG", "LQD", "GLD", "USO",
    "XLK", "XLE", "XLF", "SMH", "BTC-USD", "^VIX",
)
MOVE_BANDS = (-3.0, -2.0, -1.0, -0.5, 0.5, 1.0, 2.0, 3.0)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def latest_upstream() -> list[dict[str, object]]:
    result = []
    for pattern in UPSTREAM_GLOBS:
        files = [path for path in ROOT.glob(pattern) if path.is_file()]
        if not files:
            continue
        latest = max(files, key=lambda path: (path.stat().st_mtime_ns, str(path)))
        result.append(
            {
                "group": pattern,
                "path": str(latest.relative_to(ROOT)),
                "sha256": sha256(latest),
                "size": latest.stat().st_size,
            }
        )
    return result


def move_band(change: float) -> str:
    if not math.isfinite(change):
        return "unknown"
    lower = "below_-3"
    for threshold in MOVE_BANDS:
        if change < threshold:
            return f"{lower}_to_{threshold:g}"
        lower = f"{threshold:g}"
    return "above_3"


def _close_frame(data):
    close = data.get("Close")
    if close is None:
        raise ValueError("missing Close frame")
    return close


def quote_regimes() -> dict[str, str]:
    try:
        symbols = list(PROXIES)
        daily = _close_frame(
            yf.download(
                symbols,
                period="5d",
                interval="1d",
                auto_adjust=False,
                progress=False,
                threads=True,
            )
        )
        intraday = _close_frame(
            yf.download(
                symbols,
                period="1d",
                interval="5m",
                auto_adjust=False,
                progress=False,
                threads=True,
            )
        )
        result = {}
        for symbol in PROXIES:
            daily_series = daily[symbol].dropna()
            intra_series = intraday[symbol].dropna()
            if len(daily_series) < 2:
                result[symbol] = "unknown"
                continue
            if len(intra_series):
                current = float(intra_series.iloc[-1])
                current_date = intra_series.index[-1].date()
                earlier = daily_series[daily_series.index.date < current_date]
                previous = float(earlier.iloc[-1]) if len(earlier) else float(daily_series.iloc[-2])
            else:
                current = float(daily_series.iloc[-1])
                previous = float(daily_series.iloc[-2])
            change = (current / previous - 1.0) * 100.0 if previous else float("nan")
            result[symbol] = move_band(change)
        return result
    except Exception:
        # Stable failure state: an outage may trigger one review, then suppress
        # repeated runs until connectivity or upstream inputs change.
        return {symbol: "unavailable" for symbol in PROXIES}


def main() -> None:
    payload = {
        "upstream": latest_upstream(),
        "cross_asset_daily_move_bands": quote_regimes(),
    }
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
