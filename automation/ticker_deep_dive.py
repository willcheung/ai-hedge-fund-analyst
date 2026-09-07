#!/usr/bin/env python3
"""
Ticker Deep Dive — Gemini Deep Research + Wiki Integration + Price Monitoring

Uses Gemini's Deep Research Agent (Interactions API) to produce institutional-grade
equity research reports, then files them into the wiki and cross-references with
existing X sentiment data. Tracks conviction shortlist with live prices.

Usage:
    python3 ticker_deep_dive.py VST                      # Full deep dive (~$1-3, 5-10 min)
    python3 ticker_deep_dive.py VST --max                # Max depth (~$3-7, 10-20 min)
    python3 ticker_deep_dive.py VST --poll-interval 15
    python3 ticker_deep_dive.py VST --max-wait 900
    python3 ticker_deep_dive.py VST --update-only        # Skip Gemini, re-file from existing report
    python3 ticker_deep_dive.py VST --skip-price-check   # Skip yfinance post-check
    python3 ticker_deep_dive.py --price-check            # Check prices for all shortlist tickers
    python3 ticker_deep_dive.py --auto-pick              # Auto-select tickers needing research (for cron)

Output:
    - Raw report: ~/wiki-market/raw/papers/{TICKER}_gemini_deep_dive_{date}.md
    - Ticker page updated: ~/wiki-market/tickers/{TICKER}.md
    - Conviction shortlist: ~/wiki-market/conviction-shortlist.md
    - Price snapshot: ~/wiki-market/daily/prices_{date}.md (on --price-check)
"""
from automation_paths import configured_text

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

def load_env_vars() -> dict:
    """Load environment from process env plus ~/.hermes/.env.

    Current Hermes runs do not depend on OpenClaw. This loader intentionally reads
    only Hermes env and the live process environment, so removed ~/.openclaw
    folders cannot break deep research.
    """
    env_vars = dict(os.environ)
    env_path = Path(os.path.expanduser(configured_text('${ANALYST_HERMES_HOME}/.env')))
    if env_path.exists():
        for raw_line in env_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            key, _, value = line.partition("=")
            env_vars[key.strip()] = value.strip().strip('"').strip("'")
    return env_vars


ENV_VARS = load_env_vars()
GEMINI_API_KEY = ENV_VARS.get("GEMINI_API_KEY", "") or ENV_VARS.get("GOOGLE_API_KEY", "")
WIKI_DIR = Path(os.path.expanduser(ENV_VARS.get("WIKI_MARKET_PATH", configured_text('${ANALYST_WIKI_ROOT}'))))

# Do not spend Gemini deep-research budget on mega-caps, ETFs, or common acronym false positives.
# Daily scanner can still report these; auto-pick is for asymmetric discovery.
AUTO_PICK_EXCLUDE_TICKERS = {
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA", "AVGO",
    "AMD", "ARM", "ORCL", "NFLX", "COST", "CRM", "ADBE", "QCOM", "INTC", "IBM",
    "SPY", "QQQ", "IWM", "DIA", "VIX", "TLT", "GLD", "SLV", "DXY",
    "CEO", "CFO", "CIO", "CPU", "GPU", "AI", "IPO", "ETF", "EPS", "PE", "PEG",
    "AND", "THE", "FOR", "WITH", "FROM", "THIS", "THAT", "BULL", "BEAR", "RADAR",
}

# Conviction hunting is for multi-bagger math, not good-company tourism.
# Auto-pick can still select a >$5B name when the operator explicitly puts it in the shortlist/core hold,
# but scanner-driven discovery should bias toward <$2B and hard-skip >$5B.
AUTO_PICK_MAX_DISCOVERY_MCAP_USD = 5_000_000_000

# Two modes: "deep-research-preview-04-2026" (speed) or "deep-research-max-preview-04-2026" (max depth)
DEEP_RESEARCH_AGENT = "deep-research-preview-04-2026"
DEEP_RESEARCH_AGENT_MAX = "deep-research-max-preview-04-2026"

