#!/usr/bin/env python3
"""
Research Feed Ingestion Pipeline

Fetches RSS/Atom feeds from curated tech strategy, SaaS, macro, and asymmetric
research sources. Extracts titles, summaries, links, and tags them against
the configured watchlist for cross-referencing.

Usage:
    python3 fetch_research_feeds.py                    # Fetch all sources
    python3 fetch_research_feeds.py --sources tunguz   # Fetch specific source
    python3 fetch_research_feeds.py --since 7           # Articles from last N days
    python3 fetch_research_feeds.py --format compact    # Compact text output
"""

import argparse
import html as html_lib
import json
import re
import sys
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ─── CONFIGURATION ───────────────────────────────────────────────────────────

from private_config import load_holdings

WATCHLIST = set(load_holdings())

COMPANY_ALIASES = {
    "meta": "META", "facebook": "META", "microsoft": "MSFT", "google": "GOOG",
    "alphabet": "GOOG", "amazon": "AMZN", "apple": "AAPL", "nvidia": "NVDA",
    "tesla": "TSLA", "netflix": "NFLX", "coinbase": "COIN", "coin": "COIN",
    "robinhood": "HOOD", "hood": "HOOD", "reddit": "RDDT", "palantir": "PLTR",
    "snowflake": "SNOW", "crowdstrike": "CRWD", "datadog": "DDOG",
    "zscaler": "ZS", "mongodb": "MDB", "cloudflare": "NET", "unity": "U",
    "uber": "UBER", "lyft": "LYFT", "shopify": "SHOP", "block": "SQ",
    "paypal": "PYPL", "snap": "SNAP", "pinterest": "PINS", "disney": "DIS",
    "salesforce": "CRM", "servicenow": "NOW", "intuit": "INTU", "okta": "OKTA",
    "palo alto": "PANW", "oracle": "ORCL", "adobe": "ADBE", "amd": "AMD",
    "arm": "ARM", "broadcom": "AVGO", "marvell": "MRVL", "intel": "INTC",
    "taiwan semiconductor": "TSEM", "tsmc": "TSEM", "asml": "ASML",
    "klac": "KLAC", "lam research": "LRCX", "applied materials": "AMAT",
    "micron": "MU", "western digital": "WDC", "seagate": "STX",
}

RESEARCH_SOURCES = {
    # ─── Tech Strategy / SaaS (Tier 1) ───────────────────────────────────
    "tunguz": {
        "name": "Tomasz Tunguz",
        "feed_url": "",  # Ghost site — no RSS, uses HTML scraping
        "scrape_url": "https://www.tomtunguz.com/",
        "scrape_selector": "article",
        "category": "tech_strategy",
        "tier": 1,
        "description": "VC at Theory Ventures. Daily SaaS/AI analysis with data-driven theses.",
    },
    "clouded_judgement": {
        "name": "Clouded Judgement",
        "feed_url": "https://cloudedjudgement.substack.com/feed",
        "category": "saas",
        "tier": 1,
        "description": "Jamin Ball. Weekly data-driven SaaS/cloud infrastructure analysis.",
    },
    "stratechery": {
        "name": "Stratechery",
        "feed_url": "https://stratechery.com/feed/",
        "category": "tech_strategy",
        "tier": 1,
        "description": "Ben Thompson. Tech strategy + platform economics. Free weekly.",
    },
    "a16z": {
        "name": "a16z",
        "feed_url": "https://www.a16z.news/feed",
        "category": "vc_thesis",
        "tier": 1,
        "description": "Andreessen Horowitz. Big ideas, market sizing, tech trends.",
    },
    # ─── Strong Signal (Tier 2) ──────────────────────────────────────────
    "the_diff": {
        "name": "The Diff",
        "feed_url": "https://thediff.co/feed/",
        "category": "finance_tech",
        "tier": 2,
        "description": "Byrne Hobart. Financial analysis meets tech strategy.",
    },
    "not_boring": {
        "name": "Not Boring",
        "feed_url": "https://notboring.substack.com/feed",
        "category": "tech_business",
        "tier": 2,
        "description": "Packy McCormick. Tech/business narratives, emerging trends.",
    },
    "import_ai": {
        "name": "Import AI",
        "feed_url": "https://importai.substack.com/feed",
        "category": "ai",
        "tier": 2,
        "description": "Jack Clark. AI industry + policy landscape. Weekly.",
    },
    "latent_space": {
        "name": "Latent Space",
        "feed_url": "https://latent.space/feed.xml",
        "category": "ai_infra",
        "tier": 2,
        "description": "Swyx & Alessio. AI engineering + infrastructure.",
    },
    # ─── Daily News (Tier 2) ────────────────────────────────────────────
    "sherwood": {
        "name": "Sherwood News",
        "feed_url": "",  # No RSS — Robinhood-backed site
        "scrape_url": "https://sherwood.news/",
        "scrape_selector": "a[href*='/markets/'], a[href*='/tech/'], a[href*='/business/'], a[href*='/power/']",
        "scrape_type": "sherwood",
        "category": "daily_news",
        "tier": 2,
        "description": "Robinhood-backed. Daily markets, tech, business news with substance. Deep dives + real-time market movers.",
    },
    # ─── Macro / Asymmetric (Tier 3) ────────────────────────────────────
    "bear_cave": {
        "name": "The Bear Cave",
        "feed_url": "https://thebearcave.substack.com/feed",
        "category": "short_selling",
        "tier": 3,
        "description": "Short seller research. Asymmetric bear thesis.",
    },
    "cb_insights": {
        "name": "CB Insights",
        "feed_url": "https://www.cbinsights.com/blog/rss/",
        "category": "tech_trends",
        "tier": 3,
        "description": "Data-driven tech trends, emerging categories, funding data.",
    },
    "fwriter": {
        "name": "Moody / fwriter",
        "feed_url": "https://fwriter.substack.com/feed",
        "category": "asymmetric_research",
        "tier": 2,
        "description": "Substack stock research with photonics/industrial bottleneck angles; user-requested daily scan source.",
    },
    # ─── Experimental / Crowd Narrative Sources ──────────────────────────
    "simplywall_narratives": {
        "name": "Simply Wall St Community Narratives",
        "feed_url": "",
        "scrape_url": "https://simplywall.st/community/narratives/us",
        "scrape_type": "simplywall_narratives",
        "category": "crowd_valuation",
        "tier": 4,
        "enabled_by_default": False,
        "description": "User-submitted ticker narratives with fair-value estimates and engagement. Idea/sentiment source only; never primary evidence.",
    },
}

