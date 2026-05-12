import os
import json
from anthropic import Anthropic

_client = None


def client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
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

A news item must report a SPECIFIC EVENT that just happened. If you're not sure what concrete thing occurred, it's not breaking news.

Respond ONLY with raw JSON (no markdown fences, no prose):
{"relevant": <bool>, "severity": "critical"|"major"|"minor", "category": "conflict"|"disaster"|"outbreak"|"unrest"|"attack"|"other", "event_key": "<slug>", "reason": "<short>"}

event_key: a stable lowercase slug identifying the SPECIFIC event, suitable for matching the same event across different news sources. Format: country-or-region--what-happened--key-detail. Examples:
- "iran--us-drone-shot-down--strait-of-hormuz"
- "japan--m6.3-quake--ibaraki"
- "argentina--hantavirus-cluster--ushuaia"
- "lebanon--israeli-strikes--south"
- "russia--ukraine-drone-strike--belgorod"
Keep it 3-6 hyphenated segments. Use the event itself, NOT the publication date. Two news items describing the same real-world event MUST produce the same event_key.

Severity guide:
- critical: mass casualties, major escalation, novel outbreak, nuclear/CBRN, large-scale attack
- major: confirmed significant event, regional disaster, ongoing crisis update
- minor: developing story, small-scale incident, single-region update"""


def classify(item: dict) -> dict:
    user = (
        f"Source: {item['source_name']} (tier {item['tier']})\n"
        f"Title: {item['title']}\n"
        f"Summary: {item['summary'][:1000]}"
    )
    msg = client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    text = msg.content[0].text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        result = json.loads(text)
        result.setdefault("relevant", False)
        result.setdefault("severity", "minor")
        result.setdefault("category", "other")
        result.setdefault("event_key", "")
        result.setdefault("reason", "")
        return result
    except json.JSONDecodeError:
        return {"relevant": False, "severity": "minor", "category": "other", "event_key": "", "reason": "parse_error"}
