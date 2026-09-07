#!/usr/bin/env python3
"""Silent intraday equity price watchdog for the configured wiki-market list.

No-agent cron pattern: print only when there is an actionable alert; otherwise stay silent.
This script never places orders. Any action requires independent private authorization.
"""
from __future__ import annotations
from automation_paths import configured_text

import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

WIKI = Path(configured_text("${ANALYST_WIKI_ROOT}"))
SHORTLIST = WIKI / "queries" / "current_asymmetric_shortlist.md"
SHORTLIST_JSON = WIKI / "data" / "automation" / "current_asymmetric_shortlist_latest.json"
STATE_PATH = WIKI / "data" / "automation" / "equity_price_watchdog_state.json"
FEED_PATH = WIKI / "data" / "automation" / "intraday_equity_watchdog.json"
ALERT_ZONES = WIKI / "data" / "automation" / "price_alert_zones.json"
MAX_TICKERS = 80
ALERT_COOLDOWN_HOURS = 20
STATE_RETENTION_DAYS = 14

# Keep this mostly US-listed/common/ETF symbols; skip foreign OTC/local aliases that yfinance may mangle.
SKIP = {"KRKNF", "PNG", "AIXA", "LPKF", "LPKFF", "SIVE", "FIVG"}

BUY_WORDS = re.compile(r"\b(BUY SMALL|BUY TINY|starter zone active|starter|add zone|preferred|first tactical|first support|watch zone|pullback|reset)\b", re.I)
AVOID_WORDS = re.compile(r"\b(DO NOT BUY|NO CHASE|WAIT / NO TRADE|REMOVED|NO ADD)\b", re.I)
TICKER_RE = re.compile(r"\$([A-Z][A-Z0-9.]{1,5})\b")
WIKILINK_TICKER_RE = re.compile(r"\[\[tickers/([A-Z][A-Z0-9.]{0,8}?)(?:\.md)?(?:\|[^\]]+)?\]\]", re.I)
PRICE_RE = re.compile(r"(?<![A-Za-z0-9])\$\s*([0-9]{1,4}(?:\.[0-9]+)?)|\b([0-9]{1,4}(?:\.[0-9]+)?)\s*-\s*\$?\s*([0-9]{1,4}(?:\.[0-9]+)?)")
RANGE_RE = re.compile(r"(?:(?:[$€]\s*)|(?:SEK\s+))?([0-9]{1,4}(?:\.[0-9]+)?)\s*[-–]\s*(?:(?:[$€]\s*)|(?:SEK\s+))?([0-9]{1,4}(?:\.[0-9]+)?)", re.I)
BAD_LEVEL_CONTEXT = re.compile(r"(no add at|no chase at|no normal buy at|no fresh add at|no add after|do not add|spot/reference|close /|pre-market|after \+|eps estimates|eps guide|forward eps|fy20\d{2} eps)", re.I)
RESEARCH_ONLY_MARKERS = (
    "deferred_to_explicit_portfolio_implementation_review",
    "research-only",
    "research only",
    "implementation and sizing not assessed",
    "implementation not assessed",
)


@dataclass
class Candidate:
    symbol: str
    source: str
    context: str
    levels: list[float]


@dataclass
class Alert:
    symbol: str
    action: str
    kind: str
    text: str


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True, indent=2))
    tmp.replace(STATE_PATH)


def save_feed(payload: dict) -> None:
    """Publish the dashboard/wiki-facing consolidated tripwire feed.

    This is the structured state that the CIO dashboard consumes. Slack remains
    silent unless a review-ready action is emitted below.
    """
    FEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = FEED_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True, indent=2))
    tmp.replace(FEED_PATH)


def is_research_only(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in RESEARCH_ONLY_MARKERS)


