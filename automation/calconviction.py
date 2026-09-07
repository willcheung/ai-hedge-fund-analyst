#!/usr/bin/env python3
"""
CalConviction — X/Twitter posting client for @CalConviction

Handles: posting, threads, quote tweets, retweets, replies, mentions, follows, token refresh.
The output layer for the market wiki — research feeds this account.

Usage:
    python3 calconviction.py post "text"
    python3 calconviction.py thread "title" "tweet1" "tweet2" "tweet3" ...
    python3 calconviction.py quote TWEET_ID "text"
    python3 calconviction.py retweet TWEET_ID
    python3 calconviction.py reply TWEET_ID "text"
    python3 calconviction.py mentions [--limit N] [--json]
    python3 calconviction.py follow @username
    python3 calconviction.py follow-many @user1 @user2 @user3 ...
    python3 calconviction.py refresh
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error

import requests

from automation_paths import secret_path

# --- Config ---
CONFIG_PATH = str(secret_path('.env'))
TOKENS_PATH = str(secret_path('calconviction_tokens.json'))
CLIENT_ID_KEY = "CALCONVICTION_CLIENT_ID"
CLIENT_SECRET_KEY = "CALCONVICTION_CLIENT_SECRET"


def load_env():
    env = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def load_tokens():
    if os.path.exists(TOKENS_PATH):
        with open(TOKENS_PATH) as f:
            return json.load(f)
    # Missing selected credentials fail closed; never search shared /tmp.
    return None


def save_tokens(tokens):
    with open(TOKENS_PATH, "w") as f:
        json.dump(tokens, f, indent=2)


def refresh_token():
    """Refresh the access token using the refresh token."""
    env = load_env()
    client_id = env.get(CLIENT_ID_KEY, "")
    client_secret = env.get(CLIENT_SECRET_KEY, "")

    if not client_id or not client_secret:
        print("ERROR: Missing CalConviction OAuth client credentials in ~/.hermes/.env", file=sys.stderr)
        sys.exit(1)

    tokens = load_tokens()
    if not tokens or "refresh_token" not in tokens:
        print("ERROR: No refresh token available. Re-authenticate.")
        sys.exit(1)

    import base64
    auth_str = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
    }).encode()

    req = urllib.request.Request(
        "https://api.twitter.com/2/oauth2/token",
        data=body, method="POST",
        headers={
            "Authorization": f"Basic {auth_str}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
    )

    try:
        resp = urllib.request.urlopen(req, timeout=15)
        new_tokens = json.loads(resp.read())
        save_tokens(new_tokens)
        return new_tokens["access_token"]
    except urllib.error.HTTPError as e:
        print(f"ERROR: Token refresh failed ({e.code}): {e.read().decode()[:200]}")
        sys.exit(1)


def get_access_token():
    """Get a valid access token, refreshing if needed."""
    tokens = load_tokens()
    if not tokens:
        print("ERROR: No tokens found. Run OAuth flow first.")
        sys.exit(1)

    # Check if token might be expired (7200s = 2h, refresh at 1h to be safe)
    expires_at = tokens.get("expires_at")
    if expires_at:
        if time.time() > (expires_at - 3600):
            print("Token expiring soon, refreshing...", file=sys.stderr)
            return refresh_token()
    else:
        # No expires_at — try using it, refresh on 401
        return tokens.get("access_token", "")

    return tokens.get("access_token", "")


def api_call(method, endpoint, data=None, token=None):
    """Make an X API call. Returns parsed JSON or raises on error."""
    if not token:
        token = get_access_token()

    url = f"https://api.x.com{endpoint}"
    headers = {"Authorization": f"Bearer {token}"}

    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
    else:
        req = urllib.request.Request(url, method=method, headers=headers)

    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()[:300]
        if e.code == 401:
            # Try refresh once
            print("Got 401, refreshing token...", file=sys.stderr)
            token = refresh_token()
            headers["Authorization"] = f"Bearer {token}"
            req = urllib.request.Request(url, data=body if data else None,
                                         method=method, headers=headers)
            resp = urllib.request.urlopen(req, timeout=15)
            return json.loads(resp.read())
        print(f"API Error {e.code}: {error_body}", file=sys.stderr)
        raise


def upload_media(media_path):
    """Upload media via X API v2 media endpoint. Returns media id."""
    media_path = os.path.expanduser(media_path)
    if not os.path.exists(media_path):
        print(f"ERROR: Media file not found: {media_path}", file=sys.stderr)
        sys.exit(1)

    token = get_access_token()
    media_type = "image/png" if media_path.lower().endswith(".png") else "image/jpeg"
    total_bytes = os.path.getsize(media_path)
    endpoint = "https://api.x.com/2/media/upload"
    base_headers = {"Authorization": f"Bearer {token}", "User-Agent": "CalConvictionMediaUpload"}

    # INIT
    init_resp = requests.post(
        f"{endpoint}/initialize",
        json={
            "media_type": media_type,
            "total_bytes": total_bytes,
            "media_category": "tweet_image",
        },
        headers=base_headers,
        timeout=30,
    )
    if init_resp.status_code >= 400:
        print(f"ERROR: Media INIT failed ({init_resp.status_code}): {init_resp.text[:500]}", file=sys.stderr)
        init_resp.raise_for_status()
    media_id = init_resp.json().get("data", {}).get("id")
    if not media_id:
        print(f"ERROR: Media INIT returned no id: {init_resp.text[:500]}", file=sys.stderr)
        sys.exit(1)

    # APPEND. Images are small, but chunk anyway.
    segment = 0
    with open(media_path, "rb") as f:
        while True:
            chunk = f.read(4 * 1024 * 1024)
            if not chunk:
                break
            append_resp = requests.post(
                f"{endpoint}/{media_id}/append",
                data={"segment_index": segment},
                files={"media": (os.path.basename(media_path), chunk, media_type)},
                headers=base_headers,
                timeout=60,
            )
            if append_resp.status_code >= 400:
                print(f"ERROR: Media APPEND failed ({append_resp.status_code}): {append_resp.text[:500]}", file=sys.stderr)
                append_resp.raise_for_status()
            segment += 1

    # FINALIZE
    final_resp = requests.post(
        f"{endpoint}/{media_id}/finalize",
        headers=base_headers,
        timeout=30,
    )
    if final_resp.status_code >= 400:
        print(f"ERROR: Media FINALIZE failed ({final_resp.status_code}): {final_resp.text[:500]}", file=sys.stderr)
        final_resp.raise_for_status()
    print(f"✅ Uploaded media: {media_id}")
    return media_id


def post_tweet(text, media_paths=None):
    """Post a single tweet. Returns tweet ID."""
    payload = {"text": text}
    if media_paths:
        media_ids = [upload_media(path) for path in media_paths]
        payload["media"] = {"media_ids": media_ids}
    result = api_call("POST", "/2/tweets", payload)
    tweet_id = result["data"]["id"]
    print(f"✅ Posted: https://x.com/CalConviction/status/{tweet_id}")
    return tweet_id


def post_thread(tweets):
    """Post a thread. tweets = list of strings. Returns list of tweet IDs."""
    if not tweets:
        print("ERROR: No tweets provided")
        sys.exit(1)

    token = get_access_token()
    tweet_ids = []

    # First tweet
    result = api_call("POST", "/2/tweets", {"text": tweets[0]}, token)
    tweet_id = result["data"]["id"]
    tweet_ids.append(tweet_id)
    print(f"✅ Tweet 1/{len(tweets)}: https://x.com/CalConviction/status/{tweet_id}")

    # Reply chain
    for i, text in enumerate(tweets[1:], 2):
        time.sleep(1)  # Rate limit courtesy
        result = api_call("POST", "/2/tweets", {
            "text": text,
            "reply": {"in_reply_to_tweet_id": tweet_ids[-1]}
        }, token)
        tweet_id = result["data"]["id"]
        tweet_ids.append(tweet_id)
        print(f"✅ Tweet {i}/{len(tweets)}: https://x.com/CalConviction/status/{tweet_id}")

    return tweet_ids


def quote_tweet(tweet_id, text):
    """Quote tweet. tweet_id can be a full URL or just the ID.
    
    ⚠️ DEPRECATED: As of April 20, 2026, X removed POST /2/tweets with quote_tweet_id
    for all self-serve tiers. Use the quote-tweet-browser skill (Playwright) instead.
    """
    if "/" in tweet_id:
        tweet_id = tweet_id.rstrip("/").split("/")[-1]

    print(f"⚠️ API quote tweets removed by X (April 2026). Use the quote-tweet-browser skill (Playwright) instead.")
    print(f"   Target tweet: https://x.com/i/status/{tweet_id}")
    print(f"   Quote text: {text}")
    return None


def retweet(tweet_id):
    """Retweet. tweet_id can be a full URL or just the ID."""
    if "/" in tweet_id:
        tweet_id = tweet_id.rstrip("/").split("/")[-1]

    token = get_access_token()
    # Need our user ID for retweet
    me = api_call("GET", "/2/users/me", token=token)
    my_id = me["data"]["id"]

    result = api_call("POST", f"/2/users/{my_id}/retweets", {
        "tweet_id": tweet_id,
    }, token)
    print(f"✅ Retweeted: {tweet_id}")
    return result


def get_mentions(limit=10):
    """Fetch recent mentions of @CalConviction. Returns list of mention dicts."""
    token = get_access_token()
    me = api_call("GET", "/2/users/me", token=token)
    my_id = me["data"]["id"]

    params = f"max_results={limit}&tweet.fields=created_at,author_id,conversation_id,in_reply_to_user_id,referenced_tweets&expansions=author_id&user.fields=username,name"
    result = api_call("GET", f"/2/users/{my_id}/mentions?{params}", token=token)
    mentions = result.get("data", [])
    users = {u["id"]: u for u in result.get("includes", {}).get("users", [])}

    output = []
    for m in mentions:
        author = users.get(m.get("author_id"), {})
        output.append({
            "id": m["id"],
            "text": m["text"],
            "author": author.get("username", "unknown"),
            "author_name": author.get("name", "unknown"),
            "created_at": m.get("created_at", ""),
            "conversation_id": m.get("conversation_id", ""),
        })
    return output


def reply_to_tweet(tweet_id, text):
    """Reply to a tweet. tweet_id can be URL or ID."""
    if "/" in tweet_id:
        tweet_id = tweet_id.rstrip("/").split("/")[-1]

    result = api_call("POST", "/2/tweets", {
        "text": text,
        "reply": {"in_reply_to_tweet_id": tweet_id},
    })
    new_id = result["data"]["id"]
    print(f"✅ Replied: https://x.com/CalConviction/status/{new_id}")
    return new_id


def follow_user(username):
    """Follow a user. Accepts @handle or just handle.
    
    ⚠️ DEPRECATED: As of April 20, 2026, X removed POST /2/users/{id}/following
    for all self-serve tiers. Follows must be done manually via the X app/web.
    This function now prints a reminder instead of making the API call.
    """
    username = username.lstrip("@")
    print(f"⚠️ API follow removed by X (April 2026). Follow @{username} manually from the app/web.")
    return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 calconviction.py <command> [args...]")
        print("Commands: post, thread, quote, retweet, reply, mentions, follow, follow-many, refresh")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "post":
        if len(sys.argv) < 3:
            print("Usage: python3 calconviction.py post \"text\" [--media /path/chart.png ...]")
            sys.exit(1)
        args = sys.argv[2:]
        media_paths = []
        text_parts = []
        i = 0
        while i < len(args):
            if args[i] == "--media":
                if i + 1 >= len(args):
                    print("ERROR: --media requires a file path", file=sys.stderr)
                    sys.exit(1)
                media_paths.append(args[i + 1])
                i += 2
            else:
                text_parts.append(args[i])
                i += 1
        if not text_parts:
            print("ERROR: Missing tweet text", file=sys.stderr)
            sys.exit(1)
        post_tweet(" ".join(text_parts), media_paths or None)

    elif cmd == "thread":
        if len(sys.argv) < 3:
            print("Usage: python3 calconviction.py thread \"tweet1\" \"tweet2\" ...")
            sys.exit(1)
        tweets = sys.argv[2:]
        post_thread(tweets)

    elif cmd == "quote":
        if len(sys.argv) < 4:
            print("Usage: python3 calconviction.py quote TWEET_ID \"text\"")
            sys.exit(1)
        quote_tweet(sys.argv[2], sys.argv[3])

    elif cmd == "retweet":
        if len(sys.argv) < 3:
            print("Usage: python3 calconviction.py retweet TWEET_ID")
            sys.exit(1)
        retweet(sys.argv[2])

    elif cmd == "reply":
        if len(sys.argv) < 4:
            print('Usage: python3 calconviction.py reply TWEET_ID "text"')
            sys.exit(1)
        reply_to_tweet(sys.argv[2], sys.argv[3])

    elif cmd == "mentions":
        limit = 10
        as_json = False
        for arg in sys.argv[2:]:
            if arg == "--json":
                as_json = True
            elif arg.startswith("--limit="):
                limit = int(arg.split("=")[1])
        mentions = get_mentions(limit)
        if as_json:
            print(json.dumps(mentions, indent=2))
        else:
            if not mentions:
                print("No mentions found.")
            for m in mentions:
                print(f"@{m['author']} ({m['author_name']}) [{m['created_at']}]")
                print(f"  https://x.com/{m['author']}/status/{m['id']}")
                print(f"  {m['text'][:200]}")
                print()

    elif cmd == "follow":
        if len(sys.argv) < 3:
            print("Usage: python3 calconviction.py follow @username")
            sys.exit(1)
        follow_user(sys.argv[2])

    elif cmd == "follow-many":
        if len(sys.argv) < 3:
            print("Usage: python3 calconviction.py follow-many @user1 @user2 ...")
            sys.exit(1)
        for username in sys.argv[2:]:
            try:
                follow_user(username)
                time.sleep(1)  # Rate limit
            except Exception as e:
                print(f"⚠ Failed to follow {username}: {e}")

    elif cmd == "refresh":
        token = refresh_token()
        print(f"✅ Token refreshed. Expires in 7200s.")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