# the configured prompt template
RESEARCH_PROMPT = """Persona:
Act as a Senior Hedge Fund Manager and Lead Equity Research Analyst. You are skeptical, data-obsessed, and focused entirely on ROI (Return on Investment) and asymmetric risk/reward profiles. You do not rephrase marketing fluff; you dissect it. Your goal is to provide institutional-grade research that determines whether a ticker is a "Long," "Short," or "Avoid."

Tone & Style:
- Authoritative & Sharp: Use decisive language. Avoid hedging words like "maybe" or "could."
- Data-Centric: Every claim must be backed by a metric (e.g., margins, CAC, LTV, YoY growth).
- Skeptical: Always assume management is painting a rosy picture. Dig for the "Bear Case."
- No Corporate Mush: Cut the jargon. If a strategy is failing, call it out directly.

Mandatory Report Structure:
You must structure every response as a formal "[$TICKER] Equity Research Report [Company Name]" using the following hierarchy:

1. Executive Investment Summary
- Date: Today's date ({date})
- The Thesis: A concise narrative explaining the core tension in the stock (e.g., "Hyper-growth vs. Existential Risk").
- Recommendation: BUY, SELL, or HOLD (include a risk profile: e.g., High Risk/High Reward).
- Key Investment Merits: 3 distinct bullet points explaining why the stock could double.
- Key Investment Risks: 3 distinct bullet points explaining why the stock could crash (focus on regulatory, margin compression, or macro risks).

2. Strategic Analysis
- Value Proposition: What problem does the company actually solve? (Move beyond the "About Us" page; explain the utility).
- The Flywheel: Describe the mechanics of how the business grows. Does it have network effects? High switching costs?
- SWOT Analysis: A strict breakdown of Strengths, Weaknesses, Opportunities, and Threats.
- Macros: Does it have any macro trends as tailwind or headwind? (Fed, shifting consumer preference, AI, policy change, green energy, etc.)

3. Financial & Operational Deep Dive
- Revenue & Margins: Analyze recent financial performance. Focus on Top-line growth vs. Bottom-line profitability (GAAP vs. Non-GAAP). Consider health in cash flow, balance sheet, and income statement.
- Unit Economics: If available, analyze CAC (Customer Acquisition Cost), LTV (Lifetime Value), and Retention rates.
- Employee & Org Structure: Is the headcount growing faster than revenue? (A red flag for efficiency).

4. Market Position & Competitive Landscape
- Competitor Table: Compare the target company against its top 5 competitors using the following columns: Ticker, Business Model, Revenue Growth, Margin Profile, Valuation Multiple (EV/Revenue or P/E).
- Moat Analysis: Does the company have a durable advantage (Tech, Brand, Regulatory), or is it a commodity?

5. Strategic Growth Vectors (The "Bull Case")
- New Revenue Streams: Identify upcoming products, pivots, or partnerships (e.g., ad networks, new hardware, AI integration) that could drive future cash flow.
- Product & Pricing: Analyze the pricing power. Can they raise prices without losing customers?

6. Risk Analysis (The "Bear Case")
- Sovereign & Regulatory Risk: Are there geopolitical or legal threats (e.g., bans, antitrust)?
- Operational Risk: Execution failures, high CAPEX requirements, or management turnover.

7. Institutional Sentiment & News
- Recent News: Summarize the 5 most recent significant news stories that move the needle.
- Insider Activity: Are insiders (CEO/CFO) buying or selling? What does this signal?

8. Visualizations
- Create 3 specific chart/infographic descriptions that would support this thesis (e.g., "A bar chart comparing 3-year CAGR of [Ticker] vs. [Competitor]").

9. Final Verdict
- Conclude with a summary "Investment Potential Assessment."
- Actionable Next Step: Provide a specific trigger event to watch for (e.g., "Accumulate only if stock drops below $X or if Q3 margins exceed Y%").

Rules for Execution:
- Cite Sources: If you use external data, cite it clearly.
- Forward-Looking: Do not just report the past; predict the next 12-24 months.
- Catalyst discipline: separate CORE HOLD theses from EVENT/CATALYST trades. A good company is not automatically an asymmetric trade.
- Catalyst quality gate: identify the next 1-3 concrete events that can force estimate revisions or order/backlog conversion within 3-12 months. If no near-term catalyst exists, say HOLD / watchlist instead of BUY.
- Market-cap math: explicitly state whether a 3-5x return is mathematically plausible from today's market cap. For >$5B names, default to core-hold/watchlist unless the catalyst can change the TAM or earnings base dramatically.
- Post-event verdict: if the main catalyst already happened, judge whether it actually changed guidance, estimates, backlog, or customer proof. If the stock did not re-rate and no new catalyst appeared, downgrade event-trade framing.
- Research the ticker ${ticker} thoroughly using web search.
"""


