#!/usr/bin/env python3
"""Stable monitor snapshot for Chris Camillo primary-source disclosures.

Designed for Hermes cron monitor_script mode: output changes only when the
latest source items change. No timestamps or volatile engagement metrics.
"""

from __future__ import annotations
from automation_paths import configured_text

import json
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

HERMES_HOME = Path(configured_text("${ANALYST_HERMES_HOME}"))
X_SCANNER = HERMES_HOME / "scripts" / "fetch_x_signals.py"
X_STATE = HERMES_HOME / "state" / "chris_camillo_monitor_unused.json"
PODCAST_FEED = "https://feed.podbean.com/dumbmoneylive/feed.xml"
YOUTUBE_URLS = [
    ("dumb_money_live_videos", "https://www.youtube.com/@DumbMoneyLive/videos"),
    ("dumb_money_live_streams", "https://www.youtube.com/@DumbMoneyLive/streams"),
    # The legacy/main channel historically surfaced Trade Board theses earliest.
    ("dumb_money_videos", "https://www.youtube.com/@DumbMoney/videos"),
    ("dumb_money_streams", "https://www.youtube.com/@DumbMoney/streams"),
]


def clean(value: str | None, limit: int = 1200) -> str:
    return " ".join((value or "").split())[:limit]


def x_snapshot() -> dict:
    cmd = [
        sys.executable,
        str(X_SCANNER),
        "--per-account",
        "--accounts",
        "ChrisCamillo",
        "--hours",
        "336",
        "--max",
        "30",
        "--page-limit",
        "1",
        "--no-state",
        "--state-path",
        str(X_STATE),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
        if proc.returncode != 0:
            return {"status": "error"}
        payload = json.loads(proc.stdout)
        account = payload.get("accounts", {}).get("ChrisCamillo", {})
        if "error" in account:
            return {"status": "error"}
        tweets = []
        for item in account.get("raw_tweets", []):
            tweets.append(
                {
                    "id": item.get("url", "").rstrip("/").split("/")[-1],
                    "created_at": item.get("created_at"),
                    "text": clean(item.get("text")),
                    "url": item.get("url"),
                }
            )
        tweets.sort(key=lambda x: (x.get("created_at") or "", x.get("id") or ""), reverse=True)
        return {
            "status": "ok",
            "account": "ChrisCamillo",
            "items": tweets[:30],
        }
    except Exception:
        return {"status": "error"}


def podcast_snapshot() -> dict:
    try:
        req = urllib.request.Request(PODCAST_FEED, headers={"User-Agent": "Hermes-Camillo-Monitor/1.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            root = ET.fromstring(response.read())
        items = []
        for item in root.findall("./channel/item")[:12]:
            link = clean(item.findtext("link"))
            guid = clean(item.findtext("guid"))
            items.append(
                {
                    "id": guid or link,
                    "published": clean(item.findtext("pubDate")),
                    "title": clean(item.findtext("title"), 300),
                    "url": link or "https://dumbmoneylive.podbean.com/",
                }
            )
        return {"status": "ok", "feed": PODCAST_FEED, "items": items}
    except Exception:
        return {"status": "error"}


def youtube_playlist(label: str, url: str) -> dict:
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--playlist-end",
        "15",
        "--dump-single-json",
        url,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90, check=False)
        if proc.returncode != 0:
            return {"status": "error", "kind": label}
        payload = json.loads(proc.stdout)
        items = []
        for entry in payload.get("entries", [])[:15]:
            video_id = entry.get("id")
            if not video_id:
                continue
            items.append(
                {
                    "id": video_id,
                    "title": clean(entry.get("title"), 300),
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                }
            )
        return {"status": "ok", "kind": label, "items": items}
    except Exception:
        return {"status": "error", "kind": label}


def main() -> None:
    snapshot = {
        "source_contract": {
            "primary": "https://x.com/ChrisCamillo",
            "confirmation": "https://www.youtube.com/@DumbMoneyLive",
            "podcast": PODCAST_FEED,
            "integrity_rule": "X trade claims require official Dumb Money cross-source confirmation while account compromise is unresolved.",
        },
        "x": x_snapshot(),
        "youtube": [youtube_playlist(label, url) for label, url in YOUTUBE_URLS],
        "podcast": podcast_snapshot(),
    }
    print(json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


if __name__ == "__main__":
    main()
