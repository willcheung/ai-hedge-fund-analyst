#!/usr/bin/env python3
"""
Podcast Summary Pipeline
========================
1. Fetch latest episodes from RSS feeds
2. Download audio (yt-dlp)
3. Transcribe (faster-whisper, small model, CPU)
4. Output full transcript text

Usage:
  python3 podcast_pipeline.py                  # Process all feeds, latest episode each
  python3 podcast_pipeline.py --feeds ai,allin # Specific feeds only
  python3 podcast_pipeline.py --list           # List configured feeds + last processed
"""
from automation_paths import configured_text

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import yt_dlp

# ─── Config ────────────────────────────────────────────────────────────────────

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser(configured_text('${ANALYST_HERMES_HOME}')))
DATA_DIR = Path(HERMES_HOME) / "podcast_data"
DB_PATH = DATA_DIR / "podcasts.db"
AUDIO_DIR = DATA_DIR / "audio"

FEEDS = {
    "ai": {
        "name": "The AI Daily Brief",
        "rss": "https://anchor.fm/s/f7cac464/podcast/rss",
    },
    "allin": {
        "name": "All-In Podcast",
        "rss": "https://rss.libsyn.com/shows/254861/destinations/1928300.xml",
    },
    "hiddenbrain": {
        "name": "Hidden Brain",
        "rss": "https://feeds.simplecast.com/kwWc0lhf",
    },
}

# ─── Database ──────────────────────────────────────────────────────────────────

def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            feed_key TEXT,
            episode_url TEXT PRIMARY KEY,
            title TEXT,
            published TEXT,
            processed_at TEXT
        )
    """)
    conn.commit()
    return conn


def is_processed(conn, episode_url):
    row = conn.execute(
        "SELECT 1 FROM episodes WHERE episode_url = ?", (episode_url,)
    ).fetchone()
    return row is not None


def save_episode(conn, feed_key, episode_url, title, published):
    conn.execute(
        """INSERT OR REPLACE INTO episodes (feed_key, episode_url, title, published, processed_at)
           VALUES (?, ?, ?, ?, ?)""",
        (feed_key, episode_url, title, published,
         datetime.now(timezone.utc).isoformat())
    )
    conn.commit()


# ─── RSS Feed Fetching ─────────────────────────────────────────────────────────

def fetch_latest_episodes(feed_key, max_episodes=1):
    feed_cfg = FEEDS[feed_key]
    feed = feedparser.parse(feed_cfg["rss"])

    if feed.bozo and not feed.entries:
        print(f"  ⚠️  Feed parse error for {feed_cfg['name']}: {feed.bozo_exception}")
        return []

    episodes = []
    for entry in feed.entries[:max_episodes]:
        audio_url = None
        for link in entry.get("links", []):
            if link.get("type", "").startswith("audio/"):
                audio_url = link.get("href")
                break
        if not audio_url:
            for mc in entry.get("media_content", []):
                if mc.get("type", "").startswith("audio/"):
                    audio_url = mc.get("url")
                    break

        if not audio_url:
            print(f"  ⚠️  No audio URL for: {entry.get('title', 'unknown')}")
            continue

        published = entry.get("published", entry.get("updated", ""))
        episodes.append({
            "title": entry.get("title", "Untitled"),
            "url": entry.get("link", ""),
            "audio_url": audio_url,
            "published": published,
        })

    return episodes


# ─── Audio Download ────────────────────────────────────────────────────────────

def download_audio(audio_url, output_path):
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(output_path).replace(".mp3", ".%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "96",
        }],
        "quiet": True,
        "no_warnings": True,
        "max_filesize": 500 * 1024 * 1024,
        "socket_timeout": 30,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([audio_url])
    except Exception as e:
        if not Path(output_path).exists():
            print(f"  ⚠️  yt-dlp failed ({e}), trying direct download...")
            subprocess.run(
                ["curl", "-sL", "-o", str(output_path), "--max-time", "300", audio_url],
                check=True, capture_output=True
            )

    if not Path(output_path).exists():
        raise RuntimeError(f"Download failed: {audio_url}")

    size_mb = Path(output_path).stat().st_size / (1024 * 1024)
    print(f"  ✓ Downloaded: {size_mb:.1f} MB")
    return output_path


# ─── Transcription ─────────────────────────────────────────────────────────────

def load_gemini_key():
    """Load GEMINI_API_KEY from Hermes .env or OpenClaw .env."""
    import os
    from pathlib import Path
    for env_path in [Path(os.path.expanduser(configured_text('${ANALYST_HERMES_HOME}/.env')))]:
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line.startswith("GEMINI_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    key = os.environ.get("GEMINI_API_KEY", "")
    if key:
        return key
    raise RuntimeError("GEMINI_API_KEY not found in ~/.hermes/.env or env vars")


def transcribe(audio_path):
    """Transcribe using Gemini multimodal API. Fast, no local GPU needed."""
    from google import genai

    api_key = load_gemini_key()
    client = genai.Client(api_key=api_key)

    print("  ⏳ Transcribing with Gemini...")
    audio_file = client.files.upload(file=str(audio_path))

    # Wait for processing
    import time
    while audio_file.state.name == "PROCESSING":
        time.sleep(2)
        audio_file = client.files.get(name=audio_file.name)

    if audio_file.state.name == "FAILED":
        raise RuntimeError(f"Gemini file processing failed: {audio_file.state}")

    # Transcribe
    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=[audio_file, "Transcribe this audio accurately. Output only the transcript, no summary or commentary. Preserve speaker turns if identifiable."],
    )

    transcript = response.text.strip()
    duration_mb = Path(audio_path).stat().st_size / (1024 * 1024)
    print(f"  ✓ Transcribed: {duration_mb:.1f} MB audio, {len(transcript)} chars")

    # Clean up uploaded file
    try:
        client.files.delete(name=audio_file.name)
    except Exception:
        pass

    return transcript, "gemini"


# ─── Summarization ─────────────────────────────────────────────────────────────

def summarize(podcast_name, episode_title, transcript):
    """Summarize transcript using hermes CLI. Falls back to truncated output."""
    print("  ⏳ Summarizing...")

    # Truncate transcript if too long (hermes ask has context limits)
    # Keep first 30k chars (~30 min of speech) — covers most podcast episodes
    truncated = transcript[:30000]
    if len(transcript) > 30000:
        truncated += "\n\n[...transcript truncated...]"

    prompt = f"""Summarize this episode of "{podcast_name}" titled "{episode_title}".

