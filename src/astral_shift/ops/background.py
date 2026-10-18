"""Put a file on a gradient or solid background, with padding, rounded
corners and a soft shadow. Output is always PNG."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from .convert import first_page_image
from .files import output_path

Color = tuple[int, int, int]

# Gradient presets: (top-left colour, bottom-right colour).
PRESETS: dict[str, tuple[Color, Color]] = {
    "sunset": ((255, 94, 77), (155, 89, 255)),
    "peach": ((255, 179, 138), (255, 107, 107)),
    "ocean": ((46, 196, 255), (61, 82, 255)),
    "mint": ((120, 240, 200), (30, 160, 140)),
    "candy": ((255, 154, 209), (151, 117, 255)),
    "dusk": ((40, 48, 72), (133, 147, 152)),
    "lemon": ((255, 236, 120), (255, 160, 60)),
    "night": ((20, 20, 30), (60, 60, 90)),
}

RATIOS = {"auto": None, "1:1": (1, 1), "16:9": (16, 9), "4:5": (4, 5), "9:16": (9, 16), "4:3": (4, 3)}


@dataclass
class Background:
    colors: tuple[Color, Color] = field(default_factory=lambda: PRESETS["sunset"])
    padding: float = 0.12  # fraction of the longer side of the content
    radius: float = 0.03  # fraction of the longer side of the content
    shadow: float = 0.5  # 0 .. 1
    ratio: str = "auto"


def gradient(size: tuple[int, int], a: Color, b: Color) -> Image.Image:
    """Diagonal linear gradient from top-left ``a`` to bottom-right ``b``."""
    w, h = size
    small = Image.new("RGB", (64, 64))
    px = small.load()
    for y in range(64):
        for x in range(64):
            t = (x + y) / 126
            px[x, y] = tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))
    return small.resize((w, h), Image.Resampling.BICUBIC)


def compose(content: Image.Image, bg: Background) -> Image.Image:
    content = content.convert("RGBA")
    cw, ch = content.size
    longest = max(cw, ch)
    pad = round(longest * bg.padding)
    w, h = cw + 2 * pad, ch + 2 * pad
    ratio = RATIOS.get(bg.ratio)
    if ratio:
        rw, rh = ratio
        if w / h < rw / rh:
            w = round(h * rw / rh)
        else:
            h = round(w * rh / rw)

    canvas = gradient((w, h), *bg.colors).convert("RGBA")
    x, y = (w - cw) // 2, (h - ch) // 2

    radius = round(longest * bg.radius)
    mask = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, cw - 1, ch - 1), radius=radius, fill=255)
    if content.mode == "RGBA":
        mask = Image.composite(content.getchannel("A"), Image.new("L", (cw, ch), 0), mask)

    if bg.shadow > 0:
        blur = max(2, round(longest * 0.03 * bg.shadow))
        shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        offset = round(blur * 0.6)
        shadow_mask = Image.new("L", (w, h), 0)
        shadow_mask.paste(mask, (x, y + offset))
        shadow.putalpha(shadow_mask.point(lambda v: round(v * 0.55 * bg.shadow)))
        canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(blur)))

    canvas.paste(content, (x, y), mask)
    return canvas.convert("RGB")


def add_background(path: Path, bg: Background | None = None) -> Path:
    path = Path(path)
    out = compose(first_page_image(path), bg or Background())
    dest = output_path(path, "with Background", "png")
    out.save(dest, "PNG", optimize=True)
    return dest