USER_AGENT = "Mozilla/5.0 (compatible; ResearchFeedBot/1.0)"


# ─── RSS PARSING ─────────────────────────────────────────────────────────────

def fetch_feed(feed_url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(feed_url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_rss(xml_content: str) -> list:
    articles = []
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return articles

    channel = root.find("channel")
    if channel is not None:
        for item in channel.findall("item"):
            article = _parse_rss_item(item)
            if article:
                articles.append(article)
        return articles

    if root.tag.endswith("}feed") or root.tag == "feed":
        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0] + "}"
        for entry in root.findall(f"{ns}entry"):
            article = _parse_atom_entry(entry, ns)
            if article:
                articles.append(article)
        return articles

    return articles


def _parse_rss_item(item):
    def text(tag):
        el = item.find(tag)
        return el.text.strip() if el is not None and el.text else ""

    def text_html(tag):
        el = item.find(tag)
        if el is None:
            return ""
        return "".join(el.itertext()).strip()

    title = text("title")
    link_el = item.find("link")
    link = link_el.get("href", "") if link_el is not None else text("link")
    description = text_html("description")
    content = text_html("{http://purl.org/rss/1.0/modules/content/}encoded")
    pub_date = text("pubDate")

    if not title and not link:
        return None

    body = content or description

    return {
        "title": title,
        "link": link,
        "summary": _clean_html(body)[:2000],
        "published": _parse_date(pub_date),
    }


def _parse_atom_entry(entry, ns):
    def text(tag):
        el = entry.find(f"{ns}{tag}")
        return el.text.strip() if el is not None and el.text else ""

    def text_html(tag):
        el = entry.find(f"{ns}{tag}")
        if el is None:
            return ""
        return "".join(el.itertext()).strip()

    title = text("title")
    link_el = entry.find(f"{ns}link[@rel='alternate']") or entry.find(f"{ns}link")
    link = link_el.get("href", "") if link_el is not None else ""
    summary = text_html("summary")
    content = text_html("content")
    published = text("published") or text("updated")

    if not title and not link:
        return None

    body = content or summary

    return {
        "title": title,
        "link": link,
        "summary": _clean_html(body)[:2000],
        "published": _parse_date(published),
    }


# ─── TEXT PROCESSING ─────────────────────────────────────────────────────────

def _clean_html(html):
    text = re.sub(r"<[^>]+>", " ", html)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_date(date_str):
    if not date_str:
        return None
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%B %d, %Y",
        "%b %d, %Y",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue
    return date_str


def extract_tickers(title, summary):
    text = f"{title} {summary}".lower()
    tickers = set()

    cashtags = re.findall(r"\$([A-Z]{1,5})\b", f"{title} {summary}")
    for t in cashtags:
        if t in WATCHLIST:
            tickers.add(t)

    for alias, ticker in COMPANY_ALIASES.items():
        if ticker and re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text):
            tickers.add(ticker)

    return sorted(tickers)


