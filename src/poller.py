import feedparser
from .sources import SOURCES

PER_SOURCE_LIMIT = 15


def fetch_all() -> list[dict]:
    items = []
    for src in SOURCES:
        try:
            feed = feedparser.parse(src["url"])
            for entry in feed.entries[:PER_SOURCE_LIMIT]:
                link = entry.get("link", "").strip()
                title = entry.get("title", "").strip()
                if not link or not title:
                    continue
                items.append({
                    "source_name": src["name"],
                    "tier": src["tier"],
                    "category": src["category"],
                    "title": title,
                    "summary": (entry.get("summary", "") or "")[:1500],
                    "link": link,
                    "published": entry.get("published", ""),
                })
        except Exception as e:
            print(f"[poller] {src['name']} failed: {e}")
    return items
