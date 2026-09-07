#!/usr/bin/env python3
"""Fetch recent Meet Kevin YouTube videos + transcripts for macro analysis.

Outputs raw transcript artifacts under ~/wiki-market/raw/transcripts/meetkevin/ and
prints compact JSON manifest for an LLM cron to synthesize.
"""

from __future__ import annotations
from automation_paths import configured_text

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

CHANNEL_ID = "UCUvvj5lwue7PspotMDjk5UA"  # Meet Kevin main channel, not clips channel
RSS_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
OUT_DIR = Path(configured_text("${ANALYST_WIKI_ROOT}")) / "raw" / "transcripts" / "meetkevin"
STATE_PATH = OUT_DIR / ".state.json"


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def parse_ts(s: str) -> dt.datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return dt.datetime.fromisoformat(s).astimezone(dt.timezone.utc)


def fetch_url(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Hermes market-research bot"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def load_entries() -> list[dict]:
    root = ET.fromstring(fetch_url(RSS_URL))
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
        "media": "http://search.yahoo.com/mrss/",
    }
    out = []
    for e in root.findall("atom:entry", ns):
        video_id = e.findtext("yt:videoId", namespaces=ns)
        title = e.findtext("atom:title", namespaces=ns) or ""
        link_el = e.find("atom:link", ns)
        link = link_el.attrib.get("href") if link_el is not None else f"https://www.youtube.com/watch?v={video_id}"
        published = parse_ts(e.findtext("atom:published", namespaces=ns))
        updated = parse_ts(e.findtext("atom:updated", namespaces=ns))
        desc = e.findtext("media:group/media:description", namespaces=ns) or ""
        stats_el = e.find("media:group/media:community/media:statistics", ns)
        views = int(stats_el.attrib.get("views", "0")) if stats_el is not None else None
        out.append({
            "video_id": video_id,
            "title": title,
            "url": link,
            "published": published,
            "updated": updated,
            "description": desc.strip(),
            "views": views,
        })
    return out


def fetch_transcript(video_id: str) -> tuple[str | None, str | None]:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()
        try:
            result = api.fetch(video_id, languages=["en"])
        except Exception:
            result = api.fetch(video_id)
        lines = []
        for seg in result:
            total = int(seg.start)
            h, rem = divmod(total, 3600)
            m, s = divmod(rem, 60)
            ts = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
            text = re.sub(r"\s+", " ", seg.text).strip()
            if text:
                lines.append(f"{ts} {text}")
        return "\n".join(lines), None
    except Exception as exc:
        return None, str(exc)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            return {}
    return {}


def write_state(state: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=30, help="lookback window, default 30h")
    ap.add_argument("--limit", type=int, default=8, help="max videos to process")
    ap.add_argument("--force", action="store_true", help="ignore state and refetch within window")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    now = utc_now()
    cutoff = now - dt.timedelta(hours=args.hours)
    state = read_state()
    seen = set(state.get("seen_video_ids", []))

    entries = load_entries()
    candidates = [e for e in entries if e["published"] >= cutoff]
    candidates.sort(key=lambda x: x["published"], reverse=True)
    candidates = candidates[: args.limit]

    processed = []
    skipped = []
    for e in candidates:
        vid = e["video_id"]
        if not args.force and vid in seen:
            skipped.append({"video_id": vid, "title": e["title"], "reason": "already_seen"})
            continue
        transcript, err = fetch_transcript(vid)
        date_slug = e["published"].strftime("%Y-%m-%d")
        safe_title = re.sub(r"[^A-Za-z0-9]+", "-", e["title"]).strip("-")[:80].lower() or vid
        rel = f"raw/transcripts/meetkevin/{date_slug}_{vid}_{safe_title}.md"
        path = Path(configured_text("${ANALYST_WIKI_ROOT}")) / rel
        metadata_block = (
            "---\n"
            f"source_url: {e['url']}\n"
            f"source: Meet Kevin YouTube\n"
            f"channel_id: {CHANNEL_ID}\n"
            f"video_id: {vid}\n"
            f"title: {json.dumps(e['title'])[1:-1]}\n"
            f"published: {e['published'].isoformat()}\n"
            f"views: {e.get('views') or 0}\n"
            f"ingested: {now.date().isoformat()}\n"
        )
        if transcript:
            body = (
                metadata_block +
                f"sha256: {sha256_text(transcript)}\n"
                "---\n\n"
                f"# {e['title']}\n\n"
                f"Source: {e['url']}\n\n"
                f"Views at ingest: {e.get('views') or 0}\n\n"
                "## RSS Description\n\n"
                f"{e.get('description') or '(empty)'}\n\n"
                "## Transcript\n\n"
                f"{transcript}\n"
            )
            path.write_text(body, encoding="utf-8")
            seen.add(vid)
            processed.append({
                "video_id": vid,
                "title": e["title"],
                "url": e["url"],
                "published": e["published"].isoformat(),
                "views": e.get("views"),
                "description": e.get("description", "")[:1200],
                "raw_path": rel,
                "char_count": len(transcript),
                "transcript_status": "ok",
            })
        else:
            fallback_text = (e.get("description") or "") + "\n" + (err or "")
            body = (
                metadata_block +
                f"transcript_error: {json.dumps((err or '')[:500])[1:-1]}\n"
                f"sha256: {sha256_text(fallback_text)}\n"
                "---\n\n"
                f"# {e['title']}\n\n"
                f"Source: {e['url']}\n\n"
                f"Views at ingest: {e.get('views') or 0}\n\n"
                "## RSS Description\n\n"
                f"{e.get('description') or '(empty)'}\n\n"
                "## Transcript Status\n\n"
                f"Transcript unavailable from this server: {err}\n"
            )
            path.write_text(body, encoding="utf-8")
            seen.add(vid)
            processed.append({
                "video_id": vid,
                "title": e["title"],
                "url": e["url"],
                "published": e["published"].isoformat(),
                "views": e.get("views"),
                "description": e.get("description", "")[:1200],
                "raw_path": rel,
                "char_count": 0,
                "transcript_status": "blocked_or_unavailable",
                "error": err,
            })

    state["seen_video_ids"] = sorted(seen)[-500:]
    state["last_run_utc"] = now.isoformat()
    write_state(state)

    manifest = {
        "source": "Meet Kevin YouTube",
        "channel_url": "https://www.youtube.com/@MeetKevin",
        "rss_url": RSS_URL,
        "lookback_hours": args.hours,
        "candidate_count": len(candidates),
        "processed": processed,
        "skipped": skipped,
    }
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
