#!/usr/bin/env python3
"""
Fetch recent tweets from @KobeissiLetter via X API v2.
Used by morning briefing to get market-moving macro commentary.
Loads X_BEARER_TOKEN from ~/.hermes/.env
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

# Load env from Hermes home (where all credentials live)
env_path = Path(os.path.expanduser(configured_text('${ANALYST_HERMES_HOME}/.env')))
env_vars = {}
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            env_vars[key.strip()] = value.strip().strip('"').strip("'")

BEARER_TOKEN = env_vars.get("X_BEARER_TOKEN", "")
KOBEISSI_USER_ID = "3316376038"  # @KobeissiLetter

def fetch_user_id(bearer, username):
    """Look up user ID by username."""
    url = f"https://api.twitter.com/2/users/by/username/{username}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {bearer}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("data", {}).get("id")
    except Exception as e:
        return None

def fetch_tweets(bearer, user_id, max_results=10):
    """Fetch recent tweets from a user via X API v2."""
    url = "https://api.twitter.com/2/users/{}/tweets".format(user_id)
    params = urllib.parse.urlencode({
        "max_results": max(10, min(max_results, 100)),
        "tweet.fields": "created_at,public_metrics,text",
        "exclude": "retweets,replies",
    })
    full_url = f"{url}?{params}"
    req = urllib.request.Request(full_url, headers={"Authorization": f"Bearer {bearer}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("data", [])
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.reason}", "detail": e.read().decode()[:200]}
    except Exception as e:
        return {"error": str(e)}

def fetch_tweets_search(bearer, username, max_results=10):
    """Fallback: search for tweets from username."""
    url = "https://api.twitter.com/2/tweets/search/recent"
    params = urllib.parse.urlencode({
        "query": f"from:{username} -is:retweet -is:reply",
        "max_results": min(max_results, 10),
        "tweet.fields": "created_at,public_metrics,text",
        "sort_order": "relevancy",
    })
    full_url = f"{url}?{params}"
    req = urllib.request.Request(full_url, headers={"Authorization": f"Bearer {bearer}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("data", [])
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.reason}", "detail": e.read().decode()[:200]}
    except Exception as e:
        return {"error": str(e)}

def main():
    if not BEARER_TOKEN:
        print(json.dumps({"error": "No X_BEARER_TOKEN found"}))
        sys.exit(1)

    username = sys.argv[1] if len(sys.argv) > 1 else "KobeissiLetter"
    max_results = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    
    # Try user timeline first
    tweets = fetch_tweets(BEARER_TOKEN, KOBEISSI_USER_ID if username == "KobeissiLetter" else None)
    
    # If that fails or returns error, try search
    if isinstance(tweets, dict) and "error" in tweets:
        print(json.dumps({"method": "user_timeline", "result": tweets}), file=sys.stderr)
        tweets = fetch_tweets_search(BEARER_TOKEN, username, max_results)
    
    if isinstance(tweets, dict) and "error" in tweets:
        print(json.dumps({"method": "search", "result": tweets}), file=sys.stderr)
        print(json.dumps({"error": "All methods failed", "details": tweets}))
        sys.exit(1)
    
    # Filter to last 24 hours
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    recent = []
    for t in tweets:
        created = datetime.fromisoformat(t.get("created_at", "").replace("Z", "+00:00"))
        if created >= cutoff:
            recent.append({
                "id": t["id"],
                "text": t["text"],
                "created_at": t["created_at"],
                "likes": t.get("public_metrics", {}).get("like_count", 0),
                "retweets": t.get("public_metrics", {}).get("retweet_count", 0),
                "impressions": t.get("public_metrics", {}).get("impression_count", 0),
                "url": f"https://x.com/{username}/status/{t['id']}",
            })
    
    output = {
        "username": username,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "total_recent": len(recent),
        "tweets": recent,
    }
    print(json.dumps(output))

if __name__ == "__main__":
    main()
