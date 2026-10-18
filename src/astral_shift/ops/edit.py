"""Crop, rotate and basic image adjustments.

Rectangles are normalised ``(x0, y0, x1, y1)`` in 0..1 of the page/image,
so the UI never has to know the real pixel or point size.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf
from PIL import Image, ImageEnhance, ImageOps

from .files import kind, output_path
from .convert import save_image

Rect = tuple[float, float, float, float]


def _clamp_rect(rect: Rect) -> Rect:
    x0, y0, x1, y1 = (min(max(v, 0.0), 1.0) for v in rect)
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    if x1 - x0 < 1e-3 or y1 - y0 < 1e-3:
        raise ValueError("Crop area is empty")
    return x0, y0, x1, y1


def crop(path: Path, rect: Rect) -> Path:
    """Crop an image, or set the crop box of every page of a PDF."""
    path = Path(path)
    x0, y0, x1, y1 = _clamp_rect(rect)
    dest = output_path(path, "Cropped")
    if kind(path) == "pdf":
        with pymupdf.open(path) as doc:
            for page in doc:
                r = page.rect  # visible (rotated) space, as the user saw it
                box = pymupdf.Rect(
                    r.x0 + x0 * r.width, r.y0 + y0 * r.height,
                    r.x0 + x1 * r.width, r.y0 + y1 * r.height,
                ) * page.derotation_matrix
                box.normalize()
                page.set_cropbox(box + (page.cropbox.x0, page.cropbox.y0, page.cropbox.x0, page.cropbox.y0))
            doc.save(dest, garbage=3, deflate=True)
        return dest
    with Image.open(path) as im:
        im.load()
        w, h = im.size
        box = (round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h))
        return save_image(im.crop(box), dest)


def rotate(path: Path, degrees: int = 90) -> Path:
    """Rotate clockwise by a multiple of 90 degrees."""
    path = Path(path)
    if degrees % 90:
        raise ValueError("Rotation must be a multiple of 90")
    dest = output_path(path, "Rotated")
    if kind(path) == "pdf":
        with pymupdf.open(path) as doc:
            for page in doc:
                page.set_rotation((page.rotation + degrees) % 360)
            doc.save(dest, garbage=3, deflate=True)
        return dest
    with Image.open(path) as im:
        im.load()
        im = ImageOps.exif_transpose(im)
        return save_image(im.rotate(-degrees, expand=True), dest)


@dataclass
class Adjustments:
    rotate: int = 0  # clockwise, multiple of 90
    flip_h: bool = False
    flip_v: bool = False
    scale: float = 1.0  # 0.1 .. 4
    brightness: float = 1.0
    contrast: float = 1.0
    saturation: float = 1.0
    grayscale: bool = False


def apply_adjustments(im: Image.Image, a: Adjustments) -> Image.Image:
    im = ImageOps.exif_transpose(im)
    if a.rotate % 360:
        im = im.rotate(-a.rotate, expand=True)
    if a.flip_h:
        im = ImageOps.mirror(im)
    if a.flip_v:
        im = ImageOps.flip(im)
    if a.scale != 1.0:
        w, h = im.size
        im = im.resize((max(1, round(w * a.scale)), max(1, round(h * a.scale))), Image.Resampling.LANCZOS)
    alpha = im.getchannel("A") if im.mode == "RGBA" else None
    rgb = im.convert("RGB")
    if a.brightness != 1.0:
        rgb = ImageEnhance.Brightness(rgb).enhance(a.brightness)
    if a.contrast != 1.0:
        rgb = ImageEnhance.Contrast(rgb).enhance(a.contrast)
    if a.saturation != 1.0:
        rgb = ImageEnhance.Color(rgb).enhance(a.saturation)
    if a.grayscale:
        rgb = ImageOps.grayscale(rgb).convert("RGB")
    if alpha is not None:
        rgb.putalpha(alpha)
    return rgb


def edit(path: Path, adj: Adjustments) -> Path:
    """Apply adjustments. PDFs support rotation only (pages stay vector)."""
    path = Path(path)
    dest = output_path(path, "Edited")
    if kind(path) == "pdf":
        with pymupdf.open(path) as doc:
            for page in doc:
                page.set_rotation((page.rotation + adj.rotate) % 360)
            doc.save(dest, garbage=3, deflate=True)
        return dest
    with Image.open(path) as im:
        im.load()
        return save_image(apply_adjustments(im, adj), dest)