def run_gemini_deep_research(ticker: str, poll_interval: int = 15, max_wait: int = 600, use_max: bool = False) -> str:
    """Fire off Gemini Deep Research and poll for results."""
    from google import genai

    if not GEMINI_API_KEY:
        print(json.dumps({"error": "No GEMINI_API_KEY found in ~/.hermes/.env"}))
        sys.exit(1)

    client = genai.Client(api_key=GEMINI_API_KEY)
    today = datetime.now().strftime("%B %d, %Y")
    prompt = RESEARCH_PROMPT.format(ticker=ticker, date=today)

    agent_id = DEEP_RESEARCH_AGENT_MAX if use_max else DEEP_RESEARCH_AGENT
    mode_label = "MAX (comprehensive)" if use_max else "standard"

    print(f"🚀 Starting Gemini Deep Research for ${ticker} ({mode_label})...", flush=True)
    sys.stdout.flush()

    # Start research (async) with agent_config
    interaction = client.interactions.create(
        input=prompt,
        agent=agent_id,
        agent_config={
            "type": "deep-research",
            "visualization": "auto",
        },
        background=True,
    )
    interaction_id = interaction.id
    today_slug = datetime.now().strftime("%Y-%m-%d")
    state_dir = WIKI_DIR / "raw" / "papers"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / f"{ticker}_gemini_interaction_{today_slug}.json"
    state_path.write_text(json.dumps({
        "ticker": ticker,
        "interaction_id": interaction_id,
        "agent": agent_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "max_wait": max_wait,
    }, indent=2))
    print(f"   Interaction ID: {interaction_id}", flush=True)
    print(f"   Interaction state: {state_path}", flush=True)
    print(f"   Agent: {agent_id}", flush=True)
    print(f"   Polling every {poll_interval}s (max {max_wait}s)...", flush=True)

    # Poll for results
    start = time.time()
    while time.time() - start < max_wait:
        try:
            interaction = client.interactions.get(interaction_id)
            status = interaction.status
            elapsed = int(time.time() - start)
            print(f"   [{elapsed}s] Status: {status}", flush=True)

            if status == "completed":
                if interaction.outputs and len(interaction.outputs) > 0:
                    # Collect all text outputs; save any images
                    report_parts = []
                    image_count = 0
                    for output in interaction.outputs:
                        if hasattr(output, 'type') and output.type == "text":
                            report_parts.append(output.text)
                        elif hasattr(output, 'type') and output.type == "image" and output.data:
                            image_count += 1
                            # Save chart images
                            import base64
                            charts_dir = WIKI_DIR / "raw" / "charts"
                            charts_dir.mkdir(parents=True, exist_ok=True)
                            today = datetime.now().strftime("%Y-%m-%d")
                            img_path = charts_dir / f"{ticker}_chart_{image_count}_{today}.png"
                            img_bytes = base64.b64decode(output.data)
                            img_path.write_bytes(img_bytes)
                            report_parts.append(f"\n[Chart saved: {img_path.name}]")
                    
                    report = "\n".join(report_parts)
                    print(f"   ✓ Report received ({len(report)} chars, {elapsed}s, {image_count} charts)", flush=True)
                    return report
                else:
                    print(f"   ✗ Completed but no output", flush=True)
                    return ""
            elif status == "failed":
                error = getattr(interaction, "error", "Unknown error")
                print(f"   ✗ Failed: {error}", flush=True)
                return ""
        except Exception as e:
            print(f"   ⚠ Poll error: {e}", flush=True)

        time.sleep(poll_interval)

    print(f"   ✗ Timed out after {max_wait}s", flush=True)
    print(f"   Recover later with interaction ID: {interaction_id}", flush=True)
    print(f"   State file: {state_path}", flush=True)
    return ""


def save_raw_report(ticker: str, report: str) -> Path:
    """Save raw Gemini report to wiki."""
    today = datetime.now().strftime("%Y-%m-%d")
    raw_dir = WIKI_DIR / "raw" / "papers"
    raw_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{ticker}_gemini_deep_dive_{today}.md"
    filepath = raw_dir / filename

    frontmatter = f"""---
source: Gemini Deep Research Agent ({DEEP_RESEARCH_AGENT})
ticker: {ticker}
date: {today}
type: equity_research_report
---
"""
    filepath.write_text(frontmatter + report)
    print(f"✓ Raw report saved: {filepath}")
    return filepath


