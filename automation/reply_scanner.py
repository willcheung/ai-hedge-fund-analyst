#!/usr/bin/env python3
"""
CalConviction Reply Scanner — Contextual awareness for tweet replies.

Fetches CalConviction's recent tweets, pulls their conversation/reply threads,
classifies replies by type and sentiment, tracks engagement metrics per tweet type,
and identifies high-quality accounts engaging with content.

Usage:
    python3 reply_scanner.py [--hours 24] [--max-tweets 8] [--json] [--notify]
    
Output:
    - Structured report of replies with context (what original tweet was about)
    - Reply classification: question, agreement, disagreement, counter-argument,
      data point, spam/bot, engagement-bait
    - Tweet type performance tracking (which content gets real discussion)
    - High-quality account identification (potential follow targets)
    - JSON output for cron integration

Data persistence: ~/.hermes/calconviction_reply_data.json (accumulates over time)
"""
from automation_paths import configured_text

import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# --- Config ---
TOKENS_PATH = os.path.expanduser(configured_text('${ANALYST_HERMES_HOME}/calconviction_tokens.json'))
CONFIG_PATH = os.path.expanduser(configured_text('${ANALYST_HERMES_HOME}/.env'))
DATA_PATH = os.path.expanduser(configured_text('${ANALYST_HERMES_HOME}/calconviction_reply_data.json'))
KNOWN_ACCOUNTS_PATH = os.path.expanduser(configured_text('${ANALYST_HERMES_HOME}/scripts/fetch_x_signals.py'))

# CalConviction user ID (cached to avoid repeated lookups)
_CALCONVICTION_ID = None

# --- Auth (reuse calconviction.py patterns) ---

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
    return None


def save_tokens(tokens):
    with open(TOKENS_PATH, "w") as f:
        json.dump(tokens, f, indent=2)


def refresh_token():
    env = load_env()
    client_id = env.get("CALCONVICTION_CLIENT_ID", "")
    client_secret = env.get("CALCONVICTION_CLIENT_SECRET", "")

    tokens = load_tokens()
    if not tokens or "refresh_token" not in tokens:
        print("ERROR: No refresh token available.")
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
    tokens = load_tokens()
    if not tokens:
        print("ERROR: No tokens found.")
        sys.exit(1)

    expires_at = tokens.get("expires_at")
    if expires_at:
        if time.time() > (expires_at - 3600):
            return refresh_token()

    return tokens.get("access_token", "")


def api_call(method, endpoint, params=None, token=None):
    if not token:
        token = get_access_token()

    url = f"https://api.x.com{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    
    headers = {"Authorization": f"Bearer {token}"}
    req = urllib.request.Request(url, method=method, headers=headers)

    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()[:300]
        if e.code == 401:
            token = refresh_token()
            headers["Authorization"] = f"Bearer {token}"
            req = urllib.request.Request(url, method=method, headers=headers)
            resp = urllib.request.urlopen(req, timeout=15)
            return json.loads(resp.read())
        if e.code == 429:
            reset = int(e.headers.get("x-rate-limit-reset", time.time() + 60))
            wait = max(reset - int(time.time()), 5)
            print(f"Rate limited, waiting {wait}s...", file=sys.stderr)
            time.sleep(wait)
            token = get_access_token()
            headers["Authorization"] = f"Bearer {token}"
            req = urllib.request.Request(url, method=method, headers=headers)
            resp = urllib.request.urlopen(req, timeout=15)
            return json.loads(resp.read())
        print(f"API Error {e.code}: {error_body}", file=sys.stderr)
        raise


def get_calconviction_id(token):
    global _CALCONVICTION_ID
    if _CALCONVICTION_ID:
        return _CALCONVICTION_ID
    result = api_call("GET", "/2/users/me", token=token)
    _CALCONVICTION_ID = result["data"]["id"]
    return _CALCONVICTION_ID


# --- Data persistence ---

def load_reply_data():
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH) as f:
            return json.load(f)
    return {
        "scan_history": [],
        "tweet_performance": {},
        "engaging_accounts": {},
        "daily_summary": {},
    }


def save_reply_data(data):
    with open(DATA_PATH, "w") as f:
        json.dump(data, f, indent=2)


# --- Tweet type classification ---

