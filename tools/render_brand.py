"""Deterministic Pillow renderer for the TV Inputs brand kit.

Writes the eight images Home Assistant serves straight from
``custom_components/tv_inputs/brand/`` (no brands-repo submission needed):

    icon.png        256x256      dark_icon.png        256x256
    icon@2x.png     512x512      dark_icon@2x.png     512x512
    logo.png        864x256      dark_logo.png        864x256
    logo@2x.png     1728x512     dark_logo@2x.png     1728x512

The mark: a plain TV outline (frame, neck, base) with two arrows on its screen,
one pointing in and one pointing back - the "switch the source" cue. Flat
colour only, no gradients. ``../icon.svg`` is the same mark as hand-authored
vector art; this script does not read it, so keep the numbers below in sync.

Light variant ("icon", "logo"): indigo plate, white TV, amber return arrow.
Dark variant ("dark_icon", "dark_logo"): pale plate, indigo TV, orange arrow,
so it keeps its contrast on the dark Home Assistant header.

Pillow only, 4x supersampling, no randomness: re-running produces
byte-identical PNGs.

Usage: python3 tools/render_brand.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
BRAND_DIR = REPO_ROOT / "custom_components" / "tv_inputs" / "brand"

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def load_font(size: int) -> ImageFont.FreeTypeFont:
    """Liberation Sans Bold, then DejaVu Bold, then Pillow's default font."""
    for path in FONT_CANDIDATES:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


# ---------------------------------------------------------------------------
# Geometry, in a 256x256 reference space (identical numbers to ../icon.svg).
# Capsules are ((x0, y0), (x1, y1), radius): a round-capped stroke.
# ---------------------------------------------------------------------------

PLATE_RX = 56.0

FRAME_OUTER = (36.0, 40.0, 220.0, 184.0, 24.0)  # x0, y0, x1, y1, corner radius
FRAME_INNER = (50.0, 54.0, 206.0, 170.0, 10.0)  # the screen cut-out (plate shows through)
NECK = ((128.0, 184.0), (128.0, 204.0), 8.0)
BASE = ((92.0, 208.0), (164.0, 208.0), 7.0)

# Arrows: shaft capsule + triangle head (round-joined by a 2-unit outline).
ARROW_IN_SHAFT = ((82.0, 90.0), (146.0, 90.0), 6.5)
ARROW_IN_HEAD = ((142.0, 74.0), (176.0, 90.0), (142.0, 106.0))
ARROW_BACK_SHAFT = ((110.0, 134.0), (174.0, 134.0), 6.5)
ARROW_BACK_HEAD = ((114.0, 118.0), (80.0, 134.0), (114.0, 150.0))
HEAD_OUTLINE = 2.0  # grows the head so its corners are slightly rounded, like the SVG

# ---------------------------------------------------------------------------
# Palettes
# ---------------------------------------------------------------------------

LIGHT_VARIANT = {
    "plate": (0x43, 0x38, 0xE8),
    "mark": (0xFF, 0xFF, 0xFF),
    "accent": (0xFF, 0xC9, 0x3C),
}
DARK_VARIANT = {
    "plate": (0xEE, 0xF0, 0xFF),
    "mark": (0x43, 0x38, 0xE8),
    "accent": (0xF5, 0x7C, 0x00),
}

WORDMARK_ON_LIGHT_BG = (0x1B, 0x16, 0x5E)  # logo.png
SUBMARK_ON_LIGHT_BG = (0x43, 0x38, 0xE8)
WORDMARK_ON_DARK_BG = (0xF3, 0xF4, 0xFF)  # dark_logo.png
SUBMARK_ON_DARK_BG = (0xA9, 0xA4, 0xFF)

SS = 4  # supersampling factor


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------


def _capsule(draw, capsule, k, fill):
    (x0, y0), (x1, y1), r = capsule
    dx, dy = x1 - x0, y1 - y0
    length = (dx * dx + dy * dy) ** 0.5
    nx, ny = -dy / length * r, dx / length * r
    draw.polygon(
        [((x0 + nx) * k, (y0 + ny) * k), ((x1 + nx) * k, (y1 + ny) * k),
         ((x1 - nx) * k, (y1 - ny) * k), ((x0 - nx) * k, (y0 - ny) * k)],
        fill=fill,
    )
    for cx, cy in ((x0, y0), (x1, y1)):
        draw.ellipse([(cx - r) * k, (cy - r) * k, (cx + r) * k, (cy + r) * k], fill=fill)


def _rrect(draw, box, k, fill):
    x0, y0, x1, y1, r = box
    draw.rounded_rectangle([x0 * k, y0 * k, x1 * k, y1 * k], radius=r * k, fill=fill)


