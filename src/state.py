import json
import re
import hashlib
import time
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
SEEN_FILE = STATE_DIR / "seen.json"
TG_OFFSET_FILE = STATE_DIR / "telegram_offset.json"
EVENT_SIGS_FILE = STATE_DIR / "event_signatures.json"
DRAFTED_KEYS_FILE = STATE_DIR / "drafted_keys.json"
RECENT_DRAFTS_FILE = STATE_DIR / "recent_drafts.json"
BOT_TWEETS_FILE = STATE_DIR / "bot_tweets.json"
MAX_SEEN_AGE_DAYS = 30
EVENT_SIG_TTL_SECONDS = 3600  # 1 hour
BREAKING_WINDOW_SECONDS = 600  # 10 minutes
BREAKING_MIN_SOURCES = 2
DRAFTED_KEY_TTL_SECONDS = 24 * 3600  # don't redraft same event_key within 24h
RECENT_DRAFT_TTL_SECONDS = 48 * 3600  # text-fingerprint window, 48h
BOT_TWEET_TTL_SECONDS = 14 * 24 * 3600  # remember bot-posted tweet IDs for 14d


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


def load_drafted_keys() -> dict:
    """Map of event_key → last drafted timestamp. Auto-pruned on load."""
    _ensure_dir()
    if not DRAFTED_KEYS_FILE.exists():
        return {}
    try:
        data = json.loads(DRAFTED_KEYS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    cutoff = time.time() - DRAFTED_KEY_TTL_SECONDS
    return {k: v for k, v in data.items() if v >= cutoff}


def save_drafted_keys(keys: dict):
    _ensure_dir()
    cutoff = time.time() - DRAFTED_KEY_TTL_SECONDS
    pruned = {k: v for k, v in keys.items() if v >= cutoff}
    DRAFTED_KEYS_FILE.write_text(json.dumps(pruned, indent=2, sort_keys=True), encoding="utf-8")


# Canonicalize event-type slugs so synonyms collide under coarse dedup.
# Real-world: classifier emits "plane-crash" / "crash-landed" / "crash" for
# the same event; "airstrike" / "drone-strike" / "missile-strike" / "attack"
# for what is operationally the same incident.
_EVENT_TYPE_CANON = {
    "plane-crash": "crash",
    "crash-landed": "crash",
    "aviation-crash": "crash",
    "airstrike": "strike",
    "air-strike": "strike",
    "drone-strike": "strike",
    "missile-strike": "strike",
    "air-attack": "strike",
    "bombing": "strike",
    "attack": "strike",
    "mass-shooting": "shooting",
    "wildfire": "fire",
    "earthquake": "quake",
    "earthquake-swarm": "quake",
    "quake-swarm": "quake",
    "seismic-swarm": "quake",
    "tremor": "quake",
    "aftershock": "quake",
    "blast": "explosion",
    "detonation": "explosion",
    "ied-blast": "explosion",
    "car-bomb": "explosion",
    "shooting-plot": "shooting",
    "active-shooter": "shooting",
    "gun-attack": "shooting",
    "stabbing": "attack",
    "kidnapping": "hostage",
    "abduction": "hostage",
    "vessel-strike": "strike",
    "naval-strike": "strike",
    "combined-strike": "strike",
    "drone-attack": "strike",
    "missile-attack": "strike",
    "armed-conflict": "strike",
    "gastroenteritis-outbreak": "outbreak",
    "hantavirus": "outbreak",
    "hantavirus-exposure": "outbreak",
    "hantavirus-outbreak": "outbreak",
    "plane-crash-landed": "crash",
    "aviation-incident": "crash",
    "helicopter-crash": "crash",
}


def _coarse_key(event_key: str) -> str:
    """First 2 segments of the event_key (country + canonical event-type),
    used for fuzzy dedup so near-duplicates with different last-segment
    details still collide."""
    if not event_key:
        return ""
    parts = event_key.split("--")
    if len(parts) >= 2:
        country = parts[0]
        etype = _EVENT_TYPE_CANON.get(parts[1], parts[1])
        return f"{country}--{etype}"
    return event_key


def is_drafted(keys: dict, event_key: str) -> bool:
    """True if event_key OR its coarse form (country+event-type) was drafted recently."""
    if not event_key:
        return False
    if event_key in keys:
        return True
    coarse = _coarse_key(event_key)
    if not coarse:
        return False
    for k in keys:
        if _coarse_key(k) == coarse:
            return True
    return False


def mark_drafted(keys: dict, event_key: str):
    if not event_key:
        return
    keys[event_key] = int(time.time())


# --- Draft-text fingerprint dedup ---------------------------------
# Defense of last resort: even when event_keys diverge (different sources,
# different classifier runs, race between concurrent workflows), if the
# resulting draft text is semantically the same, suppress it.

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "to", "in", "on", "of", "at", "for",
    "with", "by", "from", "as", "is", "are", "was", "were", "be", "been",
    "has", "have", "had", "will", "would", "could", "should", "may", "might",
    "this", "that", "these", "those", "after", "before", "near", "into",
    "per", "according", "reports", "reported", "via", "amid", "amid",
}


