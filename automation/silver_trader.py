#!/usr/bin/env python3
"""
Silver Futures Trader Dashboard — comprehensive monitoring for active silver futures traders.

Data sources:
1. Silver futures (COMEX SI=F) — price, technicals, volume
2. Silver ETFs (SLV, SIVR, AGQ, SIL miners, SILJ) — prices, flows proxy
3. Macro drivers: DXY, 10Y yield (^TNX), 30Y yield (^TYX), TLT, TIP, UUP, copper (HG=F)
4. Technical indicators: RSI, MACD, Bollinger Bands, 50/200 DMA, ATR
5. SLV options put/call ratio — positioning
6. IG retail sentiment — contrarian signal
7. Seasonal context
8. Polymarket — silver/fed related prediction markets
9. CFTC COT (silver code 084691) — managed-money positioning

Output modes:
    python3 silver_trader.py --brief      # Slack-formatted briefing
    python3 silver_trader.py --json       # Raw JSON
    python3 silver_trader.py --levels     # Entry/exit levels only
    python3 silver_trader.py --full       # Everything (default)
"""
from automation_paths import configured_text

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

try:
    from precious_metals_options import format_metals_options_section, load_metals_options
except Exception:  # pragma: no cover - briefing should degrade if helper is unavailable
    format_metals_options_section = None
    load_metals_options = None

# Gold futures, US data releases, and FOMC are all scheduled in ET.
# User is on PT; display uses PT, internal math uses ET.
ET = ZoneInfo("America/New_York")
PT = ZoneInfo("America/Los_Angeles")

# Default release time (ET) per event type. Imminent-risk math uses these
# to make hours-to-event sensible instead of treating everything as midnight.
DEFAULT_EVENT_HOURS_ET = {
    "FOMC": (14, 0),    # 2:00 pm ET
    "CPI": (8, 30),
    "NFP": (8, 30),
    "PCE": (8, 30),
    "ECB": (8, 30),     # 13:45 CET -> ~7:45-8:45 ET; round to 8:30
    "BOJ": (23, 0),     # ~12 pm JST next day -> ~11 pm ET previous day
    "OPEC": (12, 0),
    "ISM": (10, 0),     # 10:00 am ET (US release)
    "CAIXIN": (21, 45), # 21:45 ET (= ~09:45 next-day Beijing); calendar dates are the ET-evening date
}


def _et_now():
    """Current time in ET, timezone-aware."""
    return datetime.now(ET)


def _make_event_dt(y, m, d, kind):
    """Construct a timezone-aware ET datetime for an event of `kind`."""
    h, mi = DEFAULT_EVENT_HOURS_ET.get(kind, (12, 0))
    return datetime(y, m, d, h, mi, tzinfo=ET)


def get_session(now=None):
    """
    Identify the current silver-futures session in CME Globex hours (ET-based).

    Sessions:
      - Asia:    Sun 6pm ET → 3am ET (Mon-Fri)
      - London:  3am ET → 8am ET (Mon-Fri)
      - NY:      8am ET → 5pm ET (Mon-Fri)
      - Pause:   5pm-6pm ET daily (Mon-Thu); Globex pause
      - Closed:  Fri 5pm ET → Sun 6pm ET

    Returns: {label, trading_active: bool, descr: str}
    """
    now = now or _et_now()
    hour = now.hour
    minute = now.minute
    minutes_of_day = hour * 60 + minute
    weekday = now.weekday()  # Mon=0 ... Sun=6

    # Closed: Friday 5pm onward through Sunday 6pm
    if weekday == 4 and minutes_of_day >= 17 * 60:
        return {"label": "CLOSED", "trading_active": False,
                "descr": "Weekend close — reopens Sun 6pm ET"}
    if weekday == 5:
        return {"label": "CLOSED", "trading_active": False,
                "descr": "Weekend (Sat) — reopens Sun 6pm ET"}
    if weekday == 6 and minutes_of_day < 18 * 60:
        return {"label": "CLOSED", "trading_active": False,
                "descr": "Weekend — reopens Sun 6pm ET"}

    # Daily pause 5-6pm ET (Mon-Thu and Sun, but Sun before 6pm is already CLOSED above)
    if 17 * 60 <= minutes_of_day < 18 * 60:
        return {"label": "PAUSE", "trading_active": False,
                "descr": "Daily Globex pause (5-6pm ET)"}

    # Sunday after 6pm = Asia open of the new week
    if weekday == 6 and minutes_of_day >= 18 * 60:
        return {"label": "ASIA", "trading_active": True,
                "descr": "Asia session — thinner liquidity"}

    if hour < 3:
        return {"label": "ASIA", "trading_active": True, "descr": "Asia session — thinner liquidity"}
    if hour < 8:
        return {"label": "LONDON", "trading_active": True, "descr": "London session"}
    if hour < 17:
        return {"label": "NY", "trading_active": True, "descr": "NY session — peak volume"}
    return {"label": "ASIA", "trading_active": True, "descr": "Asia session opening — thinner liquidity"}


def fetch_intraday_last_price():
    """
    Last 1-minute bar for SI=F. Daily close is stale during a live session;
    this gives the most-current quote available via yfinance. Returns float
    or None if unavailable / off-hours.
    """
    try:
        h = yf.Ticker("SI=F").history(period="2d", interval="1m", auto_adjust=True)
        if h is None or len(h) == 0:
            return None
        last = h["Close"].dropna()
        if len(last) == 0:
            return None
        return round(float(last.iloc[-1]), 2)
    except Exception:
        return None

try:
    import yfinance as yf
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "yfinance", "-q"])
    import yfinance as yf

try:
    import pandas as pd
    import numpy as np
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pandas", "numpy", "-q"])
    import pandas as pd
    import numpy as np

try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

# Load Hermes env (~/.hermes/.env) so GEMINI_API_KEY is available
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(os.path.expanduser(configured_text('${ANALYST_HERMES_HOME}/.env')), override=False)
except ImportError:
    # Manual fallback parser if python-dotenv isn't installed
    _env_path = os.path.expanduser(configured_text('${ANALYST_HERMES_HOME}/.env'))
    if os.path.exists(_env_path):
        with open(_env_path) as _f:
            for _line in _f:
                if "=" in _line and not _line.lstrip().startswith("#"):
                    _k, _, _v = _line.partition("=")
                    os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))


# ============================================================
# RISK EVENT CALENDAR
# ============================================================

# Annual rotation: add a new year's block here each December, drop years 2+ behind.
# Sources: FOMC + Fed dot plot calendar, BoJ MPC, ECB Governing Council,
# BLS CPI/NFP schedule, BEA PCE schedule, OPEC+ ministerial meetings.
CALENDAR_BY_YEAR = {
    2026: {
        "FOMC": [(1, 28), (3, 18), (4, 29), (6, 17), (7, 29), (9, 16), (11, 4), (12, 16)],
        "BOJ":  [(1, 23), (3, 19), (4, 30), (6, 18), (7, 30), (9, 17), (10, 30), (12, 18)],
        "ECB":  [(1, 29), (3, 12), (4, 23), (6, 10), (7, 23), (9, 10), (10, 21), (12, 10)],
        "CPI":  [(1, 14), (2, 12), (3, 11), (4, 14), (5, 13), (6, 10), (7, 14), (8, 12),
                 (9, 10), (10, 14), (11, 11), (12, 10)],
        "NFP":  [(1, 9), (2, 6), (3, 6), (4, 3), (5, 1), (6, 5), (7, 3), (8, 7),
                 (9, 4), (10, 2), (11, 6), (12, 4)],
        "PCE":  [(1, 30), (2, 27), (3, 27), (4, 30), (5, 29), (6, 26), (7, 30), (8, 28),
                 (9, 25), (10, 30), (11, 25), (12, 23)],
        "OPEC": [(2, 1), (4, 1), (6, 1), (9, 1), (12, 1)],
        # ISM Manufacturing — first business day of each month, 10am ET
        "ISM":   [(1, 2), (2, 2), (3, 2), (4, 1), (5, 1), (6, 1), (7, 1), (8, 3),
                  (9, 1), (10, 1), (11, 2), (12, 1)],
        # China Caixin Manufacturing PMI — ~21:45 ET on the listed date (= ~09:45 next-day Beijing).
        # Dates are approximate: a few entries drift 1-7 days from the actual Beijing release when
        # CNY Labor Day (early May) or Golden Week (early Oct) push the release later. Precise
        # window awareness during those weeks should consult a live calendar.
        "CAIXIN":[(1, 1), (1, 31), (2, 28), (3, 31), (4, 30), (5, 31), (6, 30), (7, 31),
                  (8, 31), (9, 30), (10, 31), (11, 30)],
    },
}

EVENT_META = {
    "FOMC":   ("FOMC Rate Decision",        "HIGH",   "uncertain"),
    "BOJ":    ("BoJ Rate Decision",          "HIGH",   "uncertain"),
    "ECB":    ("ECB Rate Decision",          "MEDIUM", "uncertain"),
    "CPI":    ("US CPI",                     "HIGH",   "uncertain"),
    "NFP":    ("US Non-Farm Payrolls",       "HIGH",   "uncertain"),
    "PCE":    ("US PCE Price Index",         "HIGH",   "uncertain"),
    "OPEC":   ("OPEC+ Meeting",              "MEDIUM", "uncertain"),
    "ISM":    ("ISM Manufacturing PMI",      "MEDIUM", "industrial"),
    "CAIXIN": ("China Caixin Mfg PMI",       "MEDIUM", "industrial"),
}


def get_risk_events():
    """
    Upcoming high-impact events that move silver.
    Combines hardcoded recurring schedules (FOMC, BoJ, ECB, CPI, NFP, OPEC)
    with scraped upcoming events from Forex Factory.
    Returns list of dicts: {date, event, impact, event_type, kind}
    """
    now = _et_now()
    events = []

    for year, by_kind in CALENDAR_BY_YEAR.items():
        for kind, days in by_kind.items():
            event_name, impact, event_type = EVENT_META.get(
                kind, (kind, "MEDIUM", "uncertain"))
            for m, d in days:
                dt = _make_event_dt(year, m, d, kind)
                if dt < now - timedelta(days=1):
                    continue
                events.append({
                    "date": dt,
                    "event": event_name,
                    "impact": impact,
                    "event_type": event_type,
                    "kind": kind,
                })

    # ---- SCRAPE UPCOMING EVENTS FROM WEB ----
    try:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        cal_data = json.loads(resp.read())
        for item in cal_data:
            try:
                date_str = item.get("date", "")
                title = item.get("title", "")
                impact = item.get("impact", "")
                # Only grab HIGH impact events relevant to silver
                if impact != "HIGH":
                    continue
                if not any(kw in title.upper() for kw in [
                    "CPI", "INFLATION", "FOMC", "FED", "RATE", "INTEREST",
                    "NON-FARM", "NFP", "EMPLOYMENT", "UNEMPLOYMENT", "JOBS",
                    "GDP", "PCE", "RETAIL", "CONSUMER", "MANUFACTURING",
                    "BOJ", "ECB", "CENTRAL BANK", "OPEC", "OIL",
                    "TREASURY", "BOND", "YIELD",
                ]):
                    continue
                # Parse date — assume ET (Forex Factory's default for US events)
                dt = datetime.strptime(date_str[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=ET)
                if dt >= now - timedelta(days=1):
                    events.append({
                        "date": dt,
                        "event": title,
                        "impact": "HIGH",
                        "event_type": "uncertain",
                        "kind": "SCRAPED",
                    })
            except (ValueError, KeyError):
                continue
    except Exception:
        pass  # Calendar scrape fails silently, hardcoded dates still work

    # Sort by date, dedupe by event name within same day
    seen = set()
    unique = []
    for e in sorted(events, key=lambda x: x["date"]):
        key = (e["date"].strftime("%Y-%m-%d"), e["event"][:20])
        if key not in seen:
            seen.add(key)
            unique.append(e)

    # Return events within next 14 days
    cutoff = now + timedelta(days=14)
    return [e for e in unique if e["date"] <= cutoff]


def get_imminent_risk(risk_events, hours=48):
    """
    Check if any high-impact event is within N hours.
    Returns (is_imminent, event_list, hours_to_nearest)
    """
    now = _et_now()
    imminent = []
    for e in risk_events:
        delta = (e["date"] - now).total_seconds() / 3600
        if 0 < delta <= hours and e["impact"] == "HIGH":
            imminent.append({**e, "hours_away": round(delta, 1)})
    if imminent:
        nearest = min(imminent, key=lambda x: x["hours_away"])
        return True, imminent, nearest["hours_away"]
    return False, [], None


def get_recent_passed_event(risk_events, hours=24):
    """
    Find the most-recently-passed HIGH-impact event within the last `hours`.
    Used to detect post-event accumulation opportunities.
    Returns dict with `event`, `hours_ago` (positive number), or None.
    """
    now = _et_now()
    candidates = []
    for e in risk_events:
        delta_h = (now - e["date"]).total_seconds() / 3600
        if 0 < delta_h <= hours and e["impact"] == "HIGH":
            candidates.append({"event": e["event"], "hours_ago": round(delta_h, 1), "date": e["date"]})
    if candidates:
        return min(candidates, key=lambda x: x["hours_ago"])
    return None


# ============================================================
# DATA FETCHERS
# ============================================================

def fetch_price_data():
    """Fetch all price data in one batch."""
    symbols = {
        "SI=F": "Silver Futures",
        "GC=F": "Gold Futures",         # kept for GSR
        "HG=F": "Copper Futures",       # kept for silver/copper ratio
        "SLV": "iShares Silver",
        "SIVR": "abrdn Silver",
        "AGQ": "ProShares 2x Silver",
        "SIL": "Silver Miners ETF",     # SIL miners (NOT the futures contract)
        "SILJ": "Silver Junior Miners",
        "GLD": "SPDR Gold",             # for GSR cross-checks
        "DX-Y.NYB": "DXY",
        "^TNX": "10Y Yield",
        "^TYX": "30Y Yield",
        "TLT": "Long Bonds",
        "TIP": "TIPS ETF",
        "UUP": "USD Bull",
    }
    
    data = {}
    try:
        hist = yf.download(list(symbols.keys()), period="1y", interval="1d", progress=False, auto_adjust=True)
        close = hist["Close"] if "Close" in hist else hist
        
        for sym, name in symbols.items():
            if sym in close.columns:
                series = close[sym].dropna()
                if len(series) == 0:
                    data[sym] = {"error": "No data"}
                    continue
                
                current = series.iloc[-1]
                prev = series.iloc[-2] if len(series) > 1 else current
                
                # Calculate various lookback returns
                returns = {}
                for label, days in [("1d", 1), ("5d", 5), ("1m", 21), ("3m", 63), ("6m", 126)]:
                    if len(series) > days:
                        past = series.iloc[-(days+1)]
                        returns[label] = round(((current - past) / past) * 100, 2)
                
                data[sym] = {
                    "name": name,
                    "price": round(float(current), 2),
                    "prev_close": round(float(prev), 2),
                    "change_pct": round(((current - prev) / prev) * 100, 2),
                    "returns": returns,
                    "high_52w": round(float(series.max()), 2),
                    "low_52w": round(float(series.min()), 2),
                    "series": series,
                }
            else:
                data[sym] = {"error": f"{sym} not in download"}
    except Exception as e:
        return {"error": str(e), "data": {}}
    
    return data


def fetch_futures_volume():
    """Fetch silver futures volume data."""
    try:
        si = yf.Ticker("SI=F")
        hist = si.history(period="30d", interval="1d", auto_adjust=True)
        if len(hist) == 0:
            return {"volume": None, "avg_volume_20d": None, "volume_ratio": None}
        
        vol = hist["Volume"].iloc[-1] if "Volume" in hist else 0
        avg_vol = hist["Volume"].tail(20).mean() if len(hist) >= 20 else vol
        
        return {
            "volume": int(vol) if not math.isnan(vol) else None,
            "avg_volume_20d": int(avg_vol) if not math.isnan(avg_vol) else None,
            "volume_ratio": round(vol / avg_vol, 2) if avg_vol and not math.isnan(avg_vol) else None,
        }
    except Exception as e:
        return {"error": str(e)}


def fetch_silver_futures_term_structure():
    """Check silver futures contango/backwardation across contracts."""
    contracts = ["SI=F", "SIK26.CMX", "SIN26.CMX", "SIU26.CMX", "SIZ26.CMX"]
    # yfinance doesn't reliably have all contracts, try what we can
    prices = {}
    for c in ["SI=F"]:
        try:
            t = yf.Ticker(c)
            h = t.history(period="2d")
            if len(h) > 0:
                prices[c] = round(float(h["Close"].iloc[-1]), 2)
        except:
            pass
    return prices


COT_CACHE_PATH = "/tmp/.silver_trader_cot_cache.json"
FRED_CACHE_PATH = "/tmp/.silver_trader_fred_cache.json"


def fetch_cot_data():
    """
    Fetch CFTC Commitments of Traders for Silver (Code 084691) — disaggregated futures only.

    Surfaces managed money net long, WoW change, 52w percentile.
    Cached daily — CFTC publishes Friday so a daily cache is plenty.
    """
    today = _et_now().strftime("%Y-%m-%d")
    cache = {}
    try:
        with open(COT_CACHE_PATH) as f:
            cache = json.load(f)
        if cache.get("fetched_on") == today and cache.get("data"):
            return cache["data"]
    except Exception:
        pass

    result = {"available": False}
    try:
        url = ("https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
               "?cftc_contract_market_code=084691"
               "&%24order=report_date_as_yyyy_mm_dd%20DESC"
               "&%24limit=53")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=15)
        rows = json.loads(resp.read())
        if not rows:
            return result

        latest = rows[0]
        long_now = int(latest.get("m_money_positions_long_all", 0))
        short_now = int(latest.get("m_money_positions_short_all", 0))
        net_now = long_now - short_now
        change_long = int(latest.get("change_in_m_money_long_all", 0))
        change_short = int(latest.get("change_in_m_money_short_all", 0))
        net_change = change_long - change_short

        nets_52w = []
        for r in rows[:52]:
            try:
                nets_52w.append(
                    int(r.get("m_money_positions_long_all", 0))
                    - int(r.get("m_money_positions_short_all", 0))
                )
            except Exception:
                continue
        if nets_52w:
            srt = sorted(nets_52w)
            rank = sum(1 for n in srt if n <= net_now)
            pct = round(100 * rank / len(srt), 0)
        else:
            pct = None

        # Signal interpretation
        if pct is not None and pct >= 90:
            signal = "EXTREME LONG (contrarian bearish)"
        elif pct is not None and pct >= 75:
            signal = "ELEVATED LONG (caution)"
        elif pct is not None and pct <= 10:
            signal = "EXTREME SHORT (contrarian bullish)"
        elif pct is not None and pct <= 25:
            signal = "LIGHT POSITIONING (room to add)"
        else:
            signal = "NEUTRAL"

        result = {
            "available": True,
            "report_date": latest.get("report_date_as_yyyy_mm_dd", "")[:10],
            "managed_money_long": long_now,
            "managed_money_short": short_now,
            "managed_money_net": net_now,
            "wow_net_change": net_change,
            "pct_52w": pct,
            "signal": signal,
        }
        cache = {"fetched_on": today, "data": result}
        with open(COT_CACHE_PATH, "w") as f:
            json.dump(cache, f)
    except Exception as e:
        result["error"] = str(e)
    return result


