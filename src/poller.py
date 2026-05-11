import feedparser
from .sources import SOURCES
from . import tg_scraper

PER_SOURCE_LIMIT = 15


def _from_rss(src: dict) -> list[dict]:
    feed = feedparser.parse(src["url"])
    out = []
    for entry in feed.entries[:PER_SOURCE_LIMIT]:
        link = entry.get("link", "").strip()
        title = entry.get("title", "").strip()
        if not link or not title:
            continue
        out.append({
            "source_name": src["name"],
            "tier": src["tier"],
            "category": src["category"],
            "title": title,
            "summary": (entry.get("summary", "") or "")[:1500],
            "link": link,
            "published": entry.get("published", ""),
        })
    return out


def _from_tg(src: dict) -> list[dict]:
    msgs = tg_scraper.fetch_channel(src["channel"], max_messages=PER_SOURCE_LIMIT)
    return [{
        "source_name": src["name"],
        "tier": src["tier"],
        "category": src["category"],
        "title": m["title"],
        "summary": m["summary"],
        "link": m["link"],
        "published": m["published"],
    } for m in msgs]


def fetch_all() -> list[dict]:
    items = []
    for src in SOURCES:
        try:
            if src.get("type") == "tg":
                got = _from_tg(src)
            else:
                got = _from_rss(src)
            print(f"[poller] {src['name']}: {len(got)} items")
            items.extend(got)
        except Exception as e:
            print(f"[poller] {src['name']} FAILED: {type(e).__name__}: {e}")
    return items