def public_context(text: str) -> str:
    """Remove explicit sizing percentages from dashboard-facing context."""
    text = re.sub(r"\b\d+(?:\.\d+)?%\s*(?:[-–]\s*\d+(?:\.\d+)?%)?", "[sizing withheld]", text)
    return re.sub(r"\s+", " ", text).strip()


def candidate_row(c: Candidate) -> dict:
    return {
        "symbol": c.symbol,
        "source_lists": sorted(set(c.source.split("+"))),
        "bucket": context_bucket(c.context),
        "levels": c.levels,
        "context": public_context(c.context),
    }


def hit_row(c: Candidate, kind: str, level: float | None, alert: Alert, quote: dict) -> dict:
    tech = technical_view({**quote, "price": quote.get("price")})
    pct = quote.get("pct")
    return {
        "symbol": c.symbol,
        "action": alert.action,
        "trigger": kind,
        "alert_kind": alert.kind,
        "price": round(float(quote.get("price")), 4) if quote.get("price") is not None else None,
        "pct_today": round(float(pct), 3) if pct is not None else None,
        "wiki_level": round(float(level), 4) if level is not None else None,
        "technical_quality": tech.get("quality"),
        "technical_note": tech.get("note"),
        "review_ok": alert.action == "REVIEW_CANDIDATE",
        "source_lists": sorted(set(c.source.split("+"))),
        "bucket": context_bucket(c.context),
        "context": public_context(c.context),
        "text": alert.text,
    }


def extract_levels(text: str) -> list[float]:
    vals: list[float] = []
    clean = text.replace("about $", "$")
    clean = re.sub(r"\b(?:no add at|no chase at|no normal buy at|no fresh add at|no add after|do not add)\b.*?(?=\b(?:first|better|preferred|normal|optional|add|starter|pullback|watch|reset)\b|$)", "", clean, flags=re.I)
    for m in PRICE_RE.finditer(clean):
        prefix = clean[:m.start()]
        segment_start = max(prefix.rfind("."), prefix.rfind(";"), prefix.rfind("|"))
        nearby = clean[max(segment_start + 1, m.start() - 90):m.start()].lower()
        if BAD_LEVEL_CONTEXT.search(nearby):
            continue
        for group in m.groups():
            if not group:
                continue
            suffix = clean[m.end():m.end() + 1].upper()
            if suffix in {"M", "B", "%"}:
                continue
            try:
                val = float(group)
            except ValueError:
                continue
            # Fiscal/calendar years are common in War Room prose and are never
            # actionable price levels. Reject them before publishing the feed.
            if 1 <= val <= 5000 and not 1900 <= val <= 2100:
                vals.append(val)
    # Keep likely actionable levels, not every stale spot/target: de-dupe and sort.
    return sorted(set(round(v, 2) for v in vals))[:12]


def extract_ranges(text: str) -> list[tuple[float, float]]:
    """Return explicit price bands from context, preserving range semantics.

    The older level extractor flattens `$190-$200` into two standalone numbers,
    which can miss the middle of a buy zone. This range extractor requires a
    nearby currency marker so dates like `2026-08-05` do not become fake zones.
    """
    out: list[tuple[float, float]] = []
    for m in RANGE_RE.finditer(text):
        snippet = text[max(0, m.start() - 8):m.end() + 8]
        if not any(tok in snippet for tok in ("$", "€", "SEK")):
            continue
        prefix = text[:m.start()]
        segment_start = max(prefix.rfind("."), prefix.rfind(";"), prefix.rfind("|"))
        nearby = text[max(segment_start + 1, m.start() - 90):m.start()].lower()
        if BAD_LEVEL_CONTEXT.search(nearby):
            continue
        try:
            a = float(m.group(1))
            b = float(m.group(2))
        except ValueError:
            continue
        lo, hi = sorted((a, b))
        if 1 <= lo <= hi <= 5000 and not (1900 <= lo <= 2100 or 1900 <= hi <= 2100):
            out.append((round(lo, 2), round(hi, 2)))
    return sorted(set(out))[:12]


