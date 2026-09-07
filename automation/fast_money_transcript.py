#!/usr/bin/env python3
"""
CNBC Fast Money daily transcript pipeline.
Downloads latest episode audio, transcribes with faster-whisper,
extracts ticker references and analyst commentary, updates research files.

Usage:
  python3 fast_money_transcript.py              # Process latest episode
  python3 fast_money_transcript.py --date 2026-04-24  # Specific date
  python3 fast_money_transcript.py --list        # List recent episodes
"""
from automation_paths import configured_text
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

RESEARCH_DIR = os.path.expanduser(configured_text('${ANALYST_WIKI_ROOT}'))
DAILY_DIR = os.path.join(RESEARCH_DIR, "daily")
TICKERS_DIR = os.path.join(RESEARCH_DIR, "tickers")
TRANSCRIPTS_DIR = os.path.join(RESEARCH_DIR, "raw", "transcripts")
FEED_URL = "https://feeds.simplecast.com/szW8tJ16"

# Watchlist tickers for cross-referencing
WATCHLIST = [
    "META", "IREN", "RBLX", "VST", "NOW", "CRWD", "BTC", "COIN", "HOOD", "RDDT",
    "LMND", "UPST", "NBIS", "QQQ", "MSFT", "GOOG", "AMZN", "AAPL", "NVDA", "CRM",
    "PLTR", "MU", "TSEM", "LITE", "AMD", "MRVL", "INTC", "ON", "CRDO", "SIVE",
    "AAOI", "ARM", "AVGO", "TSM", "LRCX", "AMAT", "KLAC", "ALAB", "ANET", "ASML",
    "COHR", "AEHR", "NVTS", "PDFS", "LPKF", "POET", "MXL", "SNDK", "TRT",
    "JBL", "TSLA", "NFLX", "DELL", "HPE", "IBM", "ORCL", "UBER", "ABNB",
    "SHOP", "SNAP", "PINS", "SQ", "PYPL", "SPOT",
]