def classify_tweet_type(text):
    """Classify what type of CalConviction tweet this is based on content."""
    text_lower = text.lower()
    
    # Deep dive indicators
    if any(kw in text_lower for kw in ["deep dive", "thesis", "valuation", "market cap", "revenue", "eps", "gross margin", "entry:", "entry zone"]):
        if "$" in text and any(c in text for c in ["%", "x"]):
            return "deep_dive"
        return "thesis_commentary"
    
    # Watchlist/conviction list
    if any(kw in text_lower for kw in ["watching", "conviction", "watchlist", "on my radar", "entry: $", "holding"]):
        return "watchlist"
    
    # Supply chain
    if any(kw in text_lower for kw in ["supply chain", "bottleneck", "demand", "here's where the money"]):
        return "supply_chain"
    
    # Market observation / opinion
    if any(kw in text_lower for kw in ["interesting", "everyone's focused", "nobody's talking", "the part nobody"]):
        return "market_observation"
    
    # Briefing insight
    if any(kw in text_lower for kw in ["this morning", "saw something", "interesting this morning"]):
        return "briefing_insight"
    
    # Weekend recap
    if any(kw in text_lower for kw in ["this week i learned", "weekend"]):
        return "weekend_recap"
    
    # Quote tweet context
    if "https://x.com/" in text or "https://twitter.com/" in text:
        return "quote_or_share"
    
    # Portfolio
    if any(kw in text_lower for kw in ["my " + "portfolio", "my " + "holdings", "core holdings"]):
        return "portfolio"
    
    return "general"


# --- Reply classification ---

def classify_reply(text, original_text=""):
    """Classify a reply by type and quality."""
    text_lower = text.strip().lower()
    
    # Remove @mentions for analysis
    clean = re.sub(r'@\w+', '', text_lower).strip()
    
    # Spam / bot detection
    spam_signals = [
        r'follow me', r'check out my', r'join my', r'subscribe', r'click here',
        r'free money', r'guaranteed', r'🚀🚀', r'crypto presale', r'nft',
        r'airdrop', r'giveaway', r'dm me', r'telegram\.gg', r't\.me/',
        r'boost your', r'get more followers', r'buy followers',
    ]
    for pattern in spam_signals:
        if re.search(pattern, text_lower):
            return "spam", 0
    
    # Very short / low effort
    if len(clean) < 15 and not any(c in clean for c in ["?", "!"]):
        if any(kw in clean for kw in ["nice", "good", "great", "lol", "lmao", "🔥", "💯", "based", "facts"]):
            return "low_effort", 1
    
    # Question
    if "?" in clean:
        # Quality question (longer, has context)
        if len(clean) > 30:
            return "quality_question", 5
        return "question", 3
    
    # Disagreement / counter-argument
    disagreement_signals = [
        r"disagree", r"wrong", r"incorrect", r"actually", r"that's not", r"not quite",
        r"misses the point", r"you're forgetting", r"but the problem", r"this is wrong",
        r"bear case", r"bull case", r"downside", r"risk here", r"overvalued", r"overrated",
        r"bubble", r"overhyped",
    ]
    for pattern in disagreement_signals:
        if re.search(pattern, clean):
            if len(clean) > 40:
                return "counter_argument", 5
            return "disagreement", 3
    
    # Data point / addition
    data_signals = [
        r'\d+%', r'\$\d+', r'pe ratio', r'market cap', r'revenue', r'eps',
        r'earnings', r'margin', r'contract', r'source:', r'according to',
        r'data shows', r'chart shows', r'the numbers',
    ]
    for pattern in data_signals:
        if re.search(pattern, clean):
            return "data_point", 4
    
    # Agreement with substance
    agreement_signals = [
        r"this is exactly", r"spot on", r"nailed it", r"great call", r"been saying this",
        r"agree", r"100%", r"couldn't agree more", r"this", r"finally someone",
    ]
    for pattern in agreement_signals:
        if re.search(pattern, clean):
            if len(clean) > 30:
                return "agreement_substantive", 3
            return "agreement", 2
    
    # Engagement bait (asking for follows, etc.)
    bait_signals = [r"follow me", r"check my profile", r"see my pinned", r"i post about"]
    for pattern in bait_signals:
        if re.search(pattern, text_lower):
            return "engagement_bait", 0
    
    # Default: if substantive length, mark as commentary
    if len(clean) > 50:
        return "commentary", 3
    
    return "other", 1


