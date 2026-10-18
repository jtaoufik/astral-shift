import math

import pytest
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRectF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QFocusEvent, QKeyEvent, QMouseEvent

from astral_shift import ops
from astral_shift.gui import icons
from astral_shift.gui import wheel as Wh
from astral_shift.gui.canvas import Document, PageCanvas

C = QPointF(Wh.SIZE / 2, Wh.SIZE / 2)


def mime(*paths):
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return md


def at_wedge(i, r=(Wh.OUTER + Wh.INNER) / 2):
    a = math.radians(i * 45)
    return QPointF(C.x() + r * math.sin(a), C.y() - r * math.cos(a))


def drag_enter(w, md, pos=None):
    e = QDragEnterEvent((pos or C).toPoint(), Qt.DropAction.CopyAction, md, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier)
    w.dragEnterEvent(e)
    return e


def drag_move(w, md, pos):
    e = QDragMoveEvent(pos.toPoint(), Qt.DropAction.CopyAction, md, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier)
    w.dragMoveEvent(e)
    return e


def drop(w, md, pos):
    e = QDropEvent(pos, Qt.DropAction.CopyAction, md, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier)
    w.dropEvent(e)
    return e


def mouse(kind, pos, buttons=Qt.MouseButton.LeftButton):
    t = {"press": QEvent.Type.MouseButtonPress, "move": QEvent.Type.MouseMove, "release": QEvent.Type.MouseButtonRelease}[kind]
    btn = Qt.MouseButton.NoButton if kind == "move" else Qt.MouseButton.LeftButton
    return QMouseEvent(t, QPointF(pos), QPointF(pos), btn, buttons, Qt.KeyboardModifier.NoModifier)


# --- wheel --------------------------------------------------------------------------

def test_hit_test_every_slot():
    assert Wh.hit_test(C, C) == Wh.CENTER
    assert Wh.hit_test(QPointF(0, 0), C) is None
    for i, action in enumerate(Wh.RING):
        assert Wh.hit_test(at_wedge(i), C) == action


def test_drag_hover_and_drop(qtbot, pdf, jpg, tmp_path):
    w = Wh.Wheel()
    qtbot.addWidget(w)
    w.popup(QPoint(5, 5))  # clamped onto the screen
    assert w.isVisible()
    for _ in range(12):
        w._step_fade()
    assert not w._fade.isActive()

    md = mime(pdf, jpg)
    assert drag_enter(w, md).isAccepted()
    e = drag_move(w, md, at_wedge(3))  # convert
    assert e.isAccepted() and w.hover.key == "convert"
    assert w.hint == "Page 001.jpg +1"
    w.grab()  # paints the highlighted wedge and the pill
    drag_move(w, md, at_wedge(3))  # same wedge: no repaint needed
    assert not drag_move(w, md, QPointF(1, 1)).isAccepted()
    w.dragLeaveEvent(None)
    assert w.hover is None and w.hint == ""

    got = []
    w.dropped.connect(lambda key, files: got.append((key, files)))
    drop(w, md, C)
    assert got == [("merge", [pdf, jpg])]  # two files: the centre merges
    assert not w.isVisible()


def test_hint_variants(qtbot, jpg, png):
    w = Wh.Wheel()
    qtbot.addWidget(w)
    assert w._hint_for(Wh.RING[0]) == ""
    w._files = [jpg]
    w.convert_target["image"] = "jpg"  # the file's own format: fall back to the default
    assert w._hint_for(Wh.RING[3]) == "Photo.pdf"
    assert w._hint_for(Wh.RING[0]) == "Photo.jpg"
    assert w._hint_for(None) == ""


def test_rejects_non_files(qtbot, tmp_path):
    w = Wh.Wheel()
    qtbot.addWidget(w)
    assert not drag_enter(w, QMimeData()).isAccepted()
    txt = tmp_path / "a.txt"
    txt.write_text("x")
    assert not drag_enter(w, mime(txt)).isAccepted()
    got = []
    w.dropped.connect(lambda *a: got.append(a))
    drop(w, mime(txt), C)
    assert got == []


def test_dismiss_paths(qtbot):
    w = Wh.Wheel()
    qtbot.addWidget(w)
    gone = []
    w.dismissed.connect(lambda: gone.append(1))
    w.popup(QPoint(400, 400), sticky=True)
    w.drag_released()  # sticky: stays
    qtbot.wait(200)
    assert w.isVisible()
    w.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier))
    assert w.isVisible()
    w.mousePressEvent(mouse("press", C))  # on the wheel: stays
    assert w.isVisible()
    w.mousePressEvent(mouse("press", QPointF(1, 1)))
    assert not w.isVisible() and gone == [1]
    w.dismiss()  # already hidden: no second signal
    assert gone == [1]

    w.popup(QPoint(400, 400), sticky=True)
    w.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert not w.isVisible()
    w.popup(QPoint(400, 400), sticky=True)
    w.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
    assert not w.isVisible()
    w.popup(QPoint(400, 400))
    w.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))  # not sticky: ignore focus
    assert w.isVisible()
    w.drag_released()
    qtbot.waitUntil(lambda: not w.isVisible())


