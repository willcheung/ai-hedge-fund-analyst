#!/usr/bin/env python3
"""
X Ticker Recon — search X for any ticker, discover accounts discussing it.

Simple discovery tool. Fetches tweets mentioning a ticker, groups by author,
shows engagement data and full text. Does NOT try to score thesis quality —
that's V's job to evaluate when presenting results to the operator.

Usage:
    python3 x_ticker_recon.py ASTS
    python3 x_ticker_recon.py ASTS --hours 72 --min-likes 20
    python3 x_ticker_recon.py ASTS --json

Output: Grouped list of accounts with engagement metrics and sample text.
"""
from automation_paths import configured_text
import json
import os
import sys
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict

# Load env
env_path = Path(os.path.expanduser(configured_text('${ANALYST_HERMES_HOME}/.env')))
env_vars = {}
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            env_vars[key.strip()] = value.strip().strip('"').strip("'")

BEARER_TOKEN = env_vars.get("X_BEARER_TOKEN", "")

# Fallback only. Runtime tracked-account source of truth is the X list.
FALLBACK_TRACKED_ACCOUNTS = {
    "aleabitoreddit", "danielisdizzy", "StockSavvyShay", "ChrisCamillo",
    "Ren_aramb", "crux_capital_", "marketmatrixs", "midascabal",
}


def load_tracked_accounts():
    """Load current scanner accounts from the X list; fall back to old static set if unavailable."""
    try:
        script_dir = Path(__file__).resolve().parent
        sys.path.insert(0, str(script_dir))
        from fetch_x_signals import fetch_list_members
        members = fetch_list_members()
        if members:
            return {m.lower() for m in members}
    except Exception:
        pass
    return {a.lower() for a in FALLBACK_TRACKED_ACCOUNTS}


def api_get(path, params=None):
    url = f"https://api.x.com/2{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {BEARER_TOKEN}"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def get_full_text(tweet):
    nt = tweet.get("note_tweet")
    if nt and "text" in nt:
        return nt["text"]
    return tweet.get("text", "")


def search_tweets(query, max_results=100):
    params = {
        "query": query,
        "max_results": min(max_results, 100),
        "tweet.fields": "created_at,public_metrics,entities,note_tweet,author_id,conversation_id",
        "expansions": "author_id",
        "user.fields": "username,name,public_metrics,description,verified,created_at",
    }
    try:
        return api_get("/tweets/search/recent", params)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode()[:300]
        except Exception:
            pass
        return {"error": f"HTTP {e.code}: {e.reason}", "detail": detail}


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: python3 x_ticker_recon.py TICKER [--hours 48] [--min-likes 5] [--json]")
        sys.exit(1)

    ticker = args[0].upper().lstrip("$")
    hours = 48
    min_likes = 5
    output_json = False

    i = 1
    while i < len(args):
        if args[i] == "--hours" and i + 1 < len(args):
            hours = int(args[i + 1])
            i += 2
        elif args[i] == "--min-likes" and i + 1 < len(args):
            min_likes = int(args[i + 1])
            i += 2
        elif args[i] == "--json":
            output_json = True
            i += 1
        else:
            i += 1

    if not BEARER_TOKEN:
        print(json.dumps({"error": "No X_BEARER_TOKEN found"}))
        sys.exit(1)

    tracked_accounts = load_tracked_accounts()
    query = f"${ticker} lang:en"
    result = search_tweets(query, max_results=100)
    if "error" in result:
        print(json.dumps({"error": result["error"], "detail": result.get("detail", "")}))
        sys.exit(1)

    tweets = result.get("data", [])
    users_map = {u["id"]: u for u in result.get("includes", {}).get("users", [])}

    # Filter by time and engagement
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    filtered = []
    for t in tweets:
        text = get_full_text(t)
        if text.startswith("RT @"):
            continue
        created = datetime.fromisoformat(t.get("created_at", "").replace("Z", "+00:00"))
        if created < cutoff:
            continue
        likes = t.get("public_metrics", {}).get("like_count", 0)
        if likes < min_likes:
            continue
        filtered.append(t)

    # Group by author
    by_author = defaultdict(list)
    for t in filtered:
        by_author[t["author_id"]].append(t)

    # Build account summaries
    accounts = []
    for author_id, author_tweets in by_author.items():
        author = users_map.get(author_id, {})
        username = author.get("username", "unknown")
        if username.lower() in tracked_accounts:
            continue

        best_tweet = max(author_tweets, key=lambda x: x.get("public_metrics", {}).get("like_count", 0))
        total_likes = sum(t.get("public_metrics", {}).get("like_count", 0) for t in author_tweets)
        total_bookmarks = sum(t.get("public_metrics", {}).get("bookmark_count", 0) for t in author_tweets)
        total_replies = sum(t.get("public_metrics", {}).get("reply_count", 0) for t in author_tweets)
        total_views = sum(t.get("public_metrics", {}).get("impression_count", 0) for t in author_tweets)

        # Get full text for best tweet (search API truncates)
        best_text = get_full_text(best_tweet)

        accounts.append({
            "username": username,
            "name": author.get("name", ""),
            "user_id": author_id,
            "followers": author.get("public_metrics", {}).get("followers_count", 0),
            "verified": author.get("verified", False),
            "bio": author.get("description", "")[:200],
            "posts_on_ticker": len(author_tweets),
            "total_likes": total_likes,
            "total_bookmarks": total_bookmarks,
            "total_replies": total_replies,
            "total_views": total_views,
            "best_text": best_text[:500],
            "best_url": f"https://x.com/{username}/status/{best_tweet['id']}",
            "all_texts": [get_full_text(t)[:300] for t in author_tweets],
        })

    # Sort by total likes
    accounts.sort(key=lambda x: -x["total_likes"])

    if output_json:
        print(json.dumps({
            "ticker": ticker,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "hours_scanned": hours,
            "total_results": len(tweets),
            "after_filter": len(filtered),
            "tracked_count": len(tracked_accounts),
            "new_accounts": len(accounts),
            "accounts": accounts[:20],
        }, indent=2))
    else:
        print(f"=== ${ticker} RECON ({hours}h, {min_likes}+ likes) ===")
        print(f"Total: {len(tweets)} | After filter: {len(filtered)} | New accounts: {len(accounts)}\n")

        if not accounts:
            print("No accounts found outside tracked list.")
            print("Try: lower --min-likes, widen --hours")
            sys.exit(0)

        for a in accounts[:15]:
            verified = " ✓" if a["verified"] else ""
            print(f"@{a['username']}{verified} — {a['name']}")
            print(f"  {a['followers']:,} followers | {a['posts_on_ticker']} posts")
            print(f"  {a['total_likes']:,} likes, {a['total_bookmarks']:,} bookmarks, {a['total_replies']:,} replies")
            print(f"  Best: {a['best_text'][:250]}")
            print(f"  Link: {a['best_url']}")
            if a["bio"]:
                print(f"  Bio: {a['bio'][:120]}")
            print(f"  ID: {a['user_id']}")
            print()


if __name__ == "__main__":
    main()