def estimate_sentiment(text):
    """Simple sentiment estimation: positive, negative, neutral, mixed."""
    clean = re.sub(r'@\w+', '', text.lower()).strip()
    
    positive_words = [
        "bullish", "great", "excellent", "undervalued", "opportunity", "growth",
        "strong", "compelling", "love", "amazing", "smart", "correct", "spot on",
        "nailed", "conviction", "buy", "long", "rocket", "moon", " breakout",
        "impressive", "underrated", "sleeper", "gem", "hidden",
    ]
    negative_words = [
        "bearish", "overvalued", "overhyped", "bubble", "risky", "dangerous",
        "terrible", "wrong", "short", "avoid", "sell", "dump", "scam", "fraud",
        "warning", "caution", "declining", "shrinking", "overpriced", "expensive",
        "red flag", "concern", "worry",
    ]
    
    pos_count = sum(1 for w in positive_words if w in clean)
    neg_count = sum(1 for w in negative_words if w in clean)
    
    if pos_count > neg_count + 1:
        return "positive"
    elif neg_count > pos_count + 1:
        return "negative"
    elif pos_count > 0 and neg_count > 0:
        return "mixed"
    return "neutral"


# --- Core scanning logic ---

def get_recent_tweets(token, user_id, hours=24, max_results=20):
    """Get CalConviction's recent tweets from the last N hours."""
    result = api_call("GET", f"/2/users/{user_id}/tweets", params={
        "max_results": min(max_results, 100),
        "tweet.fields": "created_at,public_metrics,conversation_id,context_annotations",
        "exclude": "replies",
    }, token=token)
    
    tweets = result.get("data", [])
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    
    filtered = []
    for t in tweets:
        created = t.get("created_at", "")
        if created >= cutoff:
            filtered.append(t)
    
    return filtered


def get_conversation_replies(token, conversation_id, tweet_id, max_results=20):
    """Get replies to a specific tweet/conversation."""
    # Search for replies in the conversation
    try:
        result = api_call("GET", f"/2/tweets/search/recent", params={
            "query": f"conversation_id:{conversation_id} to:CalConviction",
            "max_results": min(max_results, 100),
            "tweet.fields": "created_at,author_id,public_metrics,in_reply_to_user_id,referenced_tweets",
            "expansions": "author_id",
            "user.fields": "username,name,public_metrics,verified",
        }, token=token)
    except Exception as e:
        print(f"  Warning: Could not fetch replies for {conversation_id}: {e}", file=sys.stderr)
        return []
    
    tweets = result.get("data", [])
    users = {u["id"]: u for u in result.get("includes", {}).get("users", [])}
    
    replies = []
    for t in tweets:
        # Skip our own tweets
        author = users.get(t.get("author_id"), {})
        if author.get("username") == "CalConviction":
            continue
        
        reply_type, quality_score = classify_reply(t.get("text", ""))
        sentiment = estimate_sentiment(t.get("text", ""))
        
        replies.append({
            "id": t["id"],
            "text": t.get("text", ""),
            "author_id": t.get("author_id", ""),
            "author_username": author.get("username", "unknown"),
            "author_name": author.get("name", "unknown"),
            "author_followers": author.get("public_metrics", {}).get("followers_count", 0),
            "author_verified": author.get("verified", False),
            "created_at": t.get("created_at", ""),
            "reply_type": reply_type,
            "quality_score": quality_score,
            "sentiment": sentiment,
            "likes": t.get("public_metrics", {}).get("like_count", 0),
            "retweets": t.get("public_metrics", {}).get("retweet_count", 0),
            "replies": t.get("public_metrics", {}).get("reply_count", 0),
            "url": f"https://x.com/{author.get('username', 'unknown')}/status/{t['id']}",
        })
    
    # Sort by quality score descending
    replies.sort(key=lambda x: x["quality_score"], reverse=True)
    return replies


