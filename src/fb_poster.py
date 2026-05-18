"""Facebook Page posting via Meta Graph API.

Mirrors approved X posts to the CrisisWire Facebook Page. The Page access token
in FB_PAGE_TOKEN is never-expiring (minted from a long-lived user token via the
/me/accounts edge), so no refresh logic is needed unless Meta revokes it.

Failure here never blocks the X post — _do_post_from_msg wraps this in try/except
and treats FB as best-effort.
"""
import os
import json
import requests

GRAPH_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"
TIMEOUT = 20
VIDEO_TIMEOUT = 120
MAX_VIDEO_BYTES = 200 * 1024 * 1024
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def _download_video(video_url: str) -> bytes | None:
    """Fetch the video bytes ourselves while the CDN token is still valid.

    Facebook's /videos file_url path fetches server-side and async, by
    which time Telegram's telesco.pe token has expired / blocks FB's
    fetcher — the post then shows only a cover frame. Downloading here
    (same as x_poster) and uploading via multipart `source` avoids that.
    """
    try:
        r = requests.get(video_url, timeout=60, headers={"User-Agent": _UA})
        r.raise_for_status()
        content = r.content
    except Exception as e:
        print(f"[fb_poster] video download failed: {e}")
        return None
    if not (10_000 <= len(content) <= MAX_VIDEO_BYTES):
        print(f"[fb_poster] video size out of range ({len(content)} bytes)")
        return None
    return content


def _page_id() -> str:
    pid = os.environ.get("FB_PAGE_ID", "").strip()
    if not pid:
        raise RuntimeError("FB_PAGE_ID not set")
    return pid


def _token() -> str:
    tok = os.environ.get("FB_PAGE_TOKEN", "").strip()
    if not tok:
        raise RuntimeError("FB_PAGE_TOKEN not set")
    return tok


def enabled() -> bool:
    """True iff both env vars are set. Lets callers skip silently when FB
    integration isn't configured (e.g. in dev / first-run before token mint)."""
    return bool(os.environ.get("FB_PAGE_ID") and os.environ.get("FB_PAGE_TOKEN"))


def post(text: str, image_url: str = "", image_path: str = "",
         link_url: str = "", video_url: str = "") -> dict:
    """Post to the configured Page.

    - text-only: POST /{page_id}/feed with `message`
    - remote image: POST /{page_id}/photos with `url` (Meta fetches it
      server-side, no upload needed) and `caption`
    - local image (image_path): POST /{page_id}/photos with multipart
      `source` file upload (used for the generated headline card)
    - link_url is appended to the message body when present; FB's link
      previewer will render a card from it. We don't use the `link` param
      because Meta deprecated custom link previews for unverified apps.

    Returns {"id": "<post_id>", "had_image": bool}. Raises on hard failure.
    """
    pid = _page_id()
    token = _token()

    # Compose body. If we have a link, tack it on the end so FB renders a preview.
    body = text.strip()
    if link_url and link_url not in body:
        body = f"{body}\n\n{link_url}"

    # Video wins the post (matches X). Upload the bytes via multipart
    # `source` (download them here while the CDN token is valid) rather
    # than handing FB a file_url it fetches later and fails on. file_url
    # is kept only as a secondary attempt. Any failure falls through to
    # the image/text paths below.
    if video_url:
        content = _download_video(video_url)
        if content is not None:
            try:
                r = requests.post(
                    f"{GRAPH_BASE}/{pid}/videos",
                    data={"description": body, "access_token": token},
                    files={"source": ("video.mp4", content, "video/mp4")},
                    timeout=VIDEO_TIMEOUT,
                )
                if r.status_code == 200:
                    data = r.json()
                    return {
                        "id": data.get("post_id") or data.get("id", ""),
                        "had_image": False,
                        "had_video": True,
                    }
                print(f"[fb_poster] video source upload failed ({r.status_code}): {r.text[:200]}; trying file_url")
            except Exception as e:
                print(f"[fb_poster] video source upload exception: {e}; trying file_url")
        # Secondary attempt: let Graph fetch the URL itself.
        try:
            r = requests.post(
                f"{GRAPH_BASE}/{pid}/videos",
                data={"file_url": video_url, "description": body, "access_token": token},
                timeout=VIDEO_TIMEOUT,
            )
            if r.status_code == 200:
                data = r.json()
                return {
                    "id": data.get("post_id") or data.get("id", ""),
                    "had_image": False,
                    "had_video": True,
                }
            print(f"[fb_poster] video file_url failed ({r.status_code}): {r.text[:200]}; falling back to image/text")
        except Exception as e:
            print(f"[fb_poster] video file_url exception: {e}; falling back to image/text")

    if image_path and os.path.exists(image_path):
        # Local file (generated headline card) — multipart upload via `source`.
        try:
            with open(image_path, "rb") as fh:
                r = requests.post(
                    f"{GRAPH_BASE}/{pid}/photos",
                    data={"caption": body, "access_token": token},
                    files={"source": fh},
                    timeout=TIMEOUT,
                )
            if r.status_code == 200:
                data = r.json()
                return {"id": data.get("post_id") or data.get("id", ""), "had_image": True}
            print(f"[fb_poster] local photo upload failed ({r.status_code}): {r.text[:200]}; falling back to text")
        except Exception as e:
            print(f"[fb_poster] local photo upload exception: {e}; falling back to text")

    elif image_url:
        # Photo endpoint with remote URL — Meta handles the download itself.
        try:
            r = requests.post(
                f"{GRAPH_BASE}/{pid}/photos",
                data={"url": image_url, "caption": body, "access_token": token},
                timeout=TIMEOUT,
            )
            if r.status_code == 200:
                data = r.json()
                # /photos returns {"id": "<photo_id>", "post_id": "<page-post_id>"}.
                # Prefer post_id (the feed-post wrapping the photo) for parity with X URLs.
                return {"id": data.get("post_id") or data.get("id", ""), "had_image": True}
            else:
                # Fall back to text-only on photo failure (image URL might be hot-link
                # protected, expired, etc). Don't lose the post over a bad image.
                print(f"[fb_poster] photo post failed ({r.status_code}): {r.text[:200]}; falling back to text")
        except Exception as e:
            print(f"[fb_poster] photo post exception: {e}; falling back to text")

    # Text-only path (or photo fallback).
    r = requests.post(
        f"{GRAPH_BASE}/{pid}/feed",
        data={"message": body, "access_token": token},
        timeout=TIMEOUT,
    )
    if r.status_code != 200:
        raise RuntimeError(f"FB feed post failed ({r.status_code}): {r.text[:300]}")
    return {"id": r.json().get("id", ""), "had_image": False}