def extract_themes(title, summary):
    text = f"{title} {summary}".lower()
    themes = []

    theme_keywords = {
        "ai_infra": ["gpu", "compute", "inference", "training", "data center", "chip", "nvidia", "semiconductor"],
        "ai_apps": ["ai model", "llm", "foundation model", "gpt", "claude", "gemini", "ai agent", "copilot", "coding"],
        "saas": ["saas", "subscription", "arr", "nrr", "net retention", "rule of 40", "cloud"],
        "fintech": ["fintech", "payment", "banking", "neobank", "crypto", "defi", "bitcoin", "token"],
        "macro": ["fed", "interest rate", "treasury", "inflation", "gdp", "recession", "tariff", "fiscal"],
        "platform": ["platform", "aggregation", "moat", "network effect", "marketplace", "ecosystem"],
        "m_a": ["acquisition", "merger", "ipo", "spinoff", "buyout"],
        "regulation": ["regulation", "antitrust", "sec", "compliance", "policy", "legislation"],
        "supply_chain": ["supply chain", "bottleneck", "semiconductor", "fabrication", "foundry"],
        "consumer_tech": ["consumer", "social media", "gaming", "streaming", "subscription"],
    }

    for theme, keywords in theme_keywords.items():
        if any(kw in text for kw in keywords):
            themes.append(theme)

    return themes


# ─── MAIN PIPELINE ───────────────────────────────────────────────────────────

def scrape_sherwood(html, since_days=7):
    """Scrape Sherwood News — a link-heavy site with headings + summaries inline."""
    articles = []
    seen_urls = set()

    # Sherwood structure: <a href="/markets/slug"> containing <h2>title</h2> + <p>summary</p>
    # Also deep dive links: <a href="/tech/slug"> with heading + paragraph
    # Pattern: find all <a> tags with article links
    link_pattern = re.compile(
        r'<a\s[^>]*href="(/(?:markets|tech|business|power|crypto|world)/[^"]+)"[^>]*>(.*?)</a>',
        re.DOTALL | re.IGNORECASE
    )

    for match in link_pattern.finditer(html):
        href = match.group(1)
        full_url = f"https://sherwood.news{href}"
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        block = match.group(2)

        # Extract heading (h2 or h3)
        heading_match = re.search(
            r'<h[2-3][^>]*>(.*?)</h[2-3]>',
            block, re.DOTALL | re.IGNORECASE
        )
        title = _clean_html(heading_match.group(1)).strip() if heading_match else ""

        # Extract first paragraph
        para_match = re.search(
            r'<p[^>]*>(.*?)</p>',
            block, re.DOTALL | re.IGNORECASE
        )
        summary = _clean_html(para_match.group(1)).strip() if para_match else ""

        # Sherwood includes tickers inline like "NvidiaNVDA $208.10 (4.28%)"
        # and links to robinhood stocks — extract those
        ticker_matches = re.findall(r'([A-Z]{2,5})\s*\$', block)
        inline_tickers = [t for t in ticker_matches if t in WATCHLIST or len(t) >= 3]

        if title:
            articles.append({
                "title": title,
                "link": full_url,
                "summary": summary[:2000],
                "published": None,  # Sherwood homepage doesn't have dates inline
                "_inline_tickers": inline_tickers,
            })

    return articles


