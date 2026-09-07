#!/usr/bin/env python3
"""Collect bounded @CalConviction growth-pilot metrics.

The collector uses owned-account reads, preserves tweet-object diagnostics, and
also groups authored thread members into content units for lane comparisons.
Snapshots are stored as crash-safe append-only JSONL unless --no-append is used.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import statistics
import sys
import urllib.parse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import calconviction  # noqa: E402

from automation_paths import state_path

DEFAULT_OUTPUT = state_path('calconviction_growth_metrics.jsonl')


def full_text(tweet: dict) -> str:
    return tweet.get("note_tweet", {}).get("text") or tweet.get("text", "")


def classify_post(tweet: dict) -> str:
    text = full_text(tweet)
    lower = text.lower()
    stripped = text.lstrip()
    lines = lower.splitlines()
    first_line = lines[0] if lines else ""

    if "deep dive:" in lower:
        return "deep_dive"
    if any(marker in lower for marker in ("highest conviction", "conviction list", "weekly conviction")):
        return "conviction_list"
    if lower.startswith(("morning market map", "market map", "morning setup")):
        return "daily_market_brief"
    if lower.startswith(("macro shift:", "macro regime:")):
        return "macro"
    if lower.startswith(("friday close:", "post-close:")):
        return "friday_take"
    if any(
        marker in lower
        for marker in ("market wiki", "the agent earns", "behind the scene", "underneath the hood")
    ):
        return "process"
    if (
        (len(stripped) > 3 and stripped[0].isdigit() and ". $" in stripped[:8])
        or " names i'm watching" in lower
        or " small caps" in lower[:100]
        or " chokepoints" in lower[:100]
        or " proof layers" in lower[:100]
        or (
            first_line[:1].isdigit()
            and any(
                marker in first_line
                for marker in (" names", " stocks", " small", " companies", " chokepoints")
            )
        )
    ):
        return "watchlist"
    if stripped.startswith("$") and " earnings:" in first_line:
        return "earnings_result"
    return "timely_single"


def percentile_summary(values: list[int]) -> dict:
    if not values:
        return {"count": 0, "mean": 0, "median": 0, "max": 0}
    return {
        "count": len(values),
        "mean": round(statistics.mean(values), 2),
        "median": round(statistics.median(values), 2),
        "max": max(values),
    }


def summarize_by_format(
    items: list[dict], impression_field: str, rate_impression_field: str | None = None
) -> dict:
    rate_impression_field = rate_impression_field or impression_field
    impressions_by_format: dict[str, list[int]] = defaultdict(list)
    rate_impressions_by_format: dict[str, int] = defaultdict(int)
    public_engagements: dict[str, int] = defaultdict(int)
    x_engagements: dict[str, int] = defaultdict(int)
    profile_clicks: dict[str, int] = defaultdict(int)

    for item in items:
        lane = item["format"]
        impressions_by_format[lane].append(int(item.get(impression_field, 0) or 0))
        rate_impressions_by_format[lane] += int(item.get(rate_impression_field, 0) or 0)
        public_engagements[lane] += int(item.get("engagements", 0) or 0)
        x_engagements[lane] += int(item.get("x_total_engagements", 0) or 0)
        profile_clicks[lane] += int(item.get("profile_clicks", 0) or 0)

    result = {}
    for lane in sorted(impressions_by_format):
        summary = percentile_summary(impressions_by_format[lane])
        total_impressions = sum(impressions_by_format[lane])
        rate_impressions = rate_impressions_by_format[lane]
        engagements = public_engagements[lane]
        clicks = profile_clicks[lane]
        summary.update(
            {
                "total_impressions": total_impressions,
                "rate_denominator_impressions": rate_impressions,
                "engagements": engagements,
                "x_total_engagements": x_engagements[lane],
                "profile_clicks": clicks,
                "engagements_per_1000_impressions": round(
                    engagements / rate_impressions * 1000, 2
                )
                if rate_impressions
                else 0,
                "profile_clicks_per_1000_impressions": round(
                    clicks / rate_impressions * 1000, 2
                )
                if rate_impressions
                else 0,
            }
        )
        result[lane] = summary
    return result


def aggregate_content_units(posts: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for post in posts:
        grouped[post.get("conversation_id") or post["id"]].append(post)

    units = []
    lane_priority = (
        "watchlist",
        "earnings_result",
        "deep_dive",
        "conviction_list",
        "daily_market_brief",
        "macro",
        "friday_take",
        "process",
    )
    for conversation_id, members in grouped.items():
        members = sorted(members, key=lambda post: post.get("created_at") or "")
        root = next((post for post in members if post["id"] == conversation_id), members[0])
        lane = root["format"]
        if lane == "timely_single":
            observed = Counter(post["format"] for post in members)
            lane = next((candidate for candidate in lane_priority if observed[candidate]), lane)
        units.append(
            {
                "conversation_id": conversation_id,
                "root_post_id": root["id"],
                "created_at": root.get("created_at"),
                "format": lane,
                "tweet_objects": len(members),
                "root_impressions": int(root.get("impressions", 0) or 0),
                "object_impressions_sum": sum(int(post.get("impressions", 0) or 0) for post in members),
                "engagements": sum(int(post.get("engagements", 0) or 0) for post in members),
                "x_total_engagements": sum(
                    int(post.get("x_total_engagements", 0) or 0) for post in members
                ),
                "profile_clicks": sum(int(post.get("profile_clicks", 0) or 0) for post in members),
                "preview": root.get("preview", ""),
            }
        )
    return sorted(units, key=lambda unit: unit.get("created_at") or "", reverse=True)


def collect(max_results: int = 25) -> dict:
    max_results = max(5, min(max_results, 100))
    token = calconviction.get_access_token()
    profile_response = calconviction.api_call(
        "GET", "/2/users/me?user.fields=public_metrics", token=token
    )
    profile = profile_response["data"]
    query = urllib.parse.urlencode(
        {
            "max_results": max_results,
            "exclude": "retweets",
            "tweet.fields": (
                "created_at,conversation_id,referenced_tweets,public_metrics,"
                "non_public_metrics,organic_metrics,note_tweet"
            ),
        }
    )
    timeline_response = calconviction.api_call(
        "GET", f"/2/users/{profile['id']}/tweets?{query}", token=token
    )

    posts = []
    for tweet in timeline_response.get("data", []):
        metrics = tweet.get("public_metrics", {})
        non_public_metrics = tweet.get("non_public_metrics", {})
        organic_metrics = tweet.get("organic_metrics", {})
        text = full_text(tweet)
        impressions = int(metrics.get("impression_count", 0) or 0)
        engagements = sum(
            int(metrics.get(field, 0) or 0)
            for field in (
                "like_count",
                "reply_count",
                "retweet_count",
                "quote_count",
                "bookmark_count",
            )
        )
        x_total_engagements = int(non_public_metrics.get("engagements", engagements) or 0)
        profile_clicks = int(
            non_public_metrics.get(
                "user_profile_clicks", organic_metrics.get("user_profile_clicks", 0)
            )
            or 0
        )
        posts.append(
            {
                "id": str(tweet.get("id", "")),
                "created_at": tweet.get("created_at"),
                "conversation_id": str(tweet.get("conversation_id") or tweet.get("id") or ""),
                "format": classify_post(tweet),
                "impressions": impressions,
                "likes": int(metrics.get("like_count", 0) or 0),
                "replies": int(metrics.get("reply_count", 0) or 0),
                "reposts": int(metrics.get("retweet_count", 0) or 0),
                "quotes": int(metrics.get("quote_count", 0) or 0),
                "bookmarks": int(metrics.get("bookmark_count", 0) or 0),
                "engagements": engagements,
                "x_total_engagements": x_total_engagements,
                "profile_clicks": profile_clicks,
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "preview": " ".join(text.split())[:180],
            }
        )

    content_units = aggregate_content_units(posts)
    public_metrics = profile.get("public_metrics", {})
    timeline_meta = timeline_response.get("meta", {})
    created_values = [post["created_at"] for post in posts if post.get("created_at")]

    return {
        "schema_version": 3,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "profile": {
            "id": str(profile.get("id", "")),
            "username": profile.get("username"),
            "followers": int(public_metrics.get("followers_count", 0) or 0),
            "following": int(public_metrics.get("following_count", 0) or 0),
            "tweet_count": int(public_metrics.get("tweet_count", 0) or 0),
            "listed_count": int(public_metrics.get("listed_count", 0) or 0),
            "media_count": int(public_metrics.get("media_count", 0) or 0),
        },
        "scope": {
            "owned_reads": True,
            "timeline_max_results": max_results,
            "posts_returned": len(posts),
            "content_units_returned": len(content_units),
            "newest_id": timeline_meta.get("newest_id"),
            "oldest_id": timeline_meta.get("oldest_id"),
            "newest_created_at": max(created_values) if created_values else None,
            "oldest_created_at": min(created_values) if created_values else None,
            "next_token_present": bool(timeline_meta.get("next_token")),
            "truncated": bool(timeline_meta.get("next_token")),
        },
        "format_summary": summarize_by_format(
            content_units, "root_impressions", "object_impressions_sum"
        ),
        "tweet_object_format_summary": summarize_by_format(posts, "impressions"),
        "content_units": content_units,
        "posts": posts,
    }


def append_snapshot(snapshot: dict, output_path: Path) -> bool:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = output_path.with_name(output_path.name + ".lock")
    line = json.dumps(snapshot, separators=(",", ":")) + "\n"

    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        if output_path.exists():
            raw = output_path.read_bytes()
            if raw and not raw.endswith(b"\n"):
                last_newline = raw.rfind(b"\n")
                complete = raw[: last_newline + 1] if last_newline >= 0 else b""
                tail = raw[last_newline + 1 :]
                try:
                    json.loads(tail.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    quarantine_path = output_path.with_name(output_path.name + ".corrupt")
                    with quarantine_path.open("ab") as quarantine:
                        quarantine.write(tail + b"\n")
                        quarantine.flush()
                        os.fsync(quarantine.fileno())
                    os.chmod(quarantine_path, 0o600)
                    with output_path.open("wb") as repair_handle:
                        repair_handle.write(complete)
                        repair_handle.flush()
                        os.fsync(repair_handle.fileno())
                else:
                    with output_path.open("ab") as repair_handle:
                        repair_handle.write(b"\n")
                        repair_handle.flush()
                        os.fsync(repair_handle.fileno())
            for existing_line in output_path.read_text(encoding="utf-8").splitlines():
                try:
                    existing = json.loads(existing_line)
                except json.JSONDecodeError:
                    continue
                if existing.get("captured_at") == snapshot.get("captured_at"):
                    return False
        with output_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(output_path, 0o600)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-results", type=int, default=25)
    parser.add_argument(
        "--no-append",
        action="store_true",
        help="Collect and print a status without modifying the JSONL file.",
    )
    args = parser.parse_args()

    snapshot = collect(max_results=args.max_results)
    persisted = False if args.no_append else append_snapshot(snapshot, args.output.expanduser())
    profile = snapshot["profile"]
    print(
        json.dumps(
            {
                "status": "ok",
                "captured_at": snapshot["captured_at"],
                "followers": profile["followers"],
                "tweet_count": profile["tweet_count"],
                "posts_measured": snapshot["scope"]["posts_returned"],
                "content_units_measured": snapshot["scope"]["content_units_returned"],
                "truncated": snapshot["scope"]["truncated"],
                "persisted": persisted,
                "output": str(args.output.expanduser()),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
