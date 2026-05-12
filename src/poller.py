import os
import time
import calendar
from datetime import datetime, timezone

import feedparser
from .sources import SOURCES
from . import tg_scraper

PER_SOURCE_LIMIT = 15
MAX_AGE_HOURS = float(os.environ.get("MAX_AGE_HOURS", "6"))


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
        out.append({
            "source_name": src["name"],
            "tier": src["tier"],
            "category": src["category"],
            "title": m["title"],
            "summary": m["summary"],
            "link": m["link"],
            "published": m["published"],
            "ts": ts,
        })
        kept += 1
        if kept >= PER_SOURCE_LIMIT:
            break
    return out


def fetch_all() -> list[dict]:
    items = []
    for src in SOURCES:
        try:
            if src.get("type") == "tg":
                got = _from_tg(src)
            else:
                got = _from_rss(src)
            print(f"[poller] {src['name']}: {len(got)} fresh items")
            items.extend(got)
        except Exception as e:
            print(f"[poller] {src['name']} FAILED: {type(e).__name__}: {e}")
    # newest first
    items.sort(key=lambda x: x.get("ts") or 0, reverse=True)
    return items