def fetch_feed():
    """Fetch and parse the RSS feed."""
    req = urllib.request.Request(FEED_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        xml = resp.read().decode()
    root = ET.fromstring(xml)
    return root.findall(".//item")


def list_episodes(count=10):
    """List recent episodes."""
    items = fetch_feed()
    for i, item in enumerate(items[:count]):
        title = item.findtext("title", "N/A")
        date_str = item.findtext("pubDate", "N/A")
        enc = item.find("enclosure")
        size_mb = int(enc.get("length", 0)) / 1_000_000 if enc is not None else 0
        print(f"  [{i}] {date_str[:16]} | {size_mb:.0f}MB | {title[:80]}")


def get_latest_episode(target_date=None):
    """Get the latest (or specific date) episode audio URL."""
    items = fetch_feed()
    
    if target_date:
        # Find episode closest to target date
        target = datetime.strptime(target_date, "%Y-%m-%d")
        best = None
        best_diff = timedelta(days=999)
        for item in items[:30]:  # Check last 30 episodes
            date_str = item.findtext("pubDate", "")
            try:
                pub_date = parsedate_to_datetime(date_str).replace(tzinfo=None)
                diff = abs(pub_date.date() - target.date())
                if diff < best_diff:
                    best_diff = diff
                    best = item
            except (TypeError, ValueError, IndexError):
                continue
        return best
    else:
        return items[0] if items else None


def download_audio(url, output_path):
    """Download audio file."""
    print(f"  Downloading audio...")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        with open(output_path, "wb") as f:
            total = 0
            while True:
                chunk = resp.read(1024 * 1024)  # 1MB chunks
                if not chunk:
                    break
                f.write(chunk)
                total += len(chunk)
                if total % (5 * 1024 * 1024) == 0:
                    print(f"    {total / 1_000_000:.0f}MB...")
    size_mb = os.path.getsize(output_path) / 1_000_000
    print(f"  Downloaded: {size_mb:.1f}MB")


def transcribe(audio_path):
    """Transcribe audio using faster-whisper with cron-safe CPU settings."""
    print(f"  Transcribing with faster-whisper tiny/int8 (cron-safe settings)...")
    from faster_whisper import WhisperModel
    
    # Keep resource use low for the Hermes cron host. The previous beam_size=5
    # path routinely exceeded limits in low-memory runs; greedy decoding is less
    # polished but good enough for a sentiment/positioning source.
    model = WhisperModel("tiny", device="cpu", compute_type="int8", cpu_threads=1, num_workers=1)
    segments, info = model.transcribe(
        audio_path,
        beam_size=1,
        best_of=1,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    
    full_text = []
    for segment in segments:
        start = segment.start
        end = segment.end
        text = segment.text.strip()
        full_text.append(f"[{int(start//60):02d}:{int(start%60):02d}-{int(end//60):02d}:{int(end%60):02d}] {text}")
    
    return "\n".join(full_text), info


def extract_tickers(text):
    """Find ticker references in transcript."""
    # Name-to-ticker mapping for companies often mentioned by name
    NAME_MAP = {
        "intel": "INTC", "nvidia": "NVDA", "amd": "AMD", "apple": "AAPL",
        "tesla": "TSLA", "microsoft": "MSFT", "amazon": "AMZN", "alphabet": "GOOG",
        "google": "GOOG", "meta": "META", "facebook": "META", "netflix": "NFLX",
        "broadcom": "AVGO", "qualcomm": "QCOM", "taiwan semiconductor": "TSM",
        "tsmc": "TSM", "micron": "MU", "marvell": "MRVL", "arm": "ARM",
        "crown castle": "CCI", "palantir": "PLTR", "crowdstrike": "CRWD",
        "coinbase": "COIN", "robinhood": "HOOD", "reddit": "RDDT",
        "lumentum": "LITE", "coherent": "COHR", "service now": "NOW",
        "servicenow": "NOW", "salesforce": "CRM", "uber": "UBER", "airbnb": "ABNB",
        "alibaba": "BABA", "novavax": "NVAX", "pfizer": "PFE", "jpmorgan": "JPM",
        "goldman": "GS", "morgan stanley": "MS", "bank of america": "BAC",
        "novo": "NVO", "novonordisk": "NVO", "lululemon": "LULU",
        "united": "UAL", "boeing": "BA", "caterpillar": "CAT",
        "dell": "DELL", "hpe": "HPE", "hp": "HPQ", "oracle": "ORCL",
        "ibm": "IBM", "adobe": "ADBE", "snap": "SNAP", "pinterest": "PINS",
        "shopify": "SHOP", "spotify": "SPOT", "paypal": "PYPL",
    }
    
    found = set()
    
    # Match $TICKER format
    dollar_tickers = set(re.findall(r'\$([A-Z]{2,5})\b', text))
    found.update(dollar_tickers)
    
    # Match company names
    lower_text = text.lower()
    for name, ticker in NAME_MAP.items():
        if re.search(rf'\b{re.escape(name)}\b', lower_text):
            found.add(ticker)
    
    # Match standalone ticker symbols from watchlist
    for ticker in WATCHLIST:
        if re.search(rf'\b{ticker}\b', text):
            found.add(ticker)
    
    return sorted(found)


def extract_macro_themes(text):
    """Extract macro themes, sector trends, and news discussed."""
    lower = text.lower()
    
    # Macro categories with keyword groups
    macro_categories = {
        "Fed/Rates": ["federal reserve", "the fed", "interest rate", "rate cut", "rate hike",
                       "powell", "jerome powell", "fomc", "basis point", "treasury yield",
                       "bond market", "10-year", "2-year"],
        "Inflation": ["inflation", "cpi", "pce", "consumer price", "deflation"],
        "Geopolitics": ["china", "tariff", "trade war", "ceasefire", "iran", "russia",
                        "ukraine", "sanction", "middle east", "hormuz", "opec", "oil price",
                        "crude oil", "brent"],
        "Economy": ["recession", "soft landing", "hard landing", "gdp", "employment",
                    "jobless", "unemployment", "labor market", "consumer spending",
                    "housing market", "manufacturing", "pmi", "ism"],
        "AI/Tech Cycle": ["artificial intelligence", "ai spending", "data center", "capex",
                          "cloud spending", "hyperscaler", "infrastructure", "gpu",
                          "chip", "semiconductor", "compute"],
        "Energy": ["nuclear", "solar", "renewable", "energy", "power grid", "electricity",
                   "natural gas", "lng", "uranium", "smr", "small modular"],
        "Regulation": ["sec", "regulation", "antitrust", "congress", "legislation",
                       "white house", "administration", "executive order", "policy"],
        "Market Sentiment": ["bull market", "bear market", "rally", "selloff", "pullback",
                             "correction", "all-time high", "volatility", "vix", "fear",
                             "euphoria", "cautious", "optimistic", "frothy", "overbought"],
        "Institutional Flow / Rotation": ["institutional money", "big money", "fund flow",
                                          "fund flows", "etf flow", "etf flows", "flows into",
                                          "flows out", "inflows", "outflows", "positioning",
                                          "crowded", "underweight", "overweight", "allocation",
                                          "allocators", "hedge fund", "long-only", "mutual fund",
                                          "sector rotation", "rotation", "leadership", "breadth",
                                          "money managers", "real money", "sponsorship",
                                          "buying pressure", "selling pressure", "rebalancing"],
        "M&A / Corporate": ["merger", "acquisition", "ipo", "buyout", "spinoff",
                            "partnership", "joint venture", "strategic investment"],
    }
    
    found = {}
    for category, keywords in macro_categories.items():
        hits = []
        for kw in keywords:
            pattern = rf"[^.!?]*\b{re.escape(kw)}\b[^.!?]*[.!?]"
            matches = re.findall(pattern, lower)
            for m in matches:
                cleaned = m.strip()
                if len(cleaned) > 40:  # Skip trivial mentions
                    hits.append(cleaned)
        if hits:
            # Deduplicate and keep top 3
            unique = list(dict.fromkeys(hits))[:3]
            found[category] = unique
    
    return found


def extract_analyst_commentary(text):
    """Extract analyst names and their commentary."""
    # Known Fast Money panelists and frequent guests
    analysts = [
        "Melissa Lee", "Jim Cramer", "Jon Najarian", "Pete Najarian", 
        "Steve Grasso", "Brian Kelly", "Dan Nathan", "Guy Adami",
        "Tim Seymour", "Karen Finerman", "Joe Terranova", "Stephanie Link",
        "Gene Munster", "Josh Brown", "Carter Worth", "Mike Murphy",
        "Bonnie Baha", "Jeff Mills", "Tony Dwyer", "Mark Tepper",
        "Jill Malandrino", "Scott Wapner", "Carl Quintanilla",
        "David Faber", "Sara Eisen", "Morgan Brennan",
    ]
    
    found = {}
    for analyst in analysts:
        # Find sentences mentioning the analyst
        pattern = rf'{re.escape(analyst)}[^.!?]*[.!?]'
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            # Take the 3 most substantive mentions
            substantive = [m for m in matches if len(m) > 50][:3]
            if substantive:
                found[analyst] = substantive
    
    return found


def fetch_macro_news_crosscheck(macro_themes, max_items=5):
    """Fetch a small current-news cross-check for extracted macro themes.

    This keeps the no-agent Fast Money ingestion from treating panel commentary
    as standalone macro truth. It is deliberately lightweight: Google News RSS
    surfaces current Reuters/Bloomberg/CNBC/WSJ/FT/MarketWatch-style coverage
    when available, and failures are recorded rather than blocking transcript
    ingestion.
    """
    if not macro_themes:
        return {"checked_at": datetime.utcnow().isoformat() + "Z", "queries": [], "items": []}

    query_map = {
        "Fed/Rates": "Federal Reserve interest rates Treasury yields markets",
        "Inflation": "inflation CPI PCE Fed markets",
        "Economic Growth": "US economy GDP jobs payrolls recession markets",
        "Geopolitical": "geopolitical risk oil markets stocks",
        "Sector Rotation": "sector rotation stock market leadership",
    }
    themes = list(macro_themes.keys())[:4]
    queries = []
    for theme in themes:
        queries.append(query_map.get(theme, f"{theme} macro economy markets"))

    items = []
    errors = []
    seen_titles = set()
    for query in queries:
        encoded = urllib.parse.quote_plus(query + " when:1d")
        url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                root = ET.fromstring(resp.read())
            for item in root.findall(".//item")[:3]:
                title = (item.findtext("title") or "").strip()
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)
                source_el = item.find("source")
                items.append({
                    "query": query,
                    "title": title,
                    "source": (source_el.text or "").strip() if source_el is not None else "",
                    "link": (item.findtext("link") or "").strip(),
                    "published": (item.findtext("pubDate") or "").strip(),
                })
                if len(items) >= max_items:
                    break
        except Exception as exc:
            errors.append(f"{query}: {exc}")
        if len(items) >= max_items:
            break

    result = {"checked_at": datetime.utcnow().isoformat() + "Z", "queries": queries, "items": items}
    if errors:
        result["errors"] = errors
    return result


def generate_insights(text, title, episode_date):
    """Generate structured insights from transcript."""
    tickers = extract_tickers(text)
    analyst_hits = extract_analyst_commentary(text)
    macro_themes = extract_macro_themes(text)

    # Find bullish/bearish language near tickers
    insights = []
    # Alias map for transcript context extraction. CNBC usually says company names, not symbols.
    ticker_aliases = {
        "INTC": ["intel"], "NVDA": ["nvidia"], "AMD": ["amd"], "AAPL": ["apple"],
        "TSLA": ["tesla"], "MSFT": ["microsoft"], "AMZN": ["amazon"], "GOOG": ["alphabet", "google"],
        "META": ["meta", "facebook"], "NFLX": ["netflix"], "AVGO": ["broadcom"], "QCOM": ["qualcomm"],
        "TSM": ["taiwan semiconductor", "taiwan-semi", "tsmc"], "MU": ["micron"], "MRVL": ["marvell"],
        "ARM": ["arm"], "CCI": ["crown castle"], "PLTR": ["palantir"], "CRWD": ["crowdstrike"],
        "COIN": ["coinbase"], "HOOD": ["robinhood"], "RDDT": ["reddit"], "LITE": ["lumentum"],
        "COHR": ["coherent"], "NOW": ["service now", "servicenow"], "CRM": ["salesforce"],
        "UBER": ["uber"], "ABNB": ["airbnb"], "BABA": ["alibaba"], "NVAX": ["novavax"],
        "PFE": ["pfizer"], "JPM": ["jpmorgan"], "GS": ["goldman"], "MS": ["morgan stanley"],
        "BAC": ["bank of america"], "NVO": ["novo", "novonordisk"], "LULU": ["lululemon"],
        "UAL": ["united"], "BA": ["boeing"], "CAT": ["caterpillar"], "DELL": ["dell"],
        "HPE": ["hpe"], "HPQ": ["hp"], "ORCL": ["oracle"], "IBM": ["ibm"], "ADBE": ["adobe"],
        "SNAP": ["snap"], "PINS": ["pinterest"], "SHOP": ["shopify"], "SPOT": ["spotify"],
        "SQ": ["block inc", "block stock", "jack dorsey"], "PYPL": ["paypal"],
    }

    for ticker in tickers:
        # Get context around each ticker/company-name mention (100 chars before/after).
        contexts = []
        # Cashtags are explicit. Bare ticker symbols are case-sensitive to avoid
        # poisoning pages with common words like "now", "on", "arm", or "ms".
        # Company-name aliases remain case-insensitive because transcripts are normal text.
        compiled_patterns = [
            re.compile(rf'\${re.escape(ticker)}\b', re.IGNORECASE),
            re.compile(rf'(?<![A-Za-z0-9]){re.escape(ticker)}(?![A-Za-z0-9])'),
        ]
        compiled_patterns += [
            re.compile(rf'\b{re.escape(alias)}\b', re.IGNORECASE)
            for alias in ticker_aliases.get(ticker, [])
        ]
        for compiled in compiled_patterns:
            for m in compiled.finditer(text):
                start = max(0, m.start() - 100)
                end = min(len(text), m.end() + 100)
                contexts.append(text[start:end])
        if contexts:
            insights.append({
                "ticker": ticker,
                "mentions": len(contexts),
                "contexts": contexts[:3],  # Top 3 mentions
            })
    
    # Sort by mention count
    insights.sort(key=lambda x: x["mentions"], reverse=True)
    
    return {
        "title": title,
        "date": episode_date,
        "tickers_mentioned": tickers,
        "ticker_insights": insights,
        "analyst_commentary": analyst_hits,
        "macro_themes": macro_themes,
        "macro_news_crosscheck": fetch_macro_news_crosscheck(macro_themes),
    }


def _clean_snippet(text, max_len=260):
    """Make ASR snippets readable enough for wiki signal pages."""
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    cleaned = cleaned.replace("|", "-")
    if len(cleaned) > max_len:
        cleaned = cleaned[: max_len - 1].rstrip() + "…"
    return cleaned


def _wiki_link_for_ticker(ticker):
    """Return a wiki link if a canonical ticker page exists, otherwise plain cashtag."""
    ticker_path = os.path.join(TICKERS_DIR, f"{ticker}.md")
    if os.path.exists(ticker_path):
        return f"[[tickers/{ticker}.md|${ticker}]]"
    return f"${ticker}"


def write_fastmoney_wiki_note(insights, episode_date):
    """Write a structured Fast Money signal note into wiki-market/daily/fastmoney."""
    fastmoney_dir = os.path.join(DAILY_DIR, "fastmoney")
    os.makedirs(fastmoney_dir, exist_ok=True)

    note_path = os.path.join(fastmoney_dir, f"fastmoney_{episode_date}.md")
    transcript_rel = f"raw/transcripts/fast_money_{episode_date}.txt"
    insights_rel = f"raw/transcripts/fast_money_{episode_date}_insights.json"

    try:
        display_date = datetime.strptime(episode_date, "%Y-%m-%d").strftime("%B %-d, %Y")
    except ValueError:
        display_date = episode_date

    tickers = insights.get("tickers_mentioned", [])
    ticker_insights = insights.get("ticker_insights", [])
    macro_themes = insights.get("macro_themes", {})
    macro_news = insights.get("macro_news_crosscheck") or fetch_macro_news_crosscheck(macro_themes)
    insights["macro_news_crosscheck"] = macro_news
    analyst_commentary = insights.get("analyst_commentary", {})

    lines = [
        "---",
        f"title: Fast Money — {episode_date}",
        f"created: {episode_date}",
        f"updated: {datetime.now().strftime('%Y-%m-%d')}",
        "type: transcript",
        "tags: [daily, transcript, macro]",
        f"sources: [{transcript_rel}, {insights_rel}]",
        "---",
        "",
        "> **Signal role:** CNBC Fast Money is sentiment/positioning input, not thesis proof. Use it to spot consensus, crowded narratives, and near-term narrative catalysts. Cross-check against [[macro.md]] and [[market-map.md]] before changing sizing.",
        "",
        f"# CNBC Fast Money — {display_date}",
        "",
        f"Episode: **{insights.get('title', 'Unknown')}**",
        "",
        "## Macro Themes",
    ]

    if macro_themes:
        for theme, contexts in macro_themes.items():
            lines.append(f"### {theme}")
            for context in contexts[:3]:
                lines.append(f"- {_clean_snippet(context)} ^[{insights_rel}]")
            lines.append("")
    else:
        lines.append("- No durable macro theme extracted from the transcript.\n")

    lines.extend(["## Macro News Cross-Check", ""])
    queries = macro_news.get("queries", []) if isinstance(macro_news, dict) else []
    news_items = macro_news.get("items", []) if isinstance(macro_news, dict) else []
    news_errors = macro_news.get("errors", []) if isinstance(macro_news, dict) else []
    if queries:
        lines.append("- Queries checked: " + "; ".join(queries))
    if news_items:
        for item in news_items[:5]:
            title = _clean_snippet(item.get("title", ""), max_len=180)
            source = item.get("source") or "news"
            link = item.get("link") or ""
            if link:
                lines.append(f"- {title} — {source}: {link}")
            else:
                lines.append(f"- {title} — {source}")
    elif macro_themes:
        lines.append("- Current news cross-check attempted, but no usable headlines were returned; treat macro confidence as degraded.")
    else:
        lines.append("- No macro theme extracted, so no news cross-check required.")
    if news_errors:
        lines.append("- Source-access warnings: " + "; ".join(news_errors[:3]))
    lines.append("")

    lines.extend(["## Tickers / Opinions", ""])
    if ticker_insights:
        for item in ticker_insights[:20]:
            ticker = item.get("ticker", "")
            if not ticker:
                continue
            lines.append(f"### {_wiki_link_for_ticker(ticker)} — {item.get('mentions', 0)} mentions")
            for context in item.get("contexts", [])[:3]:
                lines.append(f"- {_clean_snippet(context)} ^[{insights_rel}]")
            lines.append("")
    elif tickers:
        lines.append("- Mentioned: " + ", ".join(_wiki_link_for_ticker(t) for t in tickers))
        lines.append("")
    else:
        lines.append("- No tracked tickers extracted.\n")

    lines.extend(["## Analyst / Guest Commentary", ""])
    if analyst_commentary:
        for analyst, quotes in list(analyst_commentary.items())[:12]:
            lines.append(f"### {analyst}")
            for quote in quotes[:3]:
                lines.append(f"- {_clean_snippet(quote)} ^[{insights_rel}]")
            lines.append("")
    else:
        lines.append("- No named analyst commentary extracted.\n")

    lines.extend([
        "## Follow-up Use",
        "- Treat as an additional signal layer for [[conviction-shortlist.md]] and ticker pages only when it overlaps with filings, earnings revisions, price action, or trusted research.",
        "- If a ticker appears repeatedly across Fast Money, X signals, and earnings/news flow, promote it to a proper research pass before adding capital.",
        "",
    ])

    content = "\n".join(lines)
    with open(note_path, "w") as f:
        f.write(content)
    print(f"  Wiki note saved: {note_path}")
    return note_path


def append_wiki_log(episode_date, note_path):
    """Append a concise ingestion entry to wiki-market/log.md."""
    log_path = os.path.join(RESEARCH_DIR, "log.md")
    rel_note = os.path.relpath(note_path, RESEARCH_DIR)
    entry = f"## [{datetime.now().strftime('%Y-%m-%d')}] ingest | CNBC Fast Money {episode_date}\n- Added structured Fast Money signal note: `{rel_note}` from raw transcript/insights.\n\n"
    try:
        if os.path.exists(log_path):
            with open(log_path) as f:
                existing = f.read()
            if f"CNBC Fast Money {episode_date}" in existing and rel_note in existing:
                return
            with open(log_path, "a") as f:
                f.write(entry)
    except OSError as exc:
        print(f"  WARNING: could not append wiki log: {exc}", file=sys.stderr)


def update_macro_regime_trace(insights, episode_date, note_path):
    """Append Fast Money macro themes to the market-regime sentiment page.

    This keeps the no-agent transcript ingestion aligned with the broader rule:
    every news/sentiment scan leaves wiki-market smarter, not just a Slack/log artifact.
    """
    regime_path = os.path.join(RESEARCH_DIR, "themes", "market_regime_risk_on_off.md")
    if not os.path.exists(regime_path):
        return

    rel_note = os.path.relpath(note_path, RESEARCH_DIR)
    macro_themes = insights.get("macro_themes", {}) or {}
    macro_news = insights.get("macro_news_crosscheck") or fetch_macro_news_crosscheck(macro_themes)
    news_count = len(macro_news.get("items", [])) if isinstance(macro_news, dict) else 0
    news_suffix = f" News cross-check: {news_count} current headline(s) checked." if news_count else " News cross-check attempted; confidence degraded if no current headlines were available."
    if macro_themes:
        theme_list = ", ".join(sorted(macro_themes.keys()))
        bullet = f"- [[{rel_note}|CNBC Fast Money {episode_date}]]: macro/positioning themes extracted: {theme_list}. Treat as sentiment input, not thesis proof.{news_suffix}"
    else:
        bullet = f"- [[{rel_note}|CNBC Fast Money {episode_date}]]: no durable macro theme extracted; no material regime change from this transcript."

    section = "## CNBC Fast Money Transcript Inputs"
    try:
        with open(regime_path) as f:
            existing = f.read()
        if f"CNBC Fast Money {episode_date}" in existing:
            return
        if section not in existing:
            existing = existing.rstrip() + f"\n\n{section}\n"
        existing = existing.rstrip() + "\n" + bullet + "\n"
        with open(regime_path, "w") as f:
            f.write(existing)
        print(f"  Macro regime trace updated: {regime_path}")
    except OSError as exc:
        print(f"  WARNING: could not update macro regime trace: {exc}", file=sys.stderr)


def save_results(transcript, insights, episode_date):
    """Save transcript/insights raw inputs and structured wiki signal note."""
    os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
    os.makedirs(DAILY_DIR, exist_ok=True)
    os.makedirs(TICKERS_DIR, exist_ok=True)
    
    # Save raw transcript
    transcript_path = os.path.join(TRANSCRIPTS_DIR, f"fast_money_{episode_date}.txt")
    with open(transcript_path, "w") as f:
        f.write(f"# CNBC Fast Money — {insights['title']}\n")
        f.write(f"# Date: {insights['date']}\n\n")
        f.write(transcript)
    print(f"  Transcript saved: {transcript_path}")
    
    # Save insights as JSON
    insights_path = os.path.join(TRANSCRIPTS_DIR, f"fast_money_{episode_date}_insights.json")
    with open(insights_path, "w") as f:
        json.dump(insights, f, indent=2)
    print(f"  Insights saved: {insights_path}")

    note_path = write_fastmoney_wiki_note(insights, episode_date)
    append_wiki_log(episode_date, note_path)
    update_macro_regime_trace(insights, episode_date, note_path)
    return transcript_path, insights_path, note_path


def main():
    args = sys.argv[1:]
    
    if "--list" in args:
        print("Recent Fast Money episodes:")
        list_episodes(10)
        return
    
    target_date = None
    if "--date" in args:
        idx = args.index("--date")
        if idx + 1 < len(args):
            target_date = args[idx + 1]
    
    print("=== CNBC Fast Money Transcript Pipeline ===\n")
    
    # Get episode
    episode = get_latest_episode(target_date)
    if not episode:
        print("No episode found.")
        return
    
    title = episode.findtext("title", "Unknown")
    date_str = episode.findtext("pubDate", "")
    enc = episode.find("enclosure")
    audio_url = enc.get("url", "") if enc is not None else ""
    
    # Parse date
    try:
        pub_date = parsedate_to_datetime(date_str).replace(tzinfo=None)
        episode_date = pub_date.strftime("%Y-%m-%d")
    except (TypeError, ValueError, IndexError):
        episode_date = datetime.now().strftime("%Y-%m-%d")
    
    print(f"Episode: {title}")
    print(f"Date: {episode_date}")
    print(f"Audio: {audio_url[:60]}...")
    
    # Check if already processed
    transcript_path = os.path.join(TRANSCRIPTS_DIR, f"fast_money_{episode_date}.txt")
    if os.path.exists(transcript_path):
        print(f"\nAlready processed. Loading cached transcript...")
        with open(transcript_path) as f:
            transcript = f.read()
        insights_path = os.path.join(TRANSCRIPTS_DIR, f"fast_money_{episode_date}_insights.json")
        with open(insights_path) as f:
            insights = json.load(f)
        note_path = write_fastmoney_wiki_note(insights, episode_date)
        append_wiki_log(episode_date, note_path)
        update_macro_regime_trace(insights, episode_date, note_path)
    else:
        # Download audio
        AUDIO_DIR = os.path.join(configured_text("${ANALYST_HERMES_HOME}"), "podcast_data", "audio")
        os.makedirs(AUDIO_DIR, exist_ok=True)
        audio_path = os.path.join(AUDIO_DIR, f"fast_money_{episode_date}.mp3")
        if not os.path.exists(audio_path):
            download_audio(audio_url, audio_path)
        
        # Transcribe
        transcript, info = transcribe(audio_path)
        print(f"  Language: {info.language} (prob: {info.language_probability:.2f})")
        
        # Keep the download until transcription and result writes both succeed so
        # a failed run can retry without downloading the episode again.

        # Generate insights
        print(f"\n  Analyzing content...")
        insights = generate_insights(transcript, title, episode_date)

        # Save, then remove the reproducible audio immediately. The general
        # podcast pipeline is no longer scheduled, so relying on its 3-day
        # cleanup allowed Fast Money downloads to accumulate indefinitely.
        save_results(transcript, insights, episode_date)
        try:
            os.unlink(audio_path)
            print(f"  Cleaned up audio: {os.path.basename(audio_path)}")
        except FileNotFoundError:
            pass
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"  TICKERS MENTIONED: {', '.join(f'${t}' for t in insights['tickers_mentioned'])}")
    print(f"  ANALYSTS QUOTED: {', '.join(insights['analyst_commentary'].keys())}")
    print(f"  MACRO THEMES: {', '.join(insights.get('macro_themes', {}).keys())}")
    print(f"{'='*60}")
    
    # Print macro themes
    for theme, contexts in insights.get("macro_themes", {}).items():
        print(f"\n  📊 {theme}:")
        for c in contexts[:2]:
            cleaned = c.strip().replace("\n", " ")[:250]
            print(f"    → {cleaned}...")
    
    # Print top ticker insights
    for ti in insights.get("ticker_insights", [])[:5]:
        print(f"\n  ${ti['ticker']} ({ti['mentions']} mentions):")
        for ctx in ti['contexts'][:2]:
            cleaned = ctx.strip().replace("\n", " ")[:200]
            print(f"    → {cleaned}...")
    
    # Print analyst commentary
    for analyst, quotes in list(insights['analyst_commentary'].items())[:5]:
        print(f"\n  🎙️ {analyst}:")
        for q in quotes[:2]:
            cleaned = q.strip().replace("\n", " ")[:200]
            print(f"    → {cleaned}...")


if __name__ == "__main__":
    main()
