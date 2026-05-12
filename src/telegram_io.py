import os
import json
import re
import requests

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
API = f"https://api.telegram.org/bot{TOKEN}"

DRAFT_SEP = "━━━━━━━━━━━━━━"
IMG_LINE_PREFIX = "🖼 "
QT_LINE_PREFIX = "💬 Quote-tweeting: "
_IMG_LINE_RE = re.compile(r"^🖼 (https?://\S+)", re.MULTILINE)
_QT_LINE_RE = re.compile(r"^💬 Quote-tweeting: (https?://\S+)", re.MULTILINE)
_TWEET_ID_RE = re.compile(r"/status/(\d+)")


def _build_body(draft_text: str, item: dict, classification: dict) -> tuple[str, str]:
    """Returns (body, image_url). Body always includes 🖼 URL line when image present."""
    char_count = len(draft_text)
    char_bar = "🟢" if char_count <= 240 else ("🟡" if char_count <= 270 else "🔴")
    severity_icon = {"critical": "🔴", "major": "🟠", "minor": "🟡"}.get(classification.get("severity", ""), "⚪")
    is_breaking = classification.get("is_breaking", False)
    is_hantavirus = classification.get("is_hantavirus", False)
    confirming = classification.get("confirming_sources", [])
    image_url = (item.get("image_url") or "").strip()
    quote_url = (item.get("quote_tweet_url") or "").strip()

    if is_hantavirus:
        header = "🦠🦠🦠 HANTAVIRUS ALERT 🦠🦠🦠"
    elif is_breaking:
        header = "🚨🚨🚨 BREAKING — CROSS-CONFIRMED 🚨🚨🚨"
    else:
        header = "📝 CRISIS WIRE DRAFT"
    breaking_line = (
        f"⚡ Confirmed by {len(confirming)} sources: {', '.join(confirming)}\n"
        if is_breaking
        else ""
    )
    body = (
        f"{header}\n"
        f"{DRAFT_SEP}\n"
        f"{draft_text}\n"
        f"{DRAFT_SEP}\n"
        f"{breaking_line}"
        f"{char_bar} {char_count}/280  •  {severity_icon} {classification.get('severity','?')}  •  🏷  {classification.get('category','?')}\n"
        f"📡 {item['source_name']}\n"
        f"🔗 {item['link']}"
    )
    if image_url:
        body += f"\n{IMG_LINE_PREFIX}{image_url}"
    if quote_url:
        body += f"\n{QT_LINE_PREFIX}{quote_url}"
    return body, image_url


def extract_quote_tweet_id_from_message(message_text: str) -> str:
    m = _QT_LINE_RE.search(message_text or "")
    if not m:
        return ""
    url = m.group(1)
    tid = _TWEET_ID_RE.search(url)
    return tid.group(1) if tid else ""


def send_draft(draft_text: str, item: dict, classification: dict) -> dict:
    body, image_url = _build_body(draft_text, item, classification)
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Approve & Post", "callback_data": "ok"},
            {"text": "❌ Reject", "callback_data": "no"},
        ]]
    }
    # Telegram caption limit is 1024 chars; bail to text if we'd overflow.
    if image_url and len(body) <= 1024:
        try:
            r = requests.post(
                f"{API}/sendPhoto",
                json={
                    "chat_id": CHAT_ID,
                    "photo": image_url,
                    "caption": body,
                    "reply_markup": keyboard,
                },
                timeout=30,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"[telegram] sendPhoto failed ({e}); falling back to text")
    # Text-only fallback
    r = requests.post(
        f"{API}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": body,
            "reply_markup": keyboard,
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def get_updates(offset: int) -> list[dict]:
    r = requests.get(
        f"{API}/getUpdates",
        params={
            "offset": offset,
            "timeout": 0,
            "allowed_updates": json.dumps(["callback_query"]),
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("result", [])


def get_webhook_info() -> dict:
    r = requests.get(f"{API}/getWebhookInfo", timeout=15)
    r.raise_for_status()
    return r.json().get("result", {})


def delete_webhook():
    r = requests.post(f"{API}/deleteWebhook", json={"drop_pending_updates": False}, timeout=15)
    r.raise_for_status()


def answer_callback(callback_id: str, text: str = ""):
    try:
        requests.post(
            f"{API}/answerCallbackQuery",
            json={"callback_query_id": callback_id, "text": text[:200]},
            timeout=15,
        )
    except Exception as e:
        print(f"[telegram] answer_callback error: {e}")


def edit_message(chat_id, message_id, new_text: str, is_photo: bool = False):
    """Edit either text or caption depending on the original message type."""
    endpoint = "editMessageCaption" if is_photo else "editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
    }
    if is_photo:
        payload["caption"] = new_text[:1024]
    else:
        payload["text"] = new_text[:4000]
        payload["disable_web_page_preview"] = True
    try:
        requests.post(f"{API}/{endpoint}", json=payload, timeout=15)
    except Exception as e:
        print(f"[telegram] edit error: {e}")


def extract_draft_from_message(message_text: str) -> str | None:
    parts = message_text.split(DRAFT_SEP)
    if len(parts) >= 3:
        return parts[1].strip()
    return None


def extract_image_url_from_message(message_text: str) -> str:
    m = _IMG_LINE_RE.search(message_text or "")
    return m.group(1).strip() if m else ""


def send_text(text: str):
    try:
        requests.post(
            f"{API}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text[:4000], "disable_web_page_preview": True},
            timeout=15,
        )
    except Exception as e:
        print(f"[telegram] send_text error: {e}")
