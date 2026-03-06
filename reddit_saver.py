#!/usr/bin/env python3
"""
reddit_saver.py

Downloads all native Reddit videos from your "Saved" posts and stitches them
into a single compilation video.  Re-running the script only downloads videos
that have not been downloaded before (tracked by post ID), then rebuilds the
compilation in a newly randomized order.

Requirements
------------
- Python 3.8+
- ffmpeg installed and available on PATH
- A Reddit "script" OAuth app (https://www.reddit.com/prefs/apps)
- Credentials stored in a .env file (see .env.example)

Usage
-----
    pip install -r requirements.txt
    cp .env.example .env   # then fill in your credentials
    python reddit_saver.py
"""

import json
import os
import random
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import praw
import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv()

DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "videos"))
OUTPUT_FILE = os.getenv("OUTPUT_FILE", "compilation.mp4")
DOWNLOADED_IDS_FILE = Path(os.getenv("DOWNLOADED_IDS_FILE", "downloaded_ids.json"))
RATE_LIMIT_DELAY = float(os.getenv("RATE_LIMIT_DELAY", "2.0"))

# ---------------------------------------------------------------------------
# Helpers: downloaded-ID tracking
# ---------------------------------------------------------------------------


def load_downloaded_ids() -> set:
    """Return the set of post IDs that have already been downloaded."""
    if DOWNLOADED_IDS_FILE.exists():
        with open(DOWNLOADED_IDS_FILE, encoding="utf-8") as fh:
            return set(json.load(fh))
    return set()


def save_downloaded_ids(ids: set) -> None:
    """Persist the set of downloaded post IDs to disk."""
    with open(DOWNLOADED_IDS_FILE, "w", encoding="utf-8") as fh:
        json.dump(sorted(ids), fh, indent=2)


# ---------------------------------------------------------------------------
# Helpers: Reddit client
# ---------------------------------------------------------------------------


def build_reddit_client() -> praw.Reddit:
    """Create an authenticated Reddit client from environment variables."""
    return praw.Reddit(
        client_id=os.getenv("REDDIT_CLIENT_ID"),
        client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
        username=os.getenv("REDDIT_USERNAME"),
        password=os.getenv("REDDIT_PASSWORD"),
        user_agent=os.getenv("REDDIT_USER_AGENT", "reddit_saver/1.0"),
    )


# ---------------------------------------------------------------------------
# Helpers: video URL extraction
# ---------------------------------------------------------------------------


def get_video_urls(submission) -> tuple:
    """
    Return (video_url, audio_url) for a Reddit-hosted video submission.

    Reddit stores video and audio as separate DASH streams.  The audio URL is
    derived from the base path of the video URL.  Returns (None, None) if the
    submission does not contain a native Reddit video.
    """
    media = getattr(submission, "media", None)
    if not media:
        return None, None

    reddit_video = media.get("reddit_video")
    if not reddit_video:
        return None, None

    video_url = reddit_video.get("fallback_url")
    if not video_url:
        return None, None

    # Strip any query-string parameters, then build the audio URL from the
    # same base path (e.g. https://v.redd.it/<id>/DASH_audio.mp4).
    base_url = video_url.split("?")[0].rsplit("/", 1)[0]
    audio_url = f"{base_url}/DASH_audio.mp4"

    return video_url, audio_url


# ---------------------------------------------------------------------------
# Helpers: downloading
# ---------------------------------------------------------------------------


def _stream_to_file(url: str, dest: Path, session: requests.Session) -> None:
    """Stream *url* to *dest*, raising on HTTP errors."""
    response = session.get(url, stream=True, timeout=30)
    response.raise_for_status()
    response.raw.decode_content = True
    with open(dest, "wb") as fh:
        shutil.copyfileobj(response.raw, fh)


