from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from astral_shift import ops
from conftest import SECRET


# --- naming -----------------------------------------------------------------

def test_output_path_never_overwrites(tmp_path):
    src = tmp_path / "Page 001.pdf"
    src.write_bytes(b"x")
    assert ops.output_path(src, "", "jpg").name == "Page 001.jpg"
    (tmp_path / "Page 001 Cropped.pdf").write_bytes(b"x")
    assert ops.output_path(src, "Cropped").name == "Page 001 Cropped 2.pdf"


def test_kind_rejects_unknown(tmp_path):
    with pytest.raises(ops.UnsupportedFile):
        ops.kind(tmp_path / "notes.txt")
    assert ops.is_supported(tmp_path / "a.JPEG")


# --- convert ----------------------------------------------------------------

def test_single_page_pdf_to_jpg_keeps_the_name(one_page_pdf):
    [out] = ops.convert(one_page_pdf, "jpg")
    assert out.name == "Single.jpg"
    with Image.open(out) as im:
        assert im.format == "JPEG"
        assert im.width > im.height  # 200x100 page, landscape


def test_multi_page_pdf_gives_one_image_per_page(pdf):
    calls = []
    outs = ops.convert(pdf, "png", progress=lambda i, n: calls.append((i, n)))
    assert [o.name for o in outs] == ["Page 001 p1.png", "Page 001 p2.png"]
    assert calls[-1] == (2, 2)


def test_image_to_pdf_and_back(png):
    [out] = ops.convert(png, "pdf")
    with pymupdf.open(out) as doc:
        assert doc.page_count == 1
    [jpg] = ops.convert(png, "jpg")
    with Image.open(jpg) as im:
        assert im.mode == "RGB"
        assert im.getpixel((5, 5)) == (255, 255, 255)  # transparency flattened on white


def test_targets_exclude_own_format(jpg, pdf):
    assert "jpg" not in ops.targets_for(jpg)
    assert ops.default_target(pdf) == "jpg"
    with pytest.raises(ValueError):
        ops.convert(jpg, "jpg")


# --- compress ---------------------------------------------------------------

def test_compress_jpg_is_smaller(jpg):
    out = ops.compress(jpg, "high")
    assert out.name == "Photo Compressed.jpg"
    assert out.stat().st_size < jpg.stat().st_size


def test_compress_pdf_with_image_is_smaller(tmp_path, jpg):
    big = Image.new("RGB", (2400, 2400))
    big.putdata([((i * 7) % 256, (i * 13) % 256, (i * 3) % 256) for i in range(2400 * 2400)])
    img_path = tmp_path / "big.png"
    big.save(img_path)
    path = tmp_path / "Scan.pdf"
    doc = pymupdf.open()
    doc.new_page(width=595, height=842).insert_image(pymupdf.Rect(0, 0, 595, 842), filename=str(img_path))
    doc.save(path)
    out = ops.compress(path, "medium")
    assert out.stat().st_size < path.stat().st_size * 0.7
    with pymupdf.open(out) as d:
        assert d.page_count == 1


def test_compress_never_grows(tmp_path):
    path = tmp_path / "tiny.png"
    Image.new("RGB", (4, 4), (1, 2, 3)).save(path)
    out = ops.compress(path)
    assert out.stat().st_size <= path.stat().st_size


# --- crop / rotate / edit ---------------------------------------------------

def test_crop_image(jpg):
    out = ops.crop(jpg, (0.25, 0.0, 0.75, 0.5))
    assert out.name == "Photo Cropped.jpg"
    with Image.open(out) as im:
        assert im.size == (200, 100)


def test_crop_pdf_sets_cropbox_on_every_page(pdf):
    out = ops.crop(pdf, (0.0, 0.0, 0.5, 0.5))
    with pymupdf.open(out) as doc:
        for page in doc:
            assert round(page.rect.width) == 298 and round(page.rect.height) == 421
        assert SECRET in doc[0].get_text()  # top-left kept
        assert "keep this line" not in doc[0].get_text(clip=doc[0].rect)


def test_crop_rejects_empty_area(jpg):
    with pytest.raises(ValueError):
        ops.crop(jpg, (0.5, 0.5, 0.5, 0.9))


def test_rotate_image_and_pdf(jpg, pdf):
    with Image.open(ops.rotate(jpg, 90)) as im:
        assert im.size == (200, 400)
    with pymupdf.open(ops.rotate(pdf, 90)) as doc:
        assert all(p.rotation == 90 for p in doc)


def test_edit_adjustments(png):
    out = ops.edit(png, ops.Adjustments(scale=0.5, grayscale=True, flip_h=True))
    with Image.open(out) as im:
        assert im.size == (150, 150)
        r, g, b, a = im.getpixel((75, 75))
        assert r == g == b and a == 255
        assert im.getpixel((2, 2))[3] == 0  # alpha kept


# --- background -------------------------------------------------------------

def test_add_background_ratio_and_padding(jpg):
    out = ops.add_background(jpg, ops.Background(ratio="1:1", padding=0.1, shadow=0.6))
    assert out.name == "Photo with Background.png"
    with Image.open(out) as im:
        assert im.width == im.height
        corner = im.getpixel((0, 0))
        assert corner[0] > 200  # sunset gradient starts red-orange


def test_add_background_from_pdf(one_page_pdf):
    with Image.open(ops.add_background(one_page_pdf)) as im:
        assert im.width > 200


# --- redact -----------------------------------------------------------------