def post_album(text: str, image_urls: list[str]) -> dict:
    """Post multiple remote images as ONE Facebook post (album).

    Used for manual tweets that carry 2+ photos — they must become a single
    multi-photo FB post, not one post per image. Each image is uploaded as an
    unpublished photo, then a single feed post ties them together via
    attached_media.

    Falls back gracefully: 0 usable urls → text-only; 1 url → normal single
    photo post; any individual upload failure is skipped; if every upload
    fails we still publish the text. Returns {"id", "had_image"}.
    """
    urls = [u for u in (image_urls or []) if u and u.lower().startswith("http")]
    if not urls:
        return post(text)
    if len(urls) == 1:
        return post(text, image_url=urls[0])

    pid = _page_id()
    token = _token()
    body = text.strip()

    media_fbids = []
    for u in urls[:10]:  # FB album cap is generous; 10 is plenty for a tweet
        try:
            r = requests.post(
                f"{GRAPH_BASE}/{pid}/photos",
                data={"url": u, "published": "false", "access_token": token},
                timeout=TIMEOUT,
            )
            if r.status_code == 200:
                mid = r.json().get("id")
                if mid:
                    media_fbids.append(mid)
            else:
                print(f"[fb_poster] album photo upload failed ({r.status_code}): {r.text[:160]}")
        except Exception as e:
            print(f"[fb_poster] album photo upload exception: {e}")

    if not media_fbids:
        # Every upload failed — don't lose the post.
        return post(text)
    if len(media_fbids) == 1:
        # Only one survived; just attach it normally.
        return post(text, image_url=urls[0])

    data = {"message": body, "access_token": token}
    for i, mid in enumerate(media_fbids):
        data[f"attached_media[{i}]"] = json.dumps({"media_fbid": mid})

    r = requests.post(f"{GRAPH_BASE}/{pid}/feed", data=data, timeout=TIMEOUT)
    if r.status_code != 200:
        print(f"[fb_poster] album feed post failed ({r.status_code}): {r.text[:200]}; "
              f"falling back to single photo")
        return post(text, image_url=urls[0])
    return {"id": r.json().get("id", ""), "had_image": True}


def post_url(post_id: str) -> str:
    """Public URL for a Page post. Format works for both feed posts and
    photo posts (Meta returns combined `<page_id>_<post_id>` strings)."""
    if not post_id:
        return ""
    pid = _page_id()
    # Page post IDs come back as either "<page_id>_<numeric>" or just numeric.
    if "_" in post_id:
        _, tail = post_id.split("_", 1)
    else:
        tail = post_id
    return f"https://www.facebook.com/{pid}/posts/{tail}"
