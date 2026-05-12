"""Fetch full article body to enrich drafter context.

RSS summaries are often just a sentence or two. Without the full article body,
the drafter has no way to include specific named entities (vessel names, exact
locations, casualty counts, official quotes).
"""
import re
import requests
import trafilatura

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def _is_google_news(url: str) -> bool:
    return "news.google.com" in (url or "")


def _is_telegram(url: str) -> bool:
    return "t.me/" in (url or "")


def _resolve_google_news(url: str) -> str:
    """Google News URLs redirect via JS. Follow HTTP redirects we CAN, return what we get."""
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=15, allow_redirects=True)
        # If we got redirected to a real source, return that URL
        if r.url and "news.google.com" not in r.url:
            return r.url
    except Exception as e:
        print(f"[article_fetcher] google news resolve failed: {e}")
    return ""


def fetch_article_text(url: str, max_chars: int = 4000) -> str:
    """Fetch and extract main article body. Returns empty string on any failure."""
    if not url:
        return ""
    if _is_telegram(url):
        # TG scraper already gave us the full message body
        return ""

    target = url
    if _is_google_news(url):
        target = _resolve_google_news(url)
        if not target:
            return ""

    try:
        downloaded = trafilatura.fetch_url(target, no_ssl=False)
        if not downloaded:
            return ""
        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            include_formatting=False,
            no_fallback=False,
        )
        if not text:
            return ""
        # Strip excessive whitespace
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text[:max_chars]
    except Exception as e:
        print(f"[article_fetcher] extract failed for {target}: {e}")
        return ""
