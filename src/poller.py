import os
import re
import time
import calendar
from datetime import datetime, timezone

import feedparser
from .sources import SOURCES
from . import tg_scraper, x_watcher

_IMG_TAG_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)


# Feeds that ship one image at several resolutions list them as separate
# media:content entries. Below this longest-edge (px) an image looks grainy
# once X upscales it in-feed, so we treat it as a thumbnail-grade last resort.
_MIN_GOOD_EDGE = 600


def _img_area(m: dict) -> int:
    """Declared pixel area of a media entry, or 0 if dimensions unknown."""
    try:
        w = int(float(m.get("width") or 0))
        h = int(float(m.get("height") or 0))
    except (TypeError, ValueError):
        return 0
    return w * h


def _largest_edge(m: dict) -> int:
    try:
        return max(int(float(m.get("width") or 0)), int(float(m.get("height") or 0)))
    except (TypeError, ValueError):
        return 0


def _extract_rss_image(entry) -> str:
    # Among same-image-multiple-resolution media:content entries, take the
    # biggest by declared area rather than the first (often the smallest).
    media = [m for m in (entry.get("media_content") or []) if isinstance(m, dict) and m.get("url")]
    if media:
        media.sort(key=_img_area, reverse=True)
        best = media[0]
        # If the best has known dimensions but is small, fall through to other
        # sources first; only return it if nothing larger turns up.
        if _img_area(best) == 0 or _largest_edge(best) >= _MIN_GOOD_EDGE:
            return best["url"]
        small_media_url = best["url"]
    else:
        small_media_url = ""

    enclosures = entry.get("enclosures") or []
    for e in enclosures:
        if not isinstance(e, dict):
            continue
        if (e.get("type") or "").startswith("image/"):
            url = e.get("href") or e.get("url")
            if url:
                return url

    # media:thumbnail is explicitly a thumbnail — only worth it if we have
    # nothing better at all.
    thumb = entry.get("media_thumbnail")
    if thumb:
        for t in thumb:
            url = t.get("url") if isinstance(t, dict) else None
            if url:
                return small_media_url or url

    summary = entry.get("summary", "") or entry.get("description", "")
    if summary:
        m = _IMG_TAG_RE.search(summary)
        if m:
            return small_media_url or m.group(1)

    return small_media_url

PER_SOURCE_LIMIT = 15
MAX_AGE_HOURS = float(os.environ.get("MAX_AGE_HOURS", "3"))


def _to_epoch_rss(entry) -> float | None:
    for key in ("published_parsed", "updated_parsed"):
        v = entry.get(key)
        if v:
            try:
                return calendar.timegm(v)
            except Exception:
                pass
    return None


def _to_epoch_iso(s: str) -> float | None:
    if not s:
        return None
    try:
        # tg datetimes look like "2026-05-10T15:30:45+00:00"
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def _is_fresh(ts: float | None) -> bool:
    if ts is None:
        return False  # no timestamp -> drop (safer than risking ancient news)
    age_h = (time.time() - ts) / 3600.0
    return age_h <= MAX_AGE_HOURS


def _from_rss(src: dict) -> list[dict]:
    feed = feedparser.parse(src["url"])
    out = []
    kept = 0
    for entry in feed.entries[:PER_SOURCE_LIMIT * 2]:
        link = entry.get("link", "").strip()
        title = entry.get("title", "").strip()
        if not link or not title:
            continue
        ts = _to_epoch_rss(entry)
        if not _is_fresh(ts):
            continue
        out.append({
            "source_name": src["name"],
            "tier": src["tier"],
            "category": src["category"],
            "title": title,
            "summary": (entry.get("summary", "") or "")[:1500],
            "link": link,
            "published": entry.get("published", ""),
            "ts": ts,
            "image_url": _extract_rss_image(entry),
        })
        kept += 1
        if kept >= PER_SOURCE_LIMIT:
            break
    return out


def _from_tg(src: dict) -> list[dict]:
    msgs = tg_scraper.fetch_channel(src["channel"], max_messages=PER_SOURCE_LIMIT * 2)
    out = []
    kept = 0
    for m in msgs:
        ts = _to_epoch_iso(m["published"])
        if not _is_fresh(ts):
            continue
        item = {
            "source_name": src["name"],
            "tier": src["tier"],
            "category": src["category"],
            "title": m["title"],
            "summary": m["summary"],
            "link": m["link"],           # t.me URL — used for is_seen dedup
            "published": m["published"],
            "ts": ts,
            "image_url": m.get("image_url", ""),
        }
        # Trusted firehose (e.g. Faytuks): we're competing with them, so don't
        # credit them in the post and don't link their telegram in the X reply.
        # Use the underlying source URL from the message body if they linked one;
        # otherwise no source reply at all.
        if src.get("trusted"):
            item["display_source"] = ""  # blank → drafter omits attribution
            item["source_url"] = m.get("external_url", "")  # may be ""
        out.append(item)
        kept += 1
        if kept >= PER_SOURCE_LIMIT:
            break
    return out


def _from_x(src: dict) -> list[dict]:
    raw = x_watcher.fetch_user_tweets(src["username"])
    out = []
    for r in raw:
        if not _is_fresh(r.get("ts")):
            continue
        # source_name stays as src["name"] (e.g. "X: @outbreakupdates") so
        # trusted-only filtering and dedup logic still work.
        # display_source overrides attribution in Telegram + drafter: when the
        # watched account links to BBC, we credit BBC, not the watched account.
        # If no outlet resolved, display_source = "" → drafter writes without
        # attribution and source reply is skipped.
        out.append({
            "source_name": src["name"],
            "display_source": (r.get("outlet") or "").strip(),
            "tier": src["tier"],
            "category": src["category"],
            "title": r["title"],
            "summary": r["summary"],
            "link": r["link"],
            "published": r["published"],
            "ts": r["ts"],
            "image_url": r.get("image_url", ""),
        })
    return out


def fetch_all() -> list[dict]:
    items = []
    for src in SOURCES:
        try:
            stype = src.get("type")
            if stype == "tg":
                got = _from_tg(src)
            elif stype == "x":
                got = _from_x(src)
            else:
                got = _from_rss(src)
            print(f"[poller] {src['name']}: {len(got)} fresh items")
            items.extend(got)
        except Exception as e:
            print(f"[poller] {src['name']} FAILED: {type(e).__name__}: {e}")
    # newest first
    items.sort(key=lambda x: x.get("ts") or 0, reverse=True)
    return items
