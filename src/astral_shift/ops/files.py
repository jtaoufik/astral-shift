"""File kinds and output naming.

Every action writes a new file next to the original and never overwrites
anything: ``Page 001.pdf`` -> ``Page 001.jpg``, ``Page 001 Cropped.jpg``,
``Page 001 Cropped 2.jpg`` if that one exists already.
"""
from __future__ import annotations

from pathlib import Path

PDF_EXTS = {".pdf"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}

# Formats Pillow writes, keyed by the extension we produce.
PIL_FORMAT = {
    "jpg": "JPEG",
    "jpeg": "JPEG",
    "png": "PNG",
    "webp": "WEBP",
    "bmp": "BMP",
    "tiff": "TIFF",
    "tif": "TIFF",
    "gif": "GIF",
}


class UnsupportedFile(ValueError):
    pass


def kind(path: Path) -> str:
    """Return ``"pdf"`` or ``"image"``; raise for anything else."""
    ext = Path(path).suffix.lower()
    if ext in PDF_EXTS:
        return "pdf"
    if ext in IMAGE_EXTS:
        return "image"
    raise UnsupportedFile(f"Unsupported file type: {Path(path).name}")


def is_supported(path: Path) -> bool:
    try:
        kind(path)
        return True
    except UnsupportedFile:
        return False


def output_path(src: Path, suffix: str = "", ext: str | None = None) -> Path:
    """Next free path beside ``src``: ``<stem>[ <suffix>][ N].<ext>``."""
    src = Path(src)
    ext = (ext or src.suffix.lstrip(".")).lower()
    stem = f"{src.stem} {suffix}".rstrip() if suffix else src.stem
    candidate = src.with_name(f"{stem}.{ext}")
    n = 2
    while candidate.exists():
        candidate = src.with_name(f"{stem} {n}.{ext}")
        n += 1
    return candidate