def scrape_simplywall_narratives(html, since_days=7):
    """Scrape Simply Wall St community narrative cards.

    Treat as crowd-sourced idea/sentiment input, not validated research.
    The page is server-rendered enough for lightweight scraping, but class names
    are noisy; anchor/h3/summary/FV patterns are more stable than CSS selectors.
    """
    articles = []
    seen_urls = set()

    pattern = re.compile(
        r'<a\s+href="(?P<href>/community/narratives/[^\"]+)"[^>]*>'
        r'(?P<body>.*?)</a>',
        re.DOTALL | re.IGNORECASE,
    )

    for match in pattern.finditer(html):
        href = match.group("href")
        if href in {"/community/narratives", "/community/narratives/us"}:
            continue
        if "#fast-comments" in href or href in seen_urls:
            continue
        seen_urls.add(href)

        body = match.group("body")
        title_match = re.search(r'<h3[^>]*>(.*?)</h3>', body, re.DOTALL | re.IGNORECASE)
        if not title_match:
            continue
        title = _clean_html(title_match.group(1)).strip()

        summary_match = re.search(
            r'<div[^>]*class="[^"]*line-clamp-4[^"]*"[^>]*>(.*?)</div>',
            body,
            re.DOTALL | re.IGNORECASE,
        )
        summary = _clean_html(summary_match.group(1)).strip() if summary_match else ""

        tail = html[match.end():match.end() + 3500]
        tail_text = _clean_html(tail)
        fv = re.search(r'((?:US|CA)?\$[\d,.]+|€[\d,.]+)\s+FV', tail_text)
        discount = re.search(r'([\d.]+%)\s+(undervalued|overvalued)', tail_text, re.IGNORECASE)
        views = re.search(r'([\d.]+k?|[\d,]+)\s+users have viewed', tail_text, re.IGNORECASE)
        likes = re.search(r'([\d,]+)\s+users have liked', tail_text, re.IGNORECASE)
        comments = re.search(r'([\d,]+)\s+users have commented', tail_text, re.IGNORECASE)
        updated = re.search(r'(\d+\s+(?:hour|day|week|month|year)s?\s+ago)\s+author updated', tail_text, re.IGNORECASE)

        metrics = []
        if fv:
            metrics.append(f"author FV {fv.group(1)}")
        if discount:
            metrics.append(f"{discount.group(1)} {discount.group(2).lower()}")
        if views:
            metrics.append(f"views {views.group(1)}")
        if likes:
            metrics.append(f"likes {likes.group(1)}")
        if comments:
            metrics.append(f"comments {comments.group(1)}")
        if updated:
            metrics.append(f"updated {updated.group(1)}")
        if metrics:
            summary = (summary + " | " if summary else "") + "SWS crowd metrics: " + "; ".join(metrics)

        ticker_from_url = None
        url_ticker_match = re.search(r'/(?:nasdaq|nyse|nysearca|amex)-([a-z0-9.]+)/', href, re.IGNORECASE)
        if url_ticker_match:
            ticker_from_url = url_ticker_match.group(1).upper()

        articles.append({
            "title": html_lib.unescape(title),
            "link": f"https://simplywall.st{href}",
            "summary": html_lib.unescape(summary)[:2000],
            "published": None,
            "_inline_tickers": [ticker_from_url] if ticker_from_url else [],
        })

    return articles


def scrape_html(url, since_days=7, scrape_type="article"):
    """Scrape articles from HTML pages (for sites without RSS)."""
    articles = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return articles

    if scrape_type == "sherwood":
        return scrape_sherwood(html, since_days)
    if scrape_type == "simplywall_narratives":
        return scrape_simplywall_narratives(html, since_days)

    # Default: Ghost blog / article-based scraping
    # Pattern: find all article blocks, then extract heading + link + summary
    article_pattern = re.compile(
        r'<article[^>]*>(.*?)</article>',
        re.DOTALL | re.IGNORECASE
    )

    for match in article_pattern.finditer(html):
        block = match.group(1)

        # Extract link from first <a> with href
        link_match = re.search(r'href="([^"]+)"', block)
        link = link_match.group(1) if link_match else ""

        # Extract heading text
        heading_match = re.search(
            r'<h[1-3][^>]*>(.*?)</h[1-3]>',
            block, re.DOTALL | re.IGNORECASE
        )
        title = ""
        if heading_match:
            title = _clean_html(heading_match.group(1)).strip()

        # Extract first paragraph as summary
        para_match = re.search(
            r'<p[^>]*>(.*?)</p>',
            block, re.DOTALL | re.IGNORECASE
        )
        summary = ""
        if para_match:
            summary = _clean_html(para_match.group(1)).strip()

        # Extract date from text
        date_match = re.search(
            r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}|Apr\s+\d{1,2},?\s+\d{4}|Jan\s+\d{1,2},?\s+\d{4}|Feb\s+\d{1,2},?\s+\d{4}|Mar\s+\d{1,2},?\s+\d{4}|May\s+\d{1,2},?\s+\d{4}|Jun\s+\d{1,2},?\s+\d{4}|Jul\s+\d{1,2},?\s+\d{4}|Aug\s+\d{1,2},?\s+\d{4}|Sep\s+\d{1,2},?\s+\d{4}|Oct\s+\d{1,2},?\s+\d{4}|Nov\s+\d{1,2},?\s+\d{4}|Dec\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2}',
            block
        )
        published = _parse_date(date_match.group(0)) if date_match else None

        if title or link:
            articles.append({
                "title": title,
                "link": link,
                "summary": summary[:2000],
                "published": published,
            })

    return articles


