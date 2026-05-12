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
        msg_text = msg.get("text") or msg.get("caption") or ""
        is_photo = bool(msg.get("photo"))
        chat_id = (msg.get("chat") or {}).get("id")
        message_id = msg.get("message_id")
        callback_id = cb.get("id")

        if action == "ok":
            posted += _do_post_from_msg(msg_text, chat_id, message_id, callback_id, is_photo=is_photo)
        elif action == "no":
            telegram_io.answer_callback(callback_id, "Rejected.")
            telegram_io.edit_message(chat_id, message_id, f"❌ REJECTED\n\n{msg_text}", is_photo=is_photo)
            rejected += 1

        state.save_tg_offset(new_offset)

    return (posted, rejected)


def _do_post_from_msg(msg_text: str, chat_id, message_id, callback_id=None, is_photo: bool = False) -> int:
    """Extract draft from message text, post to X (with image if present), edit Telegram message."""
    draft_text = telegram_io.extract_draft_from_message(msg_text)
    image_url = telegram_io.extract_image_url_from_message(msg_text)
    if not draft_text:
        if callback_id:
            telegram_io.answer_callback(callback_id, "Could not parse draft.")
        telegram_io.edit_message(chat_id, message_id, f"⚠️ PARSE FAILED\n\n{msg_text}", is_photo=is_photo)
        return 0
    try:
        result = x_poster.post(draft_text, image_url=image_url)
        tweet_url = f"https://x.com/CrisisWireHQ/status/{result['id']}"
        media_tag = "🖼 with image" if result.get("had_image") else "📝 text only"
        if callback_id:
            telegram_io.answer_callback(callback_id, "Posted ✓")
        telegram_io.edit_message(
            chat_id, message_id,
            f"✅ POSTED ({media_tag})\n\n{draft_text}\n\n{tweet_url}",
            is_photo=is_photo,
        )
        return 1
    except Exception as e:
        print(f"[post] X post failed: {e}")
        if callback_id:
            telegram_io.answer_callback(callback_id, f"X error: {str(e)[:150]}")
        telegram_io.edit_message(chat_id, message_id, f"❌ POST FAILED: {e}\n\n{msg_text}", is_photo=is_photo)
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
    is_photo = bool(payload.get("is_photo"))

    if not msg_text or chat_id is None or message_id is None:
        print(f"[webhook] incomplete payload: chat={chat_id} msg_id={message_id} text_len={len(msg_text)}")
        return 0

    posted = _do_post_from_msg(msg_text, chat_id, message_id, is_photo=is_photo)
    print(f"[webhook] posted={posted}")
    return posted


def poll_and_draft() -> int:
    items = poller.fetch_all()
    print(f"[poll] {len(items)} items fetched")
    seen = state.load_seen()
    sigs = state.load_event_signatures()
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

        # Cross-source breaking detection: record this signature, then check
        # whether 2+ distinct sources have reported the same event_key recently.
        event_key = cls.get("event_key", "")
        is_breaking, source_count, source_list = state.check_breaking(sigs, event_key, item["source_name"])
        state.record_event_signature(sigs, event_key, item["source_name"])
        cls["is_breaking"] = is_breaking
        cls["confirming_sources"] = source_list

        if is_breaking:
            print(f"[breaking] {event_key!r} confirmed by {source_count} sources: {source_list}")

        # Drop minor severity from non-tier-1 sources, UNLESS marked breaking
        if cls.get("severity") == "minor" and item.get("tier", 3) > 1 and not is_breaking:
            continue

        try:
            text = drafter.draft(item, is_breaking=is_breaking)
        except Exception as e:
            print(f"[poll] draft error: {e}")
            continue

        if not text or text.strip().upper() == "SKIP":
            print(f"[poll] drafter SKIPped: {item['title'][:80]!r}")
            continue
        if len(text) > 280:
            print(f"[poll] draft too long ({len(text)}): {text[:80]!r}")
            continue
        # Reject drafts that smell speculative or incomplete
        lowered = text.lower()
        bad_phrases = [
            "possible ", "may have ", "could be ", "could have ",
            "if confirmed", "still unclear", "developing story",
            "more to follow", "we will update", "stay tuned",
            "appears to ", "seems to ", "fears of ", "concerns that ",
            "raising questions", "may indicate", "could suggest",
        ]
        bad_starts = ("possible", "reportedly", "may ", "could ", "allegedly")
        body = text.split("—", 1)[-1].strip().lower() if "—" in text else text.lower()
        if text.rstrip().endswith("..."):
            print(f"[poll] rejected (trailing ellipsis): {text[:80]!r}")
            continue
        if any(body.lstrip().startswith(b) for b in bad_starts):
            print(f"[poll] rejected (speculative start): {text[:80]!r}")
            continue
        if any(p in lowered for p in bad_phrases):
            matched = next(p for p in bad_phrases if p in lowered)
            print(f"[poll] rejected (banned phrase {matched!r}): {text[:80]!r}")
            continue

        try:
            telegram_io.send_draft(text, item, cls)
            drafted += 1
            tag = "🚨 BREAKING " if is_breaking else ""
            print(f"[poll] {tag}DRAFTED: {text[:80]}")
        except Exception as e:
            print(f"[poll] telegram send error: {e}")

    state.save_seen(seen)
    state.save_event_signatures(sigs)
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