def fetch_real_yield():
    """
    Fetch 10yr TIPS yield (DFII10) directly from FRED.
    Returns latest value, 1mo change, level signal.
    Cached daily.
    """
    today = _et_now().strftime("%Y-%m-%d")
    cache = {}
    try:
        with open(FRED_CACHE_PATH) as f:
            cache = json.load(f)
        if cache.get("fetched_on") == today and cache.get("data"):
            return cache["data"]
    except Exception:
        pass

    result = {"available": False}
    try:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10"
        # FRED's edge layer hangs on Mozilla UAs but responds quickly to curl-style.
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.88.1", "Accept": "*/*"})
        resp = urllib.request.urlopen(req, timeout=20)
        text = resp.read().decode("utf-8", errors="ignore")
        rows = [r for r in text.strip().split("\n")[1:] if r and not r.endswith(",.")]
        if not rows:
            return result
        # Parse: date,value
        parsed = []
        for r in rows:
            try:
                d, v = r.split(",")
                if v == "." or not v.strip():
                    continue
                parsed.append((d, float(v)))
            except Exception:
                continue
        if not parsed:
            return result

        latest_date, latest_val = parsed[-1]
        # 1-month-ago value (~21 trading days back)
        prev = parsed[-22] if len(parsed) > 22 else parsed[0]
        prev_val = prev[1]
        change_1m = round(latest_val - prev_val, 2)

        # Signal: real yield > 2% structurally bearish silver; falling = bullish
        if latest_val >= 2.0:
            level_signal = "ELEVATED (>2% — structurally bearish silver)"
        elif latest_val >= 1.5:
            level_signal = "MODERATE (1.5-2% — neutral)"
        elif latest_val >= 1.0:
            level_signal = "LOW (1-1.5% — supportive of silver)"
        else:
            level_signal = "VERY LOW (<1% — strongly bullish silver)"

        if change_1m <= -0.15:
            trend_signal = "FALLING (bullish silver)"
        elif change_1m >= 0.15:
            trend_signal = "RISING (bearish silver)"
        else:
            trend_signal = "STABLE"

        result = {
            "available": True,
            "as_of": latest_date,
            "yield_pct": round(latest_val, 2),
            "change_1m_bp": int(change_1m * 100),
            "level_signal": level_signal,
            "trend_signal": trend_signal,
        }
        cache = {"fetched_on": today, "data": result}
        with open(FRED_CACHE_PATH, "w") as f:
            json.dump(cache, f)
    except Exception as e:
        result["error"] = str(e)
    return result


# ============================================================
# TECHNICAL INDICATORS
# ============================================================

def calc_rsi(series, period=14):
    """Calculate RSI."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, float("inf"))
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calc_macd(series, fast=12, slow=26, signal=9):
    """Calculate MACD."""
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_bollinger(series, period=20, std_dev=2):
    """Calculate Bollinger Bands."""
    sma = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = sma + (std * std_dev)
    lower = sma - (std * std_dev)
    return sma, upper, lower


def calc_atr(high, low, close, period=14):
    """Calculate Average True Range."""
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr


def compute_technicals(silver_series, ohlc=None):
    """
    Compute all technical indicators for silver futures.

    `ohlc`, if provided, is a DataFrame with High/Low/Close columns
    (typically from yf.Ticker.history) and is used for true Wilder ATR.
    Without it, ATR falls back to a close-only approximation.
    """
    if silver_series is None or len(silver_series) < 50:
        return {"error": "Insufficient data for technicals"}

    close = silver_series
    result = {}
    
    # Moving averages
    for period, label in [(10, "SMA_10"), (20, "SMA_20"), (50, "SMA_50"), (100, "SMA_100"), (200, "SMA_200")]:
        if len(close) >= period:
            ma = close.rolling(window=period).mean()
            result[label] = round(float(ma.iloc[-1]), 2)
            result[f"{label}_DIST"] = round(((close.iloc[-1] - ma.iloc[-1]) / ma.iloc[-1]) * 100, 2)
    
    # RSI
    rsi = calc_rsi(close)
    if not math.isnan(rsi.iloc[-1]):
        result["RSI_14"] = round(float(rsi.iloc[-1]), 1)
    
    # MACD
    macd_line, signal_line, histogram = calc_macd(close)
    if not math.isnan(histogram.iloc[-1]):
        result["MACD"] = round(float(macd_line.iloc[-1]), 2)
        result["MACD_SIGNAL"] = round(float(signal_line.iloc[-1]), 2)
        result["MACD_HIST"] = round(float(histogram.iloc[-1]), 2)
        result["MACD_CROSS"] = "BULLISH" if histogram.iloc[-1] > 0 and histogram.iloc[-2] <= 0 else (
            "BEARISH" if histogram.iloc[-1] < 0 and histogram.iloc[-2] >= 0 else "NONE")
    
    # Bollinger Bands
    sma, upper, lower = calc_bollinger(close)
    if not math.isnan(upper.iloc[-1]):
        result["BB_UPPER"] = round(float(upper.iloc[-1]), 2)
        result["BB_LOWER"] = round(float(lower.iloc[-1]), 2)
        result["BB_MID"] = round(float(sma.iloc[-1]), 2)
        result["BB_WIDTH"] = round(((upper.iloc[-1] - lower.iloc[-1]) / sma.iloc[-1]) * 100, 2)
        result["BB_POSITION"] = round(
            ((close.iloc[-1] - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1])) * 100, 1)
    
    # ATR — true Wilder ATR if OHLC provided, else close-only approximation
    atr_value = None
    atr_series = None
    if ohlc is not None and all(c in ohlc.columns for c in ("High", "Low", "Close")):
        try:
            atr_series = calc_atr(ohlc["High"], ohlc["Low"], ohlc["Close"], period=14)
            if len(atr_series) and not math.isnan(atr_series.iloc[-1]):
                atr_value = float(atr_series.iloc[-1])
                result["ATR_SOURCE"] = "OHLC"
        except Exception:
            atr_value = None
    if atr_value is None:
        atr_value = float(close.pct_change().rolling(14).std().iloc[-1] * close.iloc[-1])
        result["ATR_SOURCE"] = "close-approx"
    result["ATR_14"] = round(atr_value, 2)

    # 90-day median ATR for vol-adjusted sizing — only meaningful when we have a real ATR series.
    if atr_series is not None and len(atr_series.dropna()) >= 30:
        atr_median = float(atr_series.dropna().tail(90).median())
        result["ATR_MEDIAN_90D"] = round(atr_median, 2)
        if atr_median > 0:
            ratio = atr_value / atr_median
            result["ATR_VOL_REGIME"] = (
                "ELEVATED" if ratio > 1.5 else
                "HIGH" if ratio > 1.2 else
                "LOW" if ratio < 0.7 else
                "NORMAL"
            )
            result["ATR_VOL_RATIO"] = round(ratio, 2)

    # Key levels — comprehensive S/R from prev D, prior week, round numbers, retracement.
    current = float(close.iloc[-1])
    result["KEY_LEVELS"] = _compute_key_levels(close, ohlc, current, atr_value)

    # Backward-compat shorthand from the new key levels (nearest below/above current)
    below = sorted([k["price"] for k in result["KEY_LEVELS"] if k["price"] < current], reverse=True)
    above = sorted([k["price"] for k in result["KEY_LEVELS"] if k["price"] > current])
    if below:
        result["SUPPORT_1"] = round(below[0], 2)
    elif len(close) >= 20:
        result["SUPPORT_1"] = round(float(close.tail(20).min()), 2)
    if above:
        result["RESISTANCE_1"] = round(above[0], 2)
    elif len(close) >= 20:
        result["RESISTANCE_1"] = round(float(close.tail(20).max()), 2)

    # Trend determination
    if result.get("SMA_50") and result.get("SMA_200"):
        if result["SMA_50"] > result["SMA_200"]:
            result["TREND"] = "BULLISH (Golden Cross zone)"
        else:
            result["TREND"] = "BEARISH (Death Cross zone)"

    return result


def _round_increment(spot):
    """Pick a round-number grid spacing appropriate for the asset's price level.

    Silver at $30 needs $1 grid; gold at $4,000 wants $50. Returns int dollar increment.
    """
    if spot >= 200:
        return 50
    if spot >= 50:
        return 5
    return 1


def _compute_key_levels(close, ohlc, current, atr):
    """
    Build a unified list of key support/resistance levels.

    Combines: prev day H/L/C, prior week H/L, round numbers (price-scaled $1/$5/$50 grid),
    50% retracement of last 60d swing. Returns list of {price, type, side}.
    Levels within 0.3*ATR of each other are deduped (the more specific type wins).
    """
    levels = []

    if ohlc is not None and len(ohlc) >= 2:
        try:
            prev = ohlc.iloc[-2]
            levels.append({"price": round(float(prev["High"]), 2), "type": "PrevDay_H"})
            levels.append({"price": round(float(prev["Low"]), 2), "type": "PrevDay_L"})
            levels.append({"price": round(float(prev["Close"]), 2), "type": "PrevDay_C"})
        except Exception:
            pass

        if len(ohlc) >= 6:
            try:
                last_week = ohlc.iloc[-6:-1]  # last 5 sessions before today
                levels.append({"price": round(float(last_week["High"].max()), 2), "type": "PriorWeek_H"})
                levels.append({"price": round(float(last_week["Low"].min()), 2), "type": "PriorWeek_L"})
            except Exception:
                pass

    # Round numbers: grid spans ±5 ATR around current; spacing scales with price level
    if atr and atr > 0:
        inc = _round_increment(current)
        span = max(inc * 3, atr * 5)
        lo = int((current - span) // inc) * inc
        hi = int((current + span) // inc + 1) * inc
        for r in range(lo, hi + 1, inc):
            if r > 0:
                levels.append({"price": float(r), "type": f"Round_${inc}"})

    # 50% retracement of last 60d swing
    if len(close) >= 60:
        recent = close.tail(60)
        hi60 = float(recent.max())
        lo60 = float(recent.min())
        if hi60 > lo60:
            levels.append({"price": round((hi60 + lo60) / 2, 2), "type": "Fib_50%_60d"})

    # Dedupe: levels within 0.3*ATR collapse to the higher-priority one
    # Priority: PrevDay > PriorWeek > Fib > Round
    # Round levels share priority 1 regardless of grid spacing ($1, $5, or $50).
    priority = {"PrevDay_H": 4, "PrevDay_L": 4, "PrevDay_C": 4,
                "PriorWeek_H": 3, "PriorWeek_L": 3,
                "Fib_50%_60d": 2, "Round_$1": 1, "Round_$5": 1, "Round_$50": 1}
    threshold = (atr or current * 0.005) * 0.3
    levels.sort(key=lambda x: x["price"])
    deduped = []
    for lv in levels:
        replaced = False
        for i, existing in enumerate(deduped):
            if abs(existing["price"] - lv["price"]) < threshold:
                if priority.get(lv["type"], 0) > priority.get(existing["type"], 0):
                    deduped[i] = lv
                replaced = True
                break
        if not replaced:
            deduped.append(lv)

    for lv in deduped:
        lv["side"] = "support" if lv["price"] < current else "resistance"
    return deduped


# ============================================================
# MACRO / FUNDAMENTAL ANALYSIS
# ============================================================

def compute_macro(price_data, real_yield=None):
    """Analyze macro drivers of silver."""
    result = {}

    # Real rates: prefer FRED DFII10 directly; fall back to TIP/TLT proxy
    if real_yield and real_yield.get("available"):
        result["REAL_YIELD_10Y"] = real_yield["yield_pct"]
        result["REAL_YIELD_LEVEL"] = real_yield["level_signal"]
        result["REAL_YIELD_TREND"] = real_yield["trend_signal"]
        result["REAL_YIELD_1M_CHANGE_BP"] = real_yield["change_1m_bp"]
        # Set the canonical REAL_RATE_SIGNAL using the trend direction (consumed elsewhere)
        result["REAL_RATE_SIGNAL"] = real_yield["trend_signal"]

    # TIP/TLT proxy — kept as confirmation
    tlt = price_data.get("TLT", {})
    tip = price_data.get("TIP", {})
    if tlt.get("price") and tip.get("price"):
        tip_tlt_ratio = tip["price"] / tlt["price"]
        result["TIP_TLT_RATIO"] = round(tip_tlt_ratio, 4)
        if tlt.get("returns", {}).get("1m") and tip.get("returns", {}).get("1m"):
            tlt_1m = tlt["returns"]["1m"]
            tip_1m = tip["returns"]["1m"]
            proxy_signal = "FALLING (bullish silver)" if tip_1m > tlt_1m else "RISING (bearish silver)"
            result["TIP_TLT_PROXY_SIGNAL"] = proxy_signal
            # If FRED unavailable, fall back to the proxy as the primary signal
            if "REAL_RATE_SIGNAL" not in result:
                result["REAL_RATE_SIGNAL"] = proxy_signal
    
    # Dollar strength
    dxy = price_data.get("DX-Y.NYB", {})
    uup = price_data.get("UUP", {})
    if dxy.get("price"):
        result["DXY"] = {
            "price": dxy["price"],
            "change_pct": dxy.get("change_pct", 0),
            "returns": dxy.get("returns", {}),
        }
        result["DOLLAR_SIGNAL"] = "WEAKENING (bullish silver)" if dxy.get("change_pct", 0) < 0 else "STRENGTHENING (bearish silver)"
    
    # Bond yields
    tnx = price_data.get("^TNX", {})
    tyx = price_data.get("^TYX", {})
    if tnx.get("price"):
        result["10Y_YIELD"] = tnx["price"]
    if tyx.get("price"):
        result["30Y_YIELD"] = tyx["price"]
        if tnx.get("price"):
            result["YIELD_CURVE"] = round(tyx["price"] - tnx["price"], 2)
            result["CURVE_SIGNAL"] = "STEEPENING (risk-on, mixed silver)" if result["YIELD_CURVE"] > 0 else "INVERTED/FLAT (risk-off, bullish silver)"
    
    # Silver miners leverage — SIL (miners ETF) / SLV
    sil_miners = price_data.get("SIL", {})
    slv = price_data.get("SLV", {})
    if sil_miners.get("price") and slv.get("price"):
        result["SIL_SLV_RATIO"] = round(sil_miners["price"] / slv["price"], 4)
        if sil_miners.get("returns", {}).get("1m") and slv.get("returns", {}).get("1m"):
            slv_1m = slv["returns"]["1m"]
            result["MINER_LEVERAGE"] = round(sil_miners["returns"]["1m"] / slv_1m, 2) if slv_1m != 0 else None

    # Gold/silver ratio — classic macro tell, read with silver lens (inverted from gold).
    # High GSR = silver historically cheap → mean-revert bullish silver.
    # Low GSR = silver overheated vs gold.
    gc = price_data.get("GC=F", {})
    si = price_data.get("SI=F", {})
    if gc.get("price") and si.get("price") and si["price"] > 0:
        gsr = gc["price"] / si["price"]
        result["GSR"] = round(gsr, 1)
        # Silver lens: high GSR = silver historically cheap vs gold = mean-reversion bullish silver
        # Low GSR = silver expensive / risk-on overheated
        if gsr > 90:
            result["GSR_SIGNAL"] = "EXTREME (>90) — silver historically cheap, mean-revert bullish silver"
        elif gsr > 85:
            result["GSR_SIGNAL"] = "ELEVATED (>85) — silver cheap vs gold, modest tailwind"
        elif gsr < 65:
            result["GSR_SIGNAL"] = "EXTREME LOW (<65) — silver overheated, caution / reversion risk"
        elif gsr < 70:
            result["GSR_SIGNAL"] = "RISK-ON (<70) — silver expensive vs gold"
        else:
            result["GSR_SIGNAL"] = "NEUTRAL (70-85) — silver fairly valued vs gold"

    # Silver/Copper ratio — silver vs industrial-metal demand
    # Rising ratio = silver outperforming copper = monetary/Fed-driven (silver acting like gold)
    # Falling ratio = copper outperforming = industrial-led commodity rally (silver lagging)
    hg = price_data.get("HG=F", {})
    if si.get("price") and hg.get("price") and hg["price"] > 0:
        sc_ratio = si["price"] / hg["price"]
        result["SILVER_COPPER_RATIO"] = round(sc_ratio, 2)
        result["COPPER_PRICE"] = hg["price"]

        # Trend: compare current ratio to its 20-day MA built from si/hg series
        si_series = si.get("series")
        hg_series = hg.get("series")
        if si_series is not None and hg_series is not None:
            try:
                # Align indices (only dates where both exist)
                joined = si_series.to_frame("si").join(
                    hg_series.to_frame("hg"), how="inner"
                ).dropna()
                if len(joined) >= 20:
                    ratio_series = joined["si"] / joined["hg"]
                    ma20 = ratio_series.tail(20).mean()
                    if sc_ratio > ma20 * 1.02:
                        result["SILVER_COPPER_TREND"] = "UP (monetary-led / Fed-driven)"
                    elif sc_ratio < ma20 * 0.98:
                        result["SILVER_COPPER_TREND"] = "DOWN (industrial-led / silver lagging)"
                    else:
                        result["SILVER_COPPER_TREND"] = "FLAT (no industrial divergence)"
            except Exception:
                pass

    return result


def fetch_polymarket_silver():
    """Check Polymarket for silver/fed related markets."""
    result = []
    try:
        # Use the search endpoint instead of slug_contains
        search_terms = ["silver price", "federal reserve", "interest rate"]
        seen = set()
        
        for term in search_terms:
            url = f"https://gamma-api.polymarket.com/events?title={term}&limit=5&closed=false&order=volume24hr&ascending=false"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=10)
            events = json.loads(resp.read().decode())
            
            for event in events:
                eid = event.get("id", "")
                if eid in seen:
                    continue
                seen.add(eid)
                title = event.get("title", "")
                # Only include silver/fed/rate relevant markets
                if not any(kw in title.lower() for kw in ["silver", "fed", "rate", "treasury", "dollar", "powell", "inflation", "cpi"]):
                    continue
                markets = event.get("markets", [])
                for m in markets[:2]:
                    q_text = m.get("question", title)
                    prices = m.get("outcomePrices", "[]")
                    try:
                        p = json.loads(prices)
                        yes_pct = round(float(p[0]) * 100, 1) if p else None
                    except:
                        yes_pct = None
                    vol = m.get("volume", 0)
                    if vol and float(vol) > 10000:
                        result.append({
                            "question": q_text,
                            "yes_pct": yes_pct,
                            "volume": f"${float(vol):,.0f}",
                        })
    except Exception:
        pass
    return result[:5]


# ============================================================
# POSITIONING / SENTIMENT
# ============================================================

def fetch_slv_options(num_expiries=3, atm_band=0.08):
    """
    Fetch SLV options put/call ratios using yfinance option_chain.

    Aggregates volume and OI across the next `num_expiries` expirations,
    restricted to strikes within ±`atm_band` of spot. Calls and puts are
    properly separated (the prior regex implementation misclassified options
    by strike-vs-spot and did not actually distinguish call vs. put).
    """
    result = {
        "put_call_oi_ratio": None,
        "put_call_vol_ratio": None,
        "signal": None,
        "total_call_vol": 0,
        "total_put_vol": 0,
        "total_call_oi": 0,
        "total_put_oi": 0,
        "expiries_used": [],
        "spot": None,
    }

    try:
        slv = yf.Ticker("SLV")

        # Spot from latest close
        hist = slv.history(period="2d")
        if len(hist) == 0:
            result["error"] = "No SLV history"
            return result
        current = float(hist["Close"].iloc[-1])
        result["spot"] = round(current, 2)

        atm_low = current * (1 - atm_band)
        atm_high = current * (1 + atm_band)

        expiries = list(slv.options or [])[:num_expiries]
        if not expiries:
            result["error"] = "No expiries available"
            return result

        total_cv = total_pv = total_co = total_po = 0
        for exp in expiries:
            try:
                chain = slv.option_chain(exp)
            except Exception:
                continue
            calls = chain.calls
            puts = chain.puts
            if calls is None or puts is None:
                continue

            calls_atm = calls[(calls["strike"] >= atm_low) & (calls["strike"] <= atm_high)]
            puts_atm = puts[(puts["strike"] >= atm_low) & (puts["strike"] <= atm_high)]

            total_cv += int(calls_atm["volume"].fillna(0).sum())
            total_pv += int(puts_atm["volume"].fillna(0).sum())
            total_co += int(calls_atm["openInterest"].fillna(0).sum())
            total_po += int(puts_atm["openInterest"].fillna(0).sum())
            result["expiries_used"].append(exp)

        result["total_call_vol"] = total_cv
        result["total_put_vol"] = total_pv
        result["total_call_oi"] = total_co
        result["total_put_oi"] = total_po

        if total_cv > 0:
            result["put_call_vol_ratio"] = round(total_pv / total_cv, 2)
        if total_co > 0:
            result["put_call_oi_ratio"] = round(total_po / total_co, 2)
            oi = result["put_call_oi_ratio"]
            if oi > 2.0:
                result["signal"] = "BEARISH_HEDGE"
            elif oi > 1.5:
                result["signal"] = "CAUTIOUS"
            elif oi < 0.7:
                result["signal"] = "BULLISH"
            elif oi < 1.0:
                result["signal"] = "MILDLY_BULLISH"
            else:
                result["signal"] = "NEUTRAL"

        # SLV options chain is thinner than GLD's. Flag low conviction when total
        # ATM OI is below a working liquidity threshold.
        LOW_LIQ_THRESHOLD = 5000
        total_oi = total_co + total_po
        result["low_liquidity"] = total_oi < LOW_LIQ_THRESHOLD
        if result["low_liquidity"] and result.get("signal"):
            result["signal"] = result["signal"] + "_LOW_LIQ"
    except Exception as e:
        result["error"] = str(e)

    return result


def fetch_ig_sentiment():
    """
    IG retail positioning for silver.

    Sets `available=True` only when the scrape actually returned a percentage,
    so downstream conviction scoring can SKIP the contrarian component when
    data is missing instead of treating None as 0/neutral.
    """
    result = {"long_pct": None, "short_pct": None, "available": False}
    try:
        url = "https://www.ig.com/uk/commodities/markets-commodities/silver"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=15)
        html = resp.read().decode("utf-8", errors="ignore")
        long_match = re.search(r'(\d+)%\s+of\s+client\s+accounts?\s+are\s+(\w+)', html)
        if long_match:
            pct = int(long_match.group(1))
            direction = long_match.group(2).lower()
            if direction == "long":
                result["long_pct"] = pct
                result["short_pct"] = 100 - pct
            else:
                result["short_pct"] = pct
                result["long_pct"] = 100 - pct
            result["available"] = True
    except Exception as e:
        result["error"] = str(e)
    return result


# ============================================================
# SEASONAL ANALYSIS
# ============================================================

def seasonal_context():
    """Return seasonal tendencies for silver based on current month."""
    month = _et_now().month

    # Historical silver seasonal patterns (based on 20yr average)
    seasonal = {
        1:  ("Neutral-Positive", "Jan tends to open strong — new money flows"),
        2:  ("Positive", "Feb historically one of strongest months for silver"),
        3:  ("Weak", "Seasonal weakness — tax-loss harvesting, profit-taking"),
        4:  ("Weak-Neutral", "Apr can be choppy, late-month recovery"),
        5:  ("Neutral", "Mixed signals, wait for direction"),
        6:  ("Positive", "Jun often starts summer rally"),
        7:  ("Positive", "Jul strong — Indian/Chinese wedding season demand"),
        8:  ("Strong Positive", "Aug-Sept historically BEST months for silver"),
        9:  ("Strong Positive", "Continued seasonal strength, safe-haven demand"),
        10: ("Neutral-Weak", "Oct pullback common before year-end rally"),
        11: ("Positive", "Nov year-end positioning, Diwali demand"),
        12: ("Mixed", "Year-end profit-taking vs portfolio rebalancing"),
    }
    
    return {
        "month": _et_now().strftime("%B"),
        "tendency": seasonal.get(month, ("Neutral", ""))[0],
        "context": seasonal.get(month, ("Neutral", ""))[1],
    }


# ============================================================
# POSITION SIZING (account/vol aware)
# ============================================================

CONTRACT_OZ = 1000  # Micro Silver contract size — 1,000 oz/contract on COMEX
# "SIL" is overloaded: it's both the Micro Silver futures contract code and the
# Global X Silver Miners ETF ticker. We always use these labels in output to
# disambiguate — never bare "SIL".
MICRO_SILVER_LABEL = "SIL (Micro Silver)"
SIL_MINERS_LABEL = "SIL (Miners ETF)"


def compute_position_size(account_equity, risk_pct, atr, atr_median=None, stop_atr_mult=1.5):
    """
    Suggest max-contracts based on account size, per-trade risk %, and current ATR.

    - dollar_risk = equity * risk_pct/100
    - per-contract risk = stop_atr_mult * ATR * CONTRACT_OZ (dollar loss if stopped)
    - vol-adjustment: when ATR > 1.5x its 90d median, scale down by median/atr
      so dollar-risk stays roughly constant across vol regimes.

    Returns: {dollar_risk, per_contract_risk, suggested_max_contracts, vol_adjusted}
    """
    if not account_equity or account_equity <= 0 or not atr or atr <= 0:
        return None
    dollar_risk = account_equity * (risk_pct / 100.0)
    per_contract_risk = stop_atr_mult * atr * CONTRACT_OZ
    if per_contract_risk <= 0:
        return None
    raw = dollar_risk / per_contract_risk

    vol_adj_factor = 1.0
    if atr_median and atr_median > 0 and atr > 1.5 * atr_median:
        vol_adj_factor = atr_median / atr  # scale down in elevated vol
    suggested = max(1, int(raw * vol_adj_factor))

    return {
        "account_equity": float(account_equity),
        "risk_pct": float(risk_pct),
        "dollar_risk": round(dollar_risk, 0),
        "per_contract_risk": round(per_contract_risk, 0),
        "stop_atr_mult": stop_atr_mult,
        "atr_used": round(atr, 2),
        "atr_median_90d": round(atr_median, 2) if atr_median else None,
        "vol_adjusted": vol_adj_factor < 1.0,
        "vol_adj_factor": round(vol_adj_factor, 2),
        "suggested_max_contracts": suggested,
    }


# ============================================================
# CONVICTION SCORE — the single source of bullish/bearish bias
# ============================================================

def compute_conviction(technicals, macro, options, ig, fed_sentiment, cot=None):
    """
    Combine technicals, macro, positioning, and news sentiment into one
    conviction score (-10..+10). Used by both `generate_levels` (setup
    direction) and `generate_ladder` (allocation aggressiveness, exits).

    Returns: {score, label, reasons, components}
    """
    score = 0
    reasons = []
    components = {}

    technicals = technicals or {}
    macro = macro or {}
    options = options or {}
    ig = ig or {}
    fed_sentiment = fed_sentiment or {}
    cot = cot or {}

    # --- Technicals (up to ±5) ---
    tech_sub = 0
    trend = technicals.get("TREND", "")
    sma_200 = technicals.get("SMA_200")
    sma_20 = technicals.get("SMA_20")
    rsi = technicals.get("RSI_14", 50)
    macd_hist = technicals.get("MACD_HIST", 0)
    bb_pos = technicals.get("BB_POSITION", 50)
    # Need a current price reference — use last close anchor via SMA_20 distance if needed
    # (compute_conviction is called with full technicals dict so just use the indicators)
    sma_200_dist = technicals.get("SMA_200_DIST", 0)

    if "BULLISH" in trend and sma_200_dist > 0:
        tech_sub += 3
        reasons.append("Golden cross + above SMA_200")
    elif "BEARISH" in trend and sma_200_dist < 0:
        tech_sub -= 3
        reasons.append("Death cross + below SMA_200")

    sma_20_dist = technicals.get("SMA_20_DIST", 0)
    if sma_20_dist > 0:
        tech_sub += 1
    elif sma_20_dist < 0:
        tech_sub -= 1

    if rsi > 70:
        tech_sub -= 1
        reasons.append("RSI overbought — caution")
    elif rsi < 30:
        tech_sub += 1
        reasons.append("RSI oversold — buying opportunity")

    if macd_hist > 0:
        tech_sub += 1
    elif macd_hist < 0:
        tech_sub -= 1

    if bb_pos < 20:
        tech_sub += 1
    elif bb_pos > 80:
        tech_sub -= 1

    tech_sub = max(-5, min(5, tech_sub))
    components["technicals"] = tech_sub
    score += tech_sub

    # --- Macro (up to ±3) ---
    macro_sub = 0
    if "WEAKENING" in macro.get("DOLLAR_SIGNAL", ""):
        macro_sub += 1
        reasons.append("DXY weakening")
    elif "STRENGTHENING" in macro.get("DOLLAR_SIGNAL", ""):
        macro_sub -= 1
        reasons.append("DXY strengthening")

    if "FALLING" in macro.get("REAL_RATE_SIGNAL", ""):
        macro_sub += 1
        reasons.append("Real rates falling")
    elif "RISING" in macro.get("REAL_RATE_SIGNAL", ""):
        macro_sub -= 1
        reasons.append("Real rates rising")

    if "INVERTED" in macro.get("CURVE_SIGNAL", "") or "INVERTING" in macro.get("CURVE_SIGNAL", ""):
        macro_sub += 1
        reasons.append("Yield curve inverted")

    # GSR (silver lens, INVERTED from gold): high = silver cheap = bullish silver
    gsr = macro.get("GSR")
    if gsr:
        if gsr > 90:
            macro_sub += 1
            reasons.append("GSR extreme — silver historically cheap")
        elif gsr > 85:
            # Cross-validate with copper: high GSR + rising copper = strong; + falling copper = weak
            if "DOWN" in macro.get("SILVER_COPPER_TREND", ""):
                macro_sub += 0  # offsetting industrial drag
                reasons.append("GSR elevated but copper weak — mixed signal")
            else:
                macro_sub += 1
                reasons.append("GSR elevated — silver cheap vs gold")
        elif gsr < 65:
            macro_sub -= 1
            reasons.append("GSR low — silver overheated vs gold")

    # Silver/copper trend — small modifier (±0.5 effective inside ±3 macro band)
    sc_trend = macro.get("SILVER_COPPER_TREND", "")
    sma_50_dist = technicals.get("SMA_50_DIST", 0)
    if "UP" in sc_trend and sma_50_dist > 0:
        # Silver/copper rising AND silver above 50d MA = monetary momentum confirmed
        macro_sub += 0.5
        reasons.append("Silver/copper rising + silver > 50DMA")
    elif "DOWN" in sc_trend and sma_50_dist < 0:
        # Silver/copper falling AND silver below 50d MA = industrial drag confirmed
        macro_sub -= 0.5
        reasons.append("Silver/copper falling + silver < 50DMA")

    macro_sub = max(-3, min(3, macro_sub))
    components["macro"] = round(macro_sub, 1)
    score += macro_sub

    # --- Positioning (up to ±2) ---
    pos_sub = 0
    oi_signal = options.get("signal", "NEUTRAL") or ""
    low_liq = options.get("low_liquidity", False)
    if low_liq:
        reasons.append("SLV options low-liquidity — skipped")
    else:
        if oi_signal.startswith("BULLISH") or oi_signal.startswith("MILDLY_BULLISH"):
            pos_sub += 1
            reasons.append("SLV options bullish")
        elif oi_signal.startswith("BEARISH_HEDGE"):
            pos_sub -= 1
            reasons.append("Heavy downside hedging in SLV")

    if ig.get("available") and ig.get("long_pct") is not None:
        if ig["long_pct"] > 75:
            pos_sub -= 1
            reasons.append("IG retail crowded long")
        elif ig["long_pct"] < 30:
            pos_sub += 1
            reasons.append("IG retail crowded short")

    # COT: contrarian — extreme managed-money long is bearish
    if cot.get("available"):
        cot_signal = cot.get("signal", "")
        if "EXTREME LONG" in cot_signal:
            pos_sub -= 1
            reasons.append(f"COT MM long {cot.get('pct_52w', 0):.0f}th pct")
        elif "EXTREME SHORT" in cot_signal:
            pos_sub += 1
            reasons.append(f"COT MM short {cot.get('pct_52w', 0):.0f}th pct")

    pos_sub = max(-2, min(2, pos_sub))
    components["positioning"] = pos_sub
    score += pos_sub

    # --- News (up to ±1) ---
    news_sub = 0
    net = fed_sentiment.get("net_score", 0)
    if net >= 1:
        news_sub += 1
        reasons.append(f"Fed news dovish ({fed_sentiment.get('dovish', 0)}d/{fed_sentiment.get('hawkish', 0)}h)")
    elif net <= -1:
        news_sub -= 1
        reasons.append(f"Fed news hawkish ({fed_sentiment.get('hawkish', 0)}h/{fed_sentiment.get('dovish', 0)}d)")
    components["news"] = news_sub
    score += news_sub

    # Clamp final and round (macro can produce halves)
    score = round(max(-10, min(10, score)))

    if score >= 5:
        label = "strong_bullish"
    elif score >= 2:
        label = "bullish"
    elif score >= -1:
        label = "neutral"
    elif score >= -4:
        label = "bearish"
    else:
        label = "strong_bearish"

    return {"score": score, "label": label, "reasons": reasons, "components": components}


# ============================================================
# ENTRY/EXIT LEVEL GENERATOR
# ============================================================

def generate_levels(price, technicals, conviction, macro=None, options=None, ig=None):
    """Generate actionable entry/exit levels for silver futures."""
    if not price or not technicals:
        return {"error": "Insufficient data"}
    
    current = price
    levels = {"current_price": current, "timestamp": _et_now().isoformat()}
    
    # ATR-based stops and targets
    atr = technicals.get("ATR_14", current * 0.01)
    if atr and atr > 0:
        levels["atr"] = round(atr, 2)
        levels["atr_pct"] = round((atr / current) * 100, 2)
    
    # Support/resistance: pull from KEY_LEVELS (prev day, prior week, round, retracement)
    # plus moving averages and Bollinger bands. Tag by type.
    typed = []
    for kl in technicals.get("KEY_LEVELS", []):
        typed.append((kl["price"], kl["type"]))
    if technicals.get("SMA_50"):
        typed.append((technicals["SMA_50"], "SMA_50"))
    if technicals.get("SMA_200"):
        typed.append((technicals["SMA_200"], "SMA_200"))
    if technicals.get("BB_LOWER"):
        typed.append((technicals["BB_LOWER"], "BB_LOWER"))
    if technicals.get("BB_UPPER"):
        typed.append((technicals["BB_UPPER"], "BB_UPPER"))

    # Dedupe by price (within $1) — keep first label seen
    seen = {}
    for price, label in typed:
        key = round(price, 0)
        if key not in seen:
            seen[key] = (price, label)
    typed = list(seen.values())

    # Round-number levels are noise-prone; deprioritize when we have specific levels nearby.
    supports_raw = sorted([(p, t) for p, t in typed if p < current], key=lambda x: -x[0])
    resistances_raw = sorted([(p, t) for p, t in typed if p > current], key=lambda x: x[0])

    levels["supports"] = [{"level": round(p, 2), "type": t} for p, t in supports_raw[:3]]
    levels["resistances"] = [{"level": round(p, 2), "type": t} for p, t in resistances_raw[:3]]
    supports = [p for p, _ in supports_raw[:3]]
    resistances = [p for p, _ in resistances_raw[:3]]
    
    # Generate trade setups — direction comes from the unified conviction score.
    rsi = technicals.get("RSI_14", 50)
    macd_hist = technicals.get("MACD_HIST", 0)
    trend = technicals.get("TREND", "")

    conviction = conviction or {"score": 0, "label": "neutral", "reasons": []}
    cscore = conviction["score"]
    clabel = conviction["label"]

    # Map conviction label to display
    bias_map = {
        "strong_bullish": ("BULLISH", "🟢"),
        "bullish": ("MILDLY_BULLISH", "🟢"),
        "neutral": ("NEUTRAL", "🟡"),
        "bearish": ("MILDLY_BEARISH", "🔴"),
        "strong_bearish": ("BEARISH", "🔴"),
    }
    bias, color = bias_map.get(clabel, ("NEUTRAL", "🟡"))
    levels["bias"] = bias
    levels["color"] = color
    levels["conviction_score"] = cscore
    levels["conviction_label"] = clabel
    levels["conviction_reasons"] = conviction.get("reasons", [])

    # Trade setups
    if atr and atr > 0:
        if bias in ("BULLISH", "MILDLY_BULLISH"):
            # Long setup
            entry_zone_low = round(current - atr * 0.5, 2)
            entry_zone_high = round(current, 2)
            stop = round(min(supports[0], current - atr * 1.5) if supports else current - atr * 1.5, 2)
            target_1 = round(current + atr * 1.5, 2)
            target_2 = round(current + atr * 3.0, 2)
            risk = round(current - stop, 2)
            reward_1 = round(target_1 - current, 2)
            rr_1 = round(reward_1 / risk, 1) if risk > 0 else 0
            
            levels["long_setup"] = {
                "entry_zone": f"${entry_zone_low} - ${entry_zone_high}",
                "stop_loss": f"${stop}",
                "target_1": f"${target_1}",
                "target_2": f"${target_2}",
                "risk_reward": f"1:{rr_1}",
                "rationale": f"RSI {rsi}, {trend}, MACD {'positive' if macd_hist > 0 else 'negative'}",
            }
        
        if levels["bias"] in ("BEARISH", "MILDLY_BEARISH"):
            # Short setup
            entry_zone_low = round(current, 2)
            entry_zone_high = round(current + atr * 0.5, 2)
            stop = round(max(resistances[0], current + atr * 1.5) if resistances else current + atr * 1.5, 2)
            target_1 = round(current - atr * 1.5, 2)
            target_2 = round(current - atr * 3.0, 2)
            risk = round(stop - current, 2)
            reward_1 = round(current - target_1, 2)
            rr_1 = round(reward_1 / risk, 1) if risk > 0 else 0
            
            levels["short_setup"] = {
                "entry_zone": f"${entry_zone_low} - ${entry_zone_high}",
                "stop_loss": f"${stop}",
                "target_1": f"${target_1}",
                "target_2": f"${target_2}",
                "risk_reward": f"1:{rr_1}",
                "rationale": f"RSI {rsi}, {trend}, MACD {'positive' if macd_hist > 0 else 'negative'}",
            }
        
        if levels["bias"] == "NEUTRAL":
            # Range setup — buy low, sell high
            if supports and resistances:
                levels["range_setup"] = {
                    "buy_zone": f"${supports[0]} - ${round(supports[0] + atr * 0.3, 2)}",
                    "sell_zone": f"${resistances[0]} - ${round(resistances[0] + atr * 0.3, 2)}",
                    "stop_below": f"${round(supports[0] - atr, 2)}",
                    "stop_above": f"${round(resistances[0] + atr, 2)}",
                    "rationale": "Range-bound — buy support, sell resistance",
                }
    
    return levels


# ============================================================
# SCALING LADDER GENERATOR
# ============================================================

def generate_ladder(current_price, entry_price, contracts, max_contracts, technicals, levels,
                    imminent_risk, hours_to_event, max_loss=None, macro=None, options=None,
                    ig=None, fed_sentiment=None, conviction=None, post_event=None):
    """
    Generate scaling ladders for limit order placement.

    Buy ladder: specific prices and contract counts to accumulate at on dips.
    Sell ladder: specific prices and contract counts to trim at into strength.
    Core: contracts to hold regardless.

    Each tier is tied to a technical level (support, SMA, BB, resistance)
    so every limit order has a reason, not just a price.

    Macro/sentiment conviction determines whether to show ladders at all:
    - Strong bullish conviction → buy ladder only, sell ladder suppressed ("let it ride")
    - Mixed → both ladders, conservative trim sizes
    - Bearish → sell ladder emphasized, buy ladder smaller

    Returns: {"buy_ladder": [...], "sell_ladder": [...], "core_contracts": int,
              "conviction": str, "conviction_reasons": [str], "verdict": str}
    """
    if max_loss is None or max_loss <= 0:
        raise ValueError("Explicit positive max_loss is required for position management")
    remaining = max_contracts - contracts
    atr = technicals.get("ATR_14", current_price * 0.01)
    if not atr or atr <= 0:
        atr = current_price * 0.01

    supports = levels.get("supports", [])
    resistances = levels.get("resistances", [])
    nearest_support = supports[0].get("level", current_price - atr * 2) if supports else current_price - atr * 2
    nearest_resistance = resistances[0].get("level", current_price + atr * 2) if resistances else current_price + atr * 2
    sma_50 = technicals.get("SMA_50")
    sma_200 = technicals.get("SMA_200")
    bb_lower = technicals.get("BB_LOWER")
    rsi = technicals.get("RSI_14", 50)

    result = {
        "buy_ladder": [], "sell_ladder": [], "core_contracts": contracts,
        "conviction": "neutral", "conviction_reasons": [], "verdict": "",
    }

    if not entry_price or not contracts:
        return result

    pnl_per_oz = current_price - entry_price
    pnl_pct = (pnl_per_oz / entry_price) * 100

    # Compute take-profit level (same logic as format_brief position section)
    min_profit_oz = 20
    take_profit_level = None
    if current_price > entry_price + min_profit_oz:
        trail_profit = max(min_profit_oz, (current_price - entry_price) - atr * 1.5)
        take_profit_level = round(entry_price + trail_profit, 2)

    # Compute hard stop
    per_oz_loss = max_loss / (contracts * CONTRACT_OZ)
    hard_stop = round(entry_price - per_oz_loss, 2)
    if supports:
        tech_floor = round(nearest_support - atr * 0.5, 2)
        hard_stop = max(hard_stop, tech_floor)

    # Conviction is computed centrally — fall back to recomputing if not provided
    if conviction is None:
        conviction = compute_conviction(technicals, macro, options, ig, fed_sentiment)
    conviction_score = conviction["score"]
    conviction_reasons = conviction["reasons"]
    conviction_label = conviction["label"]

    trend = technicals.get("TREND", "")
    long_term_bullish = "BULLISH" in trend and (sma_200 and current_price > sma_200)
    long_term_bearish = "BEARISH" in trend and (sma_200 and current_price < sma_200)

    result["conviction"] = conviction_label
    result["conviction_reasons"] = conviction_reasons
    result["conviction_score"] = conviction_score

    # Local alias used by the rest of this function
    conviction = conviction_label

    # ================================================================
    # DETERMINE EXITS / ENTERS BASED ON CONVICTION
    # ================================================================

    # Exiting scenarios: risk event + profitable, or structural break
    exiting = False
    if imminent_risk and hours_to_event and hours_to_event < 48 and pnl_pct > 0.5:
        exiting = True
    if long_term_bearish and pnl_pct > 1:
        exiting = True

    # "Let it ride" mode: strong bullish conviction, no risk events, uptrend intact
    let_it_ride = (
        conviction in ("strong_bullish", "bullish")
        and not imminent_risk
        and long_term_bullish
        and pnl_pct > 0
    )

    # RSI cap — even in let-it-ride mode, force a partial trim when stretched.
    # RSI > 80 + price above the upper Bollinger band is the textbook
    # "stretched too far, mean-reversion overdue" combo.
    bb_upper = technicals.get("BB_UPPER")
    rsi_cap_active = (
        let_it_ride
        and rsi > 80
        and bb_upper
        and current_price > bb_upper
    )
    if rsi_cap_active:
        let_it_ride = False  # force a small trim through the sell-ladder path
        result["rsi_cap_triggered"] = True

    # Verdict — the human-readable summary
    if exiting:
        if imminent_risk:
            result["verdict"] = "PROTECT — risk event approaching, trim or tighten"
        else:
            result["verdict"] = "DEFENSIVE — chart breaking down, protect position"
    elif let_it_ride:
        result["verdict"] = "LET IT RIDE — strong setup, no reason to trim"
    elif conviction in ("strong_bullish", "bullish"):
        result["verdict"] = "LEAN LONG — add on dips, hold core"
    elif conviction == "neutral":
        result["verdict"] = "WAIT — mixed signals, hold and see"
    elif conviction == "bearish":
        result["verdict"] = "CAUTIOUS — tighten stops, don't add"
    else:
        result["verdict"] = "DEFENSIVE — reduce exposure if stopped"

    # ===== SELL LADDER =====
    # Only show when:
    #   - There's a catalyst (risk event, resistance, big profit, RSI-cap)
    #   - AND conviction isn't strongly bullish (if it is, let it ride)
    if pnl_per_oz > 5 and contracts >= 2:
        sell_tiers = []
        sell_remaining = contracts
        show_sell = False
        trim_aggression = 0.25  # default: trim 25% at tier 1

        # RSI-cap forces a small trim even when conviction is bullish
        if rsi_cap_active:
            show_sell = True
            trim_aggression = 0.10
            result["verdict"] = f"RSI CAP — RSI {rsi:.0f} above BB_UPPER, take 10% off the top"
        # Risk event always gets a sell ladder regardless of conviction
        elif imminent_risk and hours_to_event and hours_to_event < 48:
            show_sell = True
            trim_aggression = 0.40 if hours_to_event < 12 else 0.30  # bigger trim closer to event
        # Near resistance — trim a bit, but less if conviction is bullish
        elif nearest_resistance and current_price >= nearest_resistance * 0.98:
            if conviction in ("strong_bullish", "bullish"):
                show_sell = False  # don't trim at resistance if everything's bullish — let it break out
            else:
                show_sell = True
                trim_aggression = 0.20
        # Up big — trim if conviction is mixed/bearish, hold if bullish
        elif pnl_pct > 3:
            if conviction in ("strong_bullish", "bullish"):
                show_sell = False  # up 3% with strong conviction = let it run
            elif conviction == "neutral":
                show_sell = True
                trim_aggression = 0.15  # small trim, mostly hold
            else:
                show_sell = True
                trim_aggression = 0.30  # bigger trim if bearish
        # Take-profit active — use if conviction isn't strongly bullish
        elif take_profit_level and take_profit_level < current_price:
            if conviction in ("strong_bullish",):
                show_sell = False  # conviction is high, trail instead of taking profit
            else:
                show_sell = True
                trim_aggression = 0.20

        if show_sell:
            # Tier 1: take-profit or risk event exit
            tp_price = take_profit_level if (take_profit_level and take_profit_level < current_price) else round(nearest_resistance * 0.99, 2)
            tp_contracts = max(1, round(sell_remaining * trim_aggression))
            tp_pnl = round((tp_price - entry_price) * CONTRACT_OZ * tp_contracts, 0)

            if imminent_risk and hours_to_event and hours_to_event < 48:
                tp_label = "before risk event"
            elif take_profit_level and take_profit_level < current_price:
                tp_label = "take-profit trigger"
            elif nearest_resistance and tp_price >= nearest_resistance * 0.98:
                tp_label = "near resistance"
            else:
                tp_label = "profit target"

            sell_tiers.append({
                "price": tp_price, "contracts": tp_contracts,
                "pnl": tp_pnl, "label": tp_label,
            })
            sell_remaining -= tp_contracts

            # Tier 2: resistance target (only if room and conviction isn't bullish)
            if nearest_resistance and nearest_resistance > current_price and sell_remaining > 2:
                if conviction not in ("strong_bullish", "bullish"):
                    r_contracts = max(1, round(sell_remaining * 0.3))
                    r_pnl = round((nearest_resistance - entry_price) * CONTRACT_OZ * r_contracts, 0)
                    sell_tiers.append({
                        "price": nearest_resistance, "contracts": r_contracts,
                        "pnl": r_pnl, "label": "resistance target",
                    })
                    sell_remaining -= r_contracts

            result["sell_ladder"] = sell_tiers
            result["core_contracts"] = sell_remaining

    # ===== BUY LADDER =====
    # Show when there's room to add and we're not actively exiting.
    # Scale aggressiveness with conviction.
    if remaining > 0 and not exiting:
        buy_levels = []
        used_prices = []

        def add_level(price, label):
            for up in used_prices:
                if abs(price - up) < atr * 0.3:
                    return
            buy_levels.append({"price": price, "label": label})
            used_prices.append(price)

        # Collect technical levels below current price
        if nearest_support < current_price:
            add_level(nearest_support, "near-term support")
        if sma_50 and sma_50 < current_price:
            add_level(sma_50, "SMA_50")
        if sma_200 and sma_200 < current_price:
            add_level(sma_200, "SMA_200")
        if bb_lower and bb_lower < current_price:
            add_level(bb_lower, "BB lower band")

        # Sort nearest first
        buy_levels.sort(key=lambda x: x["price"], reverse=True)

        # Fill gaps between tiers
        filled = [buy_levels[0]] if buy_levels else []
        for bl in buy_levels[1:]:
            gap = filled[-1]["price"] - bl["price"]
            while gap > atr * 2 and len(filled) < 5:
                mid = round(filled[-1]["price"] - atr * 1.5, 2)
                filled.append({"price": mid, "label": "ATR-based level"})
                gap = filled[-1]["price"] - bl["price"]
            filled.append(bl)
        buy_levels = filled

        # Ensure 3 tiers minimum
        if len(buy_levels) < 3:
            deepest = buy_levels[-1]["price"] if buy_levels else current_price
            while len(buy_levels) < 3:
                deeper = round(deepest - atr * 1.5, 2)
                buy_levels.append({"price": deeper, "label": "ATR extension"})
                deepest = deeper

        buy_levels = buy_levels[:3]

        # Contract allocation scaled by conviction
        if conviction in ("strong_bullish", "bullish"):
            # Aggressive: 50/30/20 — front-load tier 1, you want to buy the dip
            allocation = [0.50, 0.30, 0.20]
        elif conviction == "neutral":
            # Balanced: 40/35/25
            allocation = [0.40, 0.35, 0.25]
        elif conviction in ("bearish", "strong_bearish"):
            # Conservative: 30/35/35 — save powder for deeper levels
            allocation = [0.30, 0.35, 0.35]
        else:
            allocation = [0.40, 0.35, 0.25]

        # Post-event accumulation override: high-impact event just passed and price
        # has dropped to/below pre-event support → front-load tier 1 even harder.
        post_event_active = False
        if post_event and post_event.get("event") and buy_levels:
            pre_event_support = post_event.get("pre_event_support")
            top_buy_price = buy_levels[0]["price"]
            if pre_event_support and current_price <= pre_event_support * 1.005:
                post_event_active = True
                allocation = [0.60, 0.25, 0.15]
                buy_levels[0]["label"] = (
                    f"POST-EVENT ENTRY ({post_event['event']}, {post_event.get('hours_ago', '?'):.0f}h ago)"
                )
                result["post_event_entry"] = {
                    "event": post_event["event"],
                    "hours_ago": post_event.get("hours_ago"),
                    "pre_event_support": pre_event_support,
                }

        if len(buy_levels) == 1:
            buy_levels[0]["contracts"] = remaining
        elif len(buy_levels) == 2:
            t1 = max(1, round(remaining * allocation[0]))
            buy_levels[0]["contracts"] = t1
            buy_levels[1]["contracts"] = remaining - t1
        else:
            t1 = max(1, round(remaining * allocation[0]))
            t2 = max(1, round(remaining * allocation[1]))
            t3 = max(1, remaining - t1 - t2)
            buy_levels[0]["contracts"] = t1
            buy_levels[1]["contracts"] = t2
            buy_levels[2]["contracts"] = t3

        # Calculate new average entry after each tier
        for bl in buy_levels:
            c = bl["contracts"]
            new_avg = round((entry_price * contracts + bl["price"] * c) / (contracts + c), 2)
            bl["new_avg"] = new_avg
            bl["avg_drop"] = round(entry_price - new_avg, 2)

        result["buy_ladder"] = buy_levels

    return result


# ============================================================
# FED / CENTRAL BANK NEWS
# ============================================================

def fetch_fed_news():
    """Fetch recent Fed/central bank news via ddgs CLI or direct URLs."""
    result = []
    import subprocess
    
    # Try ddgs first
    try:
        proc = subprocess.run(
            ["ddgs", "news", "-k", "federal reserve silver interest rate Powell", "-m", "5", "-t", "d", "--no-color"],
            capture_output=True, text=True, timeout=20
        )
        text = proc.stdout
        if "DDGSException" not in text and len(text) > 100:
            lines = text.strip().split("\n")
            current_title, current_body, current_url = "", "", ""
            for line in lines:
                if line.startswith("title:"):
                    current_title = line.replace("title:", "").strip()
                elif line.startswith("body:"):
                    current_body = line.replace("body:", "").strip()
                elif line.startswith("href:"):
                    current_url = line.replace("href:", "").strip()
                elif line == "" and current_title and current_url:
                    result.append({"title": current_title, "body": current_body[:200], "url": current_url})
                    current_title, current_body, current_url = "", "", ""
            if len(result) >= 3:
                return result[:8]
    except Exception:
        pass
    
    # Fallback: scrape Reuters/GZero directly for Fed headlines
    fallback_urls = [
        "https://www.reuters.com/markets/us/",
        "https://www.cnbc.com/economy/",
    ]
    for url in fallback_urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            resp = urllib.request.urlopen(req, timeout=15)
            html = resp.read().decode("utf-8", errors="ignore")
            # Extract headlines that mention fed/rate/silver/dollar
            headlines = re.findall(r'<a[^>]*href="([^"]*)"[^>]*>([^<]*(?:Fed|rate|silver|dollar|Powell|Treasury|inflation|central bank)[^<]*)</a>', html, re.IGNORECASE)
            for href, title in headlines[:5]:
                title = re.sub(r'\s+', ' ', title).strip()
                if title and len(title) > 20:
                    result.append({"title": title, "url": href if href.startswith("http") else f"https://www.reuters.com{href}"})
            if len(result) >= 3:
                break
        except Exception:
            pass
        time.sleep(1)
    
    return result[:8]


# ============================================================
# NEWS SENTIMENT CLASSIFICATION (LLM)
# ============================================================

NEWS_CACHE_PATH = "/tmp/.silver_trader_news_cache.json"

_DOVISH_KW = [
    "rate cut", "rate cuts", "easing", "dovish", "pause", "lower rate",
    "soft landing", "recession risk", "slowdown", "ease policy",
]
_HAWKISH_KW = [
    "rate hike", "rate hikes", "rate increase", "tightening", "hawkish",
    "higher for longer", "inflation pickup", "hot inflation",
]
_NEGATORS = [
    "no ", "not ", "won't ", "wont ", "rules out ", "ruled out ", "rule out ",
    "doesn't ", "doesnt ", "didn't ", "didnt ", "avoid ", "avoiding ",
]


def _news_item_hash(item):
    text = (item.get("title", "") + "|" + (item.get("body", "") or "")[:500])
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def _keyword_sentiment_fallback(item):
    """Negation-aware keyword classifier — used when LLM is unavailable."""
    text = (item.get("title", "") + " " + (item.get("body", "") or "")).lower()

    def hit(kw):
        idx = text.find(kw)
        if idx == -1:
            return False
        window = text[max(0, idx - 30):idx]
        if any(n in window for n in _NEGATORS):
            return False
        return True

    dov = sum(1 for k in _DOVISH_KW if hit(k))
    haw = sum(1 for k in _HAWKISH_KW if hit(k))
    if dov > haw:
        return {"label": "dovish", "confidence": 0.5, "reason": "keyword fallback"}
    if haw > dov:
        return {"label": "hawkish", "confidence": 0.5, "reason": "keyword fallback"}
    return {"label": "neutral", "confidence": 0.4, "reason": "keyword fallback"}


def _llm_classify_batch(items):
    """
    Batch-classify news items via Gemini API (uses GEMINI_API_KEY from ~/.hermes/.env).
    Returns dict[index] -> {label, confidence, reason} for items the LLM scored.
    Returns empty dict on any failure (caller falls back per-item).
    """
    if not items:
        return {}

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return {}

    try:
        from google import genai
    except ImportError:
        return {}

    items_text = "\n\n".join(
        f"{i}. Title: {it.get('title', '')}\n   Body: {(it.get('body', '') or '')[:300]}"
        for i, it in enumerate(items)
    )
    prompt = f"""Classify each news item by its implication for SILVER prices.

- "dovish" = bullish silver (rate cuts, easing, recession risk, dollar weakness, soft landing concerns)
- "hawkish" = bearish silver (rate hikes, tightening, hot inflation forcing more hikes, dollar strength)
- "neutral" = neither, or genuinely mixed

CRITICAL: handle negation. "no rate cut", "rules out hike", "won't ease" mean the OPPOSITE of the keyword.

Return JSON array only, no prose, no markdown fence:
[{{"i": 0, "label": "dovish|hawkish|neutral", "confidence": 0.0-1.0, "reason": "<6 words"}}, ...]

News items:
{items_text}"""

    model = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")
    try:
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(model=model, contents=prompt)
        out = (resp.text or "").strip()
        if out.startswith("```"):
            out = re.sub(r"^```\w*\n", "", out)
            out = re.sub(r"\n```\s*$", "", out)
        parsed = json.loads(out)
        result = {}
        for entry in parsed:
            i = entry.get("i")
            if isinstance(i, int) and 0 <= i < len(items):
                result[i] = {
                    "label": entry.get("label", "neutral"),
                    "confidence": float(entry.get("confidence", 0.5)),
                    "reason": entry.get("reason", ""),
                }
        return result
    except Exception:
        return {}


def classify_fed_news_sentiment(news_items, use_llm=True):
    """
    Classify Fed/macro news for silver-price implication.

    Returns:
        {
          "items": [news items annotated with label/confidence/reason],
          "dovish": int, "hawkish": int, "neutral": int,
          "net_score": int (dovish - hawkish; positive = bullish silver),
          "method": "llm" | "cache" | "keyword",
        }
    """
    if not news_items:
        return {"items": [], "dovish": 0, "hawkish": 0, "neutral": 0, "net_score": 0, "method": "none"}

    cache = {}
    try:
        with open(NEWS_CACHE_PATH) as f:
            cache = json.load(f)
    except Exception:
        cache = {}

    needed = []  # (index_in_news_items, item) needing LLM classification
    for i, it in enumerate(news_items):
        h = _news_item_hash(it)
        if h in cache:
            it["sentiment"] = dict(cache[h], source="cache")
        else:
            needed.append((i, it))

    methods_used = set("cache" for it in news_items if "sentiment" in it)

    if needed and use_llm:
        # LLM expects 0-indexed batch; map back to original indices
        batch_items = [it for _, it in needed]
        llm_results = _llm_classify_batch(batch_items)
        for batch_idx, classification in llm_results.items():
            orig_idx, orig_item = needed[batch_idx]
            orig_item["sentiment"] = dict(classification, source="llm")
            cache[_news_item_hash(orig_item)] = classification
        if llm_results:
            methods_used.add("llm")

    # Anything still missing → keyword fallback
    for _, it in needed:
        if "sentiment" not in it:
            cls = _keyword_sentiment_fallback(it)
            it["sentiment"] = dict(cls, source="keyword")
            cache[_news_item_hash(it)] = cls
            methods_used.add("keyword")

    try:
        with open(NEWS_CACHE_PATH, "w") as f:
            json.dump(cache, f)
    except Exception:
        pass

    dovish = sum(1 for it in news_items if it["sentiment"]["label"] == "dovish")
    hawkish = sum(1 for it in news_items if it["sentiment"]["label"] == "hawkish")
    neutral = sum(1 for it in news_items if it["sentiment"]["label"] == "neutral")

    method = "llm" if "llm" in methods_used else ("cache" if "cache" in methods_used else "keyword")

    return {
        "items": news_items,
        "dovish": dovish,
        "hawkish": hawkish,
        "neutral": neutral,
        "net_score": dovish - hawkish,
        "method": method,
    }


# ============================================================
# FORMATTERS
# ============================================================

def format_brief(data):
    """Format as Slack-ready briefing."""
    lines = []
    
    silver = data.get("price_data", {}).get("SI=F", {})
    slv = data.get("price_data", {}).get("SLV", {})
    sil_miners = data.get("price_data", {}).get("SIL", {})
    agq = data.get("price_data", {}).get("AGQ", {})
    tech = data.get("technicals", {})
    macro = data.get("macro", {})
    levels = data.get("levels", {})
    options = data.get("options", {})
    ig = data.get("ig_sentiment", {})
    seasonal = data.get("seasonal", {})
    fed_news = data.get("fed_news", [])
    polymarket = data.get("polymarket", [])
    volume = data.get("volume", {})
    
    now = _et_now()
    now_pt = now.astimezone(PT).strftime("%-I:%M %p PT")
    now_et = now.strftime("%-I:%M %p ET")
    session = data.get("session", {})
    session_tag = f" · {session.get('label', '')}" if session.get("label") else ""

    lines.append(f"🥈 **SILVER FUTURES TRADER BRIEFING** — {now_pt} ({now_et}){session_tag}")
    if session.get("descr"):
        lines.append(f"   Session: {session['descr']}")
    lines.append("")

    # Price header
    if silver.get("price"):
        chg = silver.get("change_pct", 0)
        emoji = "🔺" if chg > 0 else "🔻" if chg < 0 else "➡️"
        intraday_tag = " (intraday)" if silver.get("intraday") else ""
        lines.append(f"{emoji} **SI=F: ${silver['price']}**{intraday_tag} ({chg:+.2f}%) | SLV: ${slv.get('price', '?')} | {SIL_MINERS_LABEL}: ${sil_miners.get('price', '?')} | AGQ: ${agq.get('price', '?')}")
        if volume.get("volume"):
            vol_emoji = "📊" if volume.get("volume_ratio", 1) > 1.3 else ""
            lines.append(f"   Volume: {volume['volume']:,} ({volume.get('volume_ratio', 0):.1f}x avg) {vol_emoji}")
    
    lines.append("")
    
    # Bias & Recommendation — conviction is the single score
    if levels.get("bias"):
        cscore = levels.get("conviction_score", 0)
        lines.append(f"**{levels['color']} BIAS: {levels['bias']}** (Conviction: {cscore:+d})")
    
    if levels.get("long_setup"):
        s = levels["long_setup"]
        lines.append(f"**🟢 LONG SETUP:**")
        lines.append(f"   Entry: {s['entry_zone']} | Stop: {s['stop_loss']}")
        lines.append(f"   Target 1: {s['target_1']} | Target 2: {s['target_2']}")
        lines.append(f"   R:R = {s['risk_reward']} | {s['rationale']}")
    
    if levels.get("short_setup"):
        s = levels["short_setup"]
        lines.append(f"**🔴 SHORT SETUP:**")
        lines.append(f"   Entry: {s['entry_zone']} | Stop: {s['stop_loss']}")
        lines.append(f"   Target 1: {s['target_1']} | Target 2: {s['target_2']}")
        lines.append(f"   R:R = {s['risk_reward']} | {s['rationale']}")
    
    if levels.get("range_setup"):
        s = levels["range_setup"]
        lines.append(f"**🟡 RANGE SETUP:**")
        lines.append(f"   Buy: {s['buy_zone']} | Sell: {s['sell_zone']}")
        lines.append(f"   Stop Below: {s['stop_below']} | Stop Above: {s['stop_above']}")

    if format_metals_options_section:
        option_lines = format_metals_options_section(
            data.get("metals_options", {}),
            "SLV",
            spot=slv.get("price"),
            conviction_score=levels.get("conviction_score", 0),
        )
        if option_lines:
            lines.append("")
            lines.extend(option_lines)

    # Position Management (if entry price provided)
    entry_price = data.get("entry_price")
    contracts = data.get("contracts")
    max_loss = data["max_loss"]
    tech_local = data.get("technicals", {})
    macro_local = data.get("macro", {})
    fed_news = data.get("fed_news", [])

    if entry_price and silver.get("price"):
        current = silver["price"]
        pnl = current - entry_price
        pnl_pct = (pnl / entry_price) * 100
        pnl_emoji = "🟢" if pnl >= 0 else "🔴"

        # Dollar P&L for the position
        per_contract_pnl = pnl * CONTRACT_OZ  # 1,000 oz per Micro Silver contract
        total_pnl = per_contract_pnl * contracts if contracts else per_contract_pnl
        if contracts:
            lines.append("")
            lines.append(f"**💼 POSITION ({contracts} contracts {MICRO_SILVER_LABEL}, avg entry: ${entry_price:.2f}):**")
            lines.append(f"   {pnl_emoji} P&L: ${pnl:+.2f}/oz ({pnl_pct:+.2f}%) = ${total_pnl:+,.0f} total")
        else:
            lines.append("")
            lines.append(f"**💼 POSITION (avg entry: ${entry_price:.2f}):**")
            lines.append(f"   {pnl_emoji} P&L: ${pnl:+.2f} ({pnl_pct:+.2f}%)")

        sizing = data.get("sizing")
        if sizing:
            vol_tag = " ⚠️ vol-adjusted down" if sizing.get("vol_adjusted") else ""
            lines.append(
                f"   📏 Sizing: ${sizing['account_equity']:,.0f} equity × {sizing['risk_pct']:.1f}% risk → "
                f"${sizing['dollar_risk']:,.0f} risk / ${sizing['per_contract_risk']:,.0f}/contract → "
                f"max {sizing['suggested_max_contracts']} contracts{vol_tag}"
            )
            if contracts and contracts > sizing["suggested_max_contracts"]:
                lines.append(
                    f"   ⚠️ Holding {contracts} > suggested {sizing['suggested_max_contracts']} — "
                    f"position is oversized for stated risk."
                )

        # ---- LIMIT ORDER LADDER ----
        ladder = data.get("ladder", {})
        buy_ladder = ladder.get("buy_ladder", [])
        sell_ladder = ladder.get("sell_ladder", [])
        core_contracts = ladder.get("core_contracts", contracts)
        max_contracts = data["max_contracts"]
        conviction = ladder.get("conviction", "neutral")
        conviction_reasons = ladder.get("conviction_reasons", [])
        conviction_score = ladder.get("conviction_score", 0)
        verdict = ladder.get("verdict", "")

        if buy_ladder or sell_ladder or verdict:
            lines.append("")

            # Verdict line — the macro/sentiment summary
            if verdict:
                conviction_emoji = {
                    "strong_bullish": "🟢🟢",
                    "bullish": "🟢",
                    "neutral": "🟡",
                    "bearish": "🔴",
                    "strong_bearish": "🔴🔴",
                }.get(conviction, "🟡")
                session = data.get("session", {})
                hours_tag = "" if session.get("trading_active", True) else " [AFTER-HOURS — limit orders only]"
                lines.append(f"   {conviction_emoji} **{verdict}**{hours_tag} (conviction: {conviction_score:+d})")
                if conviction_reasons:
                    lines.append(f"      {' | '.join(conviction_reasons[:4])}")
                if ladder.get("post_event_entry"):
                    pe = ladder["post_event_entry"]
                    lines.append(f"   🎯 Post-event entry: {pe['event']} {pe['hours_ago']:.0f}h ago, price at pre-event support → tier 1 boosted.")

            # Ladder display
            if buy_ladder or sell_ladder:
                lines.append(f"   📐 **LIMIT ORDER LADDER:**")

            if buy_ladder:
                remaining = max_contracts - contracts
                lines.append(f"   BUY ({remaining} contracts available):")
                for i, tier in enumerate(buy_ladder, 1):
                    avg_drop = tier.get("avg_drop", 0)
                    drop_str = f" → avg ${tier['new_avg']}" if tier.get("new_avg") else ""
                    lines.append(f"     {i}. {tier['contracts']} @ ${tier['price']:.0f} ({tier['label']}){drop_str}")

            if sell_ladder:
                lines.append(f"   SELL ({contracts} contracts held):")
                for i, tier in enumerate(sell_ladder, 1):
                    pnl_dollar = tier.get("pnl", 0)
                    lines.append(f"     {i}. {tier['contracts']} @ ${tier['price']:.0f} ({tier['label']}) → +${pnl_dollar:,.0f}")
                lines.append(f"     Core: {core_contracts} contracts — hold")

        # ---- MACRO/NEWS SENTIMENT ----
        macro_bullish = 0
        macro_bearish = 0
        macro_signals = []

        # DXY
        dxy_signal = macro_local.get("DOLLAR_SIGNAL", "")
        if "WEAKENING" in dxy_signal:
            macro_bullish += 1
            macro_signals.append("DXY weakening (bullish silver)")
        elif "STRENGTHENING" in dxy_signal:
            macro_bearish += 1
            macro_signals.append("DXY strengthening (bearish silver)")

        # Real rates
        rate_signal = macro_local.get("REAL_RATE_SIGNAL", "")
        if "FALLING" in rate_signal:
            macro_bullish += 1
            macro_signals.append("Real rates falling (bullish silver)")
        elif "RISING" in rate_signal:
            macro_bearish += 1
            macro_signals.append("Real rates rising (bearish silver)")

        # Yield curve
        curve_signal = macro_local.get("CURVE_SIGNAL", "")
        if "INVERTING" in curve_signal or "INVERTED" in curve_signal:
            macro_bullish += 1
            macro_signals.append("Yield curve inverted (flight to safety)")

        # Fed news sentiment — pre-classified (LLM with keyword fallback)
        fed_sentiment = data.get("fed_sentiment", {})
        net = fed_sentiment.get("net_score", 0)
        if net >= 1:
            macro_bullish += 1
            macro_signals.append(f"Fed news dovish ({fed_sentiment.get('dovish', 0)}d/{fed_sentiment.get('hawkish', 0)}h)")
        elif net <= -1:
            macro_bearish += 1
            macro_signals.append(f"Fed news hawkish ({fed_sentiment.get('hawkish', 0)}h/{fed_sentiment.get('dovish', 0)}d)")

        macro_score = macro_bullish - macro_bearish  # -4 to +4

        # ---- KEY TECHNICALS ----
        conviction_score = levels.get("conviction_score", 0)
        components = data.get("conviction", {}).get("components", {})
        tech_sub = components.get("technicals", 0)
        atr_val = tech_local.get("ATR_14", current * 0.01)
        supports = levels.get("supports", [])
        resistances = levels.get("resistances", [])
        nearest_support = supports[0].get("level", current - atr_val * 2) if supports else current - atr_val * 2
        nearest_resistance = resistances[0].get("level", current + atr_val * 2) if resistances else current + atr_val * 2
        sma_200 = tech_local.get("SMA_200")
        trend = tech_local.get("TREND", "")
        rsi = tech_local.get("RSI_14", 50)

        long_term_bullish = "BULLISH" in trend and (sma_200 and current > sma_200)
        long_term_bearish = "BEARISH" in trend and (sma_200 and current < sma_200)
        macro_favors_long = macro_score >= 1
        macro_favors_short = macro_score <= -1

        # ---- HARD STOP (dollar-based) ----
        # Calculate from max tolerable loss
        if contracts:
            per_oz_loss = max_loss / (contracts * CONTRACT_OZ)
            hard_stop = round(entry_price - per_oz_loss, 2)
        else:
            hard_stop = round(current - atr_val * 1.5, 2)
        # Floor: never let stop go below nearest technical support minus a small buffer
        if supports:
            tech_floor = round(nearest_support - atr_val * 0.5, 2)
            hard_stop = max(hard_stop, tech_floor)

        # ---- TAKE-PROFIT / TACTICAL EXIT ----
        # Not a standing stop. Only activates when there's a reason to exit early:
        # - Risk event imminent and you're profitable → take profits, re-enter at floor
        # - Chart structural break and you're profitable → get out, re-enter at floor
        # - Otherwise: no tactical level, just HOLD with hard stop
        imminent_risk = data.get("imminent_risk", False)
        hours_to_event = data.get("hours_to_event")
        imminent_events_list = data.get("imminent_events", [])
        risk_events_list = data.get("risk_events", [])

        # Calculate take-profit level: locks in at least $20/oz profit ($2,200/contract)
        # Only meaningful if current price is above entry + $20
        min_profit_oz = 20
        take_profit_level = None
        if current > entry_price + min_profit_oz:
            # Trail: entry + max($20, current - entry - 1.5*ATR)
            # This means: keep at least $20 profit, but trail it up as price rises
            trail_profit = max(min_profit_oz, (current - entry_price) - atr_val * 1.5)
            take_profit_level = round(entry_price + trail_profit, 2)

        # ---- RECOMMENDATION ----
        # Core thesis: silver goes up long-term. Default is HOLD. But:
        # - Before risk events: take profits, set re-entry limit
        # - Chart deteriorating: tactical exit (higher than hard stop)
        # - After event passes: re-enter at the floor
        rec_lines = []

        # Macro context line
        if macro_signals:
            signal_emoji = "🟢" if macro_score > 0 else ("🔴" if macro_score < 0 else "🟡")
            lines.append(f"   {signal_emoji} Macro: {' | '.join(macro_signals[:3])}")

        # Risk event warning
        if imminent_risk and imminent_events_list:
            event_names = [e["event"] for e in imminent_events_list[:3]]
            hours_str = f"{hours_to_event:.0f}h" if hours_to_event else "?"
            lines.append(f"   ⚡ **RISK EVENT in {hours_str}:** {', '.join(event_names)}")

        # Structural breakdown: price below SMA_200 AND bearish macro
        structural_break = long_term_bearish and macro_favors_short
        # Mixed breakdown: below SMA_200 but macro still supportive (dip, not a trend change)
        dip_not_break = long_term_bearish and not macro_favors_short

        # ---- TACTICAL EXIT: risk event approaching + profitable ----
        if imminent_risk and pnl_pct > 0.5 and hours_to_event and hours_to_event < 48:
            # You're profitable and a big catalyst is coming. Take profits, re-enter after.
            event_names = [e["event"] for e in imminent_events_list[:2]]
            re_entry = round(nearest_support - atr_val * 0.3, 2)  # below support = the floor
            tp = take_profit_level if take_profit_level else current  # use TP level if it exists
            tp_profit = round((tp - entry_price) * CONTRACT_OZ * contracts, 0)
            if hours_to_event < 12:
                rec_lines.append(f"**TAKE PROFITS NOW** — {', '.join(event_names)} in {hours_to_event:.0f}h. You're up {pnl_pct:.1f}%. Lock it in.")
            else:
                rec_lines.append(f"**TAKE PROFITS before event** — {', '.join(event_names)} in {hours_to_event:.0f}h. Up {pnl_pct:.1f}%.")
            if take_profit_level and take_profit_level < current:
                rec_lines.append(f"   Sell at market or set limit at ${tp:.0f} (locks ${tp_profit:,.0f} profit). Don't wait for the event.")
            rec_lines.append(f"   After closing, set re-entry limit at **${re_entry:.0f}** (below support). Buy back cheaper after the dust settles.")
            rec_lines.append(f"   Worst case: event is bullish and silver gaps up. You miss a move but protect ${total_pnl:,.0f}.")
            rec_lines.append(f"   Best case: event dumps silver, you re-enter ${round(current - re_entry, 0):.0f}/oz lower.")
        # ---- TACTICAL EXIT: chart deteriorating + bearish news ----
        elif structural_break and pnl_pct > 1:
            # Below SMA_200 + bearish macro + still profitable. Get out, wait for floor.
            re_entry = round(nearest_support - atr_val * 0.5, 2)
            rec_lines.append(f"**TACTICAL EXIT** — Below SMA_200 + bearish macro. You're still up {pnl_pct:.1f}%. Get out now.")
            rec_lines.append(f"   Set re-entry limit at **${re_entry:.0f}**. Silver always recovers — buy back at the floor, not on the way down.")
            rec_lines.append(f"   Close 100%, wait for reversal (price back above SMA_200 or RSI < 30 bounce).")
        elif imminent_risk and pnl_pct <= 0.5 and hours_to_event and hours_to_event < 24:
            # Risk event imminent but not profitable — tighten stop to breakeven
            event_names = [e["event"] for e in imminent_events_list[:2]]
            rec_lines.append(f"**TIGHTEN STOP** — {', '.join(event_names)} in {hours_to_event:.0f}h. Move stop to ${round(entry_price, 0)} (breakeven).")
            rec_lines.append(f"   If stopped out, set re-entry limit at ${nearest_support:.0f}. Buy the dip after event passes.")
        elif structural_break:
            # Structural break but not profitable — defensive hold
            if pnl_pct > 0:
                rec_lines.append(f"**HOLD / TIGHTEN** — Below SMA_200 + bearish macro. Move stop to breakeven ${round(entry_price, 0)}.")
            elif pnl_pct > -3:
                rec_lines.append(f"**HOLD** — Down {abs(pnl_pct):.1f}%. Chart weak + bearish macro, but stop at ${hard_stop:.0f} hasn't hit.")
                rec_lines.append(f"   Silver pulls back 10-15% in bull markets. You're not there yet. Hold.")
            else:
                rec_lines.append(f"**HOLD (hard stop)** — Down {abs(pnl_pct):.1f}%. Stop at ${hard_stop:.0f}.")
                rec_lines.append(f"   If stop hits, reduce to 5 contracts. Set re-entry limit at ${nearest_support:.0f}.")
        elif dip_not_break:
            # Below SMA_200 but macro says silver — buying opportunity
            if pnl_pct > 0:
                rec_lines.append(f"**HOLD / ADD** — Below SMA_200 but macro supports silver ({', '.join(macro_signals[:2])}).")
                rec_lines.append(f"   This is a dip, not a crash. Add at ${nearest_support:.0f} to lower your avg.")
            elif pnl_pct > -3:
                rec_lines.append(f"**ADD** — Down {abs(pnl_pct):.1f}% but macro tailwind. This is the dip you want to buy.")
                rec_lines.append(f"   Add at ${nearest_support:.0f}. Lower your avg cost. Long-term thesis hasn't changed.")
            else:
                rec_lines.append(f"**ADD (careful)** — Down {abs(pnl_pct):.1f}%, macro supports silver. Scale in at ${nearest_support:.0f}.")
                rec_lines.append(f"   Add 2-3 contracts, not 10. Let it confirm bottom.")
        elif long_term_bullish:
            # Above SMA_200 — the money zone
            if pnl_pct > 5:
                rec_lines.append(f"**HOLD** — Uptrend intact, up {pnl_pct:.1f}%. Let it run.")
                if macro_favors_long:
                    rec_lines.append(f"   Macro tailwind. Add on ANY dip to ${nearest_support:.0f}.")
                else:
                    rec_lines.append(f"   Trail stop to breakeven ${round(entry_price, 0)}. Don't add until macro clears.")
            elif pnl_pct > 0:
                rec_lines.append(f"**HOLD / ADD** — Above SMA_200, uptrend intact. Add on pullbacks to ${nearest_support:.0f}.")
                if macro_favors_long:
                    rec_lines.append(f"   Macro supports you. Be aggressive on dips — build position size.")
                else:
                    rec_lines.append(f"   Macro mixed, chart says up. Add small (2-3 contracts) on dips, not here.")
            else:
                rec_lines.append(f"**HOLD / ADD** — Above SMA_200, down {abs(pnl_pct):.1f}%. Noise. Add at ${nearest_support:.0f}.")
                rec_lines.append(f"   Bull market drawdowns are buying opportunities.")
        else:
            # No clear trend — default HOLD, look for macro edge
            if macro_favors_long:
                rec_lines.append(f"**HOLD / ADD** — Macro supports silver. Buy dips to ${nearest_support:.0f}.")
                rec_lines.append(f"   Fundamentals say silver goes higher. Accumulate cheaply.")
            elif macro_favors_short:
                rec_lines.append(f"**HOLD** — Mixed signals, macro cautious. Stop at ${hard_stop:.0f}.")
                rec_lines.append(f"   Silver goes up long-term — no rush to add at uncertain levels.")
            else:
                if pnl_pct > 3:
                    rec_lines.append(f"**HOLD** — Up {pnl_pct:.1f}%. Let it run. Stop at breakeven ${round(entry_price, 2)}.")
                elif pnl_pct > 0:
                    rec_lines.append(f"**HOLD** — Small gain, no rush. Stop at ${hard_stop:.0f}. Add on pullback to ${nearest_support:.0f}.")
                else:
                    rec_lines.append(f"**HOLD** — Down {abs(pnl_pct):.1f}%, no structural break. Stop at ${hard_stop:.0f}.")
                    rec_lines.append(f"   Silver goes up long-term. This drawdown is noise.")

        for r in rec_lines:
            lines.append(f"   {r}")

        # ---- UPCOMING RISK EVENTS ----
        if risk_events_list:
            lines.append("")
            lines.append("**📅 UPCOMING RISK EVENTS:**")
            for e in risk_events_list[:5]:
                days_away = (e["date"] - _et_now()).days
                if days_away < 0:
                    continue
                event_pt = e["date"].astimezone(PT).strftime("%a %-m/%-d %-I:%M%p PT")
                when = f"in {days_away}d" if days_away > 0 else "TODAY"
                # Color = event category (industrial = silver-relevant manufacturing data)
                etype = e.get("event_type", "uncertain")
                if etype == "industrial":
                    bias_icon = "🟠"
                else:
                    bias_icon = "🟡"
                sev = "⚡" if e["impact"] == "HIGH" else "·"
                lines.append(f"   {bias_icon}{sev} {e['event']} — {when} ({event_pt})")

        # ---- RULES FOR TODAY ----
        lines.append("")
        lines.append("**🧠 RULES FOR TODAY:**")
        rules = []

        # Risk event rule
        if imminent_risk and hours_to_event and hours_to_event < 48:
            if pnl_pct > 0.5:
                rules.append(f"⚡ **Take profits before {imminent_events_list[0]['event']}.** Close and set re-entry limit below support.")
            else:
                rules.append(f"⚡ **{imminent_events_list[0]['event']} in {hours_to_event:.0f}h.** Tighten stop to tactical level.")

        # FOMO guard
        if pnl_pct > 1.5 and conviction_score >= 1:
            rules.append(f"🚫 **DON'T chase.** You're up {pnl_pct:.1f}%. Your next buy is at ${nearest_support:.0f}, NOT here.")
        elif pnl_pct > 0.5 and conviction_score >= 2:
            rules.append(f"⚠️ Don't add at current levels. Wait for pullback to ${nearest_support:.0f}.")

        # Panic sell guard — always active when in the red
        if pnl_pct < -0.5 and current > hard_stop:
            rules.append(f"🚫 **DON'T panic sell.** You're above your hard stop (${hard_stop:.0f}). This is noise.")
            if not structural_break:
                rules.append(f"   Silver goes up long-term. Selling on a dip in a bull market is how you lose money.")
        elif pnl_pct < -1 and current > hard_stop:
            rules.append(f"🚫 **DON'T panic sell.** Hard stop is ${hard_stop:.0f}. Price hasn't hit it. Sit on your hands.")

        # Macro override warnings — chart says one thing, macro says another
        if macro_favors_short and tech_sub >= 3:
            rules.append(f"⚠️ Chart says buy but macro disagrees ({', '.join(macro_signals[:2])}). Add small, not aggressive.")
        if macro_favors_long and tech_sub <= -3:
            rules.append(f"💡 Chart says sell but macro supports silver ({', '.join(macro_signals[:2])}). Don't panic sell — macro wins long-term.")

        # RSI emotional check
        if rsi > 70:
            rules.append(f"⚠️ RSI overbought ({rsi:.0f}). Things feel great — that's when retail gets burned. Don't add here.")
        elif rsi < 30:
            rules.append(f"⚠️ RSI oversold ({rsi:.0f}). Things feel terrible — that's when smart money buys. Don't sell.")

        # Hard stop
        if contracts:
            hard_dollar = round((current - hard_stop) * CONTRACT_OZ * contracts, 0)
            rules.append(f"Hard stop: **${hard_stop:.0f}** (${hard_dollar:,.0f} risk) — absolute floor, do not go below.")
            if take_profit_level:
                tp_dollar = round((take_profit_level - entry_price) * CONTRACT_OZ * contracts, 0)
                rules.append(f"Take-profit trigger: **${take_profit_level:.0f}** (${tp_dollar:,.0f} locked) — use before risk events or if chart breaks.")

        for r in rules:
            lines.append(f"   {r}")

    lines.append("")
    
    # Key Levels
    if levels.get("supports") or levels.get("resistances"):
        lines.append("**📊 KEY LEVELS:**")
        if levels.get("resistances"):
            r_str = " | ".join([f"${r['level']} ({r['type']})" for r in levels["resistances"][:3]])
            lines.append(f"   Resistance: {r_str}")
        if levels.get("supports"):
            s_str = " | ".join([f"${s['level']} ({s['type']})" for s in levels["supports"][:3]])
            lines.append(f"   Support: {s_str}")
        if tech.get("BB_POSITION") is not None:
            lines.append(f"   BB Position: {tech['BB_POSITION']}% of bands (width: {tech.get('BB_WIDTH', '?')}%)")
    
    lines.append("")
    
    # Technicals
    if tech.get("RSI_14"):
        rsi = tech["RSI_14"]
        rsi_label = "⚠️ OVERBOUGHT" if rsi > 70 else "⚠️ OVERSOLD" if rsi < 30 else "Neutral"
        lines.append(f"**📈 TECHNICALS:** RSI(14): {rsi} {rsi_label}")
    
    if tech.get("MACD_CROSS"):
        lines.append(f"   MACD: {tech['MACD_CROSS']} (hist: {tech.get('MACD_HIST', 0):.2f})")
    
    if tech.get("TREND"):
        lines.append(f"   Trend: {tech['TREND']}")
    
    ma_line = []
    for ma_name in ["SMA_10", "SMA_20", "SMA_50", "SMA_200"]:
        if tech.get(ma_name):
            dist = tech.get(f"{ma_name}_DIST", 0)
            sign = "+" if dist >= 0 else ""
            ma_line.append(f"{ma_name.replace('SMA_', '')}d: ${tech[ma_name]} ({sign}{dist}%)")
    if ma_line:
        lines.append(f"   MAs: {' | '.join(ma_line)}")
    
    lines.append("")
    
    # Macro
    if macro:
        lines.append("**🌍 MACRO DRIVERS:**")
        if macro.get("DOLLAR_SIGNAL"):
            dxy = macro.get("DXY", {})
            lines.append(f"   DXY: ${dxy.get('price', '?')} ({dxy.get('change_pct', 0):+.2f}%) — {macro['DOLLAR_SIGNAL']}")
        if macro.get("REAL_YIELD_10Y") is not None:
            chg_bp = macro.get("REAL_YIELD_1M_CHANGE_BP", 0)
            chg_str = f"{chg_bp:+d}bp 1m" if chg_bp else ""
            lines.append(f"   10Y Real Yield (DFII10): {macro['REAL_YIELD_10Y']}% {chg_str} — {macro.get('REAL_YIELD_LEVEL', '')}")
            if macro.get("REAL_YIELD_TREND"):
                lines.append(f"   Real Rate Trend: {macro['REAL_YIELD_TREND']}")
        elif macro.get("REAL_RATE_SIGNAL"):
            lines.append(f"   Real Rates (TIP/TLT proxy): {macro['REAL_RATE_SIGNAL']}")
        if macro.get("10Y_YIELD"):
            lines.append(f"   10Y: {macro['10Y_YIELD']}% | 30Y: {macro.get('30Y_YIELD', '?')}%")
            if macro.get("CURVE_SIGNAL"):
                lines.append(f"   Curve: {macro.get('YIELD_CURVE', '?')}bp — {macro['CURVE_SIGNAL']}")
        if macro.get("MINER_LEVERAGE"):
            lines.append(f"   Miner Leverage: {macro['MINER_LEVERAGE']}x (SIL/SLV)")
        if macro.get("GSR"):
            lines.append(f"   Gold/Silver Ratio: {macro['GSR']} — {macro.get('GSR_SIGNAL', '')}")
        if macro.get("SILVER_COPPER_RATIO"):
            sc = macro["SILVER_COPPER_RATIO"]
            sc_trend = macro.get("SILVER_COPPER_TREND", "")
            cu = macro.get("COPPER_PRICE")
            cu_str = f", Cu ${cu:.2f}" if cu else ""
            lines.append(f"   Silver/Copper: {sc}x ({sc_trend}{cu_str})")
    
    lines.append("")
    
    # Positioning
    lines.append("**🎯 POSITIONING:**")
    if options.get("put_call_oi_ratio"):
        oi = options["put_call_oi_ratio"]
        signals = {
            "BEARISH_HEDGE": "🟥 Heavy downside hedging",
            "CAUTIOUS": "🟨 Elevated put activity",
            "NEUTRAL": "⬜ Neutral",
            "MILDLY_BULLISH": "🟩 Mildly bullish",
            "BULLISH": "🟩 Call dominance",
        }
        liq_tag = " ⚠️ low-liq" if options.get("low_liquidity") else ""
        sig_clean = (options.get("signal") or "").removesuffix("_LOW_LIQ")
        lines.append(f"   SLV P/C OI: {oi}x ({signals.get(sig_clean, sig_clean)}){liq_tag}")
        lines.append(f"   Near-ATM Vol: {options['total_call_vol']:,}C / {options['total_put_vol']:,}P")
    
    if ig.get("available") and ig.get("long_pct") is not None:
        retail_signal = "⚠️ CROWDED LONG" if ig["long_pct"] > 70 else ("⚠️ CROWDED SHORT" if ig["long_pct"] < 30 else "")
        lines.append(f"   IG Retail: {ig['long_pct']}% long {retail_signal}")
    else:
        lines.append("   IG Retail: unavailable")

    cot = data.get("cot", {})
    if cot.get("available"):
        wow = cot.get("wow_net_change", 0)
        wow_arrow = "▲" if wow > 0 else ("▼" if wow < 0 else "•")
        lines.append(
            f"   COT MM: net long {cot['managed_money_net']:,} "
            f"({wow_arrow}{abs(wow):,} WoW, {cot.get('pct_52w', 0):.0f}th pct) — {cot['signal']}"
        )
    
    lines.append("")
    
    # Seasonal
    if seasonal:
        lines.append(f"**📅 SEASONAL:** {seasonal['tendency']} — {seasonal['context']}")
        lines.append("")
    
    # Fed / Central Bank News (with LLM classification)
    if fed_news:
        fed_sentiment = data.get("fed_sentiment", {})
        method = fed_sentiment.get("method", "")
        method_tag = f" [{method}]" if method else ""
        net = fed_sentiment.get("net_score", 0)
        summary = ""
        if fed_sentiment:
            summary = f" — net {net:+d} ({fed_sentiment.get('dovish', 0)}d/{fed_sentiment.get('hawkish', 0)}h/{fed_sentiment.get('neutral', 0)}n){method_tag}"
        lines.append(f"**🏛️ FED & CENTRAL BANK:**{summary}")
        for i, news in enumerate(fed_news[:5]):
            sent = news.get("sentiment", {})
            label = sent.get("label", "")
            label_emoji = {"dovish": "🟢", "hawkish": "🔴", "neutral": "⬜"}.get(label, "")
            reason = sent.get("reason", "")
            label_tag = f" {label_emoji} {label}" + (f" ({reason})" if reason else "") if label else ""
            lines.append(f"   •{label_tag} {news['title']}")
            if news.get("body"):
                lines.append(f"     {news['body'][:150]}")
        lines.append("")
    
    # Polymarket
    if polymarket:
        lines.append("**🎰 POLYMARKET:**")
        for m in polymarket[:3]:
            lines.append(f"   • {m['question']}: {m.get('yes_pct', '?')}% Yes")
        lines.append("")
    
    # Trading calendar note
    lines.append("_Next update: Post-market close. Trade at your own risk._")
    
    return "\n".join(lines)


def format_levels_only(data):
    """Format just the entry/exit levels."""
    lines = []
    levels = data.get("levels", {})
    silver = data.get("price_data", {}).get("SI=F", {})
    tech = data.get("technicals", {})

    now = _et_now()
    now_pt = now.astimezone(PT).strftime("%-I:%M %p PT")
    lines.append(f"🥈 SILVER LEVELS — {now_pt}")

    if silver.get("price"):
        lines.append(f"Current: ${silver['price']}")
    
    if levels.get("bias"):
        lines.append(f"Bias: {levels['color']} {levels['bias']} (Conviction: {levels.get('conviction_score', 0):+d})")
    
    if levels.get("long_setup"):
        s = levels["long_setup"]
        lines.append(f"\n🟢 LONG: Entry {s['entry_zone']} | Stop {s['stop_loss']} | T1 {s['target_1']} | T2 {s['target_2']} | R:R {s['risk_reward']}")
    
    if levels.get("short_setup"):
        s = levels["short_setup"]
        lines.append(f"\n🔴 SHORT: Entry {s['entry_zone']} | Stop {s['stop_loss']} | T1 {s['target_1']} | T2 {s['target_2']} | R:R {s['risk_reward']}")
    
    if levels.get("range_setup"):
        s = levels["range_setup"]
        lines.append(f"\n🟡 RANGE: Buy {s['buy_zone']} | Sell {s['sell_zone']}")
    
    if levels.get("supports"):
        lines.append(f"\nSupports: {' | '.join(['$' + str(s['level']) for s in levels['supports'][:3]])}")
    if levels.get("resistances"):
        lines.append(f"Resistance: {' | '.join(['$' + str(r['level']) for r in levels['resistances'][:3]])}")
    
    if tech.get("ATR_14"):
        lines.append(f"ATR(14): ${tech['ATR_14']}")

    if format_metals_options_section:
        slv = data.get("price_data", {}).get("SLV", {})
        option_lines = format_metals_options_section(
            data.get("metals_options", {}),
            "SLV",
            spot=slv.get("price"),
            conviction_score=levels.get("conviction_score", 0),
        )
        if option_lines:
            lines.append("")
            lines.extend(option_lines)
    
    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Silver Futures Trader Dashboard")
    parser.add_argument("--json", action="store_true", help="Raw JSON output")
    parser.add_argument("--brief", action="store_true", help="Slack-formatted briefing")
    parser.add_argument("--levels", action="store_true", help="Entry/exit levels only")
    parser.add_argument("--full", action="store_true", help="Full report (default)")
    parser.add_argument("--entry-price", type=float, default=None, help="Your average entry price for position management")
    parser.add_argument("--contracts", type=int, default=None, help="Number of contracts held")
    parser.add_argument("--max-loss", type=float, required=True, help="Explicit private maximum tolerable dollar loss")
    parser.add_argument("--max-contracts", type=int, required=True, help="Explicit private maximum contracts for position sizing")
    parser.add_argument("--account-equity", type=float, default=None,
                        help="Account equity in dollars; enables risk-based contract sizing")
    parser.add_argument("--risk-pct", type=float, required=True,
                        help="Explicit private risk per trade as percent of equity")
    parser.add_argument("--metals-options-cache", default=None,
                        help="Private GLD/SLV options cache generated from Robinhood MCP")
    args = parser.parse_args()

    # Fetch data
    price_data = fetch_price_data()

    # Separate OHLC fetch for silver futures so ATR is computed from H/L/C, not close-only
    try:
        silver_ohlc = yf.Ticker("SI=F").history(period="1y", interval="1d", auto_adjust=True)
        if silver_ohlc is None or len(silver_ohlc) == 0:
            silver_ohlc = None
    except Exception:
        silver_ohlc = None

    silver_series = price_data.get("SI=F", {}).get("series")
    technicals = compute_technicals(silver_series, ohlc=silver_ohlc) if silver_series is not None else {"error": "No silver data"}

    real_yield = fetch_real_yield()
    cot = fetch_cot_data()
    macro = compute_macro(price_data, real_yield=real_yield)

    # Clean series from output (not JSON-serializable). Done AFTER compute_macro so
    # silver/copper trend can use the joined SI/HG series.
    for sym in price_data:
        if "series" in price_data[sym]:
            del price_data[sym]["series"]
    volume = fetch_futures_volume()
    options = fetch_slv_options()
    ig = fetch_ig_sentiment()
    seasonal = seasonal_context()
    fed_news = fetch_fed_news()
    fed_sentiment = classify_fed_news_sentiment(fed_news)
    polymarket = fetch_polymarket_silver()
    risk_events = get_risk_events()
    metals_options = load_metals_options(args.metals_options_cache) if load_metals_options else {}
    imminent, imminent_events, hours_to_event = get_imminent_risk(risk_events)
    recent_passed = get_recent_passed_event(risk_events, hours=24)
    session = get_session()

    # Live price: prefer last 1m bar during active session, fall back to daily close
    daily_close = price_data.get("SI=F", {}).get("price")
    intraday_price = fetch_intraday_last_price() if session.get("trading_active") else None
    silver_price = intraday_price if intraday_price else daily_close
    if intraday_price and price_data.get("SI=F"):
        price_data["SI=F"]["price"] = intraday_price
        price_data["SI=F"]["intraday"] = True
        price_data["SI=F"]["daily_close"] = daily_close

    # Single conviction score, computed once and threaded through
    conviction = compute_conviction(technicals, macro, options, ig, fed_sentiment, cot=cot)

    levels = generate_levels(silver_price, technicals, conviction,
                              macro=macro, options=options, ig=ig) if silver_price else {"error": "No price"}

    # Pre-event support hint for the post-event accumulation tier
    post_event = None
    if recent_passed and levels.get("supports"):
        post_event = {
            "event": recent_passed["event"],
            "hours_ago": recent_passed["hours_ago"],
            "pre_event_support": levels["supports"][0]["level"],
        }

    sizing = compute_position_size(
        args.account_equity, args.risk_pct,
        technicals.get("ATR_14"),
        atr_median=technicals.get("ATR_MEDIAN_90D"),
    )
    # If user didn't override and sizing is available, use suggested as max
    effective_max_contracts = args.max_contracts
    if sizing:
        effective_max_contracts = min(args.max_contracts, sizing["suggested_max_contracts"])

    ladder = generate_ladder(
        silver_price, args.entry_price, args.contracts, effective_max_contracts,
        technicals, levels, imminent, hours_to_event, args.max_loss,
        macro=macro, options=options, ig=ig, fed_sentiment=fed_sentiment,
        conviction=conviction, post_event=post_event,
    ) if (silver_price and args.entry_price and args.contracts) else {"buy_ladder": [], "sell_ladder": [], "core_contracts": 0}

    data = {
        "timestamp": _et_now().isoformat(),
        "session": session,
        "price_data": price_data,
        "technicals": technicals,
        "macro": macro,
        "real_yield": real_yield,
        "cot": cot,
        "volume": volume,
        "options": options,
        "ig_sentiment": ig,
        "seasonal": seasonal,
        "fed_news": fed_news,
        "fed_sentiment": fed_sentiment,
        "polymarket": polymarket,
        "metals_options": metals_options,
        "conviction": conviction,
        "levels": levels,
        "risk_events": risk_events,
        "imminent_risk": imminent,
        "imminent_events": imminent_events,
        "hours_to_event": hours_to_event,
        "recent_passed_event": recent_passed,
        "entry_price": args.entry_price,
        "contracts": args.contracts,
        "max_contracts": effective_max_contracts,
        "max_loss": args.max_loss,
        "sizing": sizing,
        "ladder": ladder,
    }

    if args.json:
        print(json.dumps(data, indent=2, default=str))
    elif args.levels:
        print(format_levels_only(data))
    elif args.brief:
        print(format_brief(data))
    else:
        print(format_brief(data))


if __name__ == "__main__":
    main()
