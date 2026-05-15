"""Fetch full article body to enrich drafter context, and resolve Google News
redirect URLs to their actual destination so source-reply tweets cite the real
outlet instead of a `news.google.com` link.
"""
import base64
import re
import requests
import trafilatura
from urllib.parse import urljoin
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
_GN_ARTICLE_RE = re.compile(r"/articles/([A-Za-z0-9_-]+)")
_URL_IN_BYTES_RE = re.compile(r'https?://[^\x00-\x1f\x80-\xff\s"\\\'<>]+')
_TRAILING_GARBAGE_RE = re.compile(r"[^\w\-./?=&%:#~+]+$")


def _is_google_news(url: str) -> bool:
    return "news.google.com" in (url or "")


def _is_telegram(url: str) -> bool:
    return "t.me/" in (url or "")


def _decode_gnews_base64(url: str) -> str:
    """Try to extract the underlying target URL from a Google News URL's base64 payload."""
    m = _GN_ARTICLE_RE.search(url)
    if not m:
        return ""
    encoded = m.group(1)
    padding = "=" * (-len(encoded) % 4)
    try:
        decoded = base64.urlsafe_b64decode(encoded + padding)
    except Exception:
        return ""
    text = decoded.decode("latin-1", errors="ignore")
    candidates = _URL_IN_BYTES_RE.findall(text)
    # Take the longest non-Google candidate (the real article URL tends to be substantial)
    best = ""
    for c in candidates:
        c = _TRAILING_GARBAGE_RE.sub("", c)
        if "news.google.com" in c or "googleusercontent" in c or len(c) < 15:
            continue
        if len(c) > len(best):
            best = c
    return best


def _resolve_gnews_http(url: str) -> str:
    """Fallback: hit the Google News URL and see if it HTTP-redirects to the real source."""
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=15, allow_redirects=True)
        if r.url and "news.google.com" not in r.url:
            return r.url
    except Exception as e:
        print(f"[article_fetcher] http resolve failed: {e}")
    return ""


def resolve_url(url: str) -> str:
    """Return the real destination URL. Falls back to input on failure."""
    if not url or not _is_google_news(url):
        return url
    decoded = _decode_gnews_base64(url)
    if decoded:
        return decoded
    fallback = _resolve_gnews_http(url)
    return fallback or url


def fetch_article(url: str, max_chars: int = 4000) -> dict:
    """Fetch article body and resolve any Google News redirect.

    Returns dict {'text': str, 'resolved_url': str}.
    """
    result = {"text": "", "resolved_url": url}
    if not url or _is_telegram(url):
        return result

    target = resolve_url(url)
    result["resolved_url"] = target

    try:
        downloaded = trafilatura.fetch_url(target, no_ssl=False)
        if not downloaded:
            return result
        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            include_formatting=False,
            no_fallback=False,
        )
        if text:
            result["text"] = re.sub(r"\n{3,}", "\n\n", text).strip()[:max_chars]
    except Exception as e:
        print(f"[article_fetcher] extract failed for {target}: {e}")

    return result


_BAD_IMG_HINTS = (
    "logo", "sprite", "placeholder", "default", "blank", "1x1", "pixel",
    "avatar", "icon", "favicon", "share", "social-default",
    "gstatic", "googlelogo", "google_news", "news.google",
)


def fetch_og_image(url: str) -> str:
    """Return the article's lead image (og:image / twitter:image) absolute URL.

    Used as the Facebook image when an RSS/Telegram item carried no media of
    its own — the outlet's own story photo is the most relevant, story-specific
    visual we can attach for free. Returns "" if nothing usable found.
    """
    if not url or _is_telegram(url):
        return ""
    target = resolve_url(url)
    # If the Google News redirect couldn't be decoded, `target` is still a
    # google.com / news.google.com URL. Scraping it yields Google News's own
    # og:image (the Google logo), which is useless. Bail so the caller falls
    # back to the generated headline card instead.
    low_t = (target or "").lower()
    if ("news.google.com" in low_t or "google.com/" in low_t
            or "googleusercontent.com" in low_t):
        print(f"[article_fetcher] og:image skipped — unresolved Google URL: {target[:80]}")
        return ""
    try:
        r = requests.get(target, headers={"User-Agent": UA}, timeout=15)
        if r.status_code != 200 or "html" not in (r.headers.get("content-type") or "").lower():
            return ""
        soup = BeautifulSoup(r.text, "lxml")
    except Exception as e:
        print(f"[article_fetcher] og:image fetch failed for {target}: {e}")
        return ""

    candidates = []
    for prop in ("og:image:secure_url", "og:image:url", "og:image", "twitter:image", "twitter:image:src"):
        for tag in soup.find_all("meta", attrs={"property": prop}) + soup.find_all("meta", attrs={"name": prop}):
            content = (tag.get("content") or "").strip()
            if content:
                candidates.append(content)

    for c in candidates:
        absu = urljoin(target, c)
        low = absu.lower()
        if not low.startswith("http"):
            continue
        if any(h in low for h in _BAD_IMG_HINTS):
            continue
        return absu
    return ""


# Backwards-compat shim
def fetch_article_text(url: str, max_chars: int = 4000) -> str:
    return fetch_article(url, max_chars).get("text", "")