def test_redact_pdf_removes_the_text(pdf):
    # SECRET sits at x 72..~260, baseline y 100 on a 595x842 page.
    box = (60 / 595, 70 / 842, 300 / 595, 110 / 842)
    out = ops.redact(pdf, {0: [box]})
    with pymupdf.open(out) as doc:
        assert SECRET not in doc[0].get_text()
        assert "keep this line" in doc[0].get_text()
        assert SECRET in doc[1].get_text()  # only page 1 was marked


def test_redact_rotated_pdf_hits_what_the_user_saw(pdf, tmp_path):
    with pymupdf.open(pdf) as doc:
        for p in doc:
            p.set_rotation(90)
        rotated = tmp_path / "Rotated.pdf"
        doc.save(rotated)
    with pymupdf.open(rotated) as doc:
        page = doc[0]
        hit = page.search_for(SECRET)[0] * page.rotation_matrix  # search is unrotated; UI is visible space
        r = page.rect
        box = ((hit.x0 - 2) / r.width, (hit.y0 - 2) / r.height, (hit.x1 + 2) / r.width, (hit.y1 + 2) / r.height)
    out = ops.redact(rotated, {0: [box]})
    with pymupdf.open(out) as doc:
        assert SECRET not in doc[0].get_text()


def test_redact_image_blacks_out(png):
    out = ops.redact(png, {0: [(0.4, 0.4, 0.6, 0.6)]})
    with Image.open(out) as im:
        assert im.getpixel((150, 150))[:3] == (0, 0, 0)


def test_redact_nothing_is_an_error(png):
    with pytest.raises(ValueError):
        ops.redact(png, {0: []})


# --- annotate ---------------------------------------------------------------

def test_annotate_image(png):
    marks = [
        ops.Mark("rect", [(0.1, 0.1), (0.9, 0.9)], color=(0, 255, 0), width=0.02),
        ops.Mark("text", [(0.3, 0.4)], text="Hi", color=(0, 0, 255)),
        ops.Mark("arrow", [(0.1, 0.9), (0.5, 0.5)]),
        ops.Mark("pen", [(0.2, 0.2), (0.3, 0.25), (0.4, 0.2)]),
        ops.Mark("highlight", [(0.2, 0.7), (0.8, 0.7)], color=(255, 230, 0)),
    ]
    out = ops.annotate(png, {0: marks})
    with Image.open(out) as im:
        assert im.getpixel((31, 150))[:3] == (0, 255, 0)


def test_annotate_pdf_adds_text_and_keeps_pages(pdf):
    out = ops.annotate(pdf, {1: [ops.Mark("text", [(0.1, 0.5)], text="Approved"),
                                 ops.Mark("rect", [(0.1, 0.1), (0.2, 0.2)])]})
    with pymupdf.open(out) as doc:
        assert doc.page_count == 2
        assert "Approved" in doc[1].get_text()
        assert "Approved" not in doc[0].get_text()


# --- metadata ---------------------------------------------------------------

def test_read_and_strip_pdf_metadata(pdf):
    meta = ops.read_metadata(pdf)
    assert meta["Author"] == "Jane Doe" and meta["Pages"] == "2"
    out = ops.strip_metadata(pdf)
    assert out.name == "Page 001 Clean.pdf"
    clean = ops.read_metadata(out)
    assert "Author" not in clean and "Title" not in clean


def test_read_and_strip_image_metadata(jpg):
    assert ops.read_metadata(jpg)["Artist"] == "Jane Doe"
    out = ops.strip_metadata(jpg)
    meta = ops.read_metadata(out)
    assert "Artist" not in meta and "Software" not in meta
    with Image.open(out) as im:
        assert im.size == (400, 200)


def test_crop_rotated_pdf_keeps_what_the_user_saw(pdf, tmp_path):
    with pymupdf.open(pdf) as doc:
        doc[0].set_rotation(90)
        rotated = tmp_path / "Rotated.pdf"
        doc.save(rotated)
    with pymupdf.open(rotated) as doc:
        page = doc[0]
        hit = page.search_for(SECRET)[0] * page.rotation_matrix
        r = page.rect
        box = ((hit.x0 - 4) / r.width, (hit.y0 - 4) / r.height, (hit.x1 + 4) / r.width, (hit.y1 + 4) / r.height)
    out = ops.crop(rotated, box)
    with pymupdf.open(out) as doc:
        page = doc[0]
        visible = page.rect * page.derotation_matrix  # text extraction works unrotated
        assert SECRET in page.get_text(clip=visible)
        assert "keep this line" not in page.get_text(clip=visible)
        assert page.rect.height > page.rect.width  # the SECRET line runs vertically once rotated


def test_annotate_rotated_pdf_lands_where_drawn(pdf, tmp_path):
    with pymupdf.open(pdf) as doc:
        doc[0].set_rotation(90)
        rotated = tmp_path / "Rotated.pdf"
        doc.save(rotated)
    out = ops.annotate(rotated, {0: [ops.Mark("rect", [(0.05, 0.05), (0.15, 0.15)], color=(0, 200, 0), width=0.01)]})
    with pymupdf.open(out) as doc:
        page = doc[0]
        pix = page.get_pixmap(dpi=72)
        x, y = round(0.05 * pix.width), round(0.10 * pix.height)
        found = any(pix.pixel(x + dx, y)[1] > 150 and pix.pixel(x + dx, y)[0] < 80 for dx in range(-3, 4))
        assert found
