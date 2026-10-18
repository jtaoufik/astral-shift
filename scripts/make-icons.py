#!/usr/bin/env python3
"""Mechanical resize of packaging/icon-source/chatgpt-icon-1024.png into icon.icns, icon.png and
the Linux hicolor sizes. No design work happens here: the artwork comes from ChatGPT."""
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

PK = Path(__file__).resolve().parent.parent / "packaging"
src = Image.open(PK / "icon-source" / "chatgpt-icon-1024.png").convert("RGB")

# The raw render has a white backdrop outside the rounded tile: make it transparent.
rgba = src.convert("RGBA")
mask = Image.new("L", src.size, 255)
for corner in ((0, 0), (src.width - 1, 0), (0, src.height - 1), (src.width - 1, src.height - 1)):
    flood = src.copy()
    ImageDraw.floodfill(flood, corner, (255, 0, 255), thresh=40)
    px, fp = src.load(), flood.load()
    m = mask.load()
    for y in range(src.height):
        for x in range(src.width):
            if fp[x, y] == (255, 0, 255) and px[x, y] != (255, 0, 255):
                m[x, y] = 0
rgba.putalpha(mask.filter(__import__("PIL.ImageFilter", fromlist=["x"]).GaussianBlur(1.2)))
tile = rgba.resize((1024, 1024), Image.LANCZOS)

# macOS: tile inset to 824px on a 1024 canvas (system icon grid).
mac = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
mac.paste(tile.resize((824, 824), Image.LANCZOS), (100, 100))
iconset = PK / "icon.iconset"
shutil.rmtree(iconset, ignore_errors=True)
iconset.mkdir()
for base in (16, 32, 128, 256, 512):
    mac.resize((base, base), Image.LANCZOS).save(iconset / f"icon_{base}x{base}.png")
    mac.resize((base * 2, base * 2), Image.LANCZOS).save(iconset / f"icon_{base}x{base}@2x.png")
if sys.platform == "darwin":
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(PK / "icon.icns")], check=True)
shutil.rmtree(iconset)

# Linux: full tile.
tile.resize((512, 512), Image.LANCZOS).save(PK / "icon.png")
for s in (16, 24, 32, 48, 64, 128, 256, 512):
    d = PK / "hicolor" / f"{s}x{s}" / "apps"
    d.mkdir(parents=True, exist_ok=True)
    tile.resize((s, s), Image.LANCZOS).save(d / "astral-shift.png")
print("ok")
