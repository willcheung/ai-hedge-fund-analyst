#!/usr/bin/env python3
"""Search X for high-signal tweets about tickers (no min_faves param)."""
from automation_paths import configured_text
import json
import os
import urllib.request
import urllib.parse

def load_bearer():
    with open(os.path.expanduser(configured_text('${ANALYST_HERMES_HOME}/.env'))) as f:
        for line in f:
            if line.startswith("X_BEARER_TOKEN="):
                return line.strip().split("=", 1)[1]

def search_tweets(bearer, query):
    url = "https://api.x.com/2/tweets/search/recent?" + urllib.parse.urlencode({
        "query": query,
        "max_results": 10,
        "tweet.fields": "created_at,public_metrics,author_id",
        "expansions": "author_id",
        "user.fields": "username,name"
    })
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {bearer}"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())

bearer = load_bearer()

queries = [
    ("MU high-signal", "$MU (HBM OR earnings OR beat OR upgrade OR analyst) -bot"),
    ("TSEM high-signal", "$TSEM (earnings OR upgrade OR Nvidia OR photonics OR CPO) -bot"),
    ("LITE high-signal", "$LITE (earnings OR upgrade OR optical OR EML OR CPO) -bot"),
    ("SIVE vs LITE", "from:aleabitoreddit ($SIVE OR $LITE)"),
]

for label, query in queries:
    try:
        data = search_tweets(bearer, query)
        users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
        print(f"\n{'='*60}")
        print(f"  {label}  ({len(data.get('data',[]))} results)")
        print(f"{'='*60}")
        for t in data.get("data", []):
            author = users.get(t.get("author_id", ""), {})
            m = t.get("public_metrics", {})
            handle = author.get("username", "?")
            name = author.get("name", "?")
            text = t["text"][:350].replace("\n", " ")
            print(f"  [{t['created_at'][:10]}] @{handle} ({name})")
            print(f"  ❤️{m.get('like_count',0)} 🔖{m.get('bookmark_count',0)} 🔁{m.get('retweet_count',0)}")
            print(f"  {text}")
            print()
    except Exception as e:
        print(f"\n  {label}: ERROR - {e}")
