"""Edge cases and less common formats, so every branch of ops/ runs."""
import pymupdf
import pytest
from PIL import ExifTags, Image

from astral_shift import ops
from astral_shift.ops import markup


def test_convert_aliases_and_progress(png, jpg):
    calls = []
    [out] = ops.convert(jpg, ".JPEG".lower().replace("jpeg", "png"), progress=lambda i, n: calls.append((i, n)))
    assert out.suffix == ".png" and calls == [(1, 1)]
    with pytest.raises(ValueError):
        ops.convert(jpg, "jpeg")  # jpeg means jpg, which is the file's own format
    [webp] = ops.convert(png, "webp")
    assert webp.suffix == ".webp"
    [pdf] = ops.convert(png, None)  # images default to PDF
    assert pdf.suffix == ".pdf"


def test_targets_for_jpeg_extension(tmp_path):
    p = tmp_path / "a.jpeg"
    Image.new("RGB", (4, 4)).save(p, "JPEG")
    assert "jpg" not in ops.targets_for(p)


def test_first_page_image_of_an_image(png):
    assert ops.first_page_image(png).size == (300, 300)


def test_flatten_palette_with_transparency():
    from astral_shift.ops.convert import flatten
    im = Image.new("P", (2, 2))
    im.info["transparency"] = 0
    assert flatten(im).mode == "RGB"
    assert flatten(Image.new("L", (2, 2))).mode == "RGB"


@pytest.mark.parametrize("ext, fmt", [("webp", "WEBP"), ("bmp", "BMP"), ("gif", "GIF")])
def test_compress_other_formats(tmp_path, ext, fmt):
    p = tmp_path / f"pic.{ext}"
    im = Image.new("RGB", (200, 200))
    im.putdata([((i * 7) % 256, (i * 3) % 256, i % 256) for i in range(200 * 200)])
    im.save(p, fmt)
    out = ops.compress(p, "low")
    assert out.exists() and out.stat().st_size <= p.stat().st_size


def test_compress_png_without_alpha(tmp_path):
    p = tmp_path / "flat.png"
    im = Image.new("RGB", (300, 300))
    im.putdata([((i * 7) % 256, (i * 3) % 256, i % 256) for i in range(300 * 300)])
    im.save(p)
    assert ops.compress(p, "high").stat().st_size < p.stat().st_size


def test_background_without_shadow_on_transparent_png(png):
    with Image.open(ops.add_background(png, ops.Background(shadow=0, ratio="9:16"))) as im:
        assert im.height > im.width
    with Image.open(ops.add_background(png, ops.Background(ratio="16:9"))) as im:
        assert abs(im.width / im.height - 16 / 9) < 0.01


def test_rotate_rejects_odd_angles(jpg):
    with pytest.raises(ValueError):
        ops.rotate(jpg, 45)


def test_edit_every_adjustment(jpg, pdf):
    adj = ops.Adjustments(rotate=90, flip_h=True, flip_v=True, scale=0.5, brightness=1.2, contrast=0.8, saturation=0.5)
    with Image.open(ops.edit(jpg, adj)) as im:
        assert im.size == (100, 200)
    with pymupdf.open(ops.edit(pdf, ops.Adjustments(rotate=270))) as doc:
        assert doc[0].rotation == 270


def test_is_supported_false(tmp_path):
    assert not ops.is_supported(tmp_path / "x.docx")


def test_redact_skips_pages_without_boxes(pdf):
    out = ops.redact(pdf, {0: [], 1: [(0, 0, 1, 0.2)]})
    with pymupdf.open(out) as doc:
        assert "SECRET" in doc[0].get_text() and "SECRET" not in doc[1].get_text()


def test_font_fallback(monkeypatch):
    real = markup.ImageFont.truetype

    def no_system_fonts(font, *a, **k):
        if isinstance(font, str):
            raise OSError
        return real(font, *a, **k)  # Pillow's bundled default still loads
    monkeypatch.setattr(markup.ImageFont, "truetype", no_system_fonts)
    assert markup._font(12) is not None


def test_annotate_pdf_every_kind_and_ignores_incomplete(pdf):
    marks = [
        ops.Mark("pen", [(0.1, 0.1), (0.2, 0.2), (0.3, 0.1)]),
        ops.Mark("highlight", [(0.1, 0.3), (0.5, 0.3)], color=(255, 230, 0)),
        ops.Mark("rect", [(0.6, 0.6), (0.5, 0.5)]),
        ops.Mark("arrow", [(0.1, 0.9), (0.4, 0.6)]),
        ops.Mark("text", [(0.5, 0.8)], text="OK"),
        ops.Mark("pen", [(0.1, 0.1)]),  # a single point draws nothing
        ops.Mark("text", [(0.5, 0.8)], text=""),
    ]
    out = ops.annotate(pdf, {0: marks, 1: []})
    with pymupdf.open(out) as doc:
        assert "OK" in doc[0].get_text()
        assert len(doc[0].get_drawings()) > len(pymupdf.open(pdf)[0].get_drawings())
    with pytest.raises(ValueError):
        ops.annotate(pdf, {0: []})


def test_pdf_xmp_is_reported(pdf, tmp_path):
    with pymupdf.open(pdf) as doc:
        doc.set_xml_metadata("<x:xmpmeta xmlns:x='adobe:ns:meta/'></x:xmpmeta>")
        p = tmp_path / "xmp.pdf"
        doc.save(p)
    assert ops.read_metadata(p)["XMP"] == "present"
    clean = ops.strip_metadata(p)
    assert "XMP" not in ops.read_metadata(clean)


def test_image_metadata_bytes_gps_and_info(tmp_path):
    p = tmp_path / "gps.jpg"
    exif = Image.Exif()
    exif[0x010E] = "desc"
    exif[0x9C9B] = b"t\x00i\x00"  # XPTitle, bytes
    exif.get_ifd(ExifTags.IFD.Exif)[0x9286] = b"ASCII\x00\x00\x00hello"  # UserComment
    exif.get_ifd(ExifTags.IFD.GPSInfo)[1] = "N"
    Image.new("RGB", (10, 10)).save(p, "JPEG", exif=exif, dpi=(300, 300), comment=b"hi")
    meta = ops.read_metadata(p)
    assert meta["GPSLatitudeRef"] == "N"
    assert meta["UserComment"].startswith("<")
    assert meta["XPTitle"].startswith("<")
    assert "comment" in meta


def test_png_text_and_dpi_metadata(tmp_path):
    from PIL import PngImagePlugin
    p = tmp_path / "t.png"
    info = PngImagePlugin.PngInfo()
    info.add_text("Software", "Painter")
    info.add_text("XML:com.adobe.xmp", "<x/>")
    Image.new("RGB", (5, 5)).save(p, pnginfo=info, dpi=(144, 144))
    meta = ops.read_metadata(p)
    assert meta["Software"] == "Painter" and meta["XML:com.adobe.xmp"] == "present" and "dpi" in meta


def test_strip_palette_png_keeps_transparency(tmp_path):
    p = tmp_path / "pal.png"
    im = Image.new("P", (10, 10), 1)
    im.putpalette([0, 0, 0, 255, 0, 0] + [0] * 762)
    im.save(p, transparency=0)
    out = ops.strip_metadata(p)
    with Image.open(out) as o:
        assert "transparency" in o.info
