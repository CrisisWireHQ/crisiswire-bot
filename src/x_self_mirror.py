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
4. For each remaining "manual" tweet, post text + visual to FB (tweet
   media → og:image → generated headline card). No links/source comment
   on FB — external links suppress reach; attribution stays X-side.

Runs every 10 minutes from the main cron. Self-rate-limits via the same
mechanism x_watcher uses. Quiet hours are NOT respected here — if the
user manually tweets at 3am, we mirror at 3am.
"""
import os
import re
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import tweepy

from . import fb_poster, fb_card, article_fetcher, state
from .x_watcher import _extract_external_url, OUTLET_MAP  # reuse outlet resolution

OWN_USERNAME = os.environ.get("X_OWN_USERNAME", "CrisisWireHQ")
STATE_FILE = Path(__file__).resolve().parent.parent / "state" / "x_self_mirror.json"
POLL_INTERVAL_SEC = int(os.environ.get("X_SELF_MIRROR_INTERVAL", str(8 * 60)))  # 8 min default
MAX_TWEETS_PER_RUN = 5  # safety cap so a burst doesn't flood FB
MIRRORED_TTL_SECONDS = 14 * 24 * 3600
# Defer tweets younger than this. The approval flow records a bot tweet's ID
# in bot_tweets.json via a *separate* (webhook-approve) GitHub Actions run,
# which commits state asynchronously. A scheduled run-bot that checks out
# before that commit merges would not see the ID and would mirror the
# approved post as if it were manual. Waiting out a buffer lets the state
# propagate. Manual posts just mirror to FB a bit later — acceptable, since
# X (not FB) is the breaking-speed channel.
MIN_TWEET_AGE_SECONDS = int(os.environ.get("X_SELF_MIRROR_MIN_AGE", str(25 * 60)))

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
            tweet_fields=["created_at", "attachments", "entities",
                          "referenced_tweets", "note_tweet", "in_reply_to_user_id"],
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
    recent_drafts = state.load_recent_drafts()
    mirrored = st.setdefault("mirrored", {})

    # Process oldest-first so chronological order is preserved on FB.
    tweets = sorted(resp.data, key=lambda t: int(t.id))
    newest_id = since_id or "0"
    mirrored_count = 0
    now_utc = datetime.now(timezone.utc)

    for tw in tweets:
        tweet_id = str(tw.id)

        # Recency guard. Tweets are ascending by id (≈ chronological), so the
        # first too-young tweet means every following one is also too young —
        # stop here and DON'T advance newest_id, so they're re-fetched (and
        # re-evaluated against by-then-propagated bot_tweets) on a later run.
        created = getattr(tw, "created_at", None)
        if created is not None:
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age = (now_utc - created).total_seconds()
            if age < MIN_TWEET_AGE_SECONDS:
                print(f"[x_self_mirror] defer tweet {tweet_id} "
                      f"(age {int(age)}s < {MIN_TWEET_AGE_SECONDS}s); will retry later")
                break

        # Finalized (old enough to decide) — safe to advance the cursor.
        if int(tweet_id) > int(newest_id):
            newest_id = tweet_id

        # Skip quote-tweets AND reply/thread-continuation tweets: only
        # original standalone posts should mirror. exclude=["replies"] in the
        # API call is unreliable for self-thread replies, so also gate on
        # referenced_tweets (quoted/replied_to) and in_reply_to_user_id.
        refs = getattr(tw, "referenced_tweets", None) or []
        if any(getattr(r, "type", "") in ("quoted", "replied_to") for r in refs):
            print(f"[x_self_mirror] skip quote/reply tweet {tweet_id}")
            continue
        if getattr(tw, "in_reply_to_user_id", None):
            print(f"[x_self_mirror] skip reply tweet {tweet_id}")
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

        # X Premium long posts ("note tweets") truncate tw.text to 280 chars;
        # the full body lives in note_tweet.text. Use it when present.
        text = tw.text or ""
        note = getattr(tw, "note_tweet", None)
        if note:
            note_text = note.get("text") if isinstance(note, dict) else getattr(note, "text", None)
            if note_text and len(note_text) > len(text):
                text = note_text

        # Defensive: never mirror a bare "Source: <url>" auto-reply or an
        # empty/URL-only tweet (junk FB cards otherwise).
        _probe = text.strip()
        if not _probe or _probe.lower().startswith("source:") or re.fullmatch(r"https?://\S+", _probe):
            print(f"[x_self_mirror] skip non-content tweet {tweet_id}: {_probe[:60]!r}")
            continue

        # Backstop for the state-propagation race: even if this tweet's ID
        # hasn't landed in bot_tweets.json yet, the bot's approved draft text
        # is fingerprinted in recent_drafts.json. If the tweet text matches a
        # recent bot draft, it's an approved post (already mirrored to FB by
        # _do_post_from_msg) — skip it.
        try:
            if state.is_recent_draft(recent_drafts, text):
                print(f"[x_self_mirror] skip tweet {tweet_id}: matches a recent bot draft")
                continue
        except Exception as e:
            print(f"[x_self_mirror] recent-draft check failed (non-fatal): {e}")

        # Strip the trailing t.co URL X auto-appends when there's an attached image.
        # FB doesn't need it and it looks ugly.
        text = _strip_trailing_tco(text)

        # Collect ALL media from the tweet (a 2+ photo tweet must become ONE
        # FB album post, not one post per image). Photos expose .url;
        # videos / animated_gifs expose .preview_image_url.
        image_urls = []
        attachments = getattr(tw, "attachments", None) or {}
        for key in attachments.get("media_keys", []) or []:
            m = media_by_key.get(key)
            if not m:
                continue
            url = getattr(m, "url", None) or getattr(m, "preview_image_url", None)
            if url and url not in image_urls:
                image_urls.append(url)

        ext_url, _outlet = _extract_external_url(tw)

        # Visual fallback chain (mirrors _do_post_from_msg): tweet media →
        # og:image from the linked article → generated headline card. Meta
        # heavily down-ranks text-only posts.
        fb_card_path = ""
        if not image_urls and ext_url:
            try:
                og = article_fetcher.fetch_og_image(ext_url)
                if og:
                    image_urls = [og]
                    print(f"[x_self_mirror] using og:image {og[:80]}")
            except Exception as e:
                print(f"[x_self_mirror] og:image lookup failed: {e}")
        if not image_urls:
            fb_card_path = fb_card.generate(text)
            if fb_card_path:
                print("[x_self_mirror] no photo; generated headline card")

        try:
            if len(image_urls) > 1:
                fb_result = fb_poster.post_album(text, image_urls)
            else:
                fb_result = fb_poster.post(
                    text,
                    image_url=image_urls[0] if image_urls else "",
                    image_path=fb_card_path,
                    link_url="",
                )
            fb_id = fb_result.get("id", "")
            print(f"[x_self_mirror] mirrored tweet {tweet_id} → FB post {fb_id}")
        except Exception as e:
            print(f"[x_self_mirror] FB post failed for tweet {tweet_id}: {e}")
            continue  # don't mark mirrored; retry next run (finally cleans card)
        finally:
            if fb_card_path and os.path.exists(fb_card_path):
                try:
                    os.unlink(fb_card_path)
                except Exception:
                    pass

        # No source comment / links on Facebook — external links suppress
        # reach. ext_url is still used above only for the og:image lookup.

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
