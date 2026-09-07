#!/usr/bin/env python3
"""
Fetch recent tweets from @aleabitoreddit (Serenity) via X API v2.
Extracts cashtags, classifies by signal strength, and outputs structured JSON
for the daily stock signal briefing.

Categories:
- CONVICTION: Repeated mentions (3+), detailed thesis posts, or high engagement
- BULLISH: Mentioned with positive sentiment / catalyst language
- SPECULATIVE: Mentioned in speculative context (small cap, "bet", early stage)
- SUPPLY_CHAIN: Part of a supply chain mapping (arrows, pass-through analysis)
- RADAR: Mentioned but no strong thesis yet

Usage:
    python3 fetch_aleabitoreddit.py [--hours 24] [--max 50]
"""
from automation_paths import configured_text
import json
import os
import re
import sys
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict

# Load env from Hermes home
env_path = Path(os.path.expanduser(configured_text('${ANALYST_HERMES_HOME}/.env')))
env_vars = {}
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            env_vars[key.strip()] = value.strip().strip('"').strip("'")

BEARER_TOKEN = env_vars.get("X_BEARER_TOKEN", "")
USER_ID = "1940360837547565056"  # @aleabitoreddit
USERNAME = "aleabitoreddit"


def fetch_tweets(bearer, user_id, max_results=50):
    """Fetch recent tweets excluding retweets and replies."""
    url = f"https://api.x.com/2/users/{user_id}/tweets"
    params = urllib.parse.urlencode({
        "max_results": min(max_results, 100),
        "tweet.fields": "created_at,public_metrics,entities,note_tweet",
        "exclude": "retweets,replies",
    })
    req = urllib.request.Request(
        f"{url}?{params}",
        headers={"Authorization": f"Bearer {bearer}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return data.get("data", [])
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.reason}", "detail": e.read().decode()[:300]}
    except Exception as e:
        return {"error": str(e)}


def extract_cashtags(tweet):
    """Extract unique cashtags from tweet entities and text."""
    tags = set()
    # From entities (API-parsed)
    for cashtag in tweet.get("entities", {}).get("cashtags", []):
        tags.add(cashtag["tag"].upper())
    # Fallback: regex from text
    text = tweet.get("text", "")
    tags.update(m.upper() for m in re.findall(r'\$([A-Z]{1,5})\b', text))
    return sorted(tags)


def get_full_text(tweet):
    """Get full tweet text, preferring note_tweet for long-form."""
    # note_tweet has the full text for tweets > 280 chars
    nt = tweet.get("note_tweet")
    if nt and "text" in nt:
        return nt["text"]
    return tweet.get("text", "")


def classify_ticker(ticker, tweets_with_ticker):
    """
    Classify a ticker based on how it's discussed across tweets.
    Returns (category, reasons, conviction_score).
    """
    reasons = []
    score = 0
    texts = [get_full_text(t) for t in tweets_with_ticker]
    combined = " ".join(texts).lower()
    total_likes = sum(t.get("public_metrics", {}).get("like_count", 0) for t in tweets_with_ticker)
    mention_count = len(tweets_with_ticker)
    total_engagement = total_likes + sum(
        t.get("public_metrics", {}).get("bookmark_count", 0) for t in tweets_with_ticker
    )

    # CONVICTION signals
    if mention_count >= 3:
        score += 3
        reasons.append(f"mentioned {mention_count}x today")
    if total_likes >= 1000:
        score += 2
        reasons.append(f"{total_likes:,} total likes")
    if total_engagement >= 2000:
        score += 1
        reasons.append(f"high engagement ({total_engagement:,})")

    # Thesis depth signals
    long_posts = sum(1 for t in texts if len(t) > 500)
    if long_posts >= 1:
        score += 2
        reasons.append(f"{long_posts} long-form thesis post(s)")
    
    # Supply chain mapping signals
    supply_chain_markers = ["->", "→", "pass through", "bottleneck", "supply chain", 
                            "funnel", "pipeline", "mapping"]
    if any(m in combined for m in supply_chain_markers):
        score += 2
        reasons.append("supply chain mapping")

    # Bullish language
    bullish = ["buy", "bullish", "long", "conviction", "putting", "position", "loaded",
               "undervalued", "mispriced", "setup", "thesis", "breaking out", "ramp",
               "volume", "order", "contract", "agreement", "partnership", "customer"]
    if sum(1 for w in bullish if w in combined) >= 2:
        score += 1
        reasons.append("bullish language")

    # Speculative signals
    speculative = ["speculative", "bet", "risky", "small cap", "micro cap", "early",
                   "unproven", "binary", "lottery", "moon"]
    if sum(1 for w in speculative if w in combined) >= 1:
        score -= 1
        reasons.append("speculative language noted")

    # Bearish / negative
    bearish = ["short", "bearish", "avoid", "overvalued", "bubble", "risk", "warning",
               "concern", "dump", "crash"]
    if sum(1 for w in bearish if w in combined) >= 2:
        score -= 2
        reasons.append("bearish signals detected")

    # Determine category
    if score >= 5:
        category = "CONVICTION"
    elif score >= 3:
        category = "BULLISH"
    elif score >= 1:
        category = "RADAR"
    elif score >= 0:
        category = "WATCH"
    else:
        category = "AVOID"

    return category, reasons, score


def main():
    args = sys.argv[1:]
    hours = 24
    max_results = 50
    for i, arg in enumerate(args):
        if arg == "--hours" and i + 1 < len(args):
            hours = int(args[i + 1])
        elif arg == "--max" and i + 1 < len(args):
            max_results = int(args[i + 1])

    if not BEARER_TOKEN:
        print(json.dumps({"error": "No X_BEARER_TOKEN found in ~/.hermes/.env"}))
        sys.exit(1)

    tweets = fetch_tweets(BEARER_TOKEN, USER_ID, max_results)
    if isinstance(tweets, dict) and "error" in tweets:
        print(json.dumps({"error": tweets}))
        sys.exit(1)

    # Filter to last N hours
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    recent = []
    for t in tweets:
        created = datetime.fromisoformat(t.get("created_at", "").replace("Z", "+00:00"))
        if created >= cutoff:
            cashtags = extract_cashtags(t)
            metrics = t.get("public_metrics", {})
            recent.append({
                "id": t["id"],
                "text": get_full_text(t),
                "created_at": t["created_at"],
                "cashtags": cashtags,
                "likes": metrics.get("like_count", 0),
                "retweets": metrics.get("retweet_count", 0),
                "replies": metrics.get("reply_count", 0),
                "bookmarks": metrics.get("bookmark_count", 0),
                "views": metrics.get("impression_count", 0),
                "url": f"https://x.com/{USERNAME}/status/{t['id']}",
            })

    if not recent:
        print(json.dumps({
            "username": USERNAME,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "hours_scanned": hours,
            "total_tweets": 0,
            "tickers": {},
            "summary": "No tweets in the scanned timeframe.",
        }))
        return

    # Build ticker -> tweets mapping
    ticker_tweets = defaultdict(list)
    for t in recent:
        for tag in t["cashtags"]:
            ticker_tweets[tag].append(t)

    # Classify each ticker
    classified = {}
    for ticker, t_tweets in sorted(ticker_tweets.items(), key=lambda x: -len(x[1])):
        category, reasons, score = classify_ticker(ticker, t_tweets)
        classified[ticker] = {
            "category": category,
            "score": score,
            "reasons": reasons,
            "mention_count": len(t_tweets),
            "total_likes": sum(t["likes"] for t in t_tweets),
            "total_bookmarks": sum(t["bookmarks"] for t in t_tweets),
            "best_tweet": max(t_tweets, key=lambda x: x["likes"])["url"],
            "sample_texts": [t["text"][:200] for t in t_tweets[:2]],
        }

    # Sort by category priority then score
    cat_order = {"CONVICTION": 0, "BULLISH": 1, "RADAR": 2, "WATCH": 3, "AVOID": 4}
    sorted_tickers = dict(sorted(
        classified.items(),
        key=lambda x: (cat_order.get(x[1]["category"], 9), -x[1]["score"])
    ))

    output = {
        "username": USERNAME,
        "display_name": "Serenity",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "hours_scanned": hours,
        "total_tweets": len(recent),
        "unique_tickers": len(sorted_tickers),
        "tickers": sorted_tickers,
        # Raw tweets for LLM analysis
        "raw_tweets": [
            {
                "text": t["text"][:500],
                "cashtags": t["cashtags"],
                "likes": t["likes"],
                "url": t["url"],
                "created_at": t["created_at"],
            }
            for t in sorted(recent, key=lambda x: -x["likes"])
        ],
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