def _head(draw, pts, k, fill):
    """Triangle arrow head with slightly rounded corners."""
    draw.polygon([(x * k, y * k) for x, y in pts], fill=fill, outline=fill, width=round(HEAD_OUTLINE * 2 * k))


def render_mark(size, palette):
    """(size, size) RGBA icon: flat rounded plate with the TV + arrows mark."""
    big = size * SS
    k = big / 256.0
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)

    plate = palette["plate"] + (255,)
    mark = palette["mark"] + (255,)
    accent = palette["accent"] + (255,)

    d.rounded_rectangle([0, 0, big - 1, big - 1], radius=PLATE_RX * k, fill=plate)

    _rrect(d, FRAME_OUTER, k, mark)
    _rrect(d, FRAME_INNER, k, plate)
    _capsule(d, NECK, k, mark)
    _capsule(d, BASE, k, mark)

    _capsule(d, ARROW_IN_SHAFT, k, mark)
    _head(d, ARROW_IN_HEAD, k, mark)
    _capsule(d, ARROW_BACK_SHAFT, k, accent)
    _head(d, ARROW_BACK_HEAD, k, accent)

    return canvas.resize((size, size), Image.LANCZOS)


# ---------------------------------------------------------------------------
# Wordmark lockup
# ---------------------------------------------------------------------------

LOGO_ASPECT = 864 / 256  # width / height (about 3.4x)
LOGO_MARK_FRAC = 0.86  # mark size as a fraction of canvas height
LOGO_LEFT_FRAC = 0.05
LOGO_GAP_FRAC = 0.09
LOGO_NAME_FRAC = 0.40  # "TV Inputs" font size / canvas height
LOGO_SUB_FRAC = 0.19  # "Inputs & remote" font size / canvas height
LOGO_TRACK_FRAC = 0.004
LOGO_LINE_GAP_FRAC = 0.09
NAME = "TV Inputs"
SUB = "Source list & remote"


def _tracked_width(draw, text, font, tracking):
    return sum(draw.textlength(ch, font=font) for ch in text) + tracking * (len(text) - 1)


def _draw_tracked(draw, x, y, text, font, fill, tracking):
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking


def render_logo(height, palette, name_rgb, sub_rgb):
    """RGBA lockup: mark on the left, name over tagline on the right,
    transparent background, exactly `height` tall."""
    width = round(height * LOGO_ASPECT)
    mark_size = round(height * LOGO_MARK_FRAC)
    mark = render_mark(mark_size, palette)

    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    left = round(height * LOGO_LEFT_FRAC)
    canvas.alpha_composite(mark, (left, (height - mark_size) // 2))

    name_font = load_font(round(height * LOGO_NAME_FRAC))
    sub_font = load_font(round(height * LOGO_SUB_FRAC))
    tracking = height * LOGO_TRACK_FRAC
    draw = ImageDraw.Draw(canvas)

    # Vertically centre the two-line block on ink bounds, not font ascent.
    n_l, n_t, n_r, n_b = draw.textbbox((0, 0), NAME, font=name_font)
    s_l, s_t, s_r, s_b = draw.textbbox((0, 0), SUB, font=sub_font)
    line_gap = height * LOGO_LINE_GAP_FRAC
    block_h = (n_b - n_t) + line_gap + (s_b - s_t)
    top = (height - block_h) / 2
    text_x = left + mark_size + height * LOGO_GAP_FRAC

    name_w = _tracked_width(draw, NAME, name_font, tracking)
    _draw_tracked(draw, text_x - n_l, top - n_t, NAME, name_font, name_rgb + (255,), tracking)
    sub_y = top + (n_b - n_t) + line_gap
    _draw_tracked(draw, text_x - s_l, sub_y - s_t, SUB, sub_font, sub_rgb + (255,), tracking)

    sub_w = _tracked_width(draw, SUB, sub_font, tracking)
    right_edge = text_x + max(name_w, sub_w)
    assert right_edge <= width - height * 0.03, f"wordmark clipped at height {height}: {right_edge} > {width}"
    return canvas


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _save_pair(master, stem):
    """<stem>@2x.png from the 512-based master, <stem>.png as an exact half."""
    master.save(BRAND_DIR / f"{stem}@2x.png")
    half = (master.width // 2, master.height // 2)
    master.resize(half, Image.LANCZOS).save(BRAND_DIR / f"{stem}.png")


def main():
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    _save_pair(render_mark(512, LIGHT_VARIANT), "icon")
    _save_pair(render_mark(512, DARK_VARIANT), "dark_icon")
    _save_pair(render_logo(512, LIGHT_VARIANT, WORDMARK_ON_LIGHT_BG, SUBMARK_ON_LIGHT_BG), "logo")
    _save_pair(render_logo(512, DARK_VARIANT, WORDMARK_ON_DARK_BG, SUBMARK_ON_DARK_BG), "dark_logo")


if __name__ == "__main__":
    main()
