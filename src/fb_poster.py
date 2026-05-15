"""Facebook Page posting via Meta Graph API.

Mirrors approved X posts to the CrisisWire Facebook Page. The Page access token
in FB_PAGE_TOKEN is never-expiring (minted from a long-lived user token via the
/me/accounts edge), so no refresh logic is needed unless Meta revokes it.

Failure here never blocks the X post — _do_post_from_msg wraps this in try/except
and treats FB as best-effort.
"""
import os
import requests

GRAPH_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"
TIMEOUT = 20


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


def post(text: str, image_url: str = "", image_path: str = "", link_url: str = "") -> dict:
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


def comment(post_id: str, text: str) -> dict:
    """Post a comment AS the Page on one of the Page's own posts.

    Used to mirror the X behavior where every approved draft gets a follow-up
    reply with the source URL. Requires `pages_manage_engagement` scope on the
    Page token (in addition to `pages_manage_posts` used by post()).

    Returns {"id": "<comment_id>"}. Raises on failure (caller should treat
    comment failure as non-fatal — the parent post is already live)."""
    if not post_id or not text:
        return {"id": ""}
    pid = _page_id()
    token = _token()
    r = requests.post(
        f"{GRAPH_BASE}/{post_id}/comments",
        data={"message": text, "access_token": token},
        timeout=TIMEOUT,
    )
    if r.status_code != 200:
        raise RuntimeError(f"FB comment failed ({r.status_code}): {r.text[:300]}")
    return {"id": r.json().get("id", "")}


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
