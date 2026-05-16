import re
import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
PREVIEW = "https://t.me/s/{channel}"
_BG_IMG_RE = re.compile(r"background-image\s*:\s*url\(['\"]?([^'\"\)]+)['\"]?\)")


def _extract_external_url(text_el) -> str:
    """First href in the message body that is NOT a self-link to Telegram.
    Used to find the underlying source URL Faytuks et al. usually link to."""
    if text_el is None:
        return ""
    for a in text_el.find_all("a", href=True):
        href = a["href"].strip()
        if not href.startswith(("http://", "https://")):
            continue
        low = href.lower()
        if "t.me/" in low or "telegram.me/" in low or "telegram.org/" in low:
            continue
        # Skip hashtag / mention links which are tg:// or anchor refs
        if href.startswith("#") or href.startswith("tg:"):
            continue
        return href
    return ""


def _extract_image(block) -> str:
    photo = block.select_one("a.tgme_widget_message_photo_wrap")
    if photo and photo.get("style"):
        m = _BG_IMG_RE.search(photo["style"])
        if m:
            return m.group(1).strip()
    # Video poster thumbnail. NOTE: Telegram renders this as an <i> (and
    # historically <a>), so match the class on ANY tag — the old
    # `a.tgme_widget_message_video_thumb` selector silently missed every
    # video post, sending them out as bare text.
    video = block.select_one(".tgme_widget_message_video_thumb")
    if video and video.get("style"):
        m = _BG_IMG_RE.search(video["style"])
        if m:
            return m.group(1).strip()
    return ""


def _extract_video_url(block) -> str:
    """Direct CDN .mp4 URL for a video message, or '' if none.

    t.me/s/ serves a playable <video src> for most clips (it's the preview
    encode, not the original, but fine for reposting)."""
    v = block.select_one("video.tgme_widget_message_video[src], video[src]")
    if v:
        src = (v.get("src") or "").strip()
        if src.startswith(("http://", "https://")):
            return src
    return ""


def fetch_channel(channel: str, max_messages: int = 15) -> list[dict]:
    url = PREVIEW.format(channel=channel)
    r = requests.get(url, headers={"User-Agent": UA}, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    out = []
    blocks = soup.select("div.tgme_widget_message_wrap")
    for block in reversed(blocks[-max_messages:]):
        # Pick the message's OWN text, not the embedded preview of a replied-to
        # message. The reply preview lives inside a `.tgme_widget_message_reply`
        # parent, and Telegram sometimes uses `.tgme_widget_message_text` for
        # that too — so we walk all candidates and skip those nested in a reply.
        text_el = None
        for el in block.select("div.tgme_widget_message_text"):
            if el.find_parent(class_="tgme_widget_message_reply"):
                continue
            text_el = el
            break
        if not text_el:
            continue
        external_url = _extract_external_url(text_el)
        text = text_el.get_text(separator=" ", strip=True)
        if len(text) < 15:
            continue

        date_a = block.select_one("a.tgme_widget_message_date")
        link = date_a.get("href", "").strip() if date_a else ""
        # Prefer the message date link's <time datetime>; some posts (esp.
        # video / grouped media) put an unrelated <time> first, so fall back
        # to any timestamped <time> before the bare first one.
        time_el = (
            block.select_one("a.tgme_widget_message_date time[datetime]")
            or block.select_one("time[datetime]")
            or block.select_one("time")
        )
        published = time_el.get("datetime", "") if time_el else ""
        image_url = _extract_image(block)
        video_url = _extract_video_url(block)

        title = text.split("\n")[0][:200]
        out.append({
            "title": title,
            "summary": text[:1500],
            "link": link,
            "published": published,
            "image_url": image_url,
            "video_url": video_url,
            "external_url": external_url,
        })
    if channel.lower() in ("faytuks_network", "outbreakupdates"):
        for o in out[:6]:
            print(f"[tg_scraper:{channel}] {o['link']} | {o['published']} | {o['title'][:70]!r}")
    return out
