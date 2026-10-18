import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
import pytest
from PIL import Image

SECRET = "SECRET-4242"


@pytest.fixture
def pdf(tmp_path: Path) -> Path:
    """Two A4 pages with text; page 1 holds SECRET at the top-left."""
    path = tmp_path / "Page 001.pdf"
    doc = pymupdf.open()
    for i in range(2):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), f"{SECRET} page {i + 1}", fontsize=24)
        page.insert_text((72, 700), "keep this line", fontsize=14)
        page.draw_rect(pymupdf.Rect(300, 300, 500, 500), color=(1, 0, 0), fill=(1, 0.8, 0.8))
    doc.set_metadata({"author": "Jane Doe", "title": "Quarterly", "producer": "test"})
    doc.save(path)
    return path


@pytest.fixture
def one_page_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "Single.pdf"
    doc = pymupdf.open()
    doc.new_page(width=200, height=100).insert_text((20, 50), "hello")
    doc.save(path)
    return path


@pytest.fixture
def jpg(tmp_path: Path) -> Path:
    path = tmp_path / "Photo.jpg"
    im = Image.new("RGB", (400, 200))
    for x in range(400):
        for y in range(0, 200, 4):
            im.putpixel((x, y), (x % 256, (x * 3) % 256, 120))
    exif = Image.Exif()
    exif[0x013B] = "Jane Doe"  # Artist
    exif[0x0131] = "CameraSoft 1.0"  # Software
    im.save(path, "JPEG", quality=95, exif=exif)
    return path


@pytest.fixture
def png(tmp_path: Path) -> Path:
    path = tmp_path / "Logo.png"
    im = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
    for x in range(50, 250):
        for y in range(50, 250):
            im.putpixel((x, y), (x % 256, y % 256, 200, 255))
    im.save(path)
    return path