def matched_alert_level(c: Candidate, price: float) -> float | None:
    """Return the actionable zone ceiling/level when price is in a wiki zone."""
    ranges = extract_ranges(c.context)
    for lo, hi in ranges:
        if lo <= price <= hi:
            return hi
    if ranges:
        return None
    for lvl in c.levels:
        if lvl <= price <= lvl * 1.02:
            return lvl
    return None


def manual_candidates(symbols: set[str] | None = None) -> list[Candidate]:
    """Load the single newest structured ideal-entry band per symbol."""
    if not ALERT_ZONES.exists():
        return []
    try:
        data = json.loads(ALERT_ZONES.read_text())
    except Exception:
        return []
    out: list[Candidate] = []
    for sym, zones in (data.get("symbols") or {}).items():
        if sym in SKIP or (symbols is not None and sym not in symbols) or not isinstance(zones, list):
            continue
        candidates: list[tuple[datetime, int, dict]] = []
        for index, zone in enumerate(zones):
            try:
                lo = float(zone["low"])
                hi = float(zone["high"])
            except Exception:
                continue
            raw_updated = str(zone.get("updated_at_utc") or zone.get("updatedAt") or "")
            try:
                updated = datetime.fromisoformat(raw_updated.replace("Z", "+00:00"))
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=timezone.utc)
                updated = updated.astimezone(timezone.utc)
            except Exception:
                updated = datetime.min.replace(tzinfo=timezone.utc)
            candidates.append((updated, index, {**zone, "low": min(lo, hi), "high": max(lo, hi)}))
        if not candidates:
            continue
        zone = max(candidates, key=lambda item: (item[0], item[1]))[2]
        lo = float(zone["low"])
        hi = float(zone["high"])
        reason = str(zone.get("reason") or "canonical ideal-entry review")
        size = str(zone.get("size_frame") or "")
        research_only = (
            is_research_only(size)
            or str(zone.get("instrumentRisk") or "") == "implementation_not_evaluated"
        )
        prefix = "RESEARCH / REVIEW" if research_only else "BUY SMALL / REVIEW"
        # Never publish explicit sizing from the private decision configuration.
        context = f"{prefix} zone ${lo:g}-${hi:g}: {reason}"
        out.append(Candidate(symbol=sym, source=ALERT_ZONES.name, context=context[:500], levels=[lo, hi]))
    return out


def candidates_from_file(path: Path) -> list[Candidate]:
    if not path.exists():
        return []
    out: list[Candidate] = []
    for raw in path.read_text(errors="ignore").splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        syms = [s.upper() for s in [*TICKER_RE.findall(line), *WIKILINK_TICKER_RE.findall(line)] if s.upper() not in SKIP]
        if not syms:
            continue
        # Keep names that are buy/watch candidates or core holdings, but avoid pure do-not-buy lines.
        if AVOID_WORDS.search(line) and not BUY_WORDS.search(line):
            continue
        levels = extract_levels(line)
        for sym in syms:
            out.append(Candidate(symbol=sym, source=path.name, context=re.sub(r"\s+", " ", line)[:360], levels=levels))
    return out


def symbols_from_file(path: Path) -> set[str]:
    """Read only the canonical Buy/Wait/Add universe.

    Research-memory and Kill rows remain stored for learning/risk control but
    must never become fresh-entry alerts merely because price crosses a zone.
    """
    if not path.exists():
        return set()
    active_sections = {"Buy / Scout Now", "Wait for Trigger", "Add After Proof"}
    current_section = ""
    symbols: set[str] = set()
    for line in path.read_text(errors="ignore").splitlines():
        if line.startswith("## "):
            current_section = line[3:].strip()
            continue
        if current_section not in active_sections or not line.lstrip().startswith("|"):
            continue
        for symbol in [*TICKER_RE.findall(line), *WIKILINK_TICKER_RE.findall(line)]:
            symbol = symbol.upper()
            if symbol not in SKIP:
                symbols.add(symbol)
    return symbols


