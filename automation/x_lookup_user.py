#!/usr/bin/env python3
"""Look up X user and their recent tweets using OAuth."""
from automation_paths import configured_text
import json
import os
import urllib.request
import urllib.parse
import time

# Load all X credentials
env = {}
with open(os.path.expanduser(configured_text('${ANALYST_HERMES_HOME}/.env'))) as f:
    for line in f:
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k] = v

# Try OAuth2 access token first, fall back to bearer
token = env.get("X_OAUTH2_ACCESS_TOKEN", "") or env.get("X_BEARER_TOKEN", "")
if not token:
    print("ERROR: No X token found")
    exit(1)

headers = {"Authorization": f"Bearer {token}"}

def api_get(path, params=None):
    url = f"https://api.x.com/2{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())

# 1. Look up user
print("=== USER LOOKUP ===")
try:
    user = api_get("/users/by/username/Ren_aramb.by",
                   {"user.fields": "public_metrics,description,created_at,profile_image_url"})
    if "data" in user:
        u = user["data"]
        m = u.get("public_metrics", {})
        print(f"Name: {u.get('name')}")
        print(f"Handle: @{u.get('username')}")
        print(f"ID: {u.get('id')}")
        print(f"Followers: {m.get('followers_count', '?')}")
        print(f"Following: {m.get('following_count', '?')}")
        print(f"Tweets: {m.get('tweet_count', '?')}")
        print(f"Bio: {u.get('description', '')}")
        user_id = u["id"]
    else:
        print(f"User not found: {json.dumps(user)}")
        # Try without the dot
        print("\nTrying Ren_aramb...")
        user = api_get("/users/by/username/Ren_aramb",
                       {"user.fields": "public_metrics,description,created_at"})
        if "data" in user:
            u = user["data"]
            m = u.get("public_metrics", {})
            print(f"Name: {u.get('name')}")
            print(f"Handle: @{u.get('username')}")
            print(f"ID: {u.get('id')}")
            print(f"Followers: {m.get('followers_count', '?')}")
            print(f"Bio: {u.get('description', '')}")
            user_id = u["id"]
        else:
            print(f"Also not found: {json.dumps(user)}")
            exit(1)
except Exception as e:
    print(f"ERROR: {e}")
    exit(1)

print()

# 2. Get recent tweets
print("=== RECENT TWEETS (last 20) ===")
time.sleep(1)
try:
    tweets = api_get(f"/users/{user_id}/tweets",
                     {"max_results": 20,
                      "tweet.fields": "created_at,public_metrics,entities",
                      "exclude": "retweets,replies"})
    for t in tweets.get("data", []):
        m = t.get("public_metrics", {})
        text = t["text"].replace("\n", " ")[:350]
        cashtags = [e["tag"] for e in t.get("entities", {}).get("cashtags", [])]
        tags = " ".join(f"${c}" for c in cashtags) if cashtags else ""
        print(f"[{t['created_at'][:10]}] ❤️{m.get('like_count',0)} 🔖{m.get('bookmark_count',0)} 🔁{m.get('retweet_count',0)} {tags}")
        print(f"  {text}")
        print()
except Exception as e:
    print(f"ERROR: {e}")
