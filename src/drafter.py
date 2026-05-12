import os
from anthropic import Anthropic

_client = None


def client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


SYSTEM = """You write breaking-news posts for @CrisisWireHQ.

Style: dry, factual, location-prefixed. Mirror @spectatorindex / @disclosetv / @sentdefender / @BNONews.
NO opinion, NO speculation, NO hashtags, NO "follow for more", NO calls to action, NO emojis except the opening flag/topic emoji.

FORMAT:
- Start with ONE emoji: flag (🇺🇦 🇮🇱 🇺🇸 🇨🇳 etc.) if country-specific, else topic emoji (🌋 quake/volcano · 🦠 outbreak · ⚠️ general · 🚨 mass casualty · 🛩 aviation)
- Then: COUNTRY/REGION (uppercase) — factual statement
- Maximum 270 characters total
- Attribute uncertain claims: "per [source]", "according to [agency]", "[outlet] reports"
- Never fabricate numbers, names, or details not in the source
- If the source itself is uncertain, hedge appropriately ("reportedly", "unconfirmed reports")

OUTPUT: Only the post text. No quotes around it, no preamble, no commentary."""


def draft(item: dict, is_breaking: bool = False) -> str:
    breaking_note = (
        "\n\nNOTE: This event has been cross-confirmed by 2+ independent sources within a 10-minute window — it is BREAKING. Lead with 🚨 (instead of a flag emoji) and convey urgency through tighter, more declarative phrasing. Still no hashtags, opinion, or speculation."
        if is_breaking
        else ""
    )
    user = (
        f"Source: {item['source_name']}\n"
        f"Title: {item['title']}\n"
        f"Summary: {item['summary'][:1500]}"
        f"{breaking_note}"
    )
    msg = client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    text = msg.content[0].text.strip()
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1].strip()
    return text
