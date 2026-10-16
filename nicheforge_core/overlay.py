#!/usr/bin/env python3
"""NicheForge Urdu Overlay Studio (Phase 2).

Local PIL Urdu text overlay on base images for the deen/sukhan/lafz niches:
- base image resized/cropped to 1080x1080 (LANCZOS)
- bottom gradient scrim for legibility
- Urdu lines centred in Jameel Noori Nastaleeq (PIL raqm, direction=rtl)
- auto-fit font size starting at 72, shrinking until lines fit 900px width
- gold letterspaced niche wordmark at top + thin divider ornament
- optional attribution in gold at the bottom

Only niches in OVERLAY_NICHES may use Urdu overlay. Any Devanagari input
raises ValueError (register rule: Roman Urdu / Urdu script only).
"""
import os
import re
import unicodedata
from PIL import Image, ImageDraw, ImageFont

OVERLAY_NICHES = ["deen", "sukhan", "lafz"]

SIZE = 1080
MAX_LINE_W = 900
START_FONT_SIZE = 72
MIN_FONT_SIZE = 30

_HERE = os.path.dirname(os.path.abspath(__file__))
_FONT_BUNDLED = os.path.join(_HERE, "fonts", "JameelNooriNastaleeq.ttf")
_FONT_FALLBACK = os.path.expanduser("~/.local/share/fonts/JameelNooriNastaleeq.ttf")
_LATIN_BUNDLED = os.path.join(_HERE, "fonts", "Poppins-Regular.ttf")

PALETTES = {
    # Deen: deep emerald night tint + sacred gold text/accents
    "deen": {
        "scrim": (10, 20, 32),
        "body": (255, 210, 63),     # #FFD23F Sacred Gold
        "gold": (255, 210, 63),
        "wordmark": "DEEN",
    },
    # Sukhan: warm dark teal/charcoal + ivory + gold
    "sukhan": {
        "scrim": (10, 16, 15),
        "body": (244, 240, 230),    # #F4F0E6 Ivory
        "gold": (198, 161, 91),     # #C6A15B Gold
        "wordmark": "SUKHAN",
    },
    # Lafz: obsidian charcoal + literary ivory + antique gold
    "lafz": {
        "scrim": (20, 22, 26),      # #14161A Obsidian Charcoal
        "body": (245, 241, 232),    # #F5F1E8 Literary Ivory
        "gold": (201, 162, 39),     # #C9A227 Antique Gold
        "emerald": (46, 125, 106),  # Royal Emerald (divider accent)
        "wordmark": "LAFZ",
    },
}

# Devanagari block: register rule forbids it anywhere in overlay input.
_DEVANAGARI = re.compile(r"[\u0900-\u097F]")


def _font_path():
    if os.path.isfile(_FONT_BUNDLED):
        return _FONT_BUNDLED
    if os.path.isfile(_FONT_FALLBACK):
        return _FONT_FALLBACK
    raise RuntimeError(
        "JameelNooriNastaleeq.ttf not found: checked "
        f"{_FONT_BUNDLED} and {_FONT_FALLBACK}. "
        "Copy the font into ~/workspace/nicheforge/fonts/ or install it under "
        "~/.local/share/fonts/."
    )


def _urdu_font(size):
    return ImageFont.truetype(_font_path(), size, layout_engine=ImageFont.Layout.RAQM)


def _latin_font(size):
    if os.path.isfile(_LATIN_BUNDLED):
        return ImageFont.truetype(_LATIN_BUNDLED, size)
    return ImageFont.load_default()


def _check_no_devanagari(text, field):
    if text and _DEVANAGARI.search(text):
        raise ValueError(
            f"Devanagari script not allowed in {field}; use Urdu script or Roman Urdu."
        )


def _guard(niche):
    if niche not in OVERLAY_NICHES:
        raise ValueError(
            f"niche {niche!r} does not allow Urdu overlay; allowed: {OVERLAY_NICHES}"
        )


def _fit_size(draw, lines):
    """Largest font size (from START down) fitting every line within MAX_LINE_W."""
    for size in range(START_FONT_SIZE, MIN_FONT_SIZE - 1, -2):
        font = _urdu_font(size)
        if all(
            draw.textlength(ln, font=font, direction="rtl") <= MAX_LINE_W
            for ln in lines
        ):
            return size
    return MIN_FONT_SIZE


def _bottom_gradient(im, rgb, alpha=200, start=0.5):
    w, h = im.size
    grad = Image.new("L", (1, h))
    top = int(h * start)
    for y in range(h):
        grad.putpixel((0, y), 0 if y < top else int(alpha * (y - top) / (h - top)))
    grad = grad.resize((w, h))
    return Image.composite(Image.new("RGB", (w, h), rgb), im, grad)