def fetch_source(source_id, source_config, since_days=7):
    result = {
        "source_id": source_id,
        "name": source_config["name"],
        "category": source_config["category"],
        "tier": source_config["tier"],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "articles": [],
        "error": None,
    }

    try:
        # HTML scraping fallback for sites without RSS
        if source_config.get("scrape_url"):
            articles = scrape_html(
                source_config["scrape_url"],
                since_days,
                scrape_type=source_config.get("scrape_type", "article"),
            )
        else:
            xml = fetch_feed(source_config["feed_url"])
            articles = parse_rss(xml)

        if since_days:
            cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
            filtered = []
            for a in articles:
                if a["published"]:
                    try:
                        pub = datetime.fromisoformat(a["published"])
                        if pub >= cutoff:
                            filtered.append(a)
                        continue
                    except (ValueError, TypeError):
                        pass
                filtered.append(a)
            articles = filtered

        for a in articles:
            a["tickers"] = extract_tickers(a["title"], a["summary"])
            # Merge inline tickers from scrapers (e.g., Sherwood's embedded stock refs)
            if a.get("_inline_tickers"):
                for t in a["_inline_tickers"]:
                    if t not in a["tickers"]:
                        a["tickers"].append(t)
                a["tickers"].sort()
                a.pop("_inline_tickers", None)
            a["themes"] = extract_themes(a["title"], a["summary"])

        result["articles"] = articles

    except urllib.error.HTTPError as e:
        result["error"] = f"HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        result["error"] = f"URL error: {e.reason}"
    except Exception as e:
        result["error"] = str(e)

    return result


def format_compact(results):
    lines = []
    total_articles = 0
    ticker_hits = {}

    for r in results:
        tier_emoji = {1: "🔥", 2: "🟢", 3: "🔍"}.get(r["tier"], "📄")
        lines.append(f"{tier_emoji} **{r['name']}** ({r['category']})")

        if r["error"]:
            lines.append(f"  ⚠️ {r['error']}")
            lines.append("")
            continue

        if not r["articles"]:
            lines.append("  No new articles this period.")
            lines.append("")
            continue

        for a in r["articles"]:
            total_articles += 1
            date_str = ""
            if a["published"]:
                try:
                    dt = datetime.fromisoformat(a["published"])
                    date_str = f" ({dt.strftime('%b %d')})"
                except (ValueError, TypeError):
                    pass

            ticker_str = ""
            if a["tickers"]:
                ticker_str = f" [{' '.join('$' + t for t in a['tickers'])}]"
                for t in a["tickers"]:
                    ticker_hits[t] = ticker_hits.get(t, 0) + 1

            title = a["title"]
            if len(title) > 120:
                title = title[:117] + "..."

            lines.append(f"  • {title}{date_str}{ticker_str}")
            if a["link"]:
                lines.append(f"    {a['link']}")

            summary_line = a["summary"][:150].strip()
            if summary_line and len(a["summary"]) > 10:
                lines.append(f"    > {summary_line}...")

        lines.append("")

    lines.append("---")
    lines.append(f"**Total:** {total_articles} articles from {len(results)} sources")

    if ticker_hits:
        sorted_tickers = sorted(ticker_hits.items(), key=lambda x: -x[1])
        ticker_line = "  ".join(f"${t}({c}x)" for t, c in sorted_tickers[:10])
        lines.append(f"**Watchlist hits:** {ticker_line}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Fetch research feeds")
    parser.add_argument("--sources", nargs="*", help="Specific source IDs (default: all)")
    parser.add_argument("--since", type=int, default=7, help="Articles from last N days (default: 7)")
    parser.add_argument("--format", choices=["json", "compact"], default="json", help="Output format")
    parser.add_argument("--output", help="Output file path (default: stdout)")
    args = parser.parse_args()

    if args.sources:
        sources = {k: v for k, v in RESEARCH_SOURCES.items() if k in args.sources}
        if not sources:
            print(f"Unknown sources: {args.sources}", file=sys.stderr)
            print(f"Available: {', '.join(RESEARCH_SOURCES.keys())}", file=sys.stderr)
            sys.exit(1)
    else:
        sources = {k: v for k, v in RESEARCH_SOURCES.items() if v.get("enabled_by_default", True)}

    results = []
    for source_id, config in sources.items():
        result = fetch_source(source_id, config, since_days=args.since)
        results.append(result)
        time.sleep(0.5)

    if args.format == "compact":
        output = format_compact(results)
    else:
        output = json.dumps({
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "period_days": args.since,
            "sources_count": len(results),
            "total_articles": sum(len(r["articles"]) for r in results),
            "results": results,
        }, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output)
        print(f"Written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