Be detailed and specific. Include:
- Main topics discussed
- Key arguments, data points, and claims
- Notable quotes or insights
- Any actionable takeaways

Do NOT be vague. Reference specific things that were said.

## TRANSCRIPT

{truncated}"""

    result = subprocess.run(
        ["hermes", "chat", "-q", prompt],
        capture_output=True, text=True, timeout=180
    )

    if result.returncode == 0 and result.stdout.strip():
        summary = result.stdout.strip()
        print(f"  ✓ Summarized: {len(summary)} chars")
        return summary

    print("  ⚠️  hermes ask failed, returning raw transcript")
    return None


# ─── Main Pipeline ─────────────────────────────────────────────────────────────

def process_feed(feed_key, conn):
    cfg = FEEDS[feed_key]
    print(f"\n📡 {cfg['name']}")

    episodes = fetch_latest_episodes(feed_key)
    if not episodes:
        print("  No episodes found.")
        return None

    results = []
    for ep in episodes:
        if is_processed(conn, ep["url"]):
            print(f"  ⏭️  Already processed: {ep['title']}")
            continue

        print(f"  📥 {ep['title']}")
        print(f"     Published: {ep['published']}")

        safe_title = re.sub(r'[^\w\s-]', '', ep['title'])[:80].strip()
        safe_title = re.sub(r'\s+', '_', safe_title)
        audio_path = AUDIO_DIR / f"{feed_key}_{safe_title}.mp3"

        try:
            download_audio(ep["audio_url"], audio_path)
        except Exception as e:
            print(f"  ❌ Download failed: {e}")
            continue

        try:
            transcript, language = transcribe(audio_path)
        except Exception as e:
            print(f"  ❌ Transcription failed: {e}")
            continue

        # Build output (transcript only — summarization happens in the cron prompt)
        report = f"🎧 {cfg['name']}\n"
        report += f"📝 {ep['title']}\n"
        report += f"📅 {ep['published']}\n"
        report += f"{'─' * 50}\n\n"
        report += transcript

        results.append(report)
        print(f"  ✓ Done")

    return results


def list_feeds(conn):
    print("\n📚 Configured Podcast Feeds")
    print("=" * 60)
    for key, cfg in FEEDS.items():
        rows = conn.execute(
            "SELECT title, processed_at FROM episodes WHERE feed_key = ? ORDER BY processed_at DESC LIMIT 1",
            (key,)
        ).fetchall()
        last = f"Last: {rows[0][1][:10]} — {rows[0][0][:50]}" if rows else "Never processed"
        print(f"  [{key:12}] {cfg['name']}")
        print(f"               {last}")
        print()


def cleanup_old_audio(audio_dir, max_age_days=3):
    """Delete audio files older than max_age_days."""
    import time
    cutoff = time.time() - (max_age_days * 86400)
    removed = 0
    for f in Path(audio_dir).glob("*.mp3"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            removed += 1
            print(f"  🗑️  Cleaned up: {f.name}")
    if removed:
        print(f"  ✓ Removed {removed} audio file(s) older than {max_age_days} days")


def main():
    parser = argparse.ArgumentParser(description="Podcast Summary Pipeline")
    parser.add_argument("--feeds", type=str, default="all",
                        help="Comma-separated feed keys (ai,allin,hiddenbrain) or 'all'")
    parser.add_argument("--list", action="store_true", help="List configured feeds")
    parser.add_argument("--max-episodes", type=int, default=1, help="Max episodes per feed")
    args = parser.parse_args()

    conn = init_db()

    if args.list:
        list_feeds(conn)
        return

    if args.feeds == "all":
        feed_keys = list(FEEDS.keys())
    else:
        feed_keys = [k.strip() for k in args.feeds.split(",")]
        for k in feed_keys:
            if k not in FEEDS:
                print(f"Unknown feed: {k}")
                print(f"Available: {', '.join(FEEDS.keys())}")
                return

    all_reports = []
    for key in feed_keys:
        reports = process_feed(key, conn)
        if reports:
            all_reports.extend(reports)

    conn.close()

    if all_reports:
        print("\n" + "=" * 60)
        print("SUMMARIES")
        print("=" * 60)
        print("\n---\n\n".join(all_reports))

    # Clean up audio files older than 3 days
    cleanup_old_audio(AUDIO_DIR, max_age_days=3)


if __name__ == "__main__":
    main()
