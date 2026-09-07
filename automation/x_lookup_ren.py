#!/usr/bin/env python3
"""Refresh OAuth2 access token and search X."""
from automation_paths import configured_text
import json
import os
import urllib.request
import urllib.parse
import base64
import time

env = {}
with open(os.path.expanduser(configured_text('${ANALYST_HERMES_HOME}/.env'))) as f:
    for line in f:
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k] = v

client_id = env.get("X_CLIENT_ID", "")
client_secret = env.get("X_CLIENT_SECRET", "")
refresh_token = env.get("X_OAUTH2_REFRESH_TOKEN", "")

# Step 1: Refresh the access token
print("=== REFRESHING TOKEN ===")
creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
req = urllib.request.Request(
    "https://api.x.com/2/oauth2/token",
    data=urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode(),
    headers={
        "Authorization": f"Basic {creds}",
        "Content-Type": "application/x-www-form-urlencoded"
    },
    method="POST"
)
try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        token_data = json.loads(resp.read())
    new_access = token_data.get("access_token", "")
    print(f"Got access token (len={len(new_access)})")
    token = new_access
except Exception as e:
    print(f"Refresh failed: {e}")
    print("Falling back to bearer token...")
    token = env.get("X_BEARER_TOKEN", "")

headers = {"Authorization": f"Bearer {token}"}

def api_get(path, params=None):
    url = f"https://api.x.com/2{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())

# Step 2: Look up user
print("\n=== USER LOOKUP: @Ren_aramb.by ===")
for handle in ["Ren_aramb.by", "Ren_aramb"]:
    try:
        user = api_get(f"/users/by/username/{handle}",
                       {"user.fields": "public_metrics,description,created_at"})
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
            break
        else:
            print(f"  @{handle} not found: {user.get('title', 'unknown')}")
    except Exception as e:
        print(f"  @{handle} error: {e}")
else:
    print("Could not find user. Trying search...")
    try:
        results = api_get("/users/by/username/ren_aramb_by",
                         {"user.fields": "public_metrics,description"})
        if "data" in results:
            u = results["data"]
            print(f"Found: @{u['username']} — {u.get('name')}")
            user_id = u["id"]
        else:
            print("All lookups failed.")
            exit(1)
    except Exception as e:
        print(f"Search error: {e}")
        exit(1)

# Step 3: Get recent tweets
print(f"\n=== RECENT TWEETS ===")
time.sleep(0.5)
try:
    tweets = api_get(f"/users/{user_id}/tweets",
                     {"max_results": 20,
                      "tweet.fields": "created_at,public_metrics,entities",
                      "exclude": "retweets,replies"})
    count = 0
    for t in tweets.get("data", []):
        m = t.get("public_metrics", {})
        cashtags = [e["tag"] for e in t.get("entities", {}).get("cashtags", [])]
        hashtags = [e["tag"] for e in t.get("entities", {}).get("hashtags", [])]
        tags = " ".join(f"${c}" for c in cashtags + hashtags)
        text = t["text"].replace("\n", " ")[:400]
        print(f"[{t['created_at'][:10]}] ❤️{m.get('like_count',0)} 🔖{m.get('bookmark_count',0)} 🔁{m.get('retweet_count',0)} {tags}")
        print(f"  {text}")
        print()
        count += 1
    print(f"Total: {count} tweets")
except Exception as e:
    print(f"ERROR: {e}")

# Step 4: Also search for their high-engagement ticker calls
print("\n=== HIGH-ENGAGEMENT TICKER CALLS ===")
time.sleep(0.5)
try:
    results = api_get("/tweets/search/recent",
                     {"query": f"from:{user_id} $ min_faves:100",
                      "max_results": 20,
                      "tweet.fields": "created_at,public_metrics,entities"})
    for t in results.get("data", []):
        m = t.get("public_metrics", {})
        cashtags = [e["tag"] for e in t.get("entities", {}).get("cashtags", [])]
        tags = " ".join(f"${c}" for c in cashtags)
        text = t["text"].replace("\n", " ")[:350]
        print(f"[{t['created_at'][:10]}] ❤️{m.get('like_count',0)} 🔖{m.get('bookmark_count',0)} {tags}")
        print(f"  {text}")
        print()
except Exception as e:
    print(f"(skipped: {e})")
