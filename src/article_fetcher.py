"""Fetch full article body to enrich drafter context, and resolve Google News
redirect URLs to their actual destination so source-reply tweets cite the real
outlet instead of a `news.google.com` link.
"""
import base64
import re
import requests
import trafilatura

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


# Backwards-compat shim
def fetch_article_text(url: str, max_chars: int = 4000) -> str:
    return fetch_article(url, max_chars).get("text", "")