JACCARD_DUPLICATE_THRESHOLD = 0.45  # set-overlap ratio that counts as "same story"


def _draft_word_set(text: str) -> set:
    """Distinctive content words (lowercase, length>2, no stopwords/punct).
    Cuts at the first attribution clause ('per X', 'according to Y') so
    the source name doesn't leak into the comparison."""
    if not text:
        return set()
    t = text.lower()
    t = re.split(r"\b(per|according to|reported by|reports say|sources say)\b", t, 1)[0]
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return {w for w in t.split() if len(w) > 2 and w not in _STOPWORDS}


def _draft_fingerprint(text: str) -> str:
    """Stable signature hash used as the dict key for `recent_drafts.json`.
    Identical word-sets → identical hash (which lets us upsert)."""
    words = _draft_word_set(text)
    if not words:
        return ""
    return hashlib.sha256(" ".join(sorted(words)).encode("utf-8")).hexdigest()[:16]


def load_recent_drafts() -> dict:
    """Map of fingerprint → {ts, words[]}. Auto-pruned on load.

    Back-compat: old schema stored bare ints (timestamps) — those are dropped
    on load since they carry no word-set for similarity comparison."""
    _ensure_dir()
    if not RECENT_DRAFTS_FILE.exists():
        return {}
    try:
        data = json.loads(RECENT_DRAFTS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    cutoff = time.time() - RECENT_DRAFT_TTL_SECONDS
    out = {}
    for k, v in data.items():
        if not isinstance(v, dict):
            continue  # drop legacy bare-int entries
        if v.get("ts", 0) < cutoff:
            continue
        out[k] = v
    return out


def save_recent_drafts(drafts: dict):
    _ensure_dir()
    cutoff = time.time() - RECENT_DRAFT_TTL_SECONDS
    pruned = {
        k: v for k, v in drafts.items()
        if isinstance(v, dict) and v.get("ts", 0) >= cutoff
    }
    RECENT_DRAFTS_FILE.write_text(json.dumps(pruned, indent=2, sort_keys=True), encoding="utf-8")


def is_recent_draft(drafts: dict, text: str) -> bool:
    """True iff any stored draft has word-set Jaccard ≥ threshold with this text.
    Catches paraphrased restatements of the same story even when the exact
    word-set differs."""
    new_words = _draft_word_set(text)
    if len(new_words) < 4:  # too sparse to compare reliably
        return False
    best = 0.0
    for entry in drafts.values():
        if not isinstance(entry, dict):
            continue
        old_words = set(entry.get("words", []))
        if len(old_words) < 4:
            continue
        union = new_words | old_words
        if not union:
            continue
        jaccard = len(new_words & old_words) / len(union)
        if jaccard > best:
            best = jaccard
        if jaccard >= JACCARD_DUPLICATE_THRESHOLD:
            return True
    return False


def mark_recent_draft(drafts: dict, text: str):
    fp = _draft_fingerprint(text)
    if not fp:
        return
    drafts[fp] = {
        "ts": int(time.time()),
        "words": sorted(_draft_word_set(text)),
    }


# --- Bot-posted tweet IDs -----------------------------------------------
# Used by x_self_mirror to distinguish tweets the bot itself posted (via the
# Telegram approval flow) from tweets the human posted manually on X. Only
# manual tweets get mirrored to Facebook.

def load_bot_tweets() -> dict:
    """Map of tweet_id (str) → ts. Pruned on load."""
    _ensure_dir()
    if not BOT_TWEETS_FILE.exists():
        return {}
    try:
        data = json.loads(BOT_TWEETS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    cutoff = time.time() - BOT_TWEET_TTL_SECONDS
    return {k: v for k, v in data.items() if isinstance(v, (int, float)) and v >= cutoff}


def save_bot_tweets(tweets: dict):
    _ensure_dir()
    cutoff = time.time() - BOT_TWEET_TTL_SECONDS
    pruned = {k: v for k, v in tweets.items() if isinstance(v, (int, float)) and v >= cutoff}
    BOT_TWEETS_FILE.write_text(json.dumps(pruned, indent=2, sort_keys=True), encoding="utf-8")


def record_bot_tweet(tweet_id: str):
    """One-shot: load, append, save. Cheap because the file stays small."""
    if not tweet_id:
        return
    tweets = load_bot_tweets()
    tweets[str(tweet_id)] = int(time.time())
    save_bot_tweets(tweets)


def is_bot_tweet(tweets: dict, tweet_id: str) -> bool:
    return str(tweet_id) in tweets
