import re
import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
PREVIEW = "https://t.me/s/{channel}"
_BG_IMG_RE = re.compile(r"background-image\s*:\s*url\(['\"]?([^'\"\)]+)['\"]?\)")


def _extract_image(block) -> str:
    photo = block.select_one("a.tgme_widget_message_photo_wrap")
    if photo and photo.get("style"):
        m = _BG_IMG_RE.search(photo["style"])
        if m:
            return m.group(1).strip()
    # Video preview thumbnail
    video = block.select_one("a.tgme_widget_message_video_thumb")
    if video and video.get("style"):
        m = _BG_IMG_RE.search(video["style"])
        if m:
            return m.group(1).strip()
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
        text = text_el.get_text(separator=" ", strip=True)
        if len(text) < 15:
            continue

        date_a = block.select_one("a.tgme_widget_message_date")
        link = date_a.get("href", "").strip() if date_a else ""
        time_el = block.select_one("time")
        published = time_el.get("datetime", "") if time_el else ""
        image_url = _extract_image(block)

        title = text.split("\n")[0][:200]
        out.append({
            "title": title,
            "summary": text[:1500],
            "link": link,
            "published": published,
            "image_url": image_url,
        })
    if channel.lower() in ("faytuks_network", "outbreakupdates"):
        for o in out[:6]:
            print(f"[tg_scraper:{channel}] {o['link']} | {o['published']} | {o['title'][:70]!r}")
    return out
