# reddit_saver

Download every native Reddit video from your **Saved** posts and stitch them
into a single compilation.  Re-running the script only downloads *new* videos
(already-downloaded IDs are tracked in `downloaded_ids.json`) and rebuilds the
compilation in a freshly randomized order each time.

---

## Requirements

- Python 3.8+
- [ffmpeg](https://ffmpeg.org/download.html) installed and available on `PATH`
- A Reddit **script** OAuth application –
  create one at <https://www.reddit.com/prefs/apps>

## Setup

```bash
# 1. Clone / enter the repo
git clone https://github.com/willowduster/reddit_saver.git
cd reddit_saver

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Create your .env file
cp .env.example .env
# Open .env and fill in your Reddit credentials
```

## .env credentials

| Variable | Description |
|---|---|
| `REDDIT_CLIENT_ID` | OAuth app client ID |
| `REDDIT_CLIENT_SECRET` | OAuth app client secret |
| `REDDIT_USERNAME` | Your Reddit username |
| `REDDIT_PASSWORD` | Your Reddit password |
| `REDDIT_USER_AGENT` | User-agent string (see Reddit API rules) |
| `DOWNLOAD_DIR` | Directory for downloaded video files (default: `videos`) |
| `OUTPUT_FILE` | Final compilation filename (default: `compilation.mp4`) |
| `DOWNLOADED_IDS_FILE` | ID-tracking file (default: `downloaded_ids.json`) |
| `RATE_LIMIT_DELAY` | Seconds between downloads (default: `2.0`) |

## Usage

```bash
python reddit_saver.py
```

On the **first run** the script will:

1. Fetch all saved posts from your Reddit account.
2. Download every native Reddit video (`v.redd.it`) it finds, merging the
   separate video and audio DASH streams with ffmpeg.
3. Save each post ID to `downloaded_ids.json`.
4. Shuffle all downloaded videos and concatenate them into `compilation.mp4`.

On **subsequent runs** only newly saved videos are downloaded; the
compilation is then rebuilt in a new random order from the full video library.

## Rate limiting

PRAW (the Reddit API client) automatically respects Reddit's built-in rate
limits.  The `RATE_LIMIT_DELAY` setting adds an additional pause *between
individual video downloads* to further reduce the risk of being rate-limited
or banned.  Increase this value (e.g. `5.0`) if you have a large saved list.

## Notes

- Only native Reddit-hosted videos (`v.redd.it`) are downloaded.  Links to
  YouTube, Twitch, or other external sites are skipped.
- The compilation uses ffmpeg's concat demuxer with stream copy (`-c copy`)
  for speed.  All source videos should share the same codec/resolution for
  best results; ffmpeg will warn you if they do not.
- Your `.env` file, the `videos/` directory, `downloaded_ids.json`, and
  `compilation.mp4` are all listed in `.gitignore` so they are never
  accidentally committed.
