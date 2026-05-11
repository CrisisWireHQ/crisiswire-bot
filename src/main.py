import os
import json
from dotenv import load_dotenv

load_dotenv()

from . import state, poller, classifier, drafter, telegram_io, x_poster

DRAFTS_PER_RUN = int(os.environ.get("DRAFTS_PER_RUN", "3"))
MODE = os.environ.get("MODE", "")


def process_approvals() -> tuple[int, int]:
    """Legacy polling path (getUpdates). Used only when webhook isn't set."""
    try:
        wh = telegram_io.get_webhook_info()
        if wh.get("url"):
            # Webhook is the primary path; skip getUpdates entirely.
            return (0, 0)
    except Exception as e:
        print(f"[approvals] webhook check failed: {e}")

    offset = state.load_tg_offset()
    try:
        updates = telegram_io.get_updates(offset)
    except Exception as e:
        print(f"[approvals] getUpdates failed: {e}")
        return (0, 0)
    if not updates:
        return (0, 0)

    posted, rejected = 0, 0
    for upd in updates:
        new_offset = upd["update_id"] + 1
        cb = upd.get("callback_query")
        if not cb:
            state.save_tg_offset(new_offset)
            continue

        action = cb.get("data", "")
        msg = cb.get("message") or {}
        msg_text = msg.get("text", "")
        chat_id = (msg.get("chat") or {}).get("id")
        message_id = msg.get("message_id")
        callback_id = cb.get("id")

        if action == "ok":
            posted += _do_post_from_msg(msg_text, chat_id, message_id, callback_id)
        elif action == "no":
            telegram_io.answer_callback(callback_id, "Rejected.")
            telegram_io.edit_message(chat_id, message_id, f"❌ REJECTED\n\n{msg_text}")
            rejected += 1

        state.save_tg_offset(new_offset)

    return (posted, rejected)


def _do_post_from_msg(msg_text: str, chat_id, message_id, callback_id=None) -> int:
    """Extract draft from message text, post to X, edit Telegram message. Returns 1 on success."""
    draft_text = telegram_io.extract_draft_from_message(msg_text)
    if not draft_text:
        if callback_id:
            telegram_io.answer_callback(callback_id, "Could not parse draft.")
        telegram_io.edit_message(chat_id, message_id, f"⚠️ PARSE FAILED\n\n{msg_text}")
        return 0
    try:
        result = x_poster.post(draft_text)
        tweet_url = f"https://x.com/CrisisWireHQ/status/{result['id']}"
        if callback_id:
            telegram_io.answer_callback(callback_id, "Posted ✓")
        telegram_io.edit_message(chat_id, message_id, f"✅ POSTED\n\n{draft_text}\n\n{tweet_url}")
        return 1
    except Exception as e:
        print(f"[post] X post failed: {e}")
        if callback_id:
            telegram_io.answer_callback(callback_id, f"X error: {str(e)[:150]}")
        telegram_io.edit_message(chat_id, message_id, f"❌ POST FAILED: {e}\n\n{msg_text}")
        return 0


def process_webhook_approval() -> int:
    """Read GitHub event payload, post the approved draft to X."""
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path or not os.path.exists(event_path):
        print("[webhook] no GITHUB_EVENT_PATH; cannot process webhook approval")
        return 0
    try:
        with open(event_path, "r", encoding="utf-8") as f:
            event = json.load(f)
    except Exception as e:
        print(f"[webhook] failed to read event payload: {e}")
        return 0

    payload = (event.get("client_payload") or {})
    msg_text = payload.get("msg_text", "")
    chat_id = payload.get("chat_id")
    message_id = payload.get("message_id")

    if not msg_text or chat_id is None or message_id is None:
        print(f"[webhook] incomplete payload: chat={chat_id} msg_id={message_id} text_len={len(msg_text)}")
        return 0

    posted = _do_post_from_msg(msg_text, chat_id, message_id)
    print(f"[webhook] posted={posted}")
    return posted


def poll_and_draft() -> int:
    items = poller.fetch_all()
    print(f"[poll] {len(items)} items fetched")
    seen = state.load_seen()
    drafted = 0

    for item in items:
        if drafted >= DRAFTS_PER_RUN:
            break
        if state.is_seen(seen, item["link"]):
            continue
        state.mark_seen(seen, item["link"])

        try:
            cls = classifier.classify(item)
        except Exception as e:
            print(f"[poll] classify error: {e}")
            continue

        if not cls.get("relevant"):
            continue

        if cls.get("severity") == "minor" and item.get("tier", 3) > 1:
            continue

        try:
            text = drafter.draft(item)
        except Exception as e:
            print(f"[poll] draft error: {e}")
            continue

        if not text or len(text) > 280:
            print(f"[poll] bad draft len={len(text) if text else 0}: {text[:80]!r}")
            continue

        try:
            telegram_io.send_draft(text, item, cls)
            drafted += 1
            print(f"[poll] DRAFTED: {text[:80]}")
        except Exception as e:
            print(f"[poll] telegram send error: {e}")

    state.save_seen(seen)
    return drafted


def main():
    print(f"[main] === Crisis Wire run start (mode={MODE or 'full'}) ===")

    if MODE == "webhook-approve":
        # Fast path: triggered by Cloudflare Worker after user tapped Approve.
        process_webhook_approval()
        print("[main] === run end (webhook) ===")
        return

    # Fallback / legacy: try getUpdates polling (only works if no webhook set).
    posted, rejected = process_approvals()
    print(f"[main] approvals: posted={posted} rejected={rejected}")

    if MODE == "approvals-only":
        print("[main] skipping poll (approvals-only mode)")
    else:
        drafted = poll_and_draft()
        print(f"[main] new drafts sent: {drafted}")

    print("[main] === run end ===")


if __name__ == "__main__":
    main()
