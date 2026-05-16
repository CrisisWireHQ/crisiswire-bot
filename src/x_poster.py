import os
import io
import tempfile
import requests
import tweepy
from PIL import Image

_client_v2 = None
_api_v1 = None
MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = ("image/jpeg", "image/png", "image/gif", "image/webp")
# Below this shorter-edge (px), the image visibly upscales/blurs in-feed.
# Reject it so we either fall back to a better source or post clean text.
MIN_IMAGE_EDGE = 480
_UA = "Mozilla/5.0 (compatible; CrisisWireBot/1.0)"


def _decoded_size(content: bytes) -> tuple[int, int]:
    """(width, height) of image bytes, or (0, 0) if undecodable."""
    try:
        with Image.open(io.BytesIO(content)) as im:
            return im.size
    except Exception:
        return (0, 0)


def usable_image(image_url: str) -> bool:
    """True if the URL resolves to an image whose shorter edge is large
    enough to look sharp in-feed. Used to decide whether to fall back to a
    higher-quality source before posting."""
    if not image_url:
        return False
    try:
        r = requests.get(image_url, timeout=15, headers={"User-Agent": _UA})
        r.raise_for_status()
    except Exception:
        return False
    if not (r.headers.get("content-type") or "").lower().startswith("image/"):
        return False
    content = r.content
    if not (1000 <= len(content) <= MAX_IMAGE_BYTES):
        return False
    w, h = _decoded_size(content)
    if w == 0:
        return False
    return min(w, h) >= MIN_IMAGE_EDGE


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

    w, h = _decoded_size(content)
    if w and min(w, h) < MIN_IMAGE_EDGE:
        print(f"[x_poster] image too low-res ({w}x{h}, min edge < {MIN_IMAGE_EDGE}px), skipping")
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


MAX_VIDEO_BYTES = 200 * 1024 * 1024  # well under X's 512MB cap; bounds GH runner


def _upload_video(video_url: str) -> str | None:
    """Download a video and chunked-upload it to X. Returns media_id or None.

    X requires async chunked upload (INIT/APPEND/FINALIZE) plus a STATUS
    poll while it transcodes — tweepy's chunked media_upload with
    wait_for_processing=True handles all of that and raises on failure."""
    try:
        r = requests.get(video_url, timeout=60, stream=True,
                          headers={"User-Agent": _UA})
        r.raise_for_status()
        content = r.content
    except Exception as e:
        print(f"[x_poster] video download failed: {e}")
        return None

    if not (10_000 <= len(content) <= MAX_VIDEO_BYTES):
        print(f"[x_poster] video size out of range ({len(content)} bytes), skipping")
        return None

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        # Call chunked_upload directly: its wait_for_processing=True default
        # blocks until X finishes transcoding. (Passing wait_for_processing
        # through media_upload(**kwargs) leaks it into the request payload —
        # tweepy warns "Unexpected parameter" and does NOT actually wait.)
        media = api().chunked_upload(
            filename=tmp_path,
            file_type="video/mp4",
            media_category="tweet_video",
        )
        return str(media.media_id_string)
    except Exception as e:
        print(f"[x_poster] X video upload failed: {e}")
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def post(text: str, image_url: str = "", video_url: str = "",
         quote_tweet_id: str = "") -> dict:
    """Post a tweet, optionally with attached video/image and/or as a quote.

    X allows only one media type per tweet; video is the stronger in-feed
    signal, so it wins the slot. The image is the fallback if the video
    upload fails (download/size/transcode)."""
    media_ids: list[str] = []
    had_video = False
    if video_url:
        vid = _upload_video(video_url)
        if vid:
            media_ids.append(vid)
            had_video = True
            print(f"[x_poster] attached video media_id={vid}")
        else:
            print(f"[x_poster] video attachment failed; trying image fallback")

    if not media_ids and image_url:
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
        "had_image": bool(media_ids) and not had_video,
        "had_video": had_video,
        "had_quote": bool(quote_tweet_id),
    }


def reply(text: str, in_reply_to_tweet_id: str) -> dict:
    """Post a reply to an existing tweet."""
    resp = client().create_tweet(text=text, in_reply_to_tweet_id=str(in_reply_to_tweet_id))
    return {"id": resp.data["id"], "text": text}
