import os
import re
import json
from anthropic import Anthropic

# Cheap pre-filter: kill obvious non-breaking items by headline alone, so we
# never spend a Haiku call on them. Patterns mirror the SYSTEM prompt's hard
# rejections.
_REJECT_PATTERNS = re.compile(
    r"\b("
    r"what we know|what to know|everything (you|to) know|here'?s why|here'?s what|"
    r"explained|explainer|deep dive|deep-dive|"
    r"a year later|years later|years on|months later|anniversary|look back|looking back|"
    r"the human cost|voices from|what it'?s like|inside the|civilians describe|"
    r"how we got here|timeline|history of|background on|"
    r"opinion|op-ed|analysis|commentary|column|"
    r"profile|interview with|sits down with|"
    r"experts warn|fears (of|that)|concerns (over|that|grow)|tensions rise|"
    r"may happen|could happen|might happen|if confirmed|"
    r"what happens next|what comes next|"
    r"recap|roundup|round-up|weekly|in pictures|in photos"
    r")\b",
    re.IGNORECASE,
)


def cheap_prefilter_reject(item: dict) -> bool:
    """Return True if the headline obviously isn't breaking news.
    Saves a Haiku call. Conservative — only matches strong signals."""
    title = (item.get("title") or "").strip()
    if not title:
        return True
    if _REJECT_PATTERNS.search(title):
        return True
    return False

_client = None


def client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"],
            max_retries=4,   # default 2; Anthropic 529 overloads often need more
            timeout=30,
        )
    return _client


SYSTEM = """You classify news items for @CrisisWireHQ, a breaking-news X account covering:
- Armed conflict, military escalation, terror attacks
- Mass shootings, hostage incidents, major attacks on civilians
- Major natural disasters (M6+ quakes, major hurricanes, deadly wildfires, volcanic eruptions, tsunamis)
- Disease outbreaks of regional/global concern
- Aviation / maritime / rail disasters with casualties or mass impact
- Mass civil unrest, coups, major political upheaval
- Major geopolitical flashpoints with crisis potential

EXCLUDE (mark as not relevant):
- Routine politics, opinion, analysis pieces, op-eds
- Celebrity, sports, entertainment, business/markets
- Scheduled events, anniversaries, retrospectives, "look back" content
- Minor local crime, weather forecasts (only ACTIVE extreme events qualify)
- Feature / human-interest writing: "civilians describe", "what it's like", "inside the conflict", "a year later", "voices from", "the human cost"
- Explainer / context pieces: "what we know so far", "what is X", "everything you need to know", "explained"
- Profiles, interviews, reaction pieces, reactions to reactions
- Vague aggregations: "growing concerns", "tensions rise", "experts warn" without a specific event
- Single-source claims about extraordinary events (deaths of major figures, nuclear/CBRN, declarations of war) — set relevant=false UNLESS the source is the official agency itself (e.g. WHO confirming an outbreak, USGS confirming a quake)

A news item must report a SPECIFIC EVENT that JUST HAPPENED (within the last few hours). If you're not sure what concrete thing occurred, mark relevant=false.

ADDITIONAL HARD REJECTION RULES:
- If the item is about something that happened MORE than 24 hours ago (even if the article is fresh), mark relevant=false. Example: an article today recapping a battle from last week → REJECT.
- If the item is "context" / "background" / "history of" / "timeline" / "how we got here" → REJECT.
- If the item only says "X may happen" or "X is feared" or "X could occur" with no actual event → REJECT.
- If the item is a press conference, statement, or interview ABOUT an event (not the event itself) → only relevant if the statement contains hard NEW facts (death tolls, official confirmations, new actions). Pure reactions, opinions, or "concerns" → REJECT.
- If the headline contains "what we know", "explained", "everything to know", "what happens next", "here's why", "deep dive" → REJECT.
- If the item is from an official agency confirming a SPECIFIC NEW EVENT (USGS quake, WHO outbreak, GDACS alert, NWS extreme alert) → automatically relevant=true, severity at least major.

Bias toward false negatives. Better to miss a borderline story than to flood with non-breaking content.

Respond ONLY with raw JSON (no markdown fences, no prose):
{"relevant": <bool>, "severity": "critical"|"major"|"minor", "category": "conflict"|"disaster"|"outbreak"|"unrest"|"attack"|"other", "event_key": "<slug>", "reason": "<short>"}

event_key: a STABLE NORMALIZED lowercase slug identifying the SPECIFIC event. Two news items reporting the SAME real-world event MUST produce the IDENTICAL event_key.

NORMALIZATION RULES (follow strictly):
- Format: country--event-type--key-location-or-detail (3 segments, separated by double-hyphens)
- Use the BASE country only (not "south lebanon" — use "lebanon"; not "western ukraine" — use "ukraine")
- Use a CANONICAL event type from this list: strike, quake, fire, attack, shooting, explosion, crash, outbreak, coup, protest, hostage, drone-strike, missile-strike, airstrike, evacuation
- DO NOT include casualty counts (they change as the story develops). Wrong: "lebanon--strike--6-killed". Right: "lebanon--airstrike--south"
- DO NOT include date or time
- DO NOT include source-specific wording or framing
- DO NOT use synonyms — if it's an airstrike, ALWAYS write "airstrike" (not "air-attack", "bombing", "strike-from-air")

GOOD EXAMPLES:
- "iran--drone-shot-down--strait-of-hormuz"
- "japan--quake--ibaraki"
- "argentina--hantavirus--ushuaia"
- "lebanon--airstrike--south"
- "ukraine--missile-strike--kharkiv"
- "usa--mass-shooting--utah"

BAD EXAMPLES (do not produce these):
- "lebanon--six-killed-airstrike" (casualty count, wrong order)
- "south-lebanon--israeli-strike" (sub-region, source perspective)
- "lebanon--bombs-fall--3-dead" (synonym, casualty)

Severity guide:
- critical: mass casualties, major escalation, novel outbreak, nuclear/CBRN, large-scale attack
- major: confirmed significant event, regional disaster, ongoing crisis update
- minor: developing story, small-scale incident, single-region update"""