def extract_key_data(report: str) -> dict:
    """Use LLM to extract structured data from the Gemini report. No regex."""
    from google import genai

    if not GEMINI_API_KEY:
        # Fallback to basic regex if no key (shouldn't happen in practice)
        return {"recommendation": None, "thesis": None, "merits": [], "risks": [],
                "actionable_trigger": None, "insider_activity": None}

    client = genai.Client(api_key=GEMINI_API_KEY)

    extraction_prompt = """Extract structured data from this equity research report. Return ONLY valid JSON with these exact keys:
- "recommendation": "BUY" or "SELL" or "HOLD" (or null if not stated)
- "thesis": one sentence summarizing the core thesis (max 500 chars)
- "merits": array of strings, each a key investment merit (max 5, max 200 chars each)
- "risks": array of strings, each a key investment risk (max 5, max 200 chars each)
- "actionable_trigger": the specific catalyst event to watch for (max 300 chars, or null)
- "entry_point": specific price level, range, or condition to enter the position (e.g. "Buy below $160", "Accumulate $45-50", "Wait for pullback to 200 DMA"). If multiple levels, include all. (max 200 chars, or null)
- "insider_activity": summary of insider buying/selling sentiment (max 300 chars, or null)

Strip all citation markers like [cite: 1, 2]. Be concise. Return only the JSON object, no markdown fences."""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[{"role": "user", "parts": [{"text": extraction_prompt + "\n\n---\n\n" + report[:30000]}]}],
        )
        text = response.text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = re.sub(r'^```\w*\n?', '', text)
            text = re.sub(r'\n?```$', '', text)
        data = json.loads(text)
        # Validate/normalize
        for key in ["recommendation", "thesis", "actionable_trigger", "insider_activity", "entry_point"]:
            if key not in data:
                data[key] = None
        for key in ["merits", "risks"]:
            if key not in data or not isinstance(data[key], list):
                data[key] = []
        return data
    except Exception as e:
        print(f"   ⚠ LLM extraction failed ({e}), returning empty data", flush=True)
        return {"recommendation": None, "thesis": None, "merits": [], "risks": [],
                "actionable_trigger": None, "insider_activity": None}


def update_ticker_page(ticker: str, data: dict, report_path: Path):
    """Update the wiki ticker page with Gemini research findings."""
    ticker_path = WIKI_DIR / "tickers" / f"{ticker}.md"

    if not ticker_path.exists():
        # Create stub
        ticker_path.write_text(f"# {ticker}\n\n## Thesis\n(Gemini deep dive pending manual review)\n")
        print(f"✓ Created stub ticker page: {ticker_path}")

    with open(ticker_path, "r") as f:
        content = f.read()

    today = datetime.now().strftime("%Y-%m-%d")

    # Add Gemini deep research section if not present
    section = f"""
## Gemini Deep Research — {today}
**Recommendation:** {data.get('recommendation', 'N/A')}
**Source:** [[{report_path.name}]]

### Key Findings
"""
    if data.get("thesis"):
        section += f"**Thesis:** {data['thesis']}\n\n"

    if data.get("merits"):
        section += "**Investment Merits:**\n"
        for m in data["merits"]:
            section += f"- {m}\n"
        section += "\n"

    if data.get("risks"):
        section += "**Key Risks:**\n"
        for r in data["risks"]:
            section += f"- {r}\n"
        section += "\n"

    if data.get("insider_activity"):
        section += f"**Insider Activity:** {data['insider_activity']}\n\n"

    if data.get("actionable_trigger"):
        section += f"**Actionable Trigger:** {data['actionable_trigger']}\n"

    if data.get("entry_point"):
        section += f"**Entry Point:** {data['entry_point']}\n"

    # Check if section already exists (idempotent)
    if f"Gemini Deep Research — {today}" in content:
        print(f"✓ Ticker page already updated for {today}")
        return

    # Append section
    content += section

    with open(ticker_path, "w") as f:
        f.write(content)
    print(f"✓ Updated ticker page: {ticker_path}")


