"""Convert between PDF and image formats."""
from __future__ import annotations

from pathlib import Path

import pymupdf
from PIL import Image

from .files import PIL_FORMAT, kind, output_path

PDF_TARGETS = ["jpg", "png", "webp"]
IMAGE_TARGETS = ["pdf", "png", "jpg", "webp"]


def targets_for(path: Path) -> list[str]:
    """Formats a file can be converted to, the default first."""
    if kind(path) == "pdf":
        return list(PDF_TARGETS)
    own = Path(path).suffix.lower().lstrip(".")
    own = "jpg" if own == "jpeg" else own
    return [t for t in IMAGE_TARGETS if t != own]


def default_target(path: Path) -> str:
    return targets_for(path)[0]


def render_page(doc: pymupdf.Document, index: int, dpi: int = 200) -> Image.Image:
    """Render one PDF page to an RGB Pillow image."""
    pix = doc[index].get_pixmap(dpi=dpi, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def first_page_image(path: Path, dpi: int = 200) -> Image.Image:
    """The file as one image: an image as-is, a PDF as its first page."""
    if kind(path) == "pdf":
        with pymupdf.open(path) as doc:
            return render_page(doc, 0, dpi)
    with Image.open(path) as im:
        im.load()
        return im.copy()


def save_image(im: Image.Image, dest: Path, quality: int = 92) -> Path:
    fmt = PIL_FORMAT[dest.suffix.lower().lstrip(".")]
    if fmt == "JPEG" and im.mode not in ("RGB", "L"):
        im = flatten(im)
    params = {"quality": quality} if fmt in ("JPEG", "WEBP") else {}
    if fmt == "PNG":
        params["optimize"] = True
    im.save(dest, fmt, **params)
    return dest


def flatten(im: Image.Image, color=(255, 255, 255)) -> Image.Image:
    """Drop transparency onto a solid background."""
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, color)
        bg.paste(im, mask=im.split()[-1])
        return bg
    return im.convert("RGB")


def convert(path: Path, target: str | None = None, dpi: int = 200, progress=None) -> list[Path]:
    """Convert ``path`` to ``target`` and return the files written.

    A multi-page PDF gives one image per page (``Name p1.jpg``, ...).
    """
    path = Path(path)
    target = (target or default_target(path)).lower().lstrip(".")
    if target == "jpeg":
        target = "jpg"
    if target not in targets_for(path):
        raise ValueError(f"Cannot convert {path.name} to {target.upper()}")

    if kind(path) == "pdf":
        out: list[Path] = []
        with pymupdf.open(path) as doc:
            total = doc.page_count
            for i in range(total):
                suffix = f"p{i + 1}" if total > 1 else ""
                dest = output_path(path, suffix, target)
                save_image(render_page(doc, i, dpi), dest)
                out.append(dest)
                if progress:
                    progress(i + 1, total)
        return out

    with Image.open(path) as im:
        im.load()
        if target == "pdf":
            dest = output_path(path, "", "pdf")
            flatten(im).save(dest, "PDF", resolution=float(im.info.get("dpi", (72, 72))[0] or 72))
        else:
            dest = save_image(im.copy(), output_path(path, "", target))
    if progress:
        progress(1, 1)
    return [dest]