def dedupe(cands: Iterable[Candidate]) -> list[Candidate]:
    by_symbol: dict[str, Candidate] = {}
    for c in cands:
        if c.symbol not in by_symbol:
            by_symbol[c.symbol] = c
        else:
            old = by_symbol[c.symbol]
            merged = sorted(set(old.levels + c.levels))[:16]
            by_symbol[c.symbol] = Candidate(c.symbol, old.source + "+" + c.source, old.context, merged)
    return list(by_symbol.values())[:MAX_TICKERS]


def quote_rows(quotes: dict[str, dict], retrieved_at: str) -> list[dict]:
    """Project one quote with its actual market-data timestamp."""
    rows: list[dict] = []
    for symbol in sorted(quotes):
        quote = quotes[symbol]
        price = quote.get("price")
        as_of = str(quote.get("as_of") or "")
        if price is None or not as_of:
            continue
        pct = quote.get("pct")
        rows.append(
            {
                "symbol": symbol,
                "price": round(float(price), 4),
                "pct_today": round(float(pct), 3) if pct is not None else None,
                "as_of": as_of,
                "retrieved_at": retrieved_at,
            }
        )
    return rows


def fetch_quotes(symbols: list[str]) -> dict[str, dict]:
    """Fetch prices with exchange bar timestamps; retrieval time is not freshness."""
    import yfinance as yf

    result: dict[str, dict] = {}
    for sym in symbols:
        try:
            ticker = yf.Ticker(sym)
            fi = getattr(ticker, "fast_info", {}) or {}
            prev = fi.get("previous_close") or fi.get("previousClose")
            day_high = fi.get("day_high") or fi.get("dayHigh")
            day_low = fi.get("day_low") or fi.get("dayLow")
            price_f: float | None = None
            as_of = ""
            # Prefer a timestamped market bar. If unavailable, a cached fast_info
            # price may be displayed internally but is omitted from the capital feed.
            hist = ticker.history(period="5d", interval="1m", auto_adjust=False, prepost=True)
            if not hist.empty and "Close" in hist:
                closes = hist["Close"].dropna()
                if not closes.empty:
                    price_f = float(closes.iloc[-1])
                    stamp = closes.index[-1]
                    stamp_dt = stamp.to_pydatetime() if hasattr(stamp, "to_pydatetime") else stamp
                    if isinstance(stamp_dt, datetime):
                        if stamp_dt.tzinfo is None:
                            stamp_dt = stamp_dt.replace(tzinfo=timezone.utc)
                        as_of = stamp_dt.astimezone(timezone.utc).isoformat()
            if price_f is None:
                raw_price = fi.get("last_price") or fi.get("lastPrice") or fi.get("regular_market_price")
                if raw_price is not None and not math.isnan(float(raw_price)):
                    price_f = float(raw_price)
            prev_f = float(prev) if prev is not None and not math.isnan(float(prev)) else None
            if price_f:
                result[sym] = {
                    "price": price_f,
                    "as_of": as_of,
                    "prev_close": prev_f,
                    "day_high": float(day_high) if day_high is not None else None,
                    "day_low": float(day_low) if day_low is not None else None,
                    "pct": ((price_f / prev_f - 1) * 100) if prev_f and prev_f > 0 else None,
                }
        except Exception as exc:
            result[sym] = {"error": type(exc).__name__ + ": " + str(exc)[:120]}
    return result


