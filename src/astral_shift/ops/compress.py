"""Make PDFs and images smaller."""
from __future__ import annotations

from pathlib import Path

import pymupdf
from PIL import Image

from .convert import flatten
from .files import PIL_FORMAT, kind, output_path

# level -> (pdf image dpi target, jpeg/webp quality)
LEVELS = {
    "low": (200, 85),
    "medium": (150, 72),
    "high": (96, 55),
}


def compress(path: Path, level: str = "medium") -> Path:
    path = Path(path)
    dpi, quality = LEVELS[level]
    dest = output_path(path, "Compressed")

    if kind(path) == "pdf":
        with pymupdf.open(path) as doc:
            doc.rewrite_images(
                dpi_threshold=dpi + 10, dpi_target=dpi, quality=quality,
                lossy=True, lossless=True, bitonal=True, color=True, gray=True,
            )
            doc.subset_fonts()
            doc.save(dest, garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, clean=True)
        return dest

    with Image.open(path) as im:
        im.load()
        fmt = PIL_FORMAT[path.suffix.lower().lstrip(".")]
        if fmt == "JPEG":
            flatten(im).save(dest, "JPEG", quality=quality, optimize=True, progressive=True)
        elif fmt == "WEBP":
            im.save(dest, "WEBP", quality=quality, method=6)
        elif fmt == "PNG":
            colors = {"low": 256, "medium": 256, "high": 128}[level]
            has_alpha = im.mode in ("RGBA", "LA") or "transparency" in im.info
            src = im.convert("RGBA") if has_alpha else im.convert("RGB")
            method = Image.Quantize.FASTOCTREE if has_alpha else Image.Quantize.MEDIANCUT
            src.quantize(colors=colors, method=method).save(dest, "PNG", optimize=True)
        else:
            im.save(dest, fmt)
    # Never hand back a "compressed" file that grew.
    if dest.stat().st_size >= path.stat().st_size:
        dest.write_bytes(path.read_bytes())
    return dest
