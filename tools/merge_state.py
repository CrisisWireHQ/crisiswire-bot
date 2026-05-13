"""Smart-merge local state JSON files with origin/main's versions.

Used by the workflow's commit step to handle the case where a full-poll run and
a trusted-only run touch overlapping state files concurrently. git can't
auto-merge JSON, so we merge each file by its schema.
"""
import json
import subprocess
import sys
from pathlib import Path


def _load_local(rel_path: str):
    p = Path(rel_path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _load_remote(rel_path: str, ref: str = "origin/main"):
    try:
        out = subprocess.check_output(
            ["git", "show", f"{ref}:{rel_path}"],
            stderr=subprocess.DEVNULL,
        )
        return json.loads(out.decode("utf-8"))
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None


def _merge_dict_max(local: dict, remote: dict) -> dict:
    """For dicts of {key: comparable_value} (e.g. {url_hash: ts}), keep max."""
    out = dict(remote or {})
    for k, v in (local or {}).items():
        if k not in out or v > out[k]:
            out[k] = v
    return out


def _merge_event_signatures(local: list, remote: list) -> list:
    """List of {key, source, ts}. Concatenate, dedupe by tuple."""
    seen = set()
    out = []
    for entry in (remote or []) + (local or []):
        if not isinstance(entry, dict):
            continue
        sig = (entry.get("key"), entry.get("source"), entry.get("ts"))
        if sig in seen:
            continue
        seen.add(sig)
        out.append(entry)
    return out


def _merge_telegram_offset(local: dict, remote: dict) -> dict:
    a = (local or {}).get("offset", 0)
    b = (remote or {}).get("offset", 0)
    return {"offset": max(int(a or 0), int(b or 0))}


def _merge_x_watcher(local: dict, remote: dict) -> dict:
    """{username: {user_id, last_tweet_id, last_poll_ts}}. Merge per username."""
    out = dict(remote or {})
    for username, lrec in (local or {}).items():
        rrec = dict(out.get(username, {}))
        if lrec.get("user_id"):
            rrec["user_id"] = lrec["user_id"]
        if int(lrec.get("last_poll_ts", 0) or 0) > int(rrec.get("last_poll_ts", 0) or 0):
            rrec["last_poll_ts"] = lrec["last_poll_ts"]
        ltid = int(lrec.get("last_tweet_id", "0") or 0)
        rtid = int(rrec.get("last_tweet_id", "0") or 0)
        if ltid > rtid:
            rrec["last_tweet_id"] = str(ltid)
        elif rtid > 0 and "last_tweet_id" not in rrec:
            rrec["last_tweet_id"] = str(rtid)
        out[username] = rrec
    return out


MERGERS = {
    "state/seen.json": _merge_dict_max,
    "state/drafted_keys.json": _merge_dict_max,
    "state/recent_drafts.json": _merge_dict_max,
    "state/event_signatures.json": _merge_event_signatures,
    "state/telegram_offset.json": _merge_telegram_offset,
    "state/x_watcher.json": _merge_x_watcher,
}


def main():
    changed = 0
    for rel_path, merger in MERGERS.items():
        local = _load_local(rel_path)
        remote = _load_remote(rel_path)
        if local is None and remote is None:
            continue
        merged = merger(local if local is not None else type(remote)() if remote is not None else {},
                        remote if remote is not None else type(local)() if local is not None else {})
        out_path = Path(rel_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(merged, dict):
            text = json.dumps(merged, indent=2, sort_keys=True)
        else:
            text = json.dumps(merged, indent=2)
        out_path.write_text(text, encoding="utf-8")
        size = len(merged) if hasattr(merged, "__len__") else "?"
        print(f"[merge_state] {rel_path}: {size} entries after merge")
        changed += 1
    print(f"[merge_state] merged {changed} files")


if __name__ == "__main__":
    sys.exit(main())