def enrich_technicals(quotes: dict[str, dict], symbols: list[str]) -> None:
    """Add lightweight technical confirmation only for symbols already near an alert.

    This keeps the cron low-noise and avoids hammering quote APIs for every watchlist name.
    """
    if not symbols:
        return
    import yfinance as yf

    spy_ret20: float | None = None
    try:
        spy = yf.Ticker("SPY").history(period="3mo", interval="1d", auto_adjust=True)
        if len(spy) >= 21:
            spy_ret20 = float(spy["Close"].iloc[-1] / spy["Close"].iloc[-21] - 1) * 100
    except Exception:
        spy_ret20 = None

    for sym in symbols:
        q = quotes.setdefault(sym, {})
        try:
            hist = yf.Ticker(sym).history(period="3mo", interval="1d", auto_adjust=True)
            if hist.empty or "Close" not in hist:
                continue
            close = hist["Close"].dropna()
            if len(close) < 20:
                continue
            q["sma20"] = float(close.tail(20).mean())
            if len(close) >= 50:
                q["sma50"] = float(close.tail(50).mean())
            delta = close.diff().dropna()
            if len(delta) >= 14:
                gain = delta.clip(lower=0).tail(14).mean()
                loss = -delta.clip(upper=0).tail(14).mean()
                if loss == 0:
                    q["rsi14"] = 100.0
                else:
                    rs = gain / loss
                    q["rsi14"] = float(100 - (100 / (1 + rs)))
            if len(close) >= 21:
                ret20 = float(close.iloc[-1] / close.iloc[-21] - 1) * 100
                q["ret20"] = ret20
                if spy_ret20 is not None:
                    q["rel20_vs_spy"] = ret20 - spy_ret20
        except Exception as exc:
            q["technical_error"] = type(exc).__name__ + ": " + str(exc)[:120]


def context_bucket(text: str) -> str:
    lower = text.lower()
    if "trim risk" in lower or "hold token" in lower or "no blind" in lower:
        return "watch_for_proof"
    if "buy small" in lower or "starter zone active" in lower or "buy tiny" in lower:
        return "starter_candidate"
    if "optional" in lower or "tiny" in lower or "tracker" in lower or "scout" in lower:
        return "tiny_only"
    if "no chase" in lower or "no add" in lower or "wait" in lower:
        return "watch_for_proof"
    return "watchlist"


def technical_view(q: dict) -> dict[str, object]:
    price = q.get("price")
    sma20 = q.get("sma20")
    sma50 = q.get("sma50")
    rsi = q.get("rsi14")
    rel = q.get("rel20_vs_spy")
    if not price or not sma20:
        return {"quality": "unknown", "review_ok": False, "note": "technical data unavailable"}
    above20 = price >= sma20
    above50 = price >= sma50 if sma50 else True
    not_extended = rsi is None or rsi <= 72
    not_broken = rsi is None or rsi >= 32
    rel_ok = rel is None or rel >= -3
    constructive = (above20 or (sma50 and price >= 0.97 * sma50)) and not_extended and not_broken and rel_ok
    if constructive:
        qtxt = "confirming"
        review_ok = True
    else:
        qtxt = "weak_or_extended"
        review_ok = False
    pieces = []
    if sma20:
        pieces.append(f"20DMA ${sma20:.2f}")
    if sma50:
        pieces.append(f"50DMA ${sma50:.2f}")
    if rsi is not None:
        pieces.append(f"RSI {rsi:.0f}")
    if rel is not None:
        pieces.append(f"20D rel SPY {rel:+.1f}pts")
    return {"quality": qtxt, "review_ok": review_ok, "note": ", ".join(pieces)}


