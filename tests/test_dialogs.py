import pymupdf
import pytest
from PIL import Image
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtWidgets import QDialog

from astral_shift import ops
from astral_shift.gui import dialogs as D


def open_(qtbot, cls, path):
    d = cls(path)
    qtbot.addWidget(d)
    d.show()
    return d


def run_job(d):
    assert d.result() == QDialog.DialogCode.Accepted and d.job
    return d.job()


def test_crop_dialog(qtbot, pdf, jpg):
    d = open_(qtbot, D.CropDialog, pdf)
    assert "every page" in d.size_label.text() and "pt" in d.size_label.text()
    d.ratio_group.button(1).click()  # 1:1
    assert abs(d.canvas.crop_pixels()[0] - d.canvas.crop_pixels()[1]) <= 2
    d._reset()
    assert d.canvas.crop == QRectF(0, 0, 1, 1)
    d.canvas.crop = QRectF(0, 0, 0.5, 0.5)
    d._apply()
    [out] = run_job(d)
    assert out.name == "Page 001 Cropped.pdf"

    d = open_(qtbot, D.CropDialog, jpg)
    assert d.size_label.text() == "W 400  H 200 px"


def test_background_dialog(qtbot, jpg):
    d = open_(qtbot, D.BackgroundDialog, jpg)
    d.swatch_group.button(2).click()
    d.padding.setValue(30)
    d.corners.setValue(10)
    d.shadow.setValue(0)
    d.ratio_group.button(1).click()  # 1:1
    assert d._labels["Padding"][0].text() == "30%"
    qtbot.waitUntil(lambda: not d._timer.isActive())
    assert d.preview.pixmap() is not None
    bg = d._current()
    assert bg.ratio == "1:1" and bg.padding == 0.3 and bg.colors == list(ops.PRESETS.values())[2]
    d.resize(700, 760)
    d._reset()
    assert d._current().ratio == "auto"
    d._apply()
    [out] = run_job(d)
    with Image.open(out) as im:
        assert im.format == "PNG"


def test_redact_dialog_pages(qtbot, pdf):
    d = open_(qtbot, D.RedactDialog, pdf)
    assert not d.go_btn.isEnabled()
    d.canvas.boxes.append(QRectF(0.08, 0.07, 0.45, 0.07))
    d.canvas.changed.emit()
    assert d.go_btn.isEnabled()
    d.next.click()
    assert d.page == 1 and d.canvas.boxes == [] and d.page_label.text() == "Page 2 of 2"
    d.go(5)  # out of range: ignored
    d.prev.click()
    assert len(d.canvas.boxes) == 1
    d._apply()
    [out] = run_job(d)
    with pymupdf.open(out) as doc:
        assert "SECRET" not in doc[0].get_text() and "SECRET" in doc[1].get_text()


def test_redact_dialog_single_image_hides_nav(qtbot, png):
    d = open_(qtbot, D.RedactDialog, png)
    assert d.prev.isHidden() and d.next.isHidden()


def test_annotate_dialog(qtbot, pdf, monkeypatch):
    d = open_(qtbot, D.AnnotateDialog, pdf)
    d.tool_group.button(2).click()
    assert d.canvas.tool == "rect"
    d.color_group.button(4).click()
    assert d.canvas.color == D.AnnotateDialog.COLORS[4]
    monkeypatch.setattr(D.QInputDialog, "getText", lambda *a, **k: ("  Approved ", True))
    d._add_text(QPointF(0.1, 0.5))
    monkeypatch.setattr(D.QInputDialog, "getText", lambda *a, **k: ("", True))
    d._add_text(QPointF(0.1, 0.6))  # empty text is ignored
    assert [m.text for m in d.canvas.marks] == ["Approved"]
    assert d.go_btn.isEnabled()
    d.next.click()
    assert d.canvas.marks == [] and d.go_btn.isEnabled()  # page 1's marks still count
    d.prev.click()
    d._apply()
    [out] = run_job(d)
    with pymupdf.open(out) as doc:
        assert "Approved" in doc[0].get_text()


def test_edit_dialog_image(qtbot, png):
    d = open_(qtbot, D.EditDialog, png)
    buttons = {b.text().strip(): b for b in d.findChildren(D.QPushButton)}
    buttons["Rotate"].click()
    buttons["Flip H"].click()
    buttons["Flip V"].click()
    d.sliders["scale"].setValue(50)
    d.sliders["brightness"].setValue(120)
    d.gray.setChecked(True)
    assert d.adj.rotate == 90 and d.adj.flip_h and d.adj.flip_v and d.adj.scale == 0.5 and d.adj.grayscale
    d.resize(640, 720)
    d._reset()
    assert d.adj == ops.Adjustments() and d.sliders["scale"].value() == 100
    d.sliders["scale"].setValue(50)
    d._apply()
    [out] = run_job(d)
    with Image.open(out) as im:
        assert im.size == (150, 150)


def test_edit_dialog_pdf_only_rotates(qtbot, pdf):
    d = open_(qtbot, D.EditDialog, pdf)
    buttons = {b.text().strip(): b for b in d.findChildren(D.QPushButton)}
    assert not buttons["Flip H"].isEnabled()
    buttons["Rotate"].click()
    d._apply()
    [out] = run_job(d)
    with pymupdf.open(out) as doc:
        assert doc[0].rotation == 90


def test_metadata_dialog(qtbot, jpg):
    d = open_(qtbot, D.MetadataDialog, jpg)
    buttons = {b.text(): b for b in d.findChildren(D.QPushButton)}
    buttons["Save Clean Copy"].click()
    [out] = run_job(d)
    assert "Artist" not in ops.read_metadata(out)
    buttons["Cancel"].click()


def test_row_helper_accepts_layouts():
    inner = D.QHBoxLayout()
    row = D._row(inner, None)
    assert row.count() == 2


def test_merge_dialog_reorders(qtbot, pdf, png, one_page_pdf):
    d = D.MergeDialog([pdf, png, one_page_pdf])
    qtbot.addWidget(d)
    d.list.setCurrentRow(0)
    d._move(1)
    assert [p.name for p in d.ordered()] == ["Logo.png", "Page 001.pdf", "Single.pdf"]
    d._move(5)  # out of range: nothing
    d.list.setCurrentRow(0)
    d._move(-1)
    assert d.ordered()[0].name == "Logo.png"
    buttons = {b.text(): b for b in d.findChildren(D.QPushButton)}
    buttons["Move Down"].click()
    buttons["Move Up"].click()
    buttons["Merge"].click()
    [out] = run_job(d)
    with pymupdf.open(out) as doc:
        assert doc.page_count == 4


def test_edit_dialog_splits_pdfs(qtbot, pdf, one_page_pdf):
    d = open_(qtbot, D.EditDialog, pdf)
    assert d.split_btn.isEnabled()
    d.split_btn.click()
    assert [p.name for p in run_job(d)] == ["Page 001 p1.pdf", "Page 001 p2.pdf"]
    single = open_(qtbot, D.EditDialog, one_page_pdf)
    assert not single.split_btn.isEnabled()