def scan_replies(hours=24, max_tweets=None):
    """Main scan function. Returns structured report."""
    token = get_access_token()
    user_id = get_calconviction_id(token)
    
    print(f"Scanning replies from the last {hours} hours...", file=sys.stderr)
    
    # 1. Get our recent tweets
    fetch_limit = max(20, max_tweets) if max_tweets else 20
    our_tweets = get_recent_tweets(token, user_id, hours=hours, max_results=fetch_limit)
    if max_tweets:
        our_tweets = our_tweets[:max_tweets]
    
    if not our_tweets:
        print("No tweets found in the time window.", file=sys.stderr)
        return {"tweets_scanned": 0, "replies_found": 0, "report": "No tweets in time window."}
    
    print(f"Found {len(our_tweets)} CalConviction tweets to check.", file=sys.stderr)
    
    # 2. For each tweet, get conversation replies
    all_results = []
    tweet_type_stats = defaultdict(lambda: {
        "tweet_count": 0, "total_replies": 0, "quality_replies": 0,
        "reply_types": defaultdict(int), "sentiments": defaultdict(int),
    })
    engaging_accounts = defaultdict(lambda: {
        "username": "", "name": "", "followers": 0, "interactions": 0,
        "total_quality": 0, "reply_types": [], "last_seen": "",
    })
    
    for tweet in our_tweets:
        tweet_id = tweet["id"]
        tweet_text = tweet.get("text", "")
        conversation_id = tweet.get("conversation_id", tweet_id)
        metrics = tweet.get("public_metrics", {})
        
        tweet_type = classify_tweet_type(tweet_text)
        
        stats = tweet_type_stats[tweet_type]
        stats["tweet_count"] += 1
        
        print(f"  Checking tweet {tweet_id} ({tweet_type})...", file=sys.stderr)
        time.sleep(0.5)  # Rate limit courtesy
        
        replies = get_conversation_replies(token, conversation_id, tweet_id)
        
        stats["total_replies"] += len(replies)
        
        quality_replies = [r for r in replies if r["quality_score"] >= 3]
        stats["quality_replies"] += len(quality_replies)
        
        for r in replies:
            stats["reply_types"][r["reply_type"]] += 1
            stats["sentiments"][r["sentiment"]] += 1
            
            # Track engaging accounts
            author_id = r["author_id"]
            if r["quality_score"] >= 3:
                acct = engaging_accounts[author_id]
                acct["username"] = r["author_username"]
                acct["name"] = r["author_name"]
                acct["followers"] = max(acct["followers"], r["author_followers"])
                acct["interactions"] += 1
                acct["total_quality"] += r["quality_score"]
                acct["reply_types"].append(r["reply_type"])
                acct["last_seen"] = r["created_at"]
        
        all_results.append({
            "tweet_id": tweet_id,
            "tweet_url": f"https://x.com/CalConviction/status/{tweet_id}",
            "tweet_text": tweet_text[:300],
            "tweet_type": tweet_type,
            "posted_at": tweet.get("created_at", ""),
            "metrics": metrics,
            "replies": replies,
            "reply_count": len(replies),
            "quality_reply_count": len(quality_replies),
        })
    
    # 3. Build report
    report = {
        "scan_timestamp": datetime.now(timezone.utc).isoformat(),
        "hours_scanned": hours,
        "tweets_scanned": len(our_tweets),
        "total_replies": sum(r["reply_count"] for r in all_results),
        "quality_replies": sum(r["quality_reply_count"] for r in all_results),
        "tweets": all_results,
        "tweet_type_performance": {
            k: {
                "tweet_count": v["tweet_count"],
                "avg_replies": round(v["total_replies"] / v["tweet_count"], 1) if v["tweet_count"] else 0,
                "avg_quality_replies": round(v["quality_replies"] / v["tweet_count"], 1) if v["tweet_count"] else 0,
                "top_reply_types": dict(sorted(v["reply_types"].items(), key=lambda x: -x[1])[:5]),
                "sentiment_split": dict(v["sentiments"]),
            }
            for k, v in tweet_type_stats.items()
        },
        "engaging_accounts": sorted(
            [{"user_id": k, **v, "avg_quality": round(v["total_quality"] / v["interactions"], 1)} 
             for k, v in engaging_accounts.items() if v["interactions"] >= 1],
            key=lambda x: -x["total_quality"]
        )[:15],
    }
    
    # 4. Update persistent data
    data = load_reply_data()
    
    # Merge tweet performance
    for k, v in report["tweet_type_performance"].items():
        if k not in data["tweet_performance"]:
            data["tweet_performance"][k] = {
                "total_tweets": 0, "total_replies": 0, "total_quality_replies": 0,
                "daily_data": [],
            }
        perf = data["tweet_performance"][k]
        perf["total_tweets"] += v["tweet_count"]
        perf["total_replies"] += v["avg_replies"] * v["tweet_count"]
        perf["total_quality_replies"] += v["avg_quality_replies"] * v["tweet_count"]
        perf["daily_data"].append({
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "replies": v["avg_replies"],
            "quality_replies": v["avg_quality_replies"],
        })
        # Keep last 30 days
        perf["daily_data"] = perf["daily_data"][-30:]
    
    # Merge engaging accounts
    for acct in report["engaging_accounts"]:
        uid = acct["user_id"]
        if uid not in data["engaging_accounts"]:
            data["engaging_accounts"][uid] = {
                "username": acct["username"],
                "name": acct["name"],
                "followers": acct["followers"],
                "total_interactions": 0,
                "total_quality": 0,
                "first_seen": acct["last_seen"],
                "last_seen": acct["last_seen"],
                "reply_types": [],
            }
        ea = data["engaging_accounts"][uid]
        ea["total_interactions"] += acct["interactions"]
        ea["total_quality"] += acct["total_quality"]
        ea["last_seen"] = acct["last_seen"]
        ea["followers"] = max(ea["followers"], acct["followers"])
        ea["reply_types"].extend(acct["reply_types"])
    
    # Daily summary
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data["daily_summary"][today] = {
        "tweets_scanned": len(our_tweets),
        "total_replies": report["total_replies"],
        "quality_replies": report["quality_replies"],
    }
    # Keep last 60 days
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d")
    data["daily_summary"] = {k: v for k, v in data["daily_summary"].items() if k >= cutoff_date}
    
    save_reply_data(data)
    
    return report