def _default_cls(reason: str = "") -> dict:
    return {"relevant": False, "severity": "minor", "category": "other", "event_key": "", "reason": reason}


def _normalize_cls(d: dict) -> dict:
    d.setdefault("relevant", False)
    d.setdefault("severity", "minor")
    d.setdefault("category", "other")
    d.setdefault("event_key", "")
    d.setdefault("reason", "")
    return d


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return text


def classify(item: dict) -> dict:
    """Single-item classify. Kept for callers that need a one-off; the main
    poller uses classify_batch which is ~6-8x cheaper per item."""
    results = classify_batch([item])
    return results[0] if results else _default_cls("empty_batch")


BATCH_SIZE = int(os.environ.get("CLASSIFIER_BATCH_SIZE", "10"))


def classify_batch(items: list[dict]) -> list[dict]:
    """Classify multiple items in a single Haiku call.

    Amortizes the ~1900-token SYSTEM prompt across many items, which was the
    dominant cost driver (Haiku 4.5 cache minimum is 2048 tokens — our SYSTEM
    sits just under, so per-call caching never kicked in).

    Returns results aligned 1:1 with `items`. On parse failure for a batch,
    the items in that batch fall back to not-relevant (caller will skip them
    and they'll be retried next run if still unseen)."""
    if not items:
        return []

    out: list[dict] = []
    for start in range(0, len(items), BATCH_SIZE):
        chunk = items[start:start + BATCH_SIZE]
        out.extend(_classify_chunk(chunk))
    return out


def _classify_chunk(chunk: list[dict]) -> list[dict]:
    blocks = []
    for i, it in enumerate(chunk, 1):
        blocks.append(
            f"[{i}] Source: {it['source_name']} (tier {it['tier']})\n"
            f"Title: {it['title']}\n"
            f"Summary: {(it.get('summary') or '')[:400]}"
        )
    user = (
        f"Classify the following {len(chunk)} news items. "
        f"Return ONLY a raw JSON array of exactly {len(chunk)} objects in the SAME ORDER as the input. "
        f"Each object has the schema specified in the system prompt. "
        f"Do not wrap the array in markdown fences or prose.\n\n"
        + "\n\n".join(blocks)
    )
    try:
        msg = client().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120 * len(chunk),
            system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
        )
    except Exception as e:
        # Caller decides retry; surface a parse_error-style fallback so
        # caller doesn't crash but also won't mark these items seen.
        raise

    text = _strip_fences(msg.content[0].text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Try to salvage: sometimes the model emits NDJSON / one object per line.
        parsed = []
        for line in text.splitlines():
            line = line.strip().rstrip(",")
            if not line or line in ("[", "]"):
                continue
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if not parsed:
            print(f"[classifier] batch JSON parse failed; text head={text[:200]!r}")
            return [_default_cls("parse_error") for _ in chunk]

    if not isinstance(parsed, list):
        return [_default_cls("not_a_list") for _ in chunk]

    # Align length: pad / truncate so output matches input cardinality.
    if len(parsed) < len(chunk):
        parsed = parsed + [_default_cls("missing_in_batch") for _ in range(len(chunk) - len(parsed))]
    elif len(parsed) > len(chunk):
        parsed = parsed[:len(chunk)]

    return [_normalize_cls(p if isinstance(p, dict) else _default_cls("not_a_dict")) for p in parsed]