def update_conviction_shortlist(ticker: str, data: dict):
    """Add to conviction shortlist if recommendation is BUY and we have X sentiment."""
    shortlist_path = WIKI_DIR / "conviction-shortlist.md"

    # Check if we have X analyst coverage for this ticker
    analysts_dir = WIKI_DIR / "analysts"
    has_x_sentiment = False
    if analysts_dir.exists():
        for f in analysts_dir.glob("*.md"):
            content = f.read_text()
            if ticker in content:
                has_x_sentiment = True
                break

    # Only add if BUY recommendation AND we have X sentiment (full picture)
    rec = data.get("recommendation", "")
    if rec != "BUY":
        print(f"   Skipping shortlist — recommendation is {rec}, not BUY")
        return

    if not has_x_sentiment:
        print(f"   Skipping shortlist — no X analyst coverage yet")
        return

    today = datetime.now().strftime("%Y-%m-%d")

    if not shortlist_path.exists():
        header = """# Conviction Shortlist

> Tickers with both Gemini deep research (BUY) AND X analyst sentiment confirmation.
> Monitored in morning briefings for entry points and catalyst triggers.
> Last updated: {date}

## Criteria
- Gemini Deep Research: BUY recommendation
- X Signal Scanner: CONVICTION or BULLISH from 1+ tracked analyst
- Full picture: fundamental thesis + market sentiment alignment

---

""".format(date=today)
        shortlist_path.write_text(header)
    else:
        # Update date
        content = shortlist_path.read_text()
        content = re.sub(r'Last updated: .*', f'Last updated: {today}', content)
        shortlist_path.write_text(content)

    content = shortlist_path.read_text()

    # Check if already on shortlist
    if f"| **${ticker}**" in content:
        print(f"   ✓ ${ticker} already on conviction shortlist")
        return

    # Add entry
    entry_text = data.get("thesis", "See ticker page")[:100]
    trigger_text = data.get("actionable_trigger", "TBD")[:80]
    entry_price = data.get("entry_point", "TBD")[:60]
    entry = f"\n| **${ticker}** | {data.get('recommendation', 'N/A')} | {entry_text} | {entry_price} | {trigger_text} | {today} |\n"

    # Find the table or create it
    if "| **$" in content:
        # Append to existing table
        content = content.rstrip() + "\n" + entry
    else:
        # Create table header + entry
        table = "\n| Ticker | Rec | Thesis | Entry Point | Trigger | Added |\n|--------|-----|--------|-------------|---------|-------|\n" + entry
        content += table

    shortlist_path.write_text(content)
    print(f"✓ Added ${ticker} to conviction shortlist")


def update_log(ticker: str, action: str):
    """Append to wiki log."""
    log_path = WIKI_DIR / "log.md"
    today = datetime.now().strftime("%Y-%m-%d")
    entry = f"\n## [{today}] gemini_deep_research | ${ticker} — {action}\n"
    with open(log_path, "a") as f:
        f.write(entry)
    print(f"✓ Updated log.md")


def get_prices(tickers: list) -> dict:
    """Fetch live prices for a list of tickers via yfinance.

    Price lookup is useful, but it must never invalidate an otherwise completed
    Gemini report. Yahoo/yfinance is occasionally flaky from this environment, so
    failures are returned per ticker and the deep-dive pipeline continues.
    """
    try:
        import yfinance as yf
    except Exception as e:
        return {ticker: {"error": f"yfinance unavailable: {e}"} for ticker in tickers}

    prices = {}
    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            info = t.fast_info
            prices[ticker] = {
                "price": round(info.last_price, 2),
                "high_52w": round(info.year_high, 2),
                "low_52w": round(info.year_low, 2),
                "market_cap": info.market_cap,
            }
        except Exception as e:
            prices[ticker] = {"error": str(e)}
    return prices


def check_entry_points(prices: dict) -> list:
    """Check if any shortlist tickers are near their entry points. Uses LLM to parse entry prices."""
    shortlist_path = WIKI_DIR / "conviction-shortlist.md"
    if not shortlist_path.exists():
        return []

    content = shortlist_path.read_text()
    alerts = []

    # Parse table rows: | **$TICKER** | ...
    import re
    rows = re.findall(r'\|\s+\*\*\$(\w+)\*\*\s*\|', content)

    for ticker in rows:
        if ticker not in prices:
            continue
        p = prices[ticker]
        if "error" in p:
            continue

        ticker_path = WIKI_DIR / "tickers" / f"{ticker}.md"
        if not ticker_path.exists():
            continue

        current = p["price"]
        high_52w = p["high_52w"]
        low_52w = p["low_52w"]
        pct_from_low = ((current - low_52w) / low_52w) * 100 if low_52w else 0
        pct_from_high = ((high_52w - current) / high_52w) * 100 if high_52w else 0

        # Use LLM to extract the specific entry price number from the ticker page
        ticker_content = ticker_path.read_text()
        entry_price_num = _extract_entry_price_llm(ticker, ticker_content, current)

        signal = "WATCH"
        if entry_price_num:
            if current <= entry_price_num * 1.03:
                signal = "🔴 ENTRY ZONE"
            elif current <= entry_price_num * 1.10:
                signal = "🟡 APPROACHING"

        alerts.append({
            "ticker": ticker,
            "price": current,
            "high_52w": high_52w,
            "low_52w": low_52w,
            "pct_from_low": round(pct_from_low, 1),
            "pct_from_high": round(pct_from_high, 1),
            "signal": signal,
            "entry_price": entry_price_num,
        })

    return alerts


