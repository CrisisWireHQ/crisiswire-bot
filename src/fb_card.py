"""Generate a branded headline card for Facebook posts that have no photo.

Last-resort visual: when an item carried no media AND we couldn't scrape an
og:image from the source article, we render the headline onto a branded
CrisisWire background so the post is never bare text (text-only posts are
heavily down-ranked by Meta's 2026 algorithm).

Deterministic, $0 — pure Pillow, no AI/model calls. Degrades gracefully:
- If assets/fb_card_bg.png exists, it's used as the canvas.
- Otherwise a solid navy canvas with an orange accent bar is drawn in-code.
- If a bundled TTF exists in assets/fonts/, it's used; else Pillow's
  scalable default font.
"""
import os
import re
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_BG_PATH = _ASSETS / "fb_card_bg.png"
_FONTS_DIR = _ASSETS / "fonts"

CARD_W, CARD_H = 1200, 630
NAVY = (10, 20, 40)        # #0a1428
ORANGE = (255, 91, 53)     # #ff5b35
WHITE = (245, 247, 250)

# Emoji / pictograph / symbol codepoints the headline font can't render.
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"   # symbols & pictographs, supplemental, extended-A
    "\U00002600-\U000027BF"   # misc symbols + dingbats
    "\U0001F1E6-\U0001F1FF"   # regional indicators (flags)
    "\U00002190-\U000021FF"   # arrows
    "\U00002B00-\U00002BFF"   # misc symbols & arrows
    "\U0000FE00-\U0000FE0F"   # variation selectors
    "\U00002000-\U0000200D"   # zero-width joiners / special spaces
    "\U000024C2\U0000203C\U00002049\U000020E3"
    "]+",
    flags=re.UNICODE,
)

# Text box: upper-left region, leaving the bottom third for the accent bar.
MARGIN_X = 70
TEXT_TOP = 90
TEXT_MAX_W = CARD_W - 2 * MARGIN_X


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    if _FONTS_DIR.is_dir():
        for ext in ("*.ttf", "*.otf"):
            for f in sorted(_FONTS_DIR.glob(ext)):
                try:
                    return ImageFont.truetype(str(f), size)
                except Exception:
                    continue
    # Common system fallbacks (GitHub Actions ubuntu has DejaVu).
    for sysfont in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf",
        "arialbd.ttf",
        "arial.ttf",
    ):
        try:
            return ImageFont.truetype(sysfont, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)  # Pillow >=10
    except TypeError:
        return ImageFont.load_default()


def _base_canvas() -> Image.Image:
    if _BG_PATH.is_file():
        try:
            img = Image.open(_BG_PATH).convert("RGB")
            return img.resize((CARD_W, CARD_H)) if img.size != (CARD_W, CARD_H) else img
        except Exception as e:
            print(f"[fb_card] bg load failed ({e}); using drawn fallback")
    # Drawn fallback: navy field + orange bar across the bottom third.
    img = Image.new("RGB", (CARD_W, CARD_H), NAVY)
    d = ImageDraw.Draw(img)
    bar_h = 14
    d.rectangle([0, CARD_H - 150, CARD_W, CARD_H - 150 + bar_h], fill=ORANGE)
    return img


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def generate(headline: str) -> str:
    """Render `headline` onto a branded card. Returns a temp PNG path
    (caller is responsible for unlinking) or "" on failure."""
    headline = (headline or "").strip()
    if not headline:
        return ""
    # Strip ONLY a genuine trailing attribution — never plain em-dash content.
    # The drafter uses "—" as a normal sentence connector, so we must not cut
    # at the dash. Real attribution looks like "... per Reuters" or a trailing
    # "Source: <url>" / "(Reuters)"; remove just that tail.
    # Remove a genuine trailing attribution (case-insensitive). If that empties
    # the string, it WAS pure attribution ("Source: <url>") — do NOT restore
    # it; return no card so the caller posts text-only instead of junk.
    stripped = re.sub(
        r"\s*[—-]?\s*(?:source\s*:.*|per\s+[A-Za-z][\w .&'-]{1,40}|\((?:via\s+)?[A-Za-z][\w .&'-]{1,40}\))\s*$",
        "",
        headline,
        flags=re.IGNORECASE,
    ).strip()
    headline = stripped if stripped else ""

    # Archivo Black (and the DejaVu fallback) have no emoji/pictograph glyphs;
    # Pillow renders them as blank boxes. Strip emoji, symbols, URLs, and other
    # non-renderable noise — the FB post *body* still carries the original
    # emoji/links; this only cleans the rendered image.
    headline = _EMOJI_RE.sub("", headline)
    headline = re.sub(r"https?://\S+", "", headline)
    headline = re.sub(r"\s{2,}", " ", headline).strip(" -—–·|#@")
    # Need real words, not just stray punctuation/URL remnants. Require some
    # alphabetic content; otherwise bail so the caller goes text-only.
    if len(re.sub(r"[^A-Za-z]", "", headline)) < 8:
        return ""

    try:
        img = _base_canvas()
        draw = ImageDraw.Draw(img)

        # Auto-fit: shrink font until the wrapped block fits the upper area.
        for size in (74, 66, 58, 52, 46, 40, 36):
            font = _load_font(size)
            lines = _wrap(draw, headline, font, TEXT_MAX_W)
            line_h = int(size * 1.28)
            block_h = line_h * len(lines)
            if block_h <= (CARD_H - 200 - TEXT_TOP) and len(lines) <= 7:
                break

        # "BREAKING" kicker.
        kicker_font = _load_font(30)
        draw.text((MARGIN_X, TEXT_TOP - 48), "BREAKING", font=kicker_font, fill=ORANGE)

        y = TEXT_TOP
        for ln in lines:
            draw.text((MARGIN_X, y), ln, font=font, fill=WHITE)
            y += line_h

        # Footer wordmark.
        wm_font = _load_font(28)
        draw.text((MARGIN_X, CARD_H - 60), "@CrisisWireHQ", font=wm_font, fill=WHITE)

        fd, path = tempfile.mkstemp(suffix=".png", prefix="fbcard_")
        os.close(fd)
        img.save(path, "PNG")
        return path
    except Exception as e:
        print(f"[fb_card] generation failed: {e}")
        return ""