def test_popup_without_screen(qtbot, monkeypatch):
    w = Wh.Wheel()
    qtbot.addWidget(w)
    monkeypatch.setattr(Wh.QGuiApplication, "screenAt", staticmethod(lambda pos: None))
    w.popup(QPoint(1000, 1000))
    assert w.pos() == QPoint(1000 - Wh.SIZE // 2, 1000 - Wh.SIZE // 2)


def test_icons():
    assert not icons.icon("crop").isNull()
    assert b"<svg" in icons.svg("crop")


# --- canvas -------------------------------------------------------------------------------

def test_document_pdf_and_image(qapp, pdf, jpg):
    d = Document(pdf)
    assert d.count == 2 and d.kind == "pdf"
    assert d.page(1) is d.page(1)  # cached
    i = Document(jpg)
    assert i.count == 1 and not i.page(0).isNull()


@pytest.fixture
def canvas(qtbot, jpg):
    def make(mode):
        c = PageCanvas(mode)
        qtbot.addWidget(c)
        c.resize(600, 600)
        assert c.sizeHint().width() == 640
        c.set_image(Document(jpg).page(0))
        return c
    return make


def test_canvas_without_image(qtbot):
    c = PageCanvas("crop")
    qtbot.addWidget(c)
    assert c.page_rect() == QRectF()
    c.grab()


def test_crop_aspect_and_handles(canvas):
    c = canvas("crop")
    c.set_aspect(1.0)  # 400x200 image: square crop is a centred half
    assert c.crop_pixels() == (200, 200)
    c.set_aspect(0.25)  # taller than the image allows: full height
    assert round(c.crop.height(), 3) == 1.0
    c.set_aspect(None)
    assert c.crop == QRectF(0, 0, 1, 1)
    r = c.to_widget(c.crop)
    assert c._handle_at(r.topLeft()) == "tl"
    assert c._handle_at(r.center()) == "move"
    assert c._handle_at(QPointF(1, 1)) is None


def test_crop_drag_every_handle(canvas):
    c = canvas("crop")
    pr = c.page_rect()
    for handle, target in [("br", (0.5, 0.5)), ("tl", (0.1, 0.1)), ("t", (0.5, 0.2)), ("l", (0.2, 0.5)),
                           ("r", (0.9, 0.5)), ("b", (0.5, 0.9)), ("tr", (0.8, 0.2)), ("bl", (0.2, 0.8))]:
        c.crop = QRectF(0.1, 0.1, 0.8, 0.8)
        r = c.to_widget(c.crop)
        start = {"tl": r.topLeft(), "tr": r.topRight(), "bl": r.bottomLeft(), "br": r.bottomRight(),
                 "t": QPointF(r.center().x(), r.top()), "b": QPointF(r.center().x(), r.bottom()),
                 "l": QPointF(r.left(), r.center().y()), "r": QPointF(r.right(), r.center().y())}[handle]
        c.mousePressEvent(mouse("press", start))
        assert c._drag_handle == handle
        end = c.to_widget_pt(*target)
        c.mouseMoveEvent(mouse("move", end))
        c.mouseReleaseEvent(mouse("release", end))
        assert c.crop.width() > 0.01

    # aspect-locked drags from the top and the left
    c.set_aspect(1.0)
    for handle in ("tl", "br"):
        r = c.to_widget(c.crop)
        c.mousePressEvent(mouse("press", r.topLeft() if handle == "tl" else r.bottomRight()))
        c.mouseMoveEvent(mouse("move", c.to_widget_pt(0.4, 0.4) if handle == "tl" else c.to_widget_pt(0.7, 0.9)))
        c.mouseReleaseEvent(mouse("release", QPointF()))
        assert abs(c.crop_pixels()[0] - c.crop_pixels()[1]) <= 2

    # move the whole rect
    c.crop = QRectF(0.2, 0.2, 0.3, 0.3)
    mid = c.to_widget(c.crop).center()
    c.mousePressEvent(mouse("press", mid))
    c.mouseMoveEvent(mouse("move", mid + QPointF(pr.width() * 0.9, 0)))  # clamped at the edge
    assert round(c.crop.right(), 3) == 1.0

    # new rect on empty area, then hover cursors without buttons
    c.crop = QRectF(0.4, 0.4, 0.1, 0.1)
    c.mousePressEvent(mouse("press", c.to_widget_pt(0.05, 0.05)))
    c.mouseMoveEvent(mouse("move", c.to_widget_pt(0.3, 0.3)))
    c.mouseReleaseEvent(mouse("release", QPointF()))
    assert c.crop.left() == pytest.approx(0.05, abs=0.01)
    c.mouseMoveEvent(mouse("move", c.to_widget(c.crop).topLeft(), Qt.MouseButton.NoButton))
    assert c.cursor().shape() == Qt.CursorShape.SizeFDiagCursor
    c.mouseMoveEvent(mouse("move", QPointF(1, 1), Qt.MouseButton.NoButton))
    assert c.cursor().shape() == Qt.CursorShape.CrossCursor
    c.grab()


def test_boxes_mode(canvas):
    c = canvas("boxes")
    changed = []
    c.changed.connect(lambda: changed.append(1))
    c.mousePressEvent(mouse("press", c.to_widget_pt(0.1, 0.1)))
    c.mouseMoveEvent(mouse("move", c.to_widget_pt(0.4, 0.3)))
    c.grab()  # paints the live box
    c.mouseReleaseEvent(mouse("release", QPointF()))
    assert len(c.boxes) == 1
    c.mousePressEvent(mouse("press", c.to_widget_pt(0.5, 0.5)))
    c.mouseReleaseEvent(mouse("release", QPointF()))  # a click is not a box
    assert len(c.boxes) == 1
    c.mouseMoveEvent(mouse("move", c.to_widget_pt(0.6, 0.6)))  # moving without a press does nothing
    c.mouseReleaseEvent(mouse("release", QPointF()))
    c.grab()
    c.undo()
    assert c.boxes == [] and changed


def test_draw_mode_every_tool(canvas):
    c = canvas("draw")
    texts = []
    c.text_requested.connect(texts.append)
    for tool in ("pen", "highlight", "rect", "arrow"):
        c.tool = tool
        c.mousePressEvent(mouse("press", c.to_widget_pt(0.1, 0.1)))
        c.mouseMoveEvent(mouse("move", c.to_widget_pt(0.3, 0.2)))
        c.mouseMoveEvent(mouse("move", c.to_widget_pt(0.5, 0.4)))
        c.grab()  # paints the in-progress mark
        c.mouseReleaseEvent(mouse("release", QPointF()))
    assert [m.kind for m in c.marks] == ["pen", "highlight", "rect", "arrow"]
    assert len(c.marks[0].points) == 3 and len(c.marks[2].points) == 2
    c.tool = "pen"
    c.mousePressEvent(mouse("press", c.to_widget_pt(0.2, 0.2)))
    c.mouseReleaseEvent(mouse("release", QPointF()))  # a dot is dropped
    assert len(c.marks) == 4
    c.mouseMoveEvent(mouse("move", c.to_widget_pt(0.6, 0.6)))
    c.tool = "text"
    c.mousePressEvent(mouse("press", c.to_widget_pt(0.5, 0.5)))
    assert len(texts) == 1
    c.marks.append(ops.Mark("text", [(0.5, 0.5)], text="Hi"))
    c.grab()
    c.undo()
    c.undo()
    assert len(c.marks) == 3
    c.marks = []
    c.undo()  # nothing to undo is fine


def test_merge_centre_when_several_files(qtbot, pdf, png):
    w = Wh.Wheel()
    qtbot.addWidget(w)
    md = mime(pdf, png)
    drag_enter(w, md)
    drag_move(w, md, C)
    assert w.hover == Wh.MERGE and w.hint == "Page 001 Merged.pdf"
    w.grab()
    got = []
    w.dropped.connect(lambda key, files: got.append(key))
    drop(w, md, C)
    assert got == ["merge"]


def test_click_mode_with_preset_files(qtbot, jpg):
    w = Wh.Wheel()
    qtbot.addWidget(w)
    got = []
    w.dropped.connect(lambda key, files: got.append((key, files)))
    w.popup(QPoint(400, 400), files=[jpg])
    assert w._sticky and w._preset
    w.mouseMoveEvent(mouse("move", at_wedge(0), Qt.MouseButton.NoButton))
    assert w.hover.key == "compress" and w.hint == "Photo.jpg"
    w.mousePressEvent(mouse("press", at_wedge(0)))
    assert got == [("compress", [jpg])] and not w.isVisible()
    w.popup(QPoint(400, 400))  # no files: moving the mouse does nothing
    w.mouseMoveEvent(mouse("move", at_wedge(0), Qt.MouseButton.NoButton))
    assert w.hover is None


def test_wheel_blur_requested_once(qtbot, monkeypatch):
    calls = []
    monkeypatch.setattr(Wh, "blur_behind", lambda *a: calls.append(a) or True)
    w = Wh.Wheel()
    qtbot.addWidget(w)
    w.popup(QPoint(400, 400))
    w.dismiss()
    w.popup(QPoint(400, 400))
    assert len(calls) == 1 and w.blurred
    w.grab()
