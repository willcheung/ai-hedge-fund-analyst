#!/usr/bin/env python3
"""
X Referral Graph Discovery — find high-signal accounts repeatedly cited by tracked analysts.

Default: read the source X List timeline, inspect quote/reply/mention edges from tracked
accounts to untracked accounts, and rank candidates for the account-discovery pipeline.

This does NOT auto-add accounts. It produces a candidate list with evidence.
"""
from automation_paths import configured_text
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
import urllib.error
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

SOURCE_LIST_ID = os.environ.get("X_SOURCE_LIST_ID", "")
# Cost-safe default: the referral graph is a sampling tool, not an exhaustive
# archive. Override deliberately with --page-limit only for one-off audits.
DEFAULT_PAGE_LIMIT = 4
DEFAULT_HOURS = 168

NOISE_HANDLES = {
    "youtube", "x", "twitter", "elonmusk", "openai", "nvidia", "apple", "microsoft",
    "google", "meta", "amazon", "secgov", "nasdaq", "nyse", "bloomberg", "cnbc",
    "wsj", "reuters", "ft", "business", "unusual_whales",
}


def load_env_file():
    env = {}
    p = Path(os.path.expanduser(configured_text('${ANALYST_HERMES_HOME}/.env')))
    if p.exists():
        for line in p.read_text(errors="replace").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def get_oauth_token():
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from calconviction import get_access_token
        return get_access_token()
    except BaseException:
        # calconviction.get_access_token() can sys.exit() when the refresh token is
        # invalid. Referral-graph reads should still proceed with X_BEARER_TOKEN.
        return ""


def auth_tokens():
    env = load_env_file()
    tokens = []
    oauth = get_oauth_token() or env.get("X_OAUTH2_ACCESS_TOKEN", "")
    bearer = env.get("X_BEARER_TOKEN", "") or os.environ.get("X_BEARER_TOKEN", "")
    for label, tok in (("oauth", oauth), ("bearer", bearer)):
        if tok and tok not in [t for _, t in tokens]:
            tokens.append((label, tok))
    return tokens


def api_get(path, params=None, timeout=20):
    last = None
    url = f"https://api.x.com/2{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    for label, token in auth_tokens():
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read()), label
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:500]
            last = {"auth": label, "status": e.code, "body": body}
            if e.code in (401, 403):
                continue
            raise RuntimeError(f"HTTP {e.code} {path}: {body}")
    raise RuntimeError(f"All auth modes failed for {path}: {last}")


def get_list_members(list_id=SOURCE_LIST_ID):
    members = {}
    pagination = None
    while True:
        params = {
            "max_results": 100,
            "user.fields": "id,username,name,description,public_metrics,verified,created_at",
        }
        if pagination:
            params["pagination_token"] = pagination
        data, auth = api_get(f"/lists/{list_id}/members", params)
        for u in data.get("data", []) or []:
            members[u["id"]] = u
        pagination = data.get("meta", {}).get("next_token")
        if not pagination:
            return members, auth


