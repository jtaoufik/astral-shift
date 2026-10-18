import pymupdf
import pytest

from astral_shift import ops


def test_merge_pdfs_and_images_in_order(pdf, one_page_pdf, png, tmp_path):
    out = ops.merge([pdf, png, one_page_pdf])
    assert out.name == "Page 001 Merged.pdf"
    with pymupdf.open(out) as doc:
        assert doc.page_count == 4
        assert "SECRET" in doc[0].get_text() and "hello" in doc[3].get_text()
    dest = tmp_path / "custom.pdf"
    assert ops.merge([png, png], dest) == dest


def test_merge_needs_two(pdf):
    with pytest.raises(ValueError):
        ops.merge([pdf])


def test_split(pdf, one_page_pdf, jpg):
    outs = ops.split(pdf)
    assert [o.name for o in outs] == ["Page 001 p1.pdf", "Page 001 p2.pdf"]
    with pymupdf.open(outs[1]) as d:
        assert d.page_count == 1 and "page 2" in d[0].get_text()
    with pytest.raises(ValueError):
        ops.split(one_page_pdf)
    with pytest.raises(ValueError):
        ops.split(jpg)
