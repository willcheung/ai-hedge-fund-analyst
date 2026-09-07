#!/usr/bin/env python3
"""Get high-engagement tweets from @Ren_aramb."""
from automation_paths import configured_text
import json
import os
import urllib.request
import urllib.parse

env = {}
with open(os.path.expanduser(configured_text('${ANALYST_HERMES_HOME}/.env'))) as f:
    for line in f:
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k] = v

token = env.get("X_BEARER_TOKEN", "")
headers = {"Authorization": f"Bearer {token}"}
USER_ID = "1326937038692769793"

def api_get(path, params=None):
    url = f"https://api.x.com/2{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())

# Get tweets sorted by engagement (just get more and sort ourselves)
print("=== REN'S HIGHEST ENGAGEMENT TICKER CALLS (recent) ===")
try:
    # Get up to 100 tweets, exclude RTs and replies
    tweets = api_get(f"/users/{USER_ID}/tweets",
                     {"max_results": 100,
                      "tweet.fields": "created_at,public_metrics,entities,note_tweet",
                      "exclude": "retweets,replies"})
    
    # Sort by likes
    all_tweets = tweets.get("data", [])
    all_tweets.sort(key=lambda t: t.get("public_metrics", {}).get("like_count", 0), reverse=True)
    
    # Show top 25 by engagement
    for i, t in enumerate(all_tweets[:25]):
        m = t.get("public_metrics", {})
        cashtags = [e["tag"] for e in t.get("entities", {}).get("cashtags", [])]
        tags = " ".join(f"${c}" for c in cashtags)
        text = t["text"].replace("\n", " ")[:400]
        engagement = m.get("like_count",0) + m.get("bookmark_count",0) + m.get("retweet_count",0)*3
        print(f"#{i+1} [{t['created_at'][:10]}] ❤️{m.get('like_count',0)} 🔖{m.get('bookmark_count',0)} 🔁{m.get('retweet_count',0)} (eng:{engagement}) {tags}")
        print(f"  {text}")
        print()

except Exception as e:
    print(f"ERROR: {e}")

# Also get his pinned tweet
print("\n=== PINNED TWEET ===")
try:
    pinned = api_get(f"/users/{USER_ID}/tweets",
                     {"max_results": 5,
                      "tweet.fields": "created_at,public_metrics,entities",
                      "exclude": "retweets,replies"})
    # Pinned is usually the first
    if pinned.get("data"):
        t = pinned["data"][0]
        m = t.get("public_metrics", {})
        cashtags = [e["tag"] for e in t.get("entities", {}).get("cashtags", [])]
        tags = " ".join(f"${c}" for c in cashtags)
        print(f"❤️{m.get('like_count',0)} 🔖{m.get('bookmark_count',0)} {tags}")
        print(t["text"][:500])
except Exception as e:
    print(f"ERROR: {e}")