def _draw_wordmark(draw, cx, y, text, size, fill, tracking):
    font = _latin_font(size)
    widths = [draw.textlength(ch, font=font) for ch in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = cx - total / 2
    for ch, w in zip(text, widths):
        draw.text((x, y), ch, font=font, fill=fill, anchor="ma")
        x += w + tracking


def _divider(draw, cx, y, half, rgb, accent=None):
    draw.line([cx - half, y, cx + half, y], fill=rgb, width=2)
    ax, ay = cx, y
    r = 4
    draw.ellipse([ax - r, ay - r, ax + r, ay + r], fill=accent or rgb)
    draw.ellipse([ax - r + 1, ay - r + 1, ax + r - 1, ay + r - 1], fill=rgb)


def default_output_path(niche, base_image_path):
    stem = os.path.splitext(os.path.basename(base_image_path))[0]
    outdir = os.path.join(_HERE, "workspace", "niches", niche, "output")
    os.makedirs(outdir, exist_ok=True)
    return os.path.join(outdir, f"{stem}-final.png")


def overlay_urdu(base_image_path, niche, lines, output_path=None, attribution=None):
    """Overlay Urdu lines on a base image and save the final card.

    base_image_path: path to any image (resized/cropped to 1080x1080).
    niche: one of OVERLAY_NICHES.
    lines: list of Urdu strings, centred.
    output_path: where to save; defaults to niches/<niche>/output/<stem>-final.png.
    attribution: optional small gold line at the bottom (poet / reference).
    Returns output_path.
    """
    _guard(niche)
    if not os.path.isfile(base_image_path):
        raise FileNotFoundError(f"base image not found: {base_image_path}")
    if not lines or not any(ln.strip() for ln in lines):
        raise ValueError("lines must contain at least one non-empty Urdu line")
    for i, ln in enumerate(lines):
        _check_no_devanagari(ln, f"lines[{i}]")
    _check_no_devanagari(attribution, "attribution")

    pal = PALETTES[niche]

    im = Image.open(base_image_path).convert("RGB")
    if im.size != (SIZE, SIZE):
        # cover-fit: scale so the short side hits SIZE, centre-crop
        w, h = im.size
        scale = max(SIZE / w, SIZE / h)
        im = im.resize((int(w * scale + 0.5), int(h * scale + 0.5)), Image.LANCZOS)
        left = (im.width - SIZE) // 2
        top = (im.height - SIZE) // 2
        im = im.crop((left, top, left + SIZE, top + SIZE))

    im = _bottom_gradient(im, pal["scrim"], alpha=200, start=0.45)

    d = ImageDraw.Draw(im)
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ovo = ImageDraw.Draw(ov)

    # wordmark + divider at top
    _draw_wordmark(d, SIZE // 2, 64, pal["wordmark"], 26, pal["gold"], 10)
    _divider(ovo, SIZE // 2, 114, half=56, rgb=pal["gold"], accent=pal.get("emerald"))

    # verse block: fit one size for all lines, centre the block vertically
    lines = [ln.strip() for ln in lines if ln.strip()]
    size = _fit_size(d, lines)
    font = _urdu_font(size)
    line_h = int(size * 1.42)  # Nastaleeq tall glyphs
    block_h = line_h * (len(lines) - 1)
    y0 = SIZE // 2 - block_h // 2 + 40
    for i, ln in enumerate(lines):
        d.text((SIZE // 2, y0 + i * line_h), ln, font=font, fill=pal["body"],
               anchor="ma", direction="rtl")

    # bottom divider + attribution
    y_div = y0 + block_h + int(line_h * 0.75)
    if attribution:
        _divider(ovo, SIZE // 2, y_div, half=90, rgb=pal["gold"], accent=pal.get("emerald"))
        attr_font = _urdu_font(max(34, size - 18))
        d.text((SIZE // 2, y_div + 66), attribution.strip(), font=attr_font,
               fill=pal["gold"], anchor="ma", direction="rtl")
    else:
        _divider(ovo, SIZE // 2, y_div, half=90, rgb=pal["gold"], accent=pal.get("emerald"))

    im = Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")

    output_path = output_path or default_output_path(niche, base_image_path)
    outdir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(outdir, exist_ok=True)
    if output_path.lower().endswith((".jpg", ".jpeg")):
        im.save(output_path, "JPEG", quality=92)
    else:
        im.save(output_path, "PNG")
    return output_path


def list_overlays(niche):
    """List final overlay cards for a niche (filenames only)."""
    _guard(niche)
    outdir = os.path.join(_HERE, "workspace", "niches", niche, "output")
    if not os.path.isdir(outdir):
        return []
    return sorted(
        f for f in os.listdir(outdir)
        if f.lower().endswith((".png", ".jpg", ".jpeg")) and "-final" in f
    )


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 4:
        print("usage: overlay.py <base_image> <niche> <line1> [line2 ...] [--attr TEXT] [--out PATH]")
        sys.exit(1)
    args = sys.argv[1:]
    base, niche = args[0], args[1]
    rest = args[2:]
    attr = None
    out = None
    if "--attr" in rest:
        i = rest.index("--attr")
        attr = rest[i + 1]
        rest = rest[:i] + rest[i + 2:]
    if "--out" in rest:
        i = rest.index("--out")
        out = rest[i + 1]
        rest = rest[:i] + rest[i + 2:]
    print(overlay_urdu(base, niche, rest, output_path=out, attribution=attr))
