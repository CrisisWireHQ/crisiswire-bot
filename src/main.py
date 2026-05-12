import os
import re
import json
from dotenv import load_dotenv

load_dotenv()

from . import state, poller, classifier, drafter, telegram_io, x_poster, quote_finder, article_fetcher
from .sources import SOURCES

DRAFTS_PER_RUN = int(os.environ.get("DRAFTS_PER_RUN", "3"))
# MODE: "approvals-only" (fast loop) skips polling.
#       "trusted-only" polls ONLY trusted sources (Faytuks etc.) and skips Claude classifier.
#       Anything else does a full run.
MODE = os.environ.get("MODE", "")
TRUSTED_SOURCE_NAMES = {s["name"] for s in SOURCES if s.get("trusted")}


def _trusted_event_key(title: str) -> str:
    """Cheap event_key for trusted-source items (no Claude call)."""
    s = re.sub(r"[^a-z0-9\s]+", "", (title or "").lower())
    words = [w for w in s.split() if len(w) > 2][:5]
    return f"trusted-{'-'.join(words)}"[:60] if words else ""


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
    """Extract draft, post to X (image / quote-tweet if present), auto-reply with source, edit Telegram."""
    draft_text = telegram_io.extract_draft_from_message(msg_text)
    image_url = telegram_io.extract_image_url_from_message(msg_text)
    # Quote-tweeting disabled (X API forbids it for accounts not in the conversation).
    # Any legacy 💬 lines in older Telegram drafts are ignored.
    quote_tweet_id = ""
    source_url = telegram_io.extract_source_url_from_message(msg_text)
    if not draft_text:
        if callback_id:
            telegram_io.answer_callback(callback_id, "Could not parse draft.")
        telegram_io.edit_message(chat_id, message_id, f"⚠️ PARSE FAILED\n\n{msg_text}", is_photo=is_photo)
        return 0
    try:
        result = x_poster.post(draft_text, image_url=image_url, quote_tweet_id=quote_tweet_id)
        tweet_url = f"https://x.com/CrisisWireHQ/status/{result['id']}"

        # Auto-reply with source link. Failure here doesn't fail the parent post.
        reply_status = ""
        if source_url:
            try:
                reply_text = f"Source: {source_url}"
                # Truncate if needed to stay under 280
                if len(reply_text) > 280:
                    reply_text = source_url
                x_poster.reply(reply_text, in_reply_to_tweet_id=result["id"])
                reply_status = "📎 source replied"
            except Exception as e:
                print(f"[post] auto-reply failed: {e}")
                reply_status = "⚠️ reply failed"

        tags = []
        if result.get("had_image"): tags.append("🖼 image")
        if result.get("had_quote"): tags.append("💬 quote")
        if reply_status: tags.append(reply_status)
        if not tags: tags.append("📝 text only")
        media_tag = " + ".join(tags)
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
    if MODE == "trusted-only":
        items = [i for i in items if i["source_name"] in TRUSTED_SOURCE_NAMES]
        print(f"[poll] trusted-only filter → {len(items)} items")
    elif MODE == "force-trusted":
        # One-shot debug mode: unsee all trusted items so we re-draft anything
        # that got marked seen without a successful draft.
        items = [i for i in items if i["source_name"] in TRUSTED_SOURCE_NAMES]
        seen = state.load_seen()
        for i in items:
            seen.pop(state.url_hash(i["link"]), None)
        state.save_seen(seen)
        print(f"[poll] force-trusted: cleared seen-state for {len(items)} trusted items")
    else:
        # Regular runs (10-min cron, manual) skip trusted sources — those are
        # exclusively handled by the dedicated 1-min trusted-only path, otherwise
        # they'd get marked seen here and never reach the fast path.
        before = len(items)
        items = [i for i in items if i["source_name"] not in TRUSTED_SOURCE_NAMES]
        if before != len(items):
            print(f"[poll] excluded {before - len(items)} trusted items (handled by trusted-only path)")
    seen = state.load_seen()
    sigs = state.load_event_signatures()
    drafted_keys = state.load_drafted_keys()
    drafted = 0

    for item in items:
        is_trusted_src = item["source_name"] in TRUSTED_SOURCE_NAMES
        if drafted >= DRAFTS_PER_RUN:
            if is_trusted_src:
                print(f"[trusted-debug] HIT DRAFTS_PER_RUN cap; skipping {item['title'][:80]!r}")
            break
        if state.is_seen(seen, item["link"]):
            if is_trusted_src:
                print(f"[trusted-debug] already in seen.json: {item['title'][:80]!r} ({item['link']})")
            continue
        if is_trusted_src:
            print(f"[trusted-debug] NEW item, processing: {item['title'][:80]!r}")
        state.mark_seen(seen, item["link"])
        is_trusted = is_trusted_src

        # Hantavirus is a special interest — detect via keyword regex and elevate aggressively.
        full_text = f"{item.get('title','')} {item.get('summary','')}"
        is_hantavirus = quote_finder.text_mentions_hantavirus(full_text)

        if is_trusted:
            # Skip the Claude classifier entirely — Faytuks-tier sources are
            # pre-verified. Generate a cheap event_key for dedup.
            cls = {
                "relevant": True,
                "severity": "major",
                "category": item.get("category", "news"),
                "event_key": _trusted_event_key(item.get("title", "")),
                "is_trusted": True,
            }
            print(f"[trusted] bypassing classifier for {item['source_name']}")
        else:
            try:
                cls = classifier.classify(item)
            except Exception as e:
                print(f"[poll] classify error: {e}")
                continue

        cls["is_hantavirus"] = is_hantavirus

        if not cls.get("relevant") and not is_hantavirus and not is_trusted:
            continue

        if is_hantavirus:
            print(f"[hantavirus] match in {item['source_name']}: {item['title'][:80]!r}")
            # Quote-tweeting CDC/WHO disabled: X requires the quoting account
            # to be mentioned or part of the conversation thread, which we are not.
            # The HANTAVIRUS ALERT badge in Telegram still signals priority.

        # Cross-source breaking detection
        event_key = cls.get("event_key", "")
        is_breaking, source_count, source_list = state.check_breaking(sigs, event_key, item["source_name"])
        state.record_event_signature(sigs, event_key, item["source_name"])
        cls["is_breaking"] = is_breaking
        cls["confirming_sources"] = source_list

        if is_breaking:
            print(f"[breaking] {event_key!r} confirmed by {source_count} sources: {source_list}")

        # Skip if we already drafted this same event_key in the last 6h
        if state.is_drafted(drafted_keys, event_key):
            print(f"[dedup] event_key {event_key!r} already drafted in last 6h; skipping")
            continue

        # Trusted, hantavirus, and breaking all bypass the minor-tier filter
        if (cls.get("severity") == "minor"
                and item.get("tier", 3) > 1
                and not is_breaking
                and not is_hantavirus
                and not is_trusted):
            continue

        # Enrich item: resolve Google News redirect to real outlet URL + fetch full article body.
        # For TG sources we already have the full message text, so skip the network fetch.
        try:
            enriched = article_fetcher.fetch_article(item.get("link", ""))
            resolved = enriched.get("resolved_url") or item.get("link", "")
            if resolved and resolved != item.get("link"):
                print(f"[enrich] resolved URL → {resolved[:80]}")
                item["link"] = resolved
            body = enriched.get("text", "")
            if body and len(body) > len(item.get("summary", "")):
                item["summary"] = body[:4000]
                print(f"[enrich] {item['source_name']}: +{len(body)} chars from article body")
        except Exception as e:
            print(f"[enrich] fetch failed: {e}")

        try:
            text = drafter.draft(
                item,
                is_breaking=is_breaking or is_trusted,
                is_hantavirus=is_hantavirus,
                is_trusted=is_trusted,
            )
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
            state.mark_drafted(drafted_keys, event_key)
            tag = ""
            if is_trusted: tag += "🔥 TRUSTED "
            if is_hantavirus: tag += "🦠 HANTAVIRUS "
            if is_breaking: tag += "🚨 BREAKING "
            print(f"[poll] {tag}DRAFTED ({event_key}): {text[:80]}")
        except Exception as e:
            print(f"[poll] telegram send error: {e}")

    state.save_seen(seen)
    state.save_event_signatures(sigs)
    state.save_drafted_keys(drafted_keys)
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
