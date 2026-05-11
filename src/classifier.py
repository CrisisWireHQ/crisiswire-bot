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

EXCLUDE:
- Routine politics, opinion, analysis pieces
- Celebrity, sports, entertainment, business/markets
- Scheduled events, anniversaries, retrospectives
- Minor local crime, weather forecasts (only ACTIVE extreme events qualify)
- Editorial / op-ed / "explainer" content

Respond ONLY with raw JSON (no markdown fences, no prose):
{"relevant": <bool>, "severity": "critical"|"major"|"minor", "category": "conflict"|"disaster"|"outbreak"|"unrest"|"attack"|"other", "reason": "<short>"}

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
        result.setdefault("reason", "")
        return result
    except json.JSONDecodeError:
        return {"relevant": False, "severity": "minor", "category": "other", "reason": "parse_error"}