def build_level_alert(
    c: Candidate,
    price: float,
    level: float,
    quote: dict,
    *,
    pre_entry_eligible: bool = False,
) -> Alert | None:
    tech = technical_view({**quote, "price": price})
    bucket = context_bucket(c.context)
    explicit_zone = ALERT_ZONES.name in c.source
    research_only = "RESEARCH / REVIEW zone" in c.context or is_research_only(c.context)
    review_ok = (
        pre_entry_eligible
        and explicit_zone
        and not research_only
        and bucket in {"starter_candidate", "tiny_only", "watchlist"}
    )
    action = "REVIEW_CANDIDATE" if review_ok else "WATCH_ONLY"
    if research_only:
        label = "research watch only; implementation deferred"
    elif not pre_entry_eligible:
        label = "watch only; canonical research/proof/freshness gates are blocked"
    else:
        label = "canonical gates pass; ready for PM review"
    pct = quote.get("pct")
    pct_txt = f" ({pct:+.1f}% today)" if pct is not None else ""
    text = (
        f"${c.symbol}: {action} — ${price:.2f}{pct_txt} is inside the canonical ideal-entry band ending at ${level:.2f}; "
        f"{label}. Tech: {tech['quality']} ({tech['note']}). Context: {public_context(c.context[:220])}"
    )
    return Alert(c.symbol, action, f"near_level_{level}", text)


def build_large_move_alert(c: Candidate, price: float, quote: dict) -> Alert:
    pct = quote.get("pct")
    tech = technical_view({**quote, "price": price})
    direction = "up" if pct and pct > 0 else "down"
    action = "WATCH_ONLY"
    text = (
        f"${c.symbol}: WATCH_ONLY — {pct:+.1f}% today at ${price:.2f}; large {direction} move in monitored wiki name. "
        f"Tech: {tech['quality']} ({tech['note']}). Context: {public_context(c.context[:180])}"
    )
    return Alert(c.symbol, action, f"large_move_{direction}", text)


def alert_key(sym: str, kind: str) -> str:
    return f"{datetime.now(timezone.utc).date().isoformat()}|{sym}|{kind}"


def should_emit(state: dict, key: str, now_ts: float) -> bool:
    sent = state.setdefault("sent", {})
    prior = sent.get(key)
    if prior and now_ts - float(prior) < ALERT_COOLDOWN_HOURS * 3600:
        return False
    sent[key] = now_ts
    return True


def prune_state(state: dict, now_ts: float) -> None:
    """Bound the alert ledger so date-keyed entries do not grow forever."""
    cutoff = now_ts - STATE_RETENTION_DAYS * 86400
    sent = state.get("sent")
    if not isinstance(sent, dict):
        state["sent"] = {}
        return
    state["sent"] = {
        key: value
        for key, value in sent.items()
        if isinstance(value, (int, float)) and float(value) >= cutoff
    }


def load_pre_entry_eligibility() -> dict[str, bool]:
    """Read canonical non-price gates from the latest shortlist snapshot."""
    try:
        data = json.loads(SHORTLIST_JSON.read_text())
    except Exception:
        return {}
    rows = data.get("all") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return {}
    return {
        str(row.get("symbol") or "").upper(): row.get("preEntryEligible") is True
        for row in rows
        if isinstance(row, dict) and row.get("symbol")
    }


def quote_is_fresh(quote: dict, now: datetime, max_age_days: float = 1.0) -> bool:
    raw = str(quote.get("as_of") or "")
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        stamp = stamp.astimezone(timezone.utc)
    except Exception:
        return False
    age = (now - stamp).total_seconds() / 86400
    return -5 / 1440 <= age <= max_age_days