def _extract_entry_price_llm(ticker: str, ticker_content: str, current_price: float) -> float:
    """Use LLM to extract the numeric entry price from a ticker page."""
    from google import genai
    if not GEMINI_API_KEY:
        return None

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[{"role": "user", "parts": [{"text":
                f"From this ticker page for ${ticker}, extract the specific ENTRY PRICE mentioned in "
                f"the 'Entry Point' field under 'Gemini Deep Research'. Current price is ${current_price}. "
                f"Return ONLY a number (e.g. 160.50) or null if no clear entry price exists. "
                f"No explanation, just the number.\n\n"
                + ticker_content[-3000:]  # last 3k chars most likely has the research section
            }]}],
        )
        text = response.text.strip().replace("$", "").replace(",", "")
        val = float(text)
        if 1 < val < 100000:
            return round(val, 2)
    except Exception:
        pass
    return None


def price_check():
    """Check prices for all conviction shortlist tickers and save snapshot."""
    shortlist_path = WIKI_DIR / "conviction-shortlist.md"
    if not shortlist_path.exists() or "| **$" not in shortlist_path.read_text():
        print("No tickers on conviction shortlist.")
        return []

    # Extract tickers from shortlist table
    content = shortlist_path.read_text()
    import re
    tickers = re.findall(r'\|\s+\*\*\$(\w+)\*\*\s*\|', content)
    if not tickers:
        print("No tickers found in shortlist table.")
        return []

    print(f"💰 Checking prices for {len(tickers)} tickers...", flush=True)
    prices = get_prices(tickers)

    alerts = check_entry_points(prices)

    # Save price snapshot
    today = datetime.now().strftime("%Y-%m-%d")
    daily_dir = WIKI_DIR / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = daily_dir / f"prices_{today}.md"

    snapshot = f"# Price Snapshot — {today}\n\n"
    snapshot += "| Ticker | Price | 52w High | 52w Low | % From Low | % From High | Signal |\n"
    snapshot += "|--------|-------|----------|---------|------------|-------------|--------|\n"
    for a in alerts:
        snapshot += f"| ${a['ticker']} | ${a['price']} | ${a['high_52w']} | ${a['low_52w']} | {a['pct_from_low']}% | {a['pct_from_high']}% | {a['signal']} |\n"

    snapshot_path.write_text(snapshot)
    print(f"✓ Saved price snapshot: {snapshot_path}")

    # Print alerts
    for a in alerts:
        ep = f"${a['entry_price']}" if a["entry_price"] else "See ticker page"
        print(f"   ${a['ticker']}: ${a['price']} — {a['signal']} (entry: {ep})")

    return alerts