def _url_exists(url: str, session: requests.Session) -> bool:
    """Return True if a HEAD request to *url* returns HTTP 200."""
    try:
        resp = session.head(url, timeout=10)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def download_video(submission, download_dir: Path, session: requests.Session):
    """
    Download a Reddit-hosted video (and its audio track, if present) to
    *download_dir* and merge the streams with ffmpeg.

    Returns the Path of the merged output file, or None on failure.
    """
    video_url, audio_url = get_video_urls(submission)
    if not video_url:
        return None

    post_id = submission.id
    video_tmp = download_dir / f"{post_id}_video.mp4"
    audio_tmp = download_dir / f"{post_id}_audio.mp4"
    output_path = download_dir / f"{post_id}.mp4"

    print("  Downloading video stream …")
    _stream_to_file(video_url, video_tmp, session)

    has_audio = _url_exists(audio_url, session)
    if has_audio:
        print("  Downloading audio stream …")
        _stream_to_file(audio_url, audio_tmp, session)

        print("  Merging streams with ffmpeg …")
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(video_tmp),
                "-i", str(audio_tmp),
                "-c:v", "copy",
                "-c:a", "aac",
                "-loglevel", "error",
                str(output_path),
            ],
            capture_output=True,
        )

        video_tmp.unlink(missing_ok=True)
        audio_tmp.unlink(missing_ok=True)

        if result.returncode != 0:
            print(f"  Warning: ffmpeg merge failed – {result.stderr.decode().strip()}")
            return None
    else:
        # No audio track: the video file is the final output.
        video_tmp.rename(output_path)

    return output_path


# ---------------------------------------------------------------------------
# Helpers: compilation
# ---------------------------------------------------------------------------


def create_compilation(video_files: list, output_path: str) -> bool:
    """
    Concatenate *video_files* into *output_path* using the ffmpeg concat
    demuxer.  Returns True on success, False on failure.
    """
    if not video_files:
        print("No video files available for compilation.")
        return False

    concat_list = Path("concat_list.txt")
    with open(concat_list, "w", encoding="utf-8") as fh:
        for vf in video_files:
            fh.write(f"file {shlex.quote(str(vf.resolve()))}\n")

    print(f"Compiling {len(video_files)} videos into {output_path} …")
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            "-loglevel", "error",
            output_path,
        ],
        capture_output=True,
    )

    concat_list.unlink(missing_ok=True)

    if result.returncode != 0:
        print(f"Error: ffmpeg compilation failed – {result.stderr.decode().strip()}")
        return False

    print(f"Compilation saved to {output_path}")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    # Validate required environment variables.
    required_vars = [
        "REDDIT_CLIENT_ID",
        "REDDIT_CLIENT_SECRET",
        "REDDIT_USERNAME",
        "REDDIT_PASSWORD",
    ]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        print(f"Error: missing required environment variables: {', '.join(missing)}")
        print("Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)

    # Ensure ffmpeg is available before doing any work.
    if not shutil.which("ffmpeg"):
        print("Error: ffmpeg not found on PATH.  Please install ffmpeg.")
        sys.exit(1)

    DOWNLOAD_DIR.mkdir(exist_ok=True)

    downloaded_ids = load_downloaded_ids()
    print(f"Previously downloaded: {len(downloaded_ids)} video(s).")

    # Connect to Reddit (PRAW enforces Reddit's built-in rate limits automatically).
    print("Connecting to Reddit …")
    reddit = build_reddit_client()

    print("Fetching saved posts …")
    new_count = 0

    with requests.Session() as session:
        session.headers.update(
            {"User-Agent": os.getenv("REDDIT_USER_AGENT", "reddit_saver/1.0")}
        )

        for item in reddit.user.me().saved(limit=None):
            # saved() returns both Submission and Comment objects; skip comments.
            if not isinstance(item, praw.models.Submission):
                continue

            if item.id in downloaded_ids:
                continue

            video_url, _ = get_video_urls(item)
            if not video_url:
                continue

            title = getattr(item, "title", item.id)
            print(f"\nDownloading [{item.id}]: {title[:70]}")

            try:
                out = download_video(item, DOWNLOAD_DIR, session)
                if out:
                    downloaded_ids.add(item.id)
                    save_downloaded_ids(downloaded_ids)
                    new_count += 1
                    print(f"  Saved → {out}")
                else:
                    print("  Skipped (no downloadable video).")
            except Exception as exc:
                print(f"  Error downloading {item.id}: {exc}")

            # Configurable delay between downloads to avoid rate-limit bans.
            time.sleep(RATE_LIMIT_DELAY)

    print(f"\nDownloaded {new_count} new video(s).")

    # Collect every .mp4 that lives in the download directory.
    video_files = sorted(DOWNLOAD_DIR.glob("*.mp4"))

    if not video_files:
        print("No video files found.  Nothing to compile.")
        return

    # Randomise the order so each rebuild produces a different compilation.
    random.shuffle(video_files)

    create_compilation(video_files, OUTPUT_FILE)


if __name__ == "__main__":
    main()
