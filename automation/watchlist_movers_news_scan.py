#!/usr/bin/env python3
"""Low-tax watchlist mover + news-trigger wiki updater.

No-agent cron pattern for a configured installation:
- scan canonical wiki watchlists / AI portfolio earnings universe;
- rank top daily % up/down movers;
- fetch headlines only for those movers;
- write a compact durable wiki note + raw JSON;
- stay mostly silent unless called manually with --print-summary.

This script never places orders and never modifies brokerage state.
"""
from __future__ import annotations
from automation_paths import configured_text

import argparse
import contextlib
import html
import io
import json
import logging
import math
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

WIKI = Path(configured_text("${ANALYST_WIKI_ROOT}"))
SOURCES = [
    WIKI / "queries" / "ai_portfolio_earnings_universe.md",
    WIKI / "conviction-shortlist.md",
    WIKI / "queries" / "pullback_buy_list.md",
    WIKI / "queries" / "daily_monitor_queue.md",
    WIKI / "research-queue.md",
]
RAW_DIR = WIKI / "raw" / "signals"
DAILY_DIR = WIKI / "daily" / "prices"
STATE_PATH = WIKI / "data" / "automation" / "watchlist_movers_news_scan_state.json"
LATEST_JSON = WIKI / "data" / "automation" / "watchlist_movers_latest.json"
LOG_PATH = WIKI / "log.md"

# Private exclusions are explicit; only parser vocabulary is public by default.
from private_config import load_private_json
_private_watchlist = load_private_json("ANALYST_WATCHLIST_CONFIG", optional=True)
_exclusions = _private_watchlist.get("exclude_symbols", [])
if not isinstance(_exclusions, list) or any(not isinstance(s, str) for s in _exclusions):
    raise ValueError("ANALYST_WATCHLIST_CONFIG exclude_symbols must be a list of symbols")
EXCLUDE = set(_exclusions) | {
    "ETF", "TYPE", "REC", "BUY", "HOLD", "WAIT", "CORE", "WATCH", "STATUS", "ACTION",
}
TICKER_RE = re.compile(r"\$([A-Z][A-Z0-9.]{1,5})\b")

MATERIAL_KEYWORDS = re.compile(
    r"\b(earnings|results|quarter|q[1-4]|beat|miss|guidance|guide|forecast|outlook|"
    r"revenue|eps|margin|backlog|order|orders|contract|customer|hyperscaler|deployment|"
    r"partnership|acquisition|merger|deal|sec|8-k|10-q|10-k|shelf|atm|offering|convert|"
    r"insider|form 4|downgrade|upgrade|price target|estimate|cuts|raises|raise|lowered|"
    r"layoff|investigation|short report|lawsuit|approval|permit|export|tariff|policy)\b",
    re.I,
)
NOISE_PUBLISHERS = {"zacks", "benzinga insights", "insider monkey"}
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 HermesWatchlistMover/1.0"


@dataclass
class QuoteRow:
    symbol: str
    price: float | None
    prev_close: float | None
    pct_change: float | None
    source_lists: list[str]
    quote_error: str | None = None


