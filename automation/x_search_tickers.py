#!/usr/bin/env python3
"""Search X API for analyst tweets about specific tickers."""
from automation_paths import configured_text
import json
import os
import sys
import urllib.request
import urllib.parse

def load_bearer():
    with open(os.path.expanduser(configured_text('${ANALYST_HERMES_HOME}/.env'))) as f:
        for line in f:
            if line.startswith("X_BEARER_TOKEN="):
                return line.strip().split("=", 1)[1]
    raise RuntimeError("No X_BEARER_TOKEN found")

def search_tweets(bearer, query, max_results=10):
    url = "https://api.x.com/2/tweets/search/recent?" + urllib.parse.urlencode({
        "query": query,
        "max_results": min(max_results, 100),
        "tweet.fields": "created_at,public_metrics,author_id,entities",
        "expansions": "author_id",
        "user.fields": "username,name"
    })
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {bearer}"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())

def format_tweets(data):
    users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
    results = []
    for t in data.get("data", []):
        author = users.get(t.get("author_id", ""), {})
        m = t.get("public_metrics", {})
        results.append({
            "author": f"@{author.get('username', '?')} ({author.get('name', '?')})",
            "date": t["created_at"][:10],
            "likes": m.get("like_count", 0),
            "bookmarks": m.get("bookmark_count", 0),
            "retweets": m.get("retweet_count", 0),
            "text": t["text"][:400],
        })
    return results

def main():
    bearer = load_bearer()
    queries = [
        ("SERENITY MU", "from:aleabitoreddit $MU"),
        ("SERENITY TSEM", "from:aleabitoreddit $TSEM"),
        ("SERENITY LITE", "from:aleabitoreddit $LITE"),
        ("SHAY MU", "from:StockSavvyShay $MU"),
        ("SHAY TSEM", "from:StockSavvyShay $TSEM"),
        ("SHAY LITE", "from:StockSavvyShay $LITE"),
        ("MU HBM high-signal", "$MU (HBM OR earnings OR beat OR upgrade)"),
        ("TSEM high-signal", "$TSEM (earnings OR upgrade OR Nvidia OR photonics)"),
        ("LITE high-signal", "$LITE (earnings OR upgrade OR optical OR EML)"),
    ]

    for label, query in queries:
        try:
            data = search_tweets(bearer, query, 10)
            tweets = format_tweets(data)
            print(f"\n{'='*60}")
            print(f"  {label}  ({len(tweets)} results)")
            print(f"{'='*60}")
            if not tweets:
                print("  (no results)")
            for t in tweets:
                print(f"  [{t['date']}] @{t['author'].split('(')[0].strip()} | ❤️{t['likes']} 🔖{t['bookmarks']} 🔁{t['retweets']}")
                # Clean text for display
                text = t['text'].replace('\n', ' ')
                print(f"  {text[:350]}")
                print()
        except Exception as e:
            print(f"\n  {label}: ERROR - {e}")

if __name__ == "__main__":
    main()
