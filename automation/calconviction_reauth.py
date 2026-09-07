#!/usr/bin/env python3
"""Re-auth @CalConviction OAuth2 token with required scopes, including media.write."""
from automation_paths import configured_text
import base64
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

CONFIG_PATH = os.path.expanduser(configured_text('${ANALYST_HERMES_HOME}/.env'))
TOKENS_PATH = os.path.expanduser(configured_text('${ANALYST_HERMES_HOME}/calconviction_tokens.json'))
PENDING_PATH = os.path.expanduser(configured_text('${ANALYST_HERMES_HOME}/calconviction_oauth_pending.json'))
REDIRECT_URI = "http://localhost:8080/callback"
SCOPES = [
    "tweet.read",
    "tweet.write",
    "users.read",
    "follows.read",
    "follows.write",
    "list.read",
    "list.write",
    "offline.access",
    "media.write",
]


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


def client_credentials():
    env = load_env()
    cid = env.get("CALCONVICTION_CLIENT_ID")
    csec = env.get("CALCONVICTION_CLIENT_SECRET")
    if not cid or not csec:
        raise SystemExit("Missing CALCONVICTION_CLIENT_ID / CALCONVICTION_CLIENT_SECRET")
    return cid, csec


def authorize_url():
    cid, _ = client_credentials()
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(24)
    pending = {"code_verifier": verifier, "state": state, "created_at": time.time()}
    with open(PENDING_PATH, "w") as f:
        json.dump(pending, f, indent=2)
    os.chmod(PENDING_PATH, 0o600)
    params = {
        "response_type": "code",
        "client_id": cid,
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    print("https://twitter.com/i/oauth2/authorize?" + urllib.parse.urlencode(params))


def exchange(code_or_url):
    cid, csec = client_credentials()
    if not os.path.exists(PENDING_PATH):
        raise SystemExit("No pending OAuth verifier. Run: calconviction_reauth.py url")
    with open(PENDING_PATH) as f:
        pending = json.load(f)

    value = code_or_url.strip()
    if value.startswith("http"):
        parsed = urllib.parse.urlparse(value)
        qs = urllib.parse.parse_qs(parsed.query)
        code = qs.get("code", [""])[0]
        state = qs.get("state", [""])[0]
        if state and state != pending.get("state"):
            raise SystemExit("State mismatch; generate a fresh URL.")
    else:
        code = value
    if not code:
        raise SystemExit("No code provided")

    auth = base64.b64encode(f"{cid}:{csec}".encode()).decode()
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": pending["code_verifier"],
    }).encode()
    req = urllib.request.Request(
        "https://api.twitter.com/2/oauth2/token",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        resp = urllib.request.urlopen(req, timeout=20)
        tokens = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Token exchange failed ({e.code}): {e.read().decode()[:500]}")

    tokens["expires_at"] = time.time() + int(tokens.get("expires_in", 7200))
    with open(TOKENS_PATH, "w") as f:
        json.dump(tokens, f, indent=2)
    os.chmod(TOKENS_PATH, 0o600)
    try:
        os.remove(PENDING_PATH)
    except OSError:
        pass
    print("Saved @CalConviction OAuth token.")
    print("Scopes:", tokens.get("scope", ""))


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in {"url", "exchange"}:
        print("Usage: calconviction_reauth.py url | exchange CODE_OR_CALLBACK_URL")
        raise SystemExit(1)
    if sys.argv[1] == "url":
        authorize_url()
    else:
        if len(sys.argv) < 3:
            raise SystemExit("Usage: calconviction_reauth.py exchange CODE_OR_CALLBACK_URL")
        exchange(sys.argv[2])
