import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
PREVIEW = "https://t.me/s/{channel}"


def fetch_channel(channel: str, max_messages: int = 15) -> list[dict]:
    url = PREVIEW.format(channel=channel)
    r = requests.get(url, headers={"User-Agent": UA}, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    out = []
    blocks = soup.select("div.tgme_widget_message_wrap")
    for block in reversed(blocks[-max_messages:]):
        text_el = block.select_one("div.tgme_widget_message_text")
        if not text_el:
            continue
        text = text_el.get_text(separator=" ", strip=True)
        if len(text) < 15:
            continue

        date_a = block.select_one("a.tgme_widget_message_date")
        link = date_a.get("href", "").strip() if date_a else ""
        time_el = block.select_one("time")
        published = time_el.get("datetime", "") if time_el else ""

        # First sentence-ish as title; full text as summary.
        title = text.split("\n")[0][:200]
        out.append({
            "title": title,
            "summary": text[:1500],
            "link": link,
            "published": published,
        })
    return out