@dataclass
class HeadlineRow:
    title: str
    publisher: str | None
    url: str | None
    published_utc: str | None
    material: bool


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(WIKI))
    except Exception:
        return str(path)


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def extract_symbols() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for path in SOURCES:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        symbols = set(TICKER_RE.findall(text))
        # Canonical query tables often keep the ticker in column 1 without a leading cashtag.
        # Only trust the first pipe-cell, never arbitrary uppercase status words elsewhere.
        for raw in text.splitlines():
            line = raw.strip()
            if not line.startswith("|") or line.startswith("|---"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not cells:
                continue
            first = re.sub(r"\[\[[^]|]+\|", "", cells[0]).replace("]]", "").strip().lstrip("$")
            first = first.split()[0] if first.split() else ""
            if re.fullmatch(r"[A-Z][A-Z0-9.]{1,5}", first) and first.upper() not in EXCLUDE and first.upper() != "TICKER":
                symbols.add(first.upper())
        for sym in symbols:
            sym = sym.upper().replace(".", "-")  # yfinance BRK.B style normalization if ever present
            if sym in EXCLUDE:
                continue
            if not re.fullmatch(r"[A-Z][A-Z0-9-]{1,5}", sym):
                continue
            out.setdefault(sym, set()).add(rel(path))
    return out


def fetch_quotes(symbol_sources: dict[str, set[str]], max_symbols: int) -> list[QuoteRow]:
    import yfinance as yf
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)

    symbols = sorted(symbol_sources)[:max_symbols]
    rows: list[QuoteRow] = []
    for sym in symbols:
        price = prev = pct = None
        try:
            # yfinance can print noisy 404/delisted diagnostics directly; suppress them
            # so a no-agent cron does not deliver stdout just because one stale research
            # ticker has no quote.
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                ticker = yf.Ticker(sym)
                fi = getattr(ticker, "fast_info", {}) or {}
                price = fi.get("last_price") or fi.get("lastPrice") or fi.get("regular_market_price")
                prev = fi.get("previous_close") or fi.get("previousClose")
                if price is None or prev is None:
                    hist = ticker.history(period="5d", interval="1d", auto_adjust=False)
                    if hist is not None and not hist.empty:
                        closes = [float(x) for x in hist["Close"].dropna().tolist() if not math.isnan(float(x))]
                        if closes:
                            price = price or closes[-1]
                        if len(closes) >= 2:
                            prev = prev or closes[-2]
            price_f = float(price) if price is not None and not math.isnan(float(price)) else None
            prev_f = float(prev) if prev is not None and not math.isnan(float(prev)) else None
            if price_f is not None and prev_f and prev_f > 0:
                pct = (price_f / prev_f - 1.0) * 100.0
            rows.append(QuoteRow(sym, price_f, prev_f, pct, sorted(symbol_sources[sym])))
        except Exception as exc:
            err = f"{type(exc).__name__}: {str(exc)[:160]}"
            rows.append(QuoteRow(sym, None, None, None, sorted(symbol_sources[sym]), err))
        # yfinance fast_info can rate-limit; this stays cheap enough for ~100 names.
        time.sleep(0.03)
    return rows


def top_movers(rows: Iterable[QuoteRow], top_each_side: int, min_abs_pct: float, max_movers: int) -> list[QuoteRow]:
    valid = [r for r in rows if r.pct_change is not None and r.price is not None]
    ups = sorted([r for r in valid if r.pct_change and r.pct_change > 0], key=lambda r: r.pct_change or 0, reverse=True)[:top_each_side]
    downs = sorted([r for r in valid if r.pct_change and r.pct_change < 0], key=lambda r: r.pct_change or 0)[:top_each_side]
    # Add unusually large moves if they somehow fell outside the top up/down lists,
    # then cap the final wiki surface to avoid daily bloat.
    large = sorted([r for r in valid if abs(r.pct_change or 0) >= min_abs_pct], key=lambda r: abs(r.pct_change or 0), reverse=True)
    by_symbol: dict[str, QuoteRow] = {}
    for row in ups + downs + large:
        by_symbol[row.symbol] = row
    return sorted(by_symbol.values(), key=lambda r: abs(r.pct_change or 0), reverse=True)[:max_movers]


def parse_yf_news_item(item: dict) -> HeadlineRow | None:
    title = html.unescape(str(item.get("title") or "")).strip()
    if not title:
        return None
    publisher = item.get("publisher") or item.get("provider")
    if publisher and str(publisher).lower() in NOISE_PUBLISHERS:
        return None
    url = item.get("link") or item.get("url")
    ts = item.get("providerPublishTime") or item.get("publishTime")
    published = None
    try:
        if ts:
            published = datetime.fromtimestamp(float(ts), timezone.utc).isoformat()
    except Exception:
        published = None
    return HeadlineRow(title=title, publisher=str(publisher) if publisher else None, url=str(url) if url else None, published_utc=published, material=bool(MATERIAL_KEYWORDS.search(title)))