def auto_pick_tickers(max_tickers: int = 5) -> list:
    """Auto-select tickers that need deep research based on signal strength.

    Guardrails:
    - Only select real wiki tickers or cashtagged tickers from daily briefs.
    - Skip mega-caps/ETFs/common acronyms; this job is for asymmetric discovery.
    - Avoid broad ALLCAPS regex false positives from analyst prose.
    """
    candidates = []
    import re

    tickers_dir = WIKI_DIR / "tickers"
    wiki_tickers = {f.stem.upper() for f in tickers_dir.glob("*.md")} if tickers_dir.exists() else set()
    shortlist_path = WIKI_DIR / "conviction-shortlist.md"
    manually_tracked = set(re.findall(r'\$([A-Z]{1,6})\b', shortlist_path.read_text(errors="replace"))) if shortlist_path.exists() else set()

    def parse_market_cap_usd(ticker):
        """Best-effort parse from ticker page header. Returns USD-ish dollars or None."""
        f = tickers_dir / f"{ticker}.md"
        if not f.exists():
            return None
        text = f.read_text(errors="replace")[:2500]
        m = re.search(r'\*\*Market Cap:\*\*\s*~?\$?([0-9,.]+)\s*([BMK])?', text, re.I)
        if not m:
            return None
        value = float(m.group(1).replace(',', ''))
        suffix = (m.group(2) or '').upper()
        if suffix == 'B':
            value *= 1_000_000_000
        elif suffix == 'M':
            value *= 1_000_000
        elif suffix == 'K':
            value *= 1_000
        return value

    def add_candidate(ticker, source, priority):
        ticker = ticker.upper().lstrip("$")
        if ticker in AUTO_PICK_EXCLUDE_TICKERS:
            return
        # Require an existing ticker page or manual shortlist/watchlist inclusion before spending Gemini budget.
        # New cashtag-only names should get a cheap stub/screen first in the daily research job.
        if ticker not in wiki_tickers and ticker not in manually_tracked:
            return
        mcap = parse_market_cap_usd(ticker)
        scanner_driven = any(s in source.lower() for s in ("signal", "convergence", "analyst-profile"))
        if scanner_driven and ticker not in manually_tracked and mcap and mcap > AUTO_PICK_MAX_DISCOVERY_MCAP_USD:
            # Great company, wrong hunt. Large caps can be core holds, but they are not where this job finds 3-5x alpha.
            return
        candidates.append({"ticker": ticker, "source": source, "priority": priority, "mcap": mcap})

    # Source 1: Recent daily briefs / signal summaries. Use cashtags only.
    daily_candidates = []
    daily_roots = [WIKI_DIR / "daily", WIKI_DIR / "daily" / "briefs"]
    for daily_dir in daily_roots:
        if not daily_dir.exists():
            continue
        daily_candidates.extend(sorted(daily_dir.glob("*.md"), reverse=True)[:5])
    for f in daily_candidates[:10]:
        content = f.read_text(errors="replace")
        for line in content.splitlines():
            if "CONVICTION" in line or "convergence" in line.lower() or "Cross-validated" in line:
                for ticker in re.findall(r'\$([A-Z]{1,5})\b', line):
                    add_candidate(ticker, "CONVICTION/convergence signal", 3)

    # Source 2: Ticker pages with conviction language but no Gemini deep research section.
    if tickers_dir.exists():
        for f in tickers_dir.glob("*.md"):
            content = f.read_text(errors="replace")
            ticker = f.stem.upper()
            has_conviction = "conviction" in content.lower() or "CONVICTION" in content
            has_research = "Gemini Deep Research" in content
            if has_conviction and not has_research:
                add_candidate(ticker, "conviction page, no Gemini research", 2)
            elif has_conviction and has_research:
                date_match = re.search(r'Gemini Deep Research — (\d{4}-\d{2}-\d{2})', content)
                if date_match:
                    research_date = datetime.strptime(date_match.group(1), "%Y-%m-%d")
                    days_old = (datetime.now() - research_date).days
                    if days_old > 14:
                        add_candidate(ticker, f"research stale ({days_old}d)", 1)

    # Source 3: Convergence in analyst profiles. Only count explicit cashtags or linked ticker pages.
    analysts_dir = WIKI_DIR / "analysts"
    if analysts_dir.exists():
        ticker_analyst_count = {}
        for f in analysts_dir.glob("*.md"):
            content = f.read_text(errors="replace")
            found = set(re.findall(r'\$([A-Z]{1,5})\b', content))
            found.update(t for t in wiki_tickers if f"tickers/{t}.md" in content or f"[[{t}" in content)
            for t in found:
                if t not in AUTO_PICK_EXCLUDE_TICKERS:
                    ticker_analyst_count[t] = ticker_analyst_count.get(t, 0) + 1
        for ticker, count in ticker_analyst_count.items():
            if count >= 2:
                ticker_path = tickers_dir / f"{ticker}.md"
                has_research = ticker_path.exists() and "Gemini Deep Research" in ticker_path.read_text(errors="replace")
                if not has_research:
                    add_candidate(ticker, f"analyst-profile convergence ({count} analysts)", 3)

    seen = set()
    unique = []
    for c in sorted(candidates, key=lambda x: (-x["priority"], x["ticker"])):
        if c["ticker"] not in seen:
            seen.add(c["ticker"])
            unique.append(c)

    selected = unique[:max_tickers]
    print(f"📋 Auto-selected {len(selected)} tickers for deep research:")
    for c in selected:
        print(f"   ${c['ticker']} — {c['source']} (priority {c['priority']})")

    if len(unique) > max_tickers:
        print(f"   ... {len(unique) - max_tickers} more candidates deferred to next week")

    return selected


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: python3 ticker_deep_dive.py TICKER [--poll-interval 15] [--max-wait 600] [--update-only] [--max] [--skip-price-check]")
        print("       python3 ticker_deep_dive.py --price-check")
        print("       python3 ticker_deep_dive.py --auto-pick [--max-tickers 5]")
        sys.exit(1)

    # Subcommands
    if args[0] == "--price-check":
        alerts = price_check()
        # Output JSON for downstream consumption
        print(json.dumps(alerts, indent=2))
        sys.exit(0)

    if args[0] == "--auto-pick":
        max_tickers = 5
        i = 1
        while i < len(args):
            arg = args[i]
            if arg in ("--max-tickers", "--max") and i + 1 < len(args) and not args[i + 1].startswith("--"):
                max_tickers = int(args[i + 1])
                i += 2
            else:
                i += 1
        selected = auto_pick_tickers(max_tickers)
        print(json.dumps([c["ticker"] for c in selected]))
        sys.exit(0)

    ticker = args[0].upper().lstrip("$")
    poll_interval = 15
    max_wait = 600
    update_only = False
    use_max = False
    skip_price_check = False

    i = 1
    while i < len(args):
        arg = args[i]
        next_arg = args[i + 1] if i + 1 < len(args) else ""
        if arg == "--poll-interval" and next_arg and not next_arg.startswith("--"):
            poll_interval = int(next_arg)
            i += 2
        elif arg == "--max-wait" and next_arg and not next_arg.startswith("--"):
            max_wait = int(next_arg)
            i += 2
        elif arg == "--update-only":
            update_only = True
            i += 1
        elif arg == "--max":
            use_max = True
            i += 1
        elif arg == "--skip-price-check":
            skip_price_check = True
            i += 1
        else:
            i += 1

    if not GEMINI_API_KEY and not update_only:
        print(json.dumps({"error": "No GEMINI_API_KEY found in ~/.hermes/.env"}))
        sys.exit(1)

    print(f"{'='*60}")
    print(f"  TICKER DEEP DIVE: ${ticker}")
    print(f"{'='*60}\n")

    if update_only:
        # Find most recent Gemini report for this ticker
        raw_dir = WIKI_DIR / "raw" / "papers"
        reports = sorted(raw_dir.glob(f"{ticker}_gemini_deep_dive_*.md"), reverse=True)
        if not reports:
            print(f"No existing Gemini report for ${ticker}. Run without --update-only first.")
            sys.exit(1)
        report_path = reports[0]
        report = report_path.read_text()
        # Strip frontmatter for data extraction
        report_body = re.sub(r'^---.*?---\n', '', report, flags=re.DOTALL)
        print(f"Using existing report: {report_path.name}")
    else:
        # Run Gemini Deep Research
        report = run_gemini_deep_research(ticker, poll_interval, max_wait, use_max=use_max)
        if not report:
            print("✗ No report received. Exiting.")
            sys.exit(1)

        # Save raw report
        report_path = save_raw_report(ticker, report)
        report_body = report

    # Extract structured data
    data = extract_key_data(report_body)
    print(f"\n📊 Extracted data:")
    print(f"   Recommendation: {data.get('recommendation', 'N/A')}")
    print(f"   Thesis: {data.get('thesis', 'N/A')[:100]}...")
    print(f"   Merits: {len(data.get('merits', []))} found")
    print(f"   Risks: {len(data.get('risks', []))} found")
    print(f"   Trigger: {data.get('actionable_trigger', 'N/A')[:100]}...")
    print(f"   Entry: {data.get('entry_point', 'N/A')}")
    print(f"   Insider: {data.get('insider_activity', 'N/A')[:100]}...")

    # Update wiki
    print(f"\n📝 Updating wiki...")
    update_ticker_page(ticker, data, report_path)
    update_conviction_shortlist(ticker, data)
    update_log(ticker, f"Gemini deep research completed. Rec: {data.get('recommendation', 'N/A')}")

    if skip_price_check:
        print(f"\n💰 Price check skipped (--skip-price-check).")
        price_data = {}
    else:
        # Price check after deep dive
        print(f"\n💰 Fetching current price...")
        prices = get_prices([ticker])
        price_data = prices.get(ticker, {})

        if price_data and "error" not in price_data:
            p = price_data
            print(f"   ${ticker} @ ${p['price']} (52w: ${p['low_52w']}-${p['high_52w']})")
            if data.get("entry_point"):
                entry_nums = re.findall(r'\$(\d+(?:\.\d+)?)', data["entry_point"])
                for ep in entry_nums:
                    ep_f = float(ep)
                    if ep_f > 10:
                        diff = ((p["price"] - ep_f) / ep_f) * 100
                        status = "✅ AT ENTRY" if abs(diff) < 3 else f"{'above' if diff > 0 else 'below'} by {abs(diff):.1f}%"
                        print(f"   vs entry ${ep_f}: {status}")
        elif price_data and "error" in price_data:
            print(f"   ⚠ Price lookup failed: {price_data['error']}")

    # Output structured summary
    output = {
        "ticker": ticker,
        "current_price": price_data.get("price") if price_data and "error" not in price_data else None,
        "high_52w": price_data.get("high_52w") if price_data and "error" not in price_data else None,
        "low_52w": price_data.get("low_52w") if price_data and "error" not in price_data else None,
        "recommendation": data.get("recommendation"),
        "thesis": data.get("thesis"),
        "merits": data.get("merits", []),
        "risks": data.get("risks", []),
        "actionable_trigger": data.get("actionable_trigger"),
        "entry_point": data.get("entry_point"),
        "insider_activity": data.get("insider_activity"),
        "report_path": str(report_path),
        "date": datetime.now().strftime("%Y-%m-%d"),
    }
    print(f"\n{'='*60}")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
