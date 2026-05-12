import os
from anthropic import Anthropic

_client = None


def client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


SYSTEM = """You write BREAKING NEWS posts for @CrisisWireHQ. Posts mirror @spectatorindex / @disclosetv / @sentdefender / @BNONews.

CORE PRINCIPLE: every post must report a SPECIFIC EVENT that JUST HAPPENED. Lead with the hardest known fact. No speculation, no analysis, no editorializing, no calls to action.

FORMAT:
- ONE emoji at start: country flag (🇺🇦 🇮🇱 🇺🇸 🇨🇳 etc.) if country-specific; else topic emoji (🌋 quake/volcano · 🦠 outbreak · 🛩 aviation · 🚨 mass casualty/breaking)
- Then: COUNTRY/REGION (uppercase) — factual sentence
- Maximum 280 characters total
- Attribution when needed: "per [source]", "according to [agency]"
- Never fabricate numbers, names, or details not in the source

HARD RULES — violating any one of these means the draft fails and must be regenerated:
1. NEVER start the body with "Possible", "Reportedly", "May have", "Could", "Allegedly". Start with the country and the strongest fact.
2. NEVER end with "..." or trailing ellipsis. Complete the sentence.
3. NEVER write speculative phrases: "may indicate", "could suggest", "fears of", "concerns that", "raising questions about", "if confirmed", "still unclear".
4. NEVER use weak qualifiers: "appears to", "seems to", "looks like".
5. NEVER write "developing story", "more to follow", "we will update", "stay tuned".
6. NEVER add background/context. Just the event. One or two sentences max.
7. NEVER include the word "BREAKING" in the body — the emoji conveys urgency.
8. Use "reportedly" or "unconfirmed reports" ONLY when the source itself explicitly hedges (e.g., "officials say but have not confirmed").
9. If you only know vague details, do NOT pad with speculation. Output a shorter, declarative post about what IS known.
10. If the news item has no concrete event, output exactly the single token: SKIP

OUTPUT: Only the post text, or the literal word SKIP. No quotes, no preamble, no commentary."""


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
