"""Poll a specific X user's recent tweets via the paid X API.

Used for watching high-value accounts (e.g. @outbreakupdates) that have no
Telegram mirror. Self-rate-limits and respects quiet hours so cost stays
bounded even when invoked from the 1-minute trusted-only cron.
"""
import os
import json
import time
import calendar
from datetime import datetime
from pathlib import Path

import tweepy

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

_client = None
STATE_FILE = Path(__file__).resolve().parent.parent / "state" / "x_watcher.json"
DEFAULT_POLL_INTERVAL_SEC = 5 * 60   # min seconds between calls per user
QUIET_TZ = "America/New_York"
QUIET_START_HOUR = 23                 # 11pm local
QUIET_END_HOUR = 6                    # 6am local


def _client_v2() -> tweepy.Client:
    global _client
    if _client is None:
        _client = tweepy.Client(bearer_token=os.environ["X_BEARER_TOKEN"])
    return _client


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_state(data: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _is_quiet_hours() -> bool:
    if ZoneInfo is None:
        return False
    try:
        now = datetime.now(ZoneInfo(QUIET_TZ))
    except Exception:
        return False
    h = now.hour
    if QUIET_START_HOUR <= QUIET_END_HOUR:
        return QUIET_START_HOUR <= h < QUIET_END_HOUR
    return h >= QUIET_START_HOUR or h < QUIET_END_HOUR


def _resolve_user_id(username: str) -> str | None:
    try:
        resp = _client_v2().get_user(username=username)
        if resp and resp.data:
            print(f"[x_watcher] resolved @{username} → id {resp.data.id}")
            return str(resp.data.id)
    except Exception as e:
        print(f"[x_watcher] user lookup failed for @{username}: {e}")
    return None


def fetch_user_tweets(username: str, poll_interval_sec: int = DEFAULT_POLL_INTERVAL_SEC) -> list[dict]:
    """Return new tweets from `@username` since the last poll. Self-rate-limited."""
    if _is_quiet_hours():
        print(f"[x_watcher] in quiet hours; skipping @{username}")
        return []

    state = _load_state()
    rec = state.get(username, {})

    last_poll = rec.get("last_poll_ts", 0)
    if time.time() - last_poll < poll_interval_sec:
        secs_remaining = int(poll_interval_sec - (time.time() - last_poll))
        print(f"[x_watcher] @{username} rate-limited ({secs_remaining}s until next allowed)")
        return []

    user_id = rec.get("user_id")
    if not user_id:
        user_id = _resolve_user_id(username)
        if not user_id:
            return []
        rec["user_id"] = user_id

    since_id = rec.get("last_tweet_id")
    try:
        resp = _client_v2().get_users_tweets(
            id=user_id,
            max_results=10,
            tweet_fields=["created_at", "attachments"],
            media_fields=["url", "preview_image_url", "type"],
            expansions=["attachments.media_keys"],
            exclude=["replies", "retweets"],
            since_id=since_id,
        )
    except Exception as e:
        print(f"[x_watcher] @{username} fetch error: {e}")
        rec["last_poll_ts"] = int(time.time())
        state[username] = rec
        _save_state(state)
        return []

    rec["last_poll_ts"] = int(time.time())

    if not resp or not resp.data:
        print(f"[x_watcher] @{username}: no new tweets")
        state[username] = rec
        _save_state(state)
        return []

    media_by_key = {}
    if getattr(resp, "includes", None) and resp.includes.get("media"):
        for m in resp.includes["media"]:
            media_by_key[m.media_key] = m

    out = []
    newest_id = since_id or "0"
    for tw in resp.data:
        tweet_id = str(tw.id)
        if int(tweet_id) > int(newest_id):
            newest_id = tweet_id

        image_url = ""
        attachments = getattr(tw, "attachments", None) or {}
        for key in attachments.get("media_keys", []) or []:
            m = media_by_key.get(key)
            if not m:
                continue
            url = getattr(m, "url", None) or getattr(m, "preview_image_url", None)
            if url:
                image_url = url
                break

        created_at = getattr(tw, "created_at", None)
        ts = created_at.timestamp() if created_at else time.time()
        text = tw.text or ""

        out.append({
            "title": text.split("\n")[0][:200] if text else f"tweet {tweet_id}",
            "summary": text[:1500],
            "link": f"https://x.com/{username}/status/{tweet_id}",
            "published": created_at.isoformat() if created_at else "",
            "ts": ts,
            "image_url": image_url,
        })

    rec["last_tweet_id"] = newest_id
    state[username] = rec
    _save_state(state)
    print(f"[x_watcher] @{username}: {len(out)} new tweets (newest_id={newest_id})")
    return out
