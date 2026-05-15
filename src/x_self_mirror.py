"""Mirror manual @CrisisWireHQ tweets to the Facebook Page.

Bot-posted tweets (via the Telegram approval flow) are already mirrored to FB
in main._do_post_from_msg(). This module handles the OTHER case: tweets the
human posted manually on X.app or x.com that the bot never saw.

Approach:
1. Poll @CrisisWireHQ's recent tweets via the X API (paid Basic-tier read).
2. Filter out tweets the bot itself posted, tracked by tweet ID in
   state.bot_tweets.json (recorded in _do_post_from_msg after successful
   x_poster.post()).
3. Filter out tweets we already mirrored (tracked in state/x_self_mirror.json).
4. For each remaining "manual" tweet, post text + image (if any) to FB,
   then comment with the first external URL found in the tweet entities
   (parity with the X source-reply behavior).

Runs every 10 minutes from the main cron. Self-rate-limits via the same
mechanism x_watcher uses. Quiet hours are NOT respected here — if the
user manually tweets at 3am, we mirror at 3am.
"""
import os
import json
import time
from pathlib import Path

import tweepy

from . import fb_poster, state
from .x_watcher import _extract_external_url, OUTLET_MAP  # reuse outlet resolution

OWN_USERNAME = os.environ.get("X_OWN_USERNAME", "CrisisWireHQ")
STATE_FILE = Path(__file__).resolve().parent.parent / "state" / "x_self_mirror.json"
POLL_INTERVAL_SEC = int(os.environ.get("X_SELF_MIRROR_INTERVAL", str(8 * 60)))  # 8 min default
MAX_TWEETS_PER_RUN = 5  # safety cap so a burst doesn't flood FB
MIRRORED_TTL_SECONDS = 14 * 24 * 3600

_client = None


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
    # Prune the mirrored set to TTL so the file doesn't grow forever.
    cutoff = time.time() - MIRRORED_TTL_SECONDS
    mirrored = data.get("mirrored", {})
    data["mirrored"] = {k: v for k, v in mirrored.items() if isinstance(v, (int, float)) and v >= cutoff}
    STATE_FILE.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _resolve_user_id(username: str) -> str | None:
    try:
        resp = _client_v2().get_user(username=username)
        if resp and resp.data:
            return str(resp.data.id)
    except Exception as e:
        print(f"[x_self_mirror] user lookup failed for @{username}: {e}")
    return None


def run() -> int:
    """Poll own timeline and mirror new manual tweets to FB. Returns count mirrored."""
    if not fb_poster.enabled():
        return 0
    if not os.environ.get("X_BEARER_TOKEN"):
        print("[x_self_mirror] X_BEARER_TOKEN not set; skipping")
        return 0

    st = _load_state()
    last_poll = st.get("last_poll_ts", 0)
    if time.time() - last_poll < POLL_INTERVAL_SEC:
        secs = int(POLL_INTERVAL_SEC - (time.time() - last_poll))
        print(f"[x_self_mirror] rate-limited ({secs}s until next allowed)")
        return 0

    user_id = st.get("user_id")
    if not user_id:
        user_id = _resolve_user_id(OWN_USERNAME)
        if not user_id:
            return 0
        st["user_id"] = user_id

    since_id = st.get("last_tweet_id")
    try:
        resp = _client_v2().get_users_tweets(
            id=user_id,
            max_results=10,
            tweet_fields=["created_at", "attachments", "entities", "referenced_tweets"],
            media_fields=["url", "preview_image_url", "type"],
            expansions=["attachments.media_keys"],
            exclude=["replies", "retweets"],
            since_id=since_id,
        )
    except Exception as e:
        print(f"[x_self_mirror] fetch error: {e}")
        st["last_poll_ts"] = int(time.time())
        _save_state(st)
        return 0

    st["last_poll_ts"] = int(time.time())

    if not resp or not resp.data:
        print(f"[x_self_mirror] @{OWN_USERNAME}: no new tweets")
        _save_state(st)
        return 0

    media_by_key = {}
    if getattr(resp, "includes", None) and resp.includes.get("media"):
        for m in resp.includes["media"]:
            media_by_key[m.media_key] = m

    bot_tweets = state.load_bot_tweets()
    mirrored = st.setdefault("mirrored", {})

    # Process oldest-first so chronological order is preserved on FB.
    tweets = sorted(resp.data, key=lambda t: int(t.id))
    newest_id = since_id or "0"
    mirrored_count = 0

    for tw in tweets:
        tweet_id = str(tw.id)
        if int(tweet_id) > int(newest_id):
            newest_id = tweet_id

        # Skip quote-tweets: they reference another tweet by ID and the FB
        # mirror would lose that context. Easier to skip than render badly.
        refs = getattr(tw, "referenced_tweets", None) or []
        if any(getattr(r, "type", "") == "quoted" for r in refs):
            print(f"[x_self_mirror] skip quote-tweet {tweet_id}")
            continue

        if state.is_bot_tweet(bot_tweets, tweet_id):
            print(f"[x_self_mirror] skip bot-posted tweet {tweet_id}")
            continue
        if tweet_id in mirrored:
            print(f"[x_self_mirror] skip already-mirrored tweet {tweet_id}")
            continue

        if mirrored_count >= MAX_TWEETS_PER_RUN:
            print(f"[x_self_mirror] hit MAX_TWEETS_PER_RUN cap; remaining will be picked up next run")
            break

        text = tw.text or ""
        # Strip the trailing t.co URL X auto-appends when there's an attached image.
        # FB doesn't need it and it looks ugly.
        text = _strip_trailing_tco(text)

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

        ext_url, _outlet = _extract_external_url(tw)

        try:
            fb_result = fb_poster.post(text, image_url=image_url, link_url="")  # link added via comment instead
            fb_id = fb_result.get("id", "")
            print(f"[x_self_mirror] mirrored tweet {tweet_id} → FB post {fb_id}")
        except Exception as e:
            print(f"[x_self_mirror] FB post failed for tweet {tweet_id}: {e}")
            continue  # don't mark mirrored; retry next run

        # Source comment (parity with X auto-reply behavior in _do_post_from_msg).
        if ext_url and fb_id:
            try:
                fb_poster.comment(fb_id, f"Source: {ext_url}")
                print(f"[x_self_mirror] commented source on FB post {fb_id}")
            except Exception as e:
                # Non-fatal — post is already live.
                print(f"[x_self_mirror] source comment failed (non-fatal): {e}")

        mirrored[tweet_id] = int(time.time())
        mirrored_count += 1

    st["last_tweet_id"] = newest_id
    _save_state(st)
    print(f"[x_self_mirror] done; {mirrored_count} tweet(s) mirrored")
    return mirrored_count


def _strip_trailing_tco(text: str) -> str:
    """Remove a trailing 'https://t.co/...' that X auto-appends when an image
    is attached — it points back to the tweet itself, which is meaningless
    when re-posted on FB."""
    import re
    return re.sub(r"\s*https?://t\.co/\S+\s*$", "", text or "").strip()