# --- Report formatting ---

def format_report(report):
    """Format the report for human-readable output."""
    lines = []
    lines.append(f"📋 CalConviction Reply Scan — {report['hours_scanned']}h")
    lines.append(f"   {report['tweets_scanned']} tweets scanned | {report['total_replies']} replies | {report['quality_replies']} quality")
    lines.append("")
    
    if report["total_replies"] == 0:
        lines.append("No replies found in this window.")
        return "\n".join(lines)
    
    # Per-tweet breakdown
    for t in report["tweets"]:
        lines.append(f"{'─'*60}")
        lines.append(f"📊 [{t['tweet_type']}] {t['tweet_text'][:80]}{'...' if len(t['tweet_text']) > 80 else ''}")
        lines.append(f"   {t['tweet_url']}")
        lines.append(f"   ❤️ {t['metrics'].get('like_count',0)} | 🔁 {t['metrics'].get('retweet_count',0)} | 💬 {t['metrics'].get('reply_count',0)} | 📖 {t['metrics'].get('bookmark_count',0)}")
        lines.append(f"   Replies: {t['reply_count']} total, {t['quality_reply_count']} quality")
        
        # Show top quality replies
        for r in t["replies"][:5]:
            if r["quality_score"] < 2:
                continue
            emoji = {
                "quality_question": "❓", "counter_argument": "⚡", "disagreement": "⚔️",
                "data_point": "📊", "agreement_substantive": "✅", "commentary": "💬",
                "question": "❓", "agreement": "👍",
            }.get(r["reply_type"], "📌")
            sentiment_emoji = {"positive": "📈", "negative": "📉", "mixed": "↔️", "neutral": ""}.get(r["sentiment"], "")
            lines.append(f"   {emoji} @{r['author_username']} [{r['reply_type']}]{sentiment_emoji}")
            lines.append(f"      \"{r['text'][:120]}{'...' if len(r['text']) > 120 else ''}\"")
            lines.append(f"      👤 {r['author_followers']:,} followers | ❤️ {r['likes']} | {r['url']}")
        
        if t["quality_reply_count"] > 5:
            lines.append(f"   ... and {t['quality_reply_count'] - 5} more quality replies")
        lines.append("")
    
    # Tweet type performance
    lines.append(f"{'═'*60}")
    lines.append("📈 CONTENT PERFORMANCE BY TYPE")
    lines.append("")
    
    perf = report["tweet_type_performance"]
    # Sort by avg quality replies
    sorted_types = sorted(perf.items(), key=lambda x: -x[1]["avg_quality_replies"])
    
    for ttype, stats in sorted_types:
        type_label = ttype.replace("_", " ").title()
        lines.append(f"  {type_label}")
        lines.append(f"    {stats['tweet_count']} tweets | {stats['avg_replies']} avg replies | {stats['avg_quality_replies']} avg quality")
        if stats["top_reply_types"]:
            top = ", ".join(f"{k} ({v})" for k, v in list(stats["top_reply_types"].items())[:3])
            lines.append(f"    Top types: {top}")
        if stats["sentiment_split"]:
            sent = ", ".join(f"{k} {v}" for k, v in stats["sentiment_split"].items())
            lines.append(f"    Sentiment: {sent}")
        lines.append("")
    
    # Engaging accounts
    if report["engaging_accounts"]:
        lines.append(f"{'═'*60}")
        lines.append("👥 TOP ENGAGING ACCOUNTS")
        lines.append("")
        
        for acct in report["engaging_accounts"][:10]:
            lines.append(f"  @{acct['username']} ({acct['name']})")
            lines.append(f"    👤 {acct['followers']:,} followers | 💬 {acct['interactions']} quality interactions | avg score: {acct['avg_quality']}")
            lines.append(f"    Types: {', '.join(set(acct['reply_types']))}")
            lines.append(f"    {acct.get('url', '')}")
            lines.append("")
    
    return "\n".join(lines)


