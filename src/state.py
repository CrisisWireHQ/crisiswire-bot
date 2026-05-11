import json
import hashlib
import time
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
SEEN_FILE = STATE_DIR / "seen.json"
TG_OFFSET_FILE = STATE_DIR / "telegram_offset.json"
MAX_SEEN_AGE_DAYS = 30


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