def main() -> int:
    shortlist_symbols = symbols_from_file(SHORTLIST)
    shortlist_candidates = [candidate for candidate in candidates_from_file(SHORTLIST) if candidate.symbol in shortlist_symbols]
    cands = dedupe(manual_candidates(shortlist_symbols) + shortlist_candidates)
    if not cands:
        save_feed({
            "last_check_utc": datetime.now(timezone.utc).isoformat(),
            "monitored_count": 0,
            "slack_policy": "silent_unless_review_candidate",
            "summary": "No monitored tickers found in the canonical asymmetric shortlist.",
            "monitored": [],
            "top_hits": [],
            "review_candidates": [],
        })
        return 0
    quotes = fetch_quotes([c.symbol for c in cands])
    pre_entry_eligibility = load_pre_entry_eligibility()
    state = load_state()
    now = datetime.now(timezone.utc)
    now_ts = now.timestamp()
    prune_state(state, now_ts)
    emitted_alerts: list[Alert] = []
    feed_hits: list[dict] = []

    raw_hits: list[tuple[Candidate, str, float | None]] = []
    for c in cands:
        q = quotes.get(c.symbol) or {}
        price = q.get("price")
        if not price:
            continue
        pct = q.get("pct")
        if pct is not None and (pct <= -7 or pct >= 10):
            raw_hits.append((c, "large_move", None))
            continue
        level = matched_alert_level(c, float(price))
        if level is not None and BUY_WORDS.search(c.context):
            raw_hits.append((c, "near_level", level))

    enrich_technicals(quotes, sorted({c.symbol for c, _, _ in raw_hits}))

    for c, kind, level in raw_hits:
        q = quotes.get(c.symbol) or {}
        price = q.get("price")
        if not price:
            continue
        if kind == "large_move":
            alert = build_large_move_alert(c, price, q)
        else:
            assert level is not None
            alert = build_level_alert(
                c,
                price,
                level,
                q,
                pre_entry_eligible=bool(pre_entry_eligibility.get(c.symbol)) and quote_is_fresh(q, now),
            )
            if alert is None:
                continue
        feed_hits.append(hit_row(c, kind, level, alert, q))
        # Slack is reserved for actions the operator can take now. Watch-only/context hits
        # remain visible in the dashboard feed but do not interrupt.
        if alert.action == "REVIEW_CANDIDATE":
            key = alert_key(c.symbol, alert.kind)
            if should_emit(state, key, now_ts):
                emitted_alerts.append(alert)

    review_hits = [h for h in feed_hits if h.get("action") == "REVIEW_CANDIDATE"]
    ordered_hits = sorted(
        feed_hits,
        key=lambda h: (
            0 if h.get("action") == "REVIEW_CANDIDATE" else 1,
            0 if h.get("trigger") == "near_level" else 1,
            abs(float(h.get("pct_today") or 0)),
        ),
    )
    summary = (
        f"{len(review_hits)} review candidates; {len(feed_hits) - len(review_hits)} dashboard-only tripwires; "
        f"{len(cands)} canonical asymmetric-shortlist names monitored."
    )
    save_feed({
        "last_check_utc": now.isoformat(),
        "monitored_count": len(cands),
        "raw_hit_count": len(raw_hits),
        "dashboard_hit_count": len(feed_hits),
        "review_candidate_count": len(review_hits),
        "slack_policy": "silent_unless_review_candidate",
        "summary": summary,
        "sources": [str(SHORTLIST.relative_to(WIKI)), str(ALERT_ZONES.relative_to(WIKI))],
        "monitored": [candidate_row(c) for c in cands],
        "quotes": quote_rows(quotes, now.isoformat()),
        "top_hits": ordered_hits[:20],
        "review_candidates": review_hits[:10],
    })

    state["last_check_utc"] = now.isoformat()
    state["monitored_count"] = len(cands)
    state["last_raw_hits"] = len(raw_hits)
    state["last_dashboard_hits"] = len(feed_hits)
    state["last_alerts"] = len(emitted_alerts)
    save_state(state)

    if emitted_alerts:
        print("🚨 Equity price + technical watchdog — review-ready action")
        print(f"Checked {len(cands)} canonical asymmetric-shortlist equities/ETFs at {now.strftime('%Y-%m-%d %H:%M UTC')}.")
        print(f"Robinhood-ready review candidates: {len(emitted_alerts)}. Dashboard-only watch hits stayed silent.")
        print("No order was placed. Review and authorize any action independently.")
        print("")
        for item in emitted_alerts[:8]:
            print("- " + item.text)
        if len(emitted_alerts) > 8:
            print(f"- ...{len(emitted_alerts)-8} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
