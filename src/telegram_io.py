import os
import json
import requests

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
API = f"https://api.telegram.org/bot{TOKEN}"

DRAFT_SEP = "━━━━━━━━━━━━━━"


def send_draft(draft_text: str, item: dict, classification: dict) -> dict:
    body = (
        f"📝 CRISIS WIRE DRAFT\n"
        f"{DRAFT_SEP}\n"
        f"{draft_text}\n"
        f"{DRAFT_SEP}\n"
        f"🏷  {classification.get('category','?')} · {classification.get('severity','?')}\n"
        f"📡 {item['source_name']}\n"
        f"🔗 {item['link']}"
    )
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Approve & Post", "callback_data": "ok"},
            {"text": "❌ Reject", "callback_data": "no"},
        ]]
    }
    r = requests.post(
        f"{API}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": body,
            "reply_markup": keyboard,
            "disable_web_page_preview": False,
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


def edit_message(chat_id: int, message_id: int, new_text: str):
    try:
        requests.post(
            f"{API}/editMessageText",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": new_text[:4000],
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
    except Exception as e:
        print(f"[telegram] edit_message error: {e}")


def extract_draft_from_message(message_text: str) -> str | None:
    parts = message_text.split(DRAFT_SEP)
    if len(parts) >= 3:
        return parts[1].strip()
    return None


def send_text(text: str):
    try:
        requests.post(
            f"{API}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text[:4000], "disable_web_page_preview": True},
            timeout=15,
        )
    except Exception as e:
        print(f"[telegram] send_text error: {e}")
