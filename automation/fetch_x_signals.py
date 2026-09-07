#!/usr/bin/env python3
"""
Fetch recent tweets from X accounts and extract stock signals.

Source of truth: X list an explicitly configured X_SOURCE_LIST_ID
Default list-timeline scans require an explicit cost-control allow flag/environment guard
and use a durable 30-day roster cache. Optionally scan specific accounts with --accounts.

Supports onboarding new accounts: --add-to-list USERNAME (follows + adds to list).

Usage:
    python3 fetch_x_signals.py --allow-list-scan [--hours 24] [--max 100]
    HERMES_X_SCANNER_ALLOWED=1 python3 fetch_x_signals.py
    python3 fetch_x_signals.py --per-account --accounts aleabitoreddit,midascabal
    python3 fetch_x_signals.py --list-members
    python3 fetch_x_signals.py --refresh-roster --allow-list-scan
    python3 fetch_x_signals.py --add-to-list @newaccount1,@newaccount2

Output: JSON with per-account ticker classifications.
"""
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
from automation_paths import secret_path, state_path

# Use CalConviction OAuth tokens (user-context) for tweet access
# Falls back to X_BEARER_TOKEN from .env if CalConviction tokens unavailable
def _get_bearer():
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from calconviction import get_access_token
        return get_access_token()
    except Exception:
        pass
    # Fallback: read from .env
    env_path = secret_path('.env')
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("X_BEARER_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""

# Resolve credentials only when a caller requests network access, never on import.
BEARER_TOKEN = ""


def _bearer():
    global BEARER_TOKEN
    if not BEARER_TOKEN:
        BEARER_TOKEN = _get_bearer()
    return BEARER_TOKEN


def _get_env_token(name):
    """Read a token from ~/.hermes/.env without printing it."""
    env_path = secret_path('.env')
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _list_auth_tokens(preferred=None):
    """Return candidate tokens for list-member reads.

    CalConviction OAuth is tried first because it is the normal scanner auth.
    X_BEARER_TOKEN is tried second because X list-member reads currently succeed
    with app-only auth while CalConviction OAuth can 403 if the token lacks list.read.
    """
    tokens = []
    for tok in (preferred, _bearer(), _get_env_token("X_BEARER_TOKEN")):
        if tok and tok not in tokens:
            tokens.append(tok)
    return tokens

def _refresh_bearer():
    """Force refresh the bearer token from calconviction and update module-level var."""
    global BEARER_TOKEN
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from calconviction import refresh_token
        BEARER_TOKEN = refresh_token()
        return True
    except Exception:
        return False

# Source of truth: X list members (fetched at runtime)
# an explicitly configured X_SOURCE_LIST_ID
SOURCE_LIST_ID = os.environ.get("X_SOURCE_LIST_ID", "")

# Metadata cache: username -> (user_id, display_name, style)
# Populated from list API at runtime; manual entries are fallback only.
# Styles: supply_chain, momentum, value, institutional, thesis, options_flow,
#         ai_infrastructure, space_economy, photonics_dd, engineering_dd,
#         micro_cap_asymmetric, ai_semiconductor, macro_gold, news_aggregator
KNOWN_ACCOUNTS = {
    # Fallback for accounts that may not be on the list yet
    "DanielTNiles": ("1948086848", "Dan Niles", "thesis"),
    "brent_johnson": ("16185622", "Brent Johnson", "macro_gold"),
}

STATE_PATH = state_path('x_signal_scanner_state.json')
ROSTER_CACHE_PATH = state_path('x_signal_roster_cache.json')
ROSTER_CACHE_MAX_AGE = timedelta(days=30)


def load_state(path=None):
    """Load scanner state used to avoid rereading tweets already processed."""
    path = Path(path) if path else STATE_PATH
    if not path.exists():
        return {"accounts": {}}
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return {"accounts": {}}
        data.setdefault("accounts", {})
        return data
    except Exception:
        return {"accounts": {}}


def save_state(state, path=None):
    """Persist scanner state atomically."""
    path = Path(path) if path else STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp.replace(path)


def _populate_known_accounts(members):
    """Populate the in-process account map from normalized roster metadata."""
    for user in members:
        username = user.get("username")
        user_id = user.get("id")
        if username and user_id:
            KNOWN_ACCOUNTS[username] = (
                str(user_id),
                user.get("name") or username,
                user.get("style") or _guess_style(user),
            )


def save_roster_cache(members, fetched_at=None, path=None):
    """Atomically persist complete list-member metadata."""
    path = Path(path) if path else ROSTER_CACHE_PATH
    fetched_at = fetched_at or datetime.now(timezone.utc).isoformat()
    normalized = []
    for user in members:
        item = {
            "id": str(user.get("id", "")),
            "username": user.get("username", ""),
            "name": user.get("name") or user.get("username", ""),
            "description": user.get("description") or "",
            "public_metrics": user.get("public_metrics") or {},
            "style": user.get("style") or _guess_style(user),
            "fetched_at": fetched_at,
        }
        if item["id"] and item["username"]:
            normalized.append(item)
    payload = {
        "list_id": SOURCE_LIST_ID,
        "fetched_at": fetched_at,
        "member_count": len(normalized),
        "members": normalized,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    tmp.replace(path)
    return payload


def load_roster_cache(path=None, now=None):
    """Return a fresh, usable roster cache and non-sensitive cache metadata."""
    path = Path(path) if path else ROSTER_CACHE_PATH
    now = now or datetime.now(timezone.utc)
    meta = {"status": "miss", "usable": False, "member_count": 0}
    if not path.exists():
        return None, meta
    try:
        payload = json.loads(path.read_text())
        fetched_at = payload.get("fetched_at")
        fetched_dt = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        age = now - fetched_dt
        members = payload.get("members")
        usable = (
            payload.get("list_id") == SOURCE_LIST_ID
            and isinstance(members, list)
            and bool(members)
            and all(m.get("id") and m.get("username") for m in members)
            and timedelta(0) <= age <= ROSTER_CACHE_MAX_AGE
        )
        meta = {
            "status": "hit" if usable else "stale_or_invalid",
            "usable": usable,
            "fetched_at": fetched_at,
            "age_days": round(age.total_seconds() / 86400, 3),
            "member_count": len(members) if isinstance(members, list) else 0,
        }
        if usable:
            _populate_known_accounts(members)
            return members, meta
    except Exception:
        meta = {"status": "invalid", "usable": False, "member_count": 0}
    return None, meta


def invalidate_roster_cache(path=None):
    """Remove cached roster data and return non-sensitive status metadata."""
    path = Path(path) if path else ROSTER_CACHE_PATH
    try:
        if not path.exists():
            return {"status": "already_absent", "invalidated": False}
        path.unlink()
        return {"status": "invalidated", "invalidated": True}
    except Exception as exc:
        return {
            "status": "invalidation_failed",
            "invalidated": False,
            "error_type": type(exc).__name__,
        }


def get_list_roster(force_refresh=False, path=None):
    """Load the 30-day roster cache or refresh it from the list-members API."""
    path = Path(path) if path else ROSTER_CACHE_PATH
    if not force_refresh:
        members, meta = load_roster_cache(path)
        if members:
            return members, meta
    members = fetch_list_members(return_metadata=True)
    if members is None:
        return None, {"status": "refresh_failed", "usable": False, "member_count": 0}
    payload = save_roster_cache(members, path=path)
    members = payload["members"]
    _populate_known_accounts(members)
    return members, {
        "status": "refreshed",
        "usable": bool(members),
        "fetched_at": payload["fetched_at"],
        "age_days": 0.0,
        "member_count": len(members),
    }


def _max_tweet_id(tweets):
    ids = []
    for t in tweets:
        tid = str(t.get("id", ""))
        if tid.isdigit():
            ids.append(int(tid))
    return str(max(ids)) if ids else None


def fetch_tweets(bearer, user_id, max_results=20, since_id=None, cutoff=None, page_limit=5):
    """Fetch recent tweets excluding retweets/replies with pagination safeguards.

    Optimization strategy:
    - If since_id is available from prior successful run, ask X only for newer tweets.
    - Otherwise scan the requested time window and paginate only while the page is still inside it.
    - Keep a page cap so one high-volume/news account cannot burn the whole read budget.
    """
    url = f"https://api.x.com/2/users/{user_id}/tweets"
    per_page = max(5, min(max_results, 100))
    base_params = {
        "max_results": per_page,
        "tweet.fields": "created_at,public_metrics,entities,note_tweet",
        "exclude": "retweets,replies",
    }
    if since_id:
        base_params["since_id"] = since_id

    all_tweets = []
    pages = 0
    next_token = None
    stopped_reason = None

    while pages < page_limit:
        params = dict(base_params)
        if next_token:
            params["pagination_token"] = next_token
        req = urllib.request.Request(
            f"{url}?{urllib.parse.urlencode(params)}",
            headers={"Authorization": f"Bearer {bearer}"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                payload = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 401:
                if _refresh_bearer():
                    req = urllib.request.Request(
                        f"{url}?{urllib.parse.urlencode(params)}",
                        headers={"Authorization": f"Bearer {_bearer()}"}
                    )
                    try:
                        with urllib.request.urlopen(req, timeout=15) as resp:
                            payload = json.loads(resp.read().decode())
                    except urllib.error.HTTPError as e2:
                        return {"error": f"HTTP {e2.code}: {e2.reason}", "detail": e2.read().decode()[:300]}
                    except Exception as e2:
                        return {"error": str(e2)}
                else:
                    return {"error": f"HTTP {e.code}: {e.reason}", "detail": e.read().decode()[:300]}
            else:
                return {"error": f"HTTP {e.code}: {e.reason}", "detail": e.read().decode()[:300]}
        except Exception as e:
            return {"error": str(e)}

        pages += 1
        tweets = payload.get("data", [])
        all_tweets.extend(tweets)

        meta = payload.get("meta", {})
        next_token = meta.get("next_token")
        if not next_token:
            stopped_reason = "end"
            break

        # If we are doing a full time-window scan, stop once the oldest page item is older than cutoff.
        # With since_id, keep paginating until no more new tweets or page_limit.
        if cutoff and not since_id and tweets:
            oldest = None
            for t in tweets:
                created_at = t.get("created_at")
                if created_at:
                    dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    oldest = dt if oldest is None else min(oldest, dt)
            if oldest and oldest < cutoff:
                stopped_reason = "cutoff_reached"
                break

    if pages >= page_limit and next_token:
        stopped_reason = "page_limit"
    return {
        "tweets": all_tweets,
        "meta": {
            "pages": pages,
            "tweets_fetched": len(all_tweets),
            "since_id_used": bool(since_id),
            "stopped_reason": stopped_reason or "unknown",
            "page_limit": page_limit,
        }
    }

def resolve_user_id(username):
    """Look up user ID by username."""
    if username in KNOWN_ACCOUNTS:
        return KNOWN_ACCOUNTS[username][0]
    url = f"https://api.x.com/2/users/by/username/{username}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {_bearer()}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("data", {}).get("id")
    except urllib.error.HTTPError as e:
        if e.code == 401 and _refresh_bearer():
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {_bearer()}"})
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                    return data.get("data", {}).get("id")
            except Exception:
                return None
        return None
    except Exception:
        return None


def fetch_list_members(bearer=None, list_id=None, return_metadata=False):
    """Fetch all list members as usernames or complete profile metadata."""
    if not list_id:
        list_id = SOURCE_LIST_ID

    url = f"https://api.x.com/2/lists/{list_id}/members"
    base_params = {
        "max_results": 100,
        "user.fields": "public_metrics,description",
    }

    last_error = None
    tokens = _list_auth_tokens(bearer)
    for token in tokens:
        members = []
        params = urllib.parse.urlencode(base_params)

        # Paginate (max 100 per request, up to 5000 total)
        for _ in range(50):
            req = urllib.request.Request(
                f"{url}?{params}",
                headers={"Authorization": f"Bearer {token}"}
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read())
                    for user in data.get("data", []):
                        username = user["username"]
                        members.append({
                            "id": str(user["id"]),
                            "username": username,
                            "name": user.get("name", username),
                            "description": user.get("description") or "",
                            "public_metrics": user.get("public_metrics") or {},
                            "style": _guess_style(user),
                        })

                    meta = data.get("meta", {})
                    next_token = meta.get("next_token")
                    if not next_token:
                        _populate_known_accounts(members)
                        if return_metadata:
                            return members
                        return [user["username"] for user in members]
                    params = urllib.parse.urlencode({
                        **base_params,
                        "pagination_token": next_token,
                    })
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")[:500]
                last_error = f"HTTP {e.code} fetching list: {body}"
                if e.code == 401 and token == BEARER_TOKEN and _refresh_bearer():
                    # A refreshed token is a new auth attempt and must restart at page 1.
                    if BEARER_TOKEN not in tokens:
                        tokens.append(BEARER_TOKEN)
                # Never return a partial traversal. Any available token retries from page 1.
                break
            except Exception as e:
                last_error = f"List fetch error: {e}"
                # Never return a partial traversal. Any available token retries from page 1.
                break

        else:
            last_error = "List fetch error: pagination exceeded 50 pages"

        # Continue to the next auth token, if any. `members` is discarded so the
        # traversal always restarts from page 1 rather than mixing partial pages.
        continue

    if last_error:
        print(json.dumps({"error": last_error}), file=sys.stderr)
    return None

def fetch_list_tweets(bearer=None, list_id=None, max_results=100, cutoff=None, page_limit=15,
                      users_by_id=None):
    """Fetch tweets from the source List timeline.

    This is the read-optimized path: one paginated list-timeline scan instead of
    one user-timeline request per analyst. The List remains the source of truth.
    """
    if not list_id:
        list_id = SOURCE_LIST_ID
    url = f"https://api.x.com/2/lists/{list_id}/tweets"
    per_page = max(50, min(max_results, 100))
    cached_users_by_id = dict(users_by_id or {})
    base_params = {
        "max_results": per_page,
        "tweet.fields": "created_at,public_metrics,entities,note_tweet,author_id,referenced_tweets",
    }
    if not cached_users_by_id:
        # One-time fallback when there is no usable roster cache.
        base_params.update({
            "expansions": "author_id",
            "user.fields": "username,name,description,public_metrics",
        })

    last_error = None
    for auth_attempt, token in enumerate(_list_auth_tokens(bearer), start=1):
        all_tweets = []
        response_users_by_id = dict(cached_users_by_id)
        pages = 0
        next_token = None
        stopped_reason = None

        while pages < page_limit:
            params = dict(base_params)
            if next_token:
                params["pagination_token"] = next_token
            req = urllib.request.Request(
                f"{url}?{urllib.parse.urlencode(params)}",
                headers={"Authorization": f"Bearer {token}"}
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    payload = json.loads(resp.read())
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")[:500]
                last_error = f"HTTP {e.code} fetching list tweets: {body}"
                if e.code in (401, 403) and auth_attempt < len(_list_auth_tokens(bearer)):
                    break
                print(json.dumps({"error": last_error}), file=sys.stderr)
                return None
            except Exception as e:
                last_error = f"List tweets fetch error: {e}"
                if auth_attempt < len(_list_auth_tokens(bearer)):
                    break
                print(json.dumps({"error": last_error}), file=sys.stderr)
                return None

            pages += 1
            for user in payload.get("includes", {}).get("users", []):
                response_users_by_id[user["id"]] = user
                username = user.get("username")
                if username and username not in KNOWN_ACCOUNTS:
                    KNOWN_ACCOUNTS[username] = (user["id"], user.get("name", username), _guess_style(user))

            tweets = payload.get("data", [])
            all_tweets.extend(tweets)

            meta = payload.get("meta", {})
            next_token = meta.get("next_token")
            if not next_token:
                stopped_reason = "end"
                break

            if cutoff and tweets:
                oldest = None
                for t in tweets:
                    created_at = t.get("created_at")
                    if created_at:
                        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                        oldest = dt if oldest is None else min(oldest, dt)
                if oldest and oldest < cutoff:
                    stopped_reason = "cutoff_reached"
                    break

        if pages == 0 and last_error and auth_attempt < len(_list_auth_tokens(bearer)):
            # Current auth mode was rejected before any data; try the next token.
            continue
        if pages >= page_limit and next_token:
            stopped_reason = "page_limit"
        return {
            "tweets": all_tweets,
            "users_by_id": response_users_by_id,
            "meta": {
                "pages": pages,
                "tweets_fetched": len(all_tweets),
                "stopped_reason": stopped_reason or "unknown",
                "page_limit": page_limit,
                "read_path": "list_timeline",
                "author_mapping_source": "roster_cache" if cached_users_by_id else "timeline_expansion_fallback",
            }
        }

    if last_error:
        print(json.dumps({"error": last_error}), file=sys.stderr)
    return None


def _guess_style(user):
    """Guess account style from description/bio."""
    desc = (user.get("description") or "").lower()
    if any(w in desc for w in ["option", "flow", "dark pool", "gamma", "unusual"]):
        return "options_flow"
    if any(w in desc for w in ["photonics", "optic", "coherent", "lumentum"]):
        return "photonics_dd"
    if any(w in desc for w in ["semiconductor", "semi ", "chip", "nvidia", "ai infra"]):
        return "ai_infrastructure"
    if any(w in desc for w in ["space", "rocket", "aerospace", "satellite"]):
        return "space_economy"
    if any(w in desc for w in ["gold", "macro", "fiat", "dollar", "treasury", "fed"]):
        return "macro_gold"
    if any(w in desc for w in ["supply chain", "bottleneck", "component"]):
        return "supply_chain"
    if any(w in desc for w in ["engineering", "technical", "patent"]):
        return "engineering_dd"
    if any(w in desc for w in ["news", "price", "watcher", "alert"]):
        return "news_aggregator"
    return "thesis"


def add_to_list(username, user_id=None, list_id=None, token=None):
    """Add a user to the source X list. Requires user-context OAuth (CalConviction)."""
    if not list_id:
        list_id = SOURCE_LIST_ID
    if not token:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from calconviction import get_access_token
            token = get_access_token()
        except Exception:
            return {"error": "No CalConviction OAuth token available for list management"}

    if not user_id:
        user_id = resolve_user_id(username)
        if not user_id:
            return {"error": f"Could not resolve user ID for @{username}"}

    url = f"https://api.x.com/2/lists/{list_id}/members"
    body = json.dumps({"user_id": user_id}).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            return {"success": True, "username": username, "user_id": user_id, "list_id": list_id}
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:300]
        # 409 = already a member, treat as success
        if e.code == 409 or "already a member" in detail:
            return {"success": True, "username": username, "user_id": user_id, "already_member": True}
        return {"error": f"HTTP {e.code}: {detail}"}
    except Exception as e:
        return {"error": str(e)}


def follow_user(username, user_id=None, token=None):
    """Follow a user from CalConviction's account. Requires user-context OAuth."""
    if not token:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from calconviction import get_access_token, api_call
            token = get_access_token()
        except Exception:
            return {"error": "No CalConviction OAuth token available"}

    if not user_id:
        user_id = resolve_user_id(username)
        if not user_id:
            return {"error": f"Could not resolve user ID for @{username}"}

    # Get CalConviction's user ID
    url = "https://api.x.com/2/users/me"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            me = json.loads(resp.read())
            my_id = me["data"]["id"]
    except Exception:
        return {"error": "Could not resolve authenticated user ID"}

    url = f"https://api.x.com/2/users/{my_id}/following"
    body = json.dumps({"target_user_id": user_id}).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return {"success": True, "username": username, "user_id": user_id}
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:300]
        if e.code == 409 or "already" in detail.lower():
            return {"success": True, "username": username, "user_id": user_id, "already_following": True}
        return {"error": f"HTTP {e.code}: {detail}"}
    except Exception as e:
        return {"error": str(e)}


def onboard_account(username, user_id=None, roster_cache_path=None):
    """Onboard a new account: follow + add to source list. Single action."""
    results = {"username": username}
    r1 = add_to_list(username, user_id)
    results["add_to_list"] = r1
    add_confirmed = r1.get("success", False) or r1.get("already_member", False)
    if add_confirmed:
        results["roster_cache"] = invalidate_roster_cache(roster_cache_path)
    else:
        results["roster_cache"] = {
            "status": "unchanged",
            "invalidated": False,
            "reason": "add_not_confirmed",
        }
    r2 = follow_user(username, user_id)
    results["follow"] = r2
    results["success"] = add_confirmed
    return results


def extract_cashtags(tweet):
    """Extract unique cashtags from tweet entities and text."""
    tags = set()
    for cashtag in tweet.get("entities", {}).get("cashtags", []):
        tags.add(cashtag["tag"].upper())
    text = tweet.get("text", "")
    tags.update(m.upper() for m in re.findall(r'\$([A-Z]{1,5})\b', text))
    return sorted(tags)


def get_full_text(tweet):
    """Get full tweet text, preferring note_tweet for long-form."""
    nt = tweet.get("note_tweet")
    if nt and "text" in nt:
        return nt["text"]
    return tweet.get("text", "")


def classify_ticker(ticker, tweets_with_ticker, style="supply_chain"):
    """
    Classify a ticker based on how it's discussed.
    Returns (category, reasons, conviction_score).
    """
    reasons = []
    score = 0
    texts = [get_full_text(t) for t in tweets_with_ticker]
    combined = " ".join(texts).lower()
    total_likes = sum(t.get("public_metrics", {}).get("like_count", 0) for t in tweets_with_ticker)
    mention_count = len(tweets_with_ticker)
    total_bookmarks = sum(t.get("public_metrics", {}).get("bookmark_count", 0) for t in tweets_with_ticker)
    total_engagement = total_likes + total_bookmarks

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

    # Thesis depth
    long_posts = sum(1 for t in texts if len(t) > 500)
    if long_posts >= 1:
        score += 2
        reasons.append(f"{long_posts} long-form thesis post(s)")

    # Supply chain mapping
    sc_markers = ["->", "→", "pass through", "bottleneck", "supply chain",
                  "funnel", "pipeline", "mapping"]
    if any(m in combined for m in sc_markers):
        score += 2
        reasons.append("supply chain mapping")

    # Bullish language
    bullish = ["buy", "bullish", "long", "conviction", "putting", "position", "loaded",
               "undervalued", "mispriced", "setup", "thesis", "breaking out", "ramp",
               "volume", "order", "contract", "agreement", "partnership", "customer",
               "called", "10x", "next"]
    bullish_hits = sum(1 for w in bullish if w in combined)
    if bullish_hits >= 2:
        score += 1
        reasons.append("bullish language")

    # Momentum-style hype (for accounts like midascabal)
    if style == "momentum":
        hype = ["crash", "generational", "bagholder", "rugpull", "manipulated", "euphoria"]
        if sum(1 for w in hype if w in combined) >= 2:
            score -= 1
            reasons.append("fear/hype posting (context-dependent)")

    # Speculative signals
    speculative = ["speculative", "bet", "risky", "small cap", "micro cap", "early",
                   "unproven", "binary", "lottery", "moon"]
    if sum(1 for w in speculative if w in combined) >= 1:
        score -= 1
        reasons.append("speculative language noted")

    # Bearish
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


def process_account(username, hours, max_results, state=None, use_state=True, page_limit=5):
    """Process a single account and return classified ticker data."""
    user_id = resolve_user_id(username)
    if not user_id:
        return {"error": f"Could not resolve user ID for @{username}"}

    _, display_name, style = KNOWN_ACCOUNTS.get(
        username, (user_id, username, "supply_chain")
    )

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    account_state = (state or {}).get("accounts", {}).get(username, {}) if use_state else {}
    since_id = account_state.get("last_seen_id") if use_state else None

    fetched = fetch_tweets(
        _bearer(),
        user_id,
        max_results=max_results,
        since_id=since_id,
        cutoff=cutoff,
        page_limit=page_limit,
    )
    if isinstance(fetched, dict) and "error" in fetched:
        return {"error": fetched}

    tweets = fetched.get("tweets", [])
    fetch_meta = fetched.get("meta", {})
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
                "url": f"https://x.com/{username}/status/{t['id']}",
            })

    newest_id = _max_tweet_id(tweets)
    result_base = {
        "username": username,
        "display_name": display_name,
        "fetch_meta": fetch_meta,
        "newest_id": newest_id,
    }

    if not recent:
        return {
            **result_base,
            "total_tweets": 0,
            "unique_tickers": 0,
            "tickers": {},
            "raw_tweets": [],
        }

    ticker_tweets = defaultdict(list)
    for t in recent:
        for tag in t["cashtags"]:
            ticker_tweets[tag].append(t)

    classified = {}
    for ticker, t_tweets in sorted(ticker_tweets.items(), key=lambda x: -len(x[1])):
        category, reasons, score = classify_ticker(ticker, t_tweets, style)
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

    cat_order = {"CONVICTION": 0, "BULLISH": 1, "RADAR": 2, "WATCH": 3, "AVOID": 4}
    sorted_tickers = dict(sorted(
        classified.items(),
        key=lambda x: (cat_order.get(x[1]["category"], 9), -x[1]["score"])
    ))

    return {
        **result_base,
        "total_tweets": len(recent),
        "unique_tickers": len(sorted_tickers),
        "tickers": sorted_tickers,
        "raw_tweets": [
            {
                "text": t["text"][:500],
                "cashtags": t["cashtags"],
                "likes": t["likes"],
                "bookmarks": t.get("bookmarks", 0),
                "url": t["url"],
                "created_at": t["created_at"],
            }
            for t in sorted(recent, key=lambda x: -x["likes"])
        ],
    }

def _is_retweet_or_reply(tweet):
    for ref in tweet.get("referenced_tweets", []) or []:
        if ref.get("type") in ("retweeted", "replied_to"):
            return True
    text = tweet.get("text", "")
    return text.startswith("RT @")


def process_list_timeline(accounts, hours, max_results=100, page_limit=15, roster_members=None):
    """Process all accounts from one List timeline scan."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    roster_id_map = {
        str(user["id"]): user for user in (roster_members or [])
        if user.get("id") and user.get("username")
    }
    fetched = fetch_list_tweets(
        max_results=max_results,
        cutoff=cutoff,
        page_limit=page_limit,
        users_by_id=roster_id_map or None,
    )
    if not fetched:
        return None, {"error": "Failed to fetch list timeline"}

    users_by_id = fetched.get("users_by_id", {})
    grouped = defaultdict(list)
    skipped_retweets_replies = 0
    out_of_window = 0
    newest_id = _max_tweet_id(fetched.get("tweets", []))

    for t in fetched.get("tweets", []):
        if _is_retweet_or_reply(t):
            skipped_retweets_replies += 1
            continue
        created_at = t.get("created_at")
        if not created_at:
            continue
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if created < cutoff:
            out_of_window += 1
            continue
        user = users_by_id.get(t.get("author_id"), {})
        username = user.get("username")
        if not username:
            continue
        grouped[username].append(t)

    results = {}
    for account in accounts:
        user_id, display_name, style = KNOWN_ACCOUNTS.get(account, (None, account, "supply_chain"))
        recent = []
        for t in grouped.get(account, []):
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
                "url": f"https://x.com/{account}/status/{t['id']}",
            })

        result_base = {
            "username": account,
            "display_name": display_name,
            "fetch_meta": {"read_path": "list_timeline"},
            "newest_id": _max_tweet_id(grouped.get(account, [])),
        }
        if not recent:
            results[account] = {
                **result_base,
                "total_tweets": 0,
                "unique_tickers": 0,
                "tickers": {},
                "raw_tweets": [],
            }
            continue

        ticker_tweets = defaultdict(list)
        for t in recent:
            for tag in t["cashtags"]:
                ticker_tweets[tag].append(t)

        classified = {}
        for ticker, t_tweets in sorted(ticker_tweets.items(), key=lambda x: -len(x[1])):
            category, reasons, score = classify_ticker(ticker, t_tweets, style)
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

        cat_order = {"CONVICTION": 0, "BULLISH": 1, "RADAR": 2, "WATCH": 3, "AVOID": 4}
        sorted_tickers = dict(sorted(
            classified.items(),
            key=lambda x: (cat_order.get(x[1]["category"], 9), -x[1]["score"])
        ))
        results[account] = {
            **result_base,
            "total_tweets": len(recent),
            "unique_tickers": len(sorted_tickers),
            "tickers": sorted_tickers,
            "raw_tweets": [
                {
                    "text": t["text"][:500],
                    "cashtags": t["cashtags"],
                    "likes": t["likes"],
                    "bookmarks": t.get("bookmarks", 0),
                    "url": t["url"],
                    "created_at": t["created_at"],
                }
                for t in sorted(recent, key=lambda x: -x["likes"])
            ],
        }

    meta = fetched.get("meta", {})
    meta.update({
        "tweets_in_window": sum(r.get("total_tweets", 0) for r in results.values()),
        "skipped_retweets_replies": skipped_retweets_replies,
        "out_of_window": out_of_window,
        "newest_id": newest_id,
    })
    return results, meta


def main():
    args = sys.argv[1:]
    hours = 24
    # Cost-safe defaults for X's per-resource pricing. Cron jobs may override these
    # explicitly, but ad-hoc/manual runs should not accidentally pull a large slice
    # of the list timeline.
    max_results = 50
    page_limit = 2
    accounts = None  # None = fetch from X list (source of truth)
    accounts_explicit = False
    use_state = True
    state_path = STATE_PATH
    read_path = "list_timeline"  # optimized default: one list timeline scan, not N user timeline reads
    allow_list_scan = False
    allow_list_scan_source = None
    refresh_roster = False
    list_members_only = False
    roster_members = None
    roster_cache_meta = {"status": "not_used", "usable": False, "member_count": 0}

    # Parse CLI args
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--hours" and i + 1 < len(args):
            hours = int(args[i + 1])
            i += 2
        elif arg == "--max" and i + 1 < len(args):
            max_results = int(args[i + 1])
            i += 2
        elif arg == "--page-limit" and i + 1 < len(args):
            page_limit = int(args[i + 1])
            i += 2
        elif arg == "--per-account":
            read_path = "per_account"
            i += 1
        elif arg == "--allow-list-scan":
            allow_list_scan = True
            allow_list_scan_source = "cli"
            i += 1
        elif arg == "--refresh-roster":
            refresh_roster = True
            i += 1
        elif arg in ("--no-state", "--full-window"):
            use_state = False
            i += 1
        elif arg == "--state-path" and i + 1 < len(args):
            state_path = Path(args[i + 1])
            i += 2
        elif arg == "--accounts" and i + 1 < len(args):
            accounts = [a.strip() for a in args[i + 1].split(",") if a.strip()]
            accounts_explicit = True
            read_path = "per_account"
            i += 2
        elif arg == "--add-to-list" and i + 1 < len(args):
            # Onboard: add to list + follow
            usernames = [a.strip().lstrip("@") for a in args[i + 1].split(",")]
            results = []
            for u in usernames:
                r = onboard_account(u)
                results.append(r)
                print(json.dumps(r))
            return
        elif arg == "--list-members":
            list_members_only = True
            refresh_roster = True
            i += 1
        else:
            i += 1

    env_allows_list_scan = os.environ.get("HERMES_X_SCANNER_ALLOWED") == "1"
    if env_allows_list_scan and not allow_list_scan:
        allow_list_scan = True
        allow_list_scan_source = "environment"

    # An explicit roster refresh is permitted independently of the paid timeline
    # guard. Persist it first, then still refuse the timeline unless separately allowed.
    if refresh_roster and not list_members_only:
        if not _bearer():
            print(json.dumps({"error": "No X_BEARER_TOKEN found in ~/.hermes/.env"}))
            sys.exit(1)
        roster_members, roster_cache_meta = get_list_roster(force_refresh=True)
        if roster_members is None:
            print(json.dumps({"error": "Failed to refresh list members"}))
            sys.exit(1)

    # The paid List timeline is a singleton collector. Ordinary default runs are
    # refused before any roster or timeline API request.
    if read_path == "list_timeline" and not accounts_explicit and not list_members_only and not allow_list_scan:
        print(json.dumps({
            "error": (
                "Default X List timeline scan refused. Pass --allow-list-scan or set "
                "HERMES_X_SCANNER_ALLOWED=1 for the canonical scanner; other jobs must "
                "consume the latest saved artifact under raw/signals/x_signals_*.json."
            ),
            "scan_stats": {
                "list_scan_guard": {
                    "required": True,
                    "allowed": False,
                    "source": None,
                },
                "roster_cache": roster_cache_meta,
            },
        }))
        sys.exit(2)

    if not _bearer():
        print(json.dumps({"error": "No X_BEARER_TOKEN found in ~/.hermes/.env"}))
        sys.exit(1)

    if list_members_only:
        roster_members, roster_cache_meta = get_list_roster(force_refresh=True)
        if roster_members is None:
            print(json.dumps({"error": "Failed to fetch list members"}))
            sys.exit(1)
        print(json.dumps({
            "list_id": SOURCE_LIST_ID,
            "member_count": len(roster_members),
            "members": sorted(user["username"] for user in roster_members),
            "scan_stats": {"roster_cache": roster_cache_meta},
        }))
        return

    # Fetch accounts from X list if not explicitly specified. This is the source-of-truth roster.
    if accounts is None:
        if roster_members is None:
            roster_members, roster_cache_meta = get_list_roster(force_refresh=refresh_roster)
        if roster_members is None:
            print(json.dumps({"error": "Failed to fetch list members, and no --accounts provided"}))
            sys.exit(1)
        accounts = [user["username"] for user in roster_members]
        if not accounts:
            print(json.dumps({"error": "X list is empty", "list_id": SOURCE_LIST_ID}))
            sys.exit(1)

    if read_path == "list_timeline" and not accounts_explicit:
        results, meta = process_list_timeline(
            accounts,
            hours,
            max_results=max_results,
            page_limit=page_limit,
            roster_members=roster_members,
        )
        if results is None:
            print(json.dumps(meta))
            sys.exit(1)
        scan_stats = {
            "mode": "list_timeline_full_window",
            "max_results_per_page": max(50, min(max_results, 100)),
            "page_limit": page_limit,
            "api_pages": meta.get("pages", 0),
            "tweets_fetched": meta.get("tweets_fetched", 0),
            "tweets_in_window": meta.get("tweets_in_window", 0),
            "skipped_retweets_replies": meta.get("skipped_retweets_replies", 0),
            "out_of_window": meta.get("out_of_window", 0),
            "account_errors": 0,
            "page_limit_hit": meta.get("stopped_reason") == "page_limit",
            "stopped_reason": meta.get("stopped_reason"),
            "author_mapping_source": meta.get("author_mapping_source"),
            "roster_cache": roster_cache_meta,
            "list_scan_guard": {
                "required": True,
                "allowed": True,
                "source": allow_list_scan_source,
            },
        }
    else:
        state = load_state(state_path) if use_state else {"accounts": {}}
        results = {}
        scan_stats = {
            "mode": "per_account_incremental_since_last" if use_state else "per_account_full_window",
            "max_results_per_page": max_results,
            "page_limit_per_account": page_limit,
            "api_pages": 0,
            "tweets_fetched": 0,
            "tweets_in_window": 0,
            "account_errors": 0,
            "page_limit_accounts": [],
            "roster_cache": roster_cache_meta,
            "list_scan_guard": {
                "required": False,
                "allowed": True,
                "source": "not_applicable",
            },
        }

        for account in accounts:
            result = process_account(account, hours, max_results, state=state, use_state=use_state, page_limit=page_limit)
            results[account] = result
            if isinstance(result, dict) and "error" in result:
                scan_stats["account_errors"] += 1
                continue
            meta = result.get("fetch_meta", {}) if isinstance(result, dict) else {}
            scan_stats["api_pages"] += meta.get("pages", 0)
            scan_stats["tweets_fetched"] += meta.get("tweets_fetched", 0)
            scan_stats["tweets_in_window"] += result.get("total_tweets", 0)
            if meta.get("stopped_reason") == "page_limit":
                scan_stats["page_limit_accounts"].append(account)
            newest_id = result.get("newest_id") if isinstance(result, dict) else None
            if use_state and newest_id:
                state.setdefault("accounts", {}).setdefault(account, {})
                state["accounts"][account].update({
                    "user_id": KNOWN_ACCOUNTS.get(account, (None,))[0],
                    "last_seen_id": newest_id,
                    "last_success_at": datetime.now(timezone.utc).isoformat(),
                })

        if use_state and scan_stats["account_errors"] == 0:
            state.update({
                "source_list": SOURCE_LIST_ID,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "account_count": len(accounts),
            })
            save_state(state, state_path)

    output = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "hours_scanned": hours,
        "source_list": SOURCE_LIST_ID,
        "account_count": len(accounts),
        "read_path": read_path,
        "accounts_source": "x_list" if not accounts_explicit else "explicit_accounts",
        "scan_stats": scan_stats,
        "accounts": results,
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
