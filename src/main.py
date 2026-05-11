import os
from dotenv import load_dotenv

load_dotenv()

from . import state, poller, classifier, drafter, telegram_io, x_poster

DRAFTS_PER_RUN = int(os.environ.get("DRAFTS_PER_RUN", "3"))


def process_approvals() -> tuple[int, int]:
    """Process pending Telegram button presses. Returns (posted, rejected)."""
    offset = state.load_tg_offset()
    try:
        updates = telegram_io.get_updates(offset)
    except Exception as e:
        print(f"[approvals] getUpdates failed: {e}")
        return (0, 0)

    posted = 0
    rejected = 0
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
            draft_text = telegram_io.extract_draft_from_message(msg_text)
            if not draft_text:
                telegram_io.answer_callback(callback_id, "Could not parse draft.")
            else:
                try:
                    result = x_poster.post(draft_text)
                    tweet_url = f"https://x.com/CrisisWireHQ/status/{result['id']}"
                    telegram_io.answer_callback(callback_id, "Posted ✓")
                    telegram_io.edit_message(
                        chat_id, message_id,
                        f"✅ POSTED\n\n{draft_text}\n\n{tweet_url}"
                    )
                    posted += 1
                except Exception as e:
                    print(f"[approvals] X post failed: {e}")
                    telegram_io.answer_callback(callback_id, f"X error: {str(e)[:150]}")
                    telegram_io.edit_message(
                        chat_id, message_id,
                        f"❌ POST FAILED: {e}\n\n{msg_text}"
                    )
        elif action == "no":
            telegram_io.answer_callback(callback_id, "Rejected.")
            telegram_io.edit_message(chat_id, message_id, f"❌ REJECTED\n\n{msg_text}")
            rejected += 1

        state.save_tg_offset(new_offset)

    return (posted, rejected)


def poll_and_draft() -> int:
    items = poller.fetch_all()
    print(f"[poll] {len(items)} items fetched")
    seen = state.load_seen()
    drafted = 0

    items.sort(key=lambda x: x.get("tier", 9))

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

        if not text or len(text) > 270:
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
    print("[main] === Crisis Wire run start ===")
    posted, rejected = process_approvals()
    print(f"[main] approvals: posted={posted} rejected={rejected}")
    drafted = poll_and_draft()
    print(f"[main] new drafts sent: {drafted}")
    print("[main] === run end ===")


if __name__ == "__main__":
    main()
