#!/usr/bin/env python3
"""
Pre-market data fetcher for morning briefing cron job.
Fetches stock prices from Finnhub and earnings calendar from FMP first, with Finnhub fallback.
Outputs JSON to stdout for the cron agent to consume.

Usage: python3 market_prefetch.py
Output: JSON with "quotes" and "earnings" keys.
"""
import json
import os
import sys
import urllib.request
import urllib.error
import time
from datetime import datetime, timedelta

FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")
FMP_API_KEY = os.environ.get("FMP_API_KEY", "")
FINNHUB_BASE = "https://finnhub.io/api/v1"
FMP_BASE = "https://financialmodelingprep.com/stable"

from private_config import load_holdings

# Public market benchmarks; private holdings are opt-in external inputs.
TICKERS = ["SPY", "QQQ"]


def earnings_watchlist():
    return set(TICKERS) | set(load_holdings())

def fetch_json(url, timeout=8):
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}

def fetch_quotes():
    quotes = {}
    for i, sym in enumerate(TICKERS):
        if i > 0:
            time.sleep(0.35)
        data = fetch_json(f"{FINNHUB_BASE}/quote?symbol={sym}&token={FINNHUB_API_KEY}")
        if "error" not in data and data.get("c", 0) > 0:
            quotes[sym] = {
                "price": data["c"],
                "prev_close": data["pc"],
                "change": data["d"],
                "change_pct": round(data["dp"], 2),
                "high": data["h"],
                "low": data["l"],
                "timestamp": data["t"],
            }
        else:
            quotes[sym] = None
    return quotes

def normalize_fmp_hour(raw):
    """Normalize FMP timing into the same rough field used by the old Finnhub path."""
    if not raw:
        return ""
    val = str(raw).strip().lower()
    if val in {"bmo", "before market open", "pre-market", "premarket"}:
        return "bmo"
    if val in {"amc", "after market close", "after-market", "post-market", "postmarket"}:
        return "amc"
    return str(raw).strip()


def fetch_earnings_fmp(today, end):
    """Primary earnings calendar source: FMP stable earnings calendar."""
    if not FMP_API_KEY:
        return []
    url = f"{FMP_BASE}/earnings-calendar?from={today}&to={end}&apikey={FMP_API_KEY}"
    data = fetch_json(url)
    if isinstance(data, dict) and data.get("error"):
        return []
    if not isinstance(data, list):
        return []

    earnings = []
    watchlist = earnings_watchlist()
    for e in data:
        sym = e.get("symbol")
        if sym in watchlist:
            earnings.append({
                "date": e.get("date"),
                "symbol": sym,
                "hour": normalize_fmp_hour(e.get("time")),
                "quarter": e.get("quarter"),
                "year": e.get("year"),
                "eps_estimate": e.get("epsEstimated"),
                "eps_actual": e.get("epsActual"),
                "revenue_estimate": e.get("revenueEstimated"),
                "revenue_actual": e.get("revenueActual"),
                "source": "fmp",
            })
    return earnings


def fetch_earnings_finnhub(today, end):
    """Fallback earnings calendar source: Finnhub."""
    if not FINNHUB_API_KEY:
        return []
    data = fetch_json(f"{FINNHUB_BASE}/calendar/earnings?token={FINNHUB_API_KEY}&_from={today}&_to={end}")

    earnings = []
    watchlist = earnings_watchlist()
    if "earningsCalendar" in data:
        for e in data["earningsCalendar"]:
            if e.get("symbol") in watchlist:
                earnings.append({
                    "date": e.get("date"),
                    "symbol": e.get("symbol"),
                    "hour": e.get("hour", ""),
                    "quarter": e.get("quarter"),
                    "year": e.get("year"),
                    "eps_estimate": e.get("epsEstimate"),
                    "eps_actual": e.get("epsActual"),
                    "revenue_estimate": e.get("revenueEstimate"),
                    "revenue_actual": e.get("revenueActual"),
                    "source": "finnhub",
                })
    return earnings


def fetch_earnings():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    end = (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%d")

    earnings = fetch_earnings_fmp(today, end)
    if earnings:
        return earnings

    return fetch_earnings_finnhub(today, end)

if __name__ == "__main__":
    result = {
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "quotes": fetch_quotes(),
        "earnings": fetch_earnings(),
    }
    print(json.dumps(result))
