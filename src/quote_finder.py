"""Find recent hantavirus tweets from official health agencies for quote-tweeting."""
import os
import re
import tweepy

_client = None

# (username, numeric_user_id) — pre-resolved so we skip an extra lookup call.
# Verified IDs as of 2025.
HANTAVIRUS_ACCOUNTS = [
    ("CDCgov", "146569971"),
    ("CDCemergency", "78586090"),
    ("WHO", "14499829"),
    ("PAHOhq", "33533108"),
]

HANTAVIRUS_RE = re.compile(
    r"\b(hantavirus|sin\s*nombre|andes\s*virus|HPS|HFRS|hantavirus\s+pulmonary)\b",
    re.IGNORECASE,
)

EBOLA_RE = re.compile(
    r"\b(ebola|ebolavirus|EVD|filovirus|hemorrhagic\s+fever|"
    r"(zaire|sudan|bundibugyo|ta[iï]\s*forest|reston)\s+ebola)\b",
    re.IGNORECASE,
)


def client() -> tweepy.Client:
    global _client
    if _client is None:
        _client = tweepy.Client(bearer_token=os.environ["X_BEARER_TOKEN"])
    return _client


def find_hantavirus_tweet(max_age_hours: int = 48) -> tuple[str, str, str] | None:
    """Search official agency timelines for a recent hantavirus tweet.

    Returns (tweet_id, tweet_url, source_username) or None.
    """
    import time
    cutoff_epoch = time.time() - max_age_hours * 3600

    for username, user_id in HANTAVIRUS_ACCOUNTS:
        try:
            resp = client().get_users_tweets(
                id=user_id,
                max_results=10,
                tweet_fields=["created_at"],
                exclude=["replies", "retweets"],
            )
        except Exception as e:
            print(f"[quote_finder] {username}: {e}")
            continue

        if not resp or not resp.data:
            continue

        for tweet in resp.data:
            if not HANTAVIRUS_RE.search(tweet.text or ""):
                continue
            created = tweet.created_at
            if created and created.timestamp() < cutoff_epoch:
                continue
            url = f"https://x.com/{username}/status/{tweet.id}"
            print(f"[quote_finder] match: {username} → {tweet.id}")
            return (str(tweet.id), url, username)

    return None


def text_mentions_hantavirus(text: str) -> bool:
    return bool(HANTAVIRUS_RE.search(text or ""))


def text_mentions_ebola(text: str) -> bool:
    return bool(EBOLA_RE.search(text or ""))