def format_content_strategy_advice(data):
    """Generate content strategy recommendations based on accumulated data."""
    lines = []
    lines.append("💡 CONTENT STRATEGY FEEDBACK")
    lines.append("")
    
    perf = data.get("tweet_performance", {})
    if not perf:
        lines.append("Not enough data yet. Run for 5+ days to get recommendations.")
        return "\n".join(lines)
    
    # Calculate averages across all types
    all_avg = []
    for ttype, stats in perf.items():
        if stats["total_tweets"] >= 2:
            avg_q = stats["total_quality_replies"] / stats["total_tweets"]
            avg_r = stats["total_replies"] / stats["total_tweets"]
            all_avg.append((ttype, avg_q, avg_r, stats["total_tweets"]))
    
    if not all_avg:
        lines.append("Not enough data yet. Need at least 2 tweets per type.")
        return "\n".join(lines)
    
    all_avg.sort(key=lambda x: -x[1])
    
    lines.append("🏆 BEST PERFORMING CONTENT (by quality replies):")
    for ttype, avg_q, avg_r, count in all_avg[:3]:
        label = ttype.replace("_", " ").title()
        lines.append(f"  {label}: {avg_q:.1f} quality replies/tweet ({count} tweets)")
    lines.append("")
    
    lines.append("📉 WORST PERFORMING CONTENT:")
    for ttype, avg_q, avg_r, count in all_avg[-3:]:
        label = ttype.replace("_", " ").title()
        lines.append(f"  {label}: {avg_q:.1f} quality replies/tweet ({count} tweets)")
    lines.append("")
    
    # Time-based analysis
    daily = data.get("daily_summary", {})
    if len(daily) >= 5:
        total_days = len(daily)
        avg_total = sum(d["total_replies"] for d in daily.values()) / total_days
        avg_quality = sum(d["quality_replies"] for d in daily.values()) / total_days
        lines.append(f"📊 DAILY AVERAGES (last {total_days} days):")
        lines.append(f"  {avg_total:.1f} total replies/day | {avg_quality:.1f} quality replies/day")
    
    return "\n".join(lines)


def main():
    hours = 24
    max_tweets = None
    as_json = False
    show_strategy = False
    
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg.startswith("--hours="):
            hours = int(arg.split("=")[1])
        elif arg == "--hours" and i + 1 < len(sys.argv):
            hours = int(sys.argv[i + 1])
            i += 1
        elif arg.startswith("--max-tweets="):
            max_tweets = int(arg.split("=")[1])
        elif arg == "--max-tweets" and i + 1 < len(sys.argv):
            max_tweets = int(sys.argv[i + 1])
            i += 1
        elif arg == "--json":
            as_json = True
        elif arg == "--strategy":
            show_strategy = True
        i += 1
    
    report = scan_replies(hours=hours, max_tweets=max_tweets)
    
    if as_json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(format_report(report))
        print()
        
        if show_strategy:
            data = load_reply_data()
            print(format_content_strategy_advice(data))


if __name__ == "__main__":
    main()
