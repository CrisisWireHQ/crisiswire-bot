import os
import io
import tempfile
import requests
import tweepy

_client_v2 = None
_api_v1 = None
MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = ("image/jpeg", "image/png", "image/gif", "image/webp")


def client() -> tweepy.Client:
    global _client_v2
    if _client_v2 is None:
        _client_v2 = tweepy.Client(
            consumer_key=os.environ["X_API_KEY"],
            consumer_secret=os.environ["X_API_SECRET"],
            access_token=os.environ["X_ACCESS_TOKEN"],
            access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
        )
    return _client_v2


def api() -> tweepy.API:
    global _api_v1
    if _api_v1 is None:
        auth = tweepy.OAuth1UserHandler(
            os.environ["X_API_KEY"],
            os.environ["X_API_SECRET"],
            os.environ["X_ACCESS_TOKEN"],
            os.environ["X_ACCESS_TOKEN_SECRET"],
        )
        _api_v1 = tweepy.API(auth)
    return _api_v1


def _upload_image(image_url: str) -> str | None:
    """Download image from URL and upload to X. Returns media_id or None on failure."""
    try:
        r = requests.get(image_url, timeout=20, headers={
            "User-Agent": "Mozilla/5.0 (compatible; CrisisWireBot/1.0)"
        })
        r.raise_for_status()
    except Exception as e:
        print(f"[x_poster] image download failed: {e}")
        return None

    ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
    if not ctype.startswith("image/"):
        print(f"[x_poster] non-image content-type: {ctype}")
        return None
    if ctype not in ALLOWED_IMAGE_TYPES:
        # Some servers return image/jpg, image/x-png etc. — best-effort accept anything image/*
        print(f"[x_poster] unusual image type {ctype}, trying anyway")

    content = r.content
    if len(content) > MAX_IMAGE_BYTES:
        print(f"[x_poster] image too large ({len(content)} bytes), skipping")
        return None
    if len(content) < 1000:
        print(f"[x_poster] image suspiciously small ({len(content)} bytes), skipping")
        return None

    # Determine extension for tweepy
    ext = "jpg"
    if "png" in ctype:
        ext = "png"
    elif "gif" in ctype:
        ext = "gif"
    elif "webp" in ctype:
        ext = "webp"

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        media = api().media_upload(filename=tmp_path)
        return str(media.media_id_string)
    except Exception as e:
        print(f"[x_poster] X media_upload failed: {e}")
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def post(text: str, image_url: str = "", quote_tweet_id: str = "") -> dict:
    """Post a tweet, optionally with an attached image and/or as a quote-tweet."""
    media_ids: list[str] = []
    if image_url:
        mid = _upload_image(image_url)
        if mid:
            media_ids.append(mid)
            print(f"[x_poster] attached media_id={mid}")
        else:
            print(f"[x_poster] image attachment failed; posting text only")

    kwargs = {"text": text}
    if media_ids:
        kwargs["media_ids"] = media_ids
    if quote_tweet_id:
        kwargs["quote_tweet_id"] = str(quote_tweet_id)
        print(f"[x_poster] quote-tweeting {quote_tweet_id}")

    resp = client().create_tweet(**kwargs)
    return {
        "id": resp.data["id"],
        "text": text,
        "had_image": bool(media_ids),
        "had_quote": bool(quote_tweet_id),
    }


def reply(text: str, in_reply_to_tweet_id: str) -> dict:
    """Post a reply to an existing tweet."""
    resp = client().create_tweet(text=text, in_reply_to_tweet_id=str(in_reply_to_tweet_id))
    return {"id": resp.data["id"], "text": text}