def fetch_list_timeline(list_id=SOURCE_LIST_ID, hours=DEFAULT_HOURS, page_limit=DEFAULT_PAGE_LIMIT):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    tweets = []
    users = {}
    referenced_tweets = {}
    next_token = None
    pages = 0
    stopped_reason = None
    auth_used = None
    while pages < page_limit:
        params = {
            "max_results": 100,
            "tweet.fields": "created_at,public_metrics,entities,note_tweet,author_id,referenced_tweets,conversation_id",
            "expansions": "author_id,referenced_tweets.id,referenced_tweets.id.author_id",
            "user.fields": "id,username,name,description,public_metrics,verified,created_at",
        }
        if next_token:
            params["pagination_token"] = next_token
        data, auth_used = api_get(f"/lists/{list_id}/tweets", params)
        pages += 1
        for u in data.get("includes", {}).get("users", []) or []:
            users[u["id"]] = u
        for rt in data.get("includes", {}).get("tweets", []) or []:
            referenced_tweets[rt["id"]] = rt
        page_tweets = data.get("data", []) or []
        tweets.extend(page_tweets)
        if page_tweets:
            oldest = min(datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")) for t in page_tweets if t.get("created_at"))
            if oldest < cutoff:
                stopped_reason = "cutoff_reached"
                break
        next_token = data.get("meta", {}).get("next_token")
        if not next_token:
            stopped_reason = "end_of_timeline"
            break
    if pages >= page_limit and next_token and not stopped_reason:
        stopped_reason = "page_limit"
    return {
        "tweets": tweets,
        "users": users,
        "referenced_tweets": referenced_tweets,
        "pages": pages,
        "auth": auth_used,
        "page_limit_hit": stopped_reason == "page_limit",
        "stopped_reason": stopped_reason,
    }


def full_text(tweet):
    nt = tweet.get("note_tweet") or {}
    return nt.get("text") or tweet.get("text") or ""


def engagement(tweet):
    m = tweet.get("public_metrics", {}) or {}
    return {
        "likes": m.get("like_count", 0),
        "bookmarks": m.get("bookmark_count", 0),
        "replies": m.get("reply_count", 0),
        "retweets": m.get("retweet_count", 0),
        "views": m.get("impression_count", 0),
    }


def candidate_record(user):
    pm = user.get("public_metrics", {}) or {}
    return {
        "user_id": user.get("id"),
        "username": user.get("username", "unknown"),
        "name": user.get("name", ""),
        "bio": user.get("description", ""),
        "followers": pm.get("followers_count", 0),
        "verified": user.get("verified", False),
        "referrers": set(),
        "edge_types": Counter(),
        "total_source_likes": 0,
        "total_source_bookmarks": 0,
        "total_source_views": 0,
        "examples": [],
    }


def add_edge(candidates, candidate_user, referrer_user, edge_type, source_tweet):
    if not candidate_user or not candidate_user.get("username"):
        return
    handle = candidate_user["username"].lower()
    if handle in NOISE_HANDLES:
        return
    if handle not in candidates:
        candidates[handle] = candidate_record(candidate_user)
    rec = candidates[handle]
    ref_handle = referrer_user.get("username", "unknown")
    rec["referrers"].add(ref_handle)
    rec["edge_types"][edge_type] += 1
    m = engagement(source_tweet)
    rec["total_source_likes"] += m["likes"]
    rec["total_source_bookmarks"] += m["bookmarks"]
    rec["total_source_views"] += m["views"]
    if len(rec["examples"]) < 5:
        rec["examples"].append({
            "referrer": ref_handle,
            "edge_type": edge_type,
            "source_url": f"https://x.com/{ref_handle}/status/{source_tweet.get('id')}",
            "created_at": source_tweet.get("created_at"),
            "likes": m["likes"],
            "bookmarks": m["bookmarks"],
            "text": full_text(source_tweet)[:500],
        })


def build_graph(hours=DEFAULT_HOURS, page_limit=DEFAULT_PAGE_LIMIT, min_referrers=2):
    members, member_auth = get_list_members()
    tracked_ids = set(members.keys())
    tracked_handles = {u["username"].lower() for u in members.values()}
    timeline = fetch_list_timeline(hours=hours, page_limit=page_limit)
    users = timeline["users"]
    referenced = timeline["referenced_tweets"]
    candidates = {}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    in_window = 0

    for t in timeline["tweets"]:
        created = datetime.fromisoformat(t["created_at"].replace("Z", "+00:00"))
        if created < cutoff:
            continue
        in_window += 1
        author = users.get(t.get("author_id")) or members.get(t.get("author_id"))
        if not author or author.get("id") not in tracked_ids:
            continue

        # Strong edges: quote/reply/retweet references with author expansion.
        for ref in t.get("referenced_tweets", []) or []:
            ref_tweet = referenced.get(ref.get("id"), {})
            ref_author_id = ref_tweet.get("author_id")
            if ref_author_id and ref_author_id not in tracked_ids:
                cand = users.get(ref_author_id)
                add_edge(candidates, cand, author, ref.get("type", "referenced"), t)

        # Weak edges: explicit @mentions in source tweets.
        for mention in (t.get("entities", {}) or {}).get("mentions", []) or []:
            mid = mention.get("id")
            uname = (mention.get("username") or "").lower()
            if not uname or uname in tracked_handles or mid in tracked_ids:
                continue
            cand = users.get(mid) or {"id": mid, "username": mention.get("username"), "name": mention.get("username"), "public_metrics": {}}
            add_edge(candidates, cand, author, "mention", t)

    ranked = []
    for rec in candidates.values():
        ref_count = len(rec["referrers"])
        edge_count = sum(rec["edge_types"].values())
        strong_edges = sum(v for k, v in rec["edge_types"].items() if k in ("quoted", "replied_to", "retweeted"))
        b_l = rec["total_source_bookmarks"] / rec["total_source_likes"] if rec["total_source_likes"] else 0
        follower_factor = min((rec.get("followers") or 0) / 100_000, 2.0)
        score = ref_count * 3 + strong_edges * 2 + edge_count * 0.5 + min(b_l * 5, 3) + follower_factor
        # Default discovery standard: require cross-validation by multiple tracked referrers.
        # A single account repeatedly retweeting the same source is not enough.
        if ref_count < min_referrers:
            continue
        out = dict(rec)
        out["referrers"] = sorted(rec["referrers"])
        out["edge_types"] = dict(rec["edge_types"])
        out["referrer_count"] = ref_count
        out["edge_count"] = edge_count
        out["strong_edge_count"] = strong_edges
        out["source_bookmark_like_ratio"] = round(b_l, 3)
        out["referral_score"] = round(score, 2)
        out["profile_url"] = f"https://x.com/{rec['username']}"
        ranked.append(out)
    ranked.sort(key=lambda r: (-r["referral_score"], -r["referrer_count"], -r["strong_edge_count"], -r.get("followers", 0)))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_list_id": SOURCE_LIST_ID,
        "hours": hours,
        "member_count": len(members),
        "member_auth": member_auth,
        "timeline_auth": timeline["auth"],
        "timeline_pages": timeline["pages"],
        "timeline_tweets": len(timeline["tweets"]),
        "tweets_in_window": in_window,
        "page_limit_hit": timeline["page_limit_hit"],
        "stopped_reason": timeline["stopped_reason"],
        "candidate_count": len(ranked),
        "candidates": ranked,
    }