def fetch_yf_news(sym: str, limit: int = 4) -> list[HeadlineRow]:
    try:
        import yfinance as yf
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            news = getattr(yf.Ticker(sym), "news", None) or []
        rows: list[HeadlineRow] = []
        for item in news[: limit * 2]:
            parsed = parse_yf_news_item(item)
            if parsed:
                rows.append(parsed)
            if len(rows) >= limit:
                break
        return rows
    except Exception:
        return []


def fetch_google_news(sym: str, limit: int = 4) -> list[HeadlineRow]:
    # Query only the ticker + stock to avoid a broad market crawl.
    q = urllib.parse.quote(f'"{sym}" stock earnings OR shares when:2d')
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read(500_000)
        root = ET.fromstring(data)
    except Exception:
        return []
    rows: list[HeadlineRow] = []
    for item in root.findall(".//item"):
        title = html.unescape((item.findtext("title") or "").strip())
        if not title:
            continue
        link = item.findtext("link") or None
        pub_date = item.findtext("pubDate") or None
        source_el = item.find("source")
        publisher = source_el.text if source_el is not None else None
        if publisher and publisher.lower() in NOISE_PUBLISHERS:
            continue
        rows.append(HeadlineRow(title=title, publisher=publisher, url=link, published_utc=pub_date, material=bool(MATERIAL_KEYWORDS.search(title))))
        if len(rows) >= limit:
            break
    return rows


def fetch_headlines(symbols: Iterable[str], per_symbol: int) -> dict[str, list[HeadlineRow]]:
    out: dict[str, list[HeadlineRow]] = {}
    for sym in symbols:
        rows = fetch_yf_news(sym, per_symbol)
        if not rows:
            rows = fetch_google_news(sym, per_symbol)
        # De-dupe similar titles.
        seen: set[str] = set()
        unique: list[HeadlineRow] = []
        for r in rows:
            key = re.sub(r"\W+", " ", r.title.lower()).strip()[:110]
            if key in seen:
                continue
            seen.add(key)
            unique.append(r)
        out[sym] = unique[:per_symbol]
        time.sleep(0.05)
    return out


def ticker_link(sym: str) -> str:
    path = WIKI / "tickers" / f"{sym}.md"
    if path.exists():
        return f"[[tickers/{sym}.md|${sym}]]"
    return f"${sym}"


def classify(row: QuoteRow, headlines: list[HeadlineRow]) -> str:
    pct = row.pct_change or 0
    material = [h for h in headlines if h.material]
    if material:
        return "news/proof trigger found"
    if abs(pct) >= 10:
        return "large move; no obvious fresh headline"
    if abs(pct) >= 5:
        return "notable move; likely tape/peer/sentiment unless later source appears"
    return "context only"


