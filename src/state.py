import json
import hashlib
import time
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
SEEN_FILE = STATE_DIR / "seen.json"
TG_OFFSET_FILE = STATE_DIR / "telegram_offset.json"
EVENT_SIGS_FILE = STATE_DIR / "event_signatures.json"
MAX_SEEN_AGE_DAYS = 30
EVENT_SIG_TTL_SECONDS = 3600  # event signatures expire after 1 hour
BREAKING_WINDOW_SECONDS = 600  # cross-source detection window: 10 minutes
BREAKING_MIN_SOURCES = 2  # how many distinct sources to trigger breaking


def _ensure_dir():
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def load_seen() -> dict:
    _ensure_dir()
    if not SEEN_FILE.exists():
        return {}
    try:
        return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_seen(seen: dict):
    _ensure_dir()
    cutoff = time.time() - (MAX_SEEN_AGE_DAYS * 86400)
    pruned = {k: v for k, v in seen.items() if v >= cutoff}
    SEEN_FILE.write_text(json.dumps(pruned, indent=2, sort_keys=True), encoding="utf-8")


def mark_seen(seen: dict, url: str):
    seen[url_hash(url)] = int(time.time())


def is_seen(seen: dict, url: str) -> bool:
    return url_hash(url) in seen


def load_tg_offset() -> int:
    _ensure_dir()
    if not TG_OFFSET_FILE.exists():
        return 0
    try:
        return int(json.loads(TG_OFFSET_FILE.read_text(encoding="utf-8")).get("offset", 0))
    except (json.JSONDecodeError, ValueError):
        return 0


def save_tg_offset(offset: int):
    _ensure_dir()
    TG_OFFSET_FILE.write_text(json.dumps({"offset": offset}), encoding="utf-8")


def load_event_signatures() -> list[dict]:
    """List of {key, source, ts}. Auto-pruned to last hour."""
    _ensure_dir()
    if not EVENT_SIGS_FILE.exists():
        return []
    try:
        sigs = json.loads(EVENT_SIGS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    cutoff = time.time() - EVENT_SIG_TTL_SECONDS
    return [s for s in sigs if s.get("ts", 0) >= cutoff]


def save_event_signatures(sigs: list[dict]):
    _ensure_dir()
    cutoff = time.time() - EVENT_SIG_TTL_SECONDS
    pruned = [s for s in sigs if s.get("ts", 0) >= cutoff]
    EVENT_SIGS_FILE.write_text(json.dumps(pruned, indent=2), encoding="utf-8")


def check_breaking(sigs: list[dict], event_key: str, current_source: str) -> tuple[bool, int, list[str]]:
    """Check if this event_key has been reported by 2+ distinct sources within BREAKING_WINDOW.

    Returns (is_breaking, source_count, source_list).
    """
    if not event_key:
        return (False, 0, [])
    cutoff = time.time() - BREAKING_WINDOW_SECONDS
    distinct_sources = set()
    for s in sigs:
        if s.get("key") != event_key:
            continue
        if s.get("ts", 0) < cutoff:
            continue
        distinct_sources.add(s.get("source", ""))
    distinct_sources.add(current_source)
    return (len(distinct_sources) >= BREAKING_MIN_SOURCES, len(distinct_sources), sorted(distinct_sources))


def record_event_signature(sigs: list[dict], event_key: str, source: str):
    if not event_key:
        return
    sigs.append({"key": event_key, "source": source, "ts": int(time.time())})