def render_markdown(result, limit=15):
    lines = []
    date = result['generated_at'][:10]
    lines.append("---")
    lines.append(f"title: X Referral Graph Discovery - {date}")
    lines.append(f"created: {date}")
    lines.append(f"updated: {date}")
    lines.append("type: daily")
    lines.append("tags: [daily]")
    lines.append(f"sources: [raw/signals/x_referral_graph_{date}.json]")
    lines.append("---")
    lines.append("")
    lines.append(f"# X Referral Graph Discovery — {date}")
    lines.append("")
    lines.append(f"Source list: `{result['source_list_id']}`")
    lines.append(f"Window: {result['hours']}h | members: {result['member_count']} | pages: {result['timeline_pages']} | tweets: {result['tweets_in_window']}")
    lines.append(f"Stopped: {result['stopped_reason']} | page_limit_hit: {result['page_limit_hit']}")
    lines.append("")
    lines.append("## Related Pages")
    lines.append("- [[jukan05_jukan]]")
    lines.append("- [[SpaceInvestor_D]]")
    lines.append("")
    if not result["candidates"]:
        lines.append("No referral candidates met threshold.")
        return "\n".join(lines) + "\n"
    lines.append("## Top Candidates")
    lines.append("")
    for i, c in enumerate(result["candidates"][:limit], 1):
        lines.append(f"### {i}. @{c['username']} — {c.get('name','')}")
        lines.append(f"- Score: {c['referral_score']} | referrers: {c['referrer_count']} ({', '.join('@'+r for r in c['referrers'])})")
        lines.append(f"- Edges: {c['edge_types']} | strong: {c['strong_edge_count']} | source B/L: {c['source_bookmark_like_ratio']}")
        lines.append(f"- Followers: {c.get('followers', 0):,} | URL: {c['profile_url']}")
        bio = (c.get("bio") or "").replace("\n", " ")[:240]
        if bio:
            lines.append(f"- Bio: {bio}")
        if c.get("examples"):
            ex = c["examples"][0]
            text = ex["text"].replace("\n", " ")[:260]
            lines.append(f"- Example: @{ex['referrer']} {ex['edge_type']} — {text}")
            lines.append(f"  {ex['source_url']}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=DEFAULT_HOURS)
    ap.add_argument("--page-limit", type=int, default=DEFAULT_PAGE_LIMIT)
    ap.add_argument("--min-referrers", type=int, default=2)
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save", action="store_true", help="Save JSON+markdown under wiki-market raw/signals and daily/briefs")
    args = ap.parse_args()

    result = build_graph(hours=args.hours, page_limit=args.page_limit, min_referrers=args.min_referrers)
    if args.save:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        raw_dir = Path(os.path.expanduser(configured_text('${ANALYST_WIKI_ROOT}/raw/signals')))
        brief_dir = Path(os.path.expanduser(configured_text('${ANALYST_WIKI_ROOT}/daily/briefs')))
        raw_dir.mkdir(parents=True, exist_ok=True)
        brief_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / f"x_referral_graph_{date}.json").write_text(json.dumps(result, indent=2))
        (brief_dir / f"x_referral_graph_{date}.md").write_text(render_markdown(result, args.limit))
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(render_markdown(result, args.limit))


if __name__ == "__main__":
    main()