def render_markdown(now: datetime, raw_rel: str, movers: list[QuoteRow], headlines: dict[str, list[HeadlineRow]], quote_count: int, errors: int) -> str:
    stamp = now.strftime("%Y-%m-%d %H:%M UTC")
    date = now.date().isoformat()
    title = f"Watchlist Movers and News Trigger Scan — {date}"
    lines = [
        "---",
        f"title: {title}",
        f"created: {date}",
        f"updated: {date}",
        "type: daily",
        "tags: [daily, catalyst]",
        "confidence: medium",
        f"sources: [queries/ai_portfolio_earnings_universe.md, conviction-shortlist.md, queries/pullback_buy_list.md, queries/daily_monitor_queue.md, {raw_rel}]",
        "---",
        "",
        f"# {title}",
        "",
        f"Generated: **{stamp}**. Low-tax scan of [[queries/ai_portfolio_earnings_universe|AI Portfolio Earnings Universe]], [[conviction-shortlist|Conviction Shortlist]], [[queries/pullback_buy_list|Pullback Buy List]], and [[queries/daily_monitor_queue|Daily Monitor Queue]].",
        "",
        "## PM read",
        "",
    ]
    material = [r for r in movers if any(h.material for h in headlines.get(r.symbol, []))]
    unexplained = [r for r in movers if abs(r.pct_change or 0) >= 7 and not any(h.material for h in headlines.get(r.symbol, []))]
    lines.append(f"- Checked **{quote_count}** wiki/watchlist symbols; quote errors: **{errors}**.")
    lines.append(f"- Top mover set: **{len(movers)}** symbols. Material headline/proof candidates: **{len(material)}**. Large unexplained movers: **{len(unexplained)}**.")
    lines.append("- This page is the daily tripwire log. Ticker-page patches and War Rooms should be reserved for earnings/proof/action changes, not every price squiggle.")
    lines.append("")
    lines.append("## Top watchlist movers")
    lines.append("")
    lines.append("| Ticker | Move | Price | News trigger? | Headlines checked | Source lists |")
    lines.append("|---|---:|---:|---|---|---|")
    for r in movers:
        hs = headlines.get(r.symbol, [])
        htxt = "<br>".join([f"{('* ' if h.material else '')}{h.title}" for h in hs[:3]]) or "No fresh headline found in capped scan"
        lists = ", ".join(sorted({s.replace("queries/", "q/") for s in r.source_lists})[:3])
        lines.append(
            f"| {ticker_link(r.symbol)} | {r.pct_change:+.2f}% | ${r.price:.2f} | {classify(r, hs)} | {htxt} | {lists} |"
        )
    lines.append("")
    lines.append("## Escalation rules")
    lines.append("")
    lines.append("- **Ticker page patch:** only if a headline changes revenue/backlog/guidance/margins/dilution/customer proof, or confirms an existing proof gate.")
    lines.append("- **War Room / War Room-lite:** earnings result, thesis conflict, buy/add/trim/kill decision, or a large move with real business news.")
    lines.append("- **No-action log only:** price move with no material headline, or headline that is just recap/target noise without estimate/proof change.")
    lines.append("")
    lines.append(f"Raw artifact: `{raw_rel}`")
    lines.append("")
    return "\n".join(lines)


def append_log(now: datetime, daily_rel: str, raw_rel: str, movers: list[QuoteRow], headlines: dict[str, list[HeadlineRow]]) -> None:
    date = now.date().isoformat()
    material_syms = [r.symbol for r in movers if any(h.material for h in headlines.get(r.symbol, []))]
    big_unexplained = [r.symbol for r in movers if abs(r.pct_change or 0) >= 7 and not any(h.material for h in headlines.get(r.symbol, []))]
    line = (
        f"\n## {date} watchlist_movers | Low-tax watchlist mover/news trigger scan\n"
        f"- Updated [[{daily_rel.replace('.md','')}|Watchlist movers]] from AI portfolio/conviction/pullback/daily-monitor sources. "
        f"Material headline candidates: {', '.join('$'+s for s in material_syms[:10]) or 'none'}; "
        f"large unexplained movers: {', '.join('$'+s for s in big_unexplained[:10]) or 'none'}. Raw: `{raw_rel}`.\n"
    )
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line)


def run_wiki_tools() -> dict:
    out: dict[str, object] = {}
    for cmd_name, cmd in {
        "build_index": [sys.executable, "_tools/build_index.py"],
        "wiki_lint": [sys.executable, "_tools/wiki_lint.py"],
    }.items():
        try:
            proc = subprocess.run(cmd, cwd=str(WIKI), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
            out[cmd_name] = {"exit_code": proc.returncode, "output_tail": proc.stdout[-2000:]}
        except Exception as exc:
            out[cmd_name] = {"exit_code": 999, "output_tail": f"{type(exc).__name__}: {exc}"}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10, help="Top up and down movers to keep before large-move de-dupe")
    ap.add_argument("--max-movers", type=int, default=20, help="Hard cap on final mover rows written to the wiki")
    ap.add_argument("--max-symbols", type=int, default=120, help="Cap quote scan universe")
    ap.add_argument("--min-abs-pct", type=float, default=5.0, help="Always include movers beyond this absolute %")
    ap.add_argument("--news-per-symbol", type=int, default=4)
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--print-summary", action="store_true")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%d_%H%M")
    date = now.date().isoformat()
    symbol_sources = extract_symbols()
    quotes = fetch_quotes(symbol_sources, args.max_symbols)
    movers = top_movers(quotes, args.top, args.min_abs_pct, args.max_movers)
    headlines = fetch_headlines([m.symbol for m in movers], args.news_per_symbol)

    raw_path = RAW_DIR / f"watchlist_movers_{stamp}.json"
    daily_path = DAILY_DIR / f"{date}_watchlist_movers.md"
    raw_payload = {
        "generated_at_utc": now.isoformat(),
        "source_files": [rel(p) for p in SOURCES if p.exists()],
        "symbol_count": len(symbol_sources),
        "quote_count": len(quotes),
        "quote_errors": sum(1 for q in quotes if q.quote_error),
        "parameters": {"top": args.top, "max_movers": args.max_movers, "max_symbols": args.max_symbols, "min_abs_pct": args.min_abs_pct, "news_per_symbol": args.news_per_symbol},
        "movers": [asdict(m) for m in movers],
        "headlines": {sym: [asdict(h) for h in hs] for sym, hs in headlines.items()},
    }
    atomic_write(raw_path, json.dumps(raw_payload, indent=2, sort_keys=True))
    raw_rel = rel(raw_path)
    md = render_markdown(now, raw_rel, movers, headlines, len(quotes), raw_payload["quote_errors"])
    atomic_write(daily_path, md)
    append_log(now, rel(daily_path), raw_rel, movers, headlines)

    latest_payload = {
        "generated_at_utc": now.isoformat(),
        "daily_note": rel(daily_path),
        "raw_artifact": raw_rel,
        "top_movers": [asdict(m) for m in movers[:20]],
        "material_headline_symbols": [m.symbol for m in movers if any(h.material for h in headlines.get(m.symbol, []))],
        "large_unexplained_symbols": [m.symbol for m in movers if abs(m.pct_change or 0) >= 7 and not any(h.material for h in headlines.get(m.symbol, []))],
    }
    atomic_write(LATEST_JSON, json.dumps(latest_payload, indent=2, sort_keys=True))
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(STATE_PATH, json.dumps({"last_run_utc": now.isoformat(), "last_daily_note": rel(daily_path), "last_raw_artifact": raw_rel}, indent=2, sort_keys=True))

    tool_results = None if args.skip_build else run_wiki_tools()
    if tool_results is not None:
        raw_payload["wiki_tools"] = tool_results
        atomic_write(raw_path, json.dumps(raw_payload, indent=2, sort_keys=True))

    if args.print_summary:
        material_syms = latest_payload["material_headline_symbols"]
        big_unexplained = latest_payload["large_unexplained_symbols"]
        lint = (tool_results or {}).get("wiki_lint", {}) if tool_results else {}
        print("Watchlist mover/news scan complete")
        print(f"Daily note: {rel(daily_path)}")
        print(f"Raw: {raw_rel}")
        print(f"Movers: {len(movers)} | material headline candidates: {', '.join(material_syms[:10]) or 'none'} | large unexplained: {', '.join(big_unexplained[:10]) or 'none'}")
        if lint:
            print(f"Lint exit: {lint.get('exit_code')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
