"""A page preview that the user can draw on. Everything it reports is in
normalised 0..1 coordinates of the page."""
from __future__ import annotations

from pathlib import Path

import pymupdf
from PIL import Image
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .. import ops
from ..ops.markup import Mark


def pil_to_qimage(im: Image.Image) -> QImage:
    im = im.convert("RGBA")
    data = im.tobytes("raw", "RGBA")
    return QImage(data, im.width, im.height, im.width * 4, QImage.Format.Format_RGBA8888).copy()


class Document:
    """Pages of a PDF or the single image, rendered for preview on demand."""

    def __init__(self, path: Path, max_side: int = 1400) -> None:
        self.path = Path(path)
        self.kind = ops.kind(self.path)
        self.max_side = max_side
        self._cache: dict[int, QImage] = {}
        if self.kind == "pdf":
            with pymupdf.open(self.path) as doc:
                self.count = doc.page_count
                self.sizes = [(p.rect.width, p.rect.height) for p in doc]
        else:
            with Image.open(self.path) as im:
                from PIL import ImageOps
                im = ImageOps.exif_transpose(im)
                self.count = 1
                self.sizes = [im.size]

    def page(self, i: int) -> QImage:
        if i not in self._cache:
            if self.kind == "pdf":
                w, h = self.sizes[i]
                zoom = min(3.0, self.max_side / max(w, h))
                with pymupdf.open(self.path) as doc:
                    pix = doc[i].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
                    img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
            else:
                with Image.open(self.path) as im:
                    im.load()
                    im.thumbnail((self.max_side, self.max_side))
                    img = pil_to_qimage(im)
            self._cache[i] = img
        return self._cache[i]


class PageCanvas(QWidget):
    """Modes: ``crop`` (one rect with an optional aspect ratio), ``boxes``
    (many rects, for redaction) and ``draw`` (annotation marks)."""

    changed = Signal()
    text_requested = Signal(QPointF)  # normalised point where a text mark goes

    HANDLE = 7

    def __init__(self, mode: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.mode = mode
        self.image = QImage()
        self.setMinimumSize(420, 420)
        self.setMouseTracking(True)
        # crop
        self.crop = QRectF(0, 0, 1, 1)
        self.aspect: float | None = None  # w/h in page pixels
        self._drag_handle: str | None = None
        self._drag_origin = QPointF()
        self._crop_origin = QRectF()
        # boxes
        self.boxes: list[QRectF] = []
        # draw
        self.marks: list[Mark] = []
        self.tool = "pen"
        self.color = (255, 59, 48)
        self._current: Mark | None = None
        self._start: QPointF | None = None
        self._live: QRectF | None = None

    def sizeHint(self) -> QSize:
        return QSize(640, 640)

    def set_image(self, img: QImage) -> None:
        self.image = img
        self.update()

    # --- geometry ---------------------------------------------------------------

    def page_rect(self) -> QRectF:
        if self.image.isNull():
            return QRectF()
        avail = QRectF(self.rect()).adjusted(12, 12, -12, -12)
        s = min(avail.width() / self.image.width(), avail.height() / self.image.height())
        w, h = self.image.width() * s, self.image.height() * s
        return QRectF(avail.center().x() - w / 2, avail.center().y() - h / 2, w, h)

    def to_norm(self, p: QPointF) -> QPointF:
        r = self.page_rect()
        return QPointF(min(max((p.x() - r.x()) / r.width(), 0), 1), min(max((p.y() - r.y()) / r.height(), 0), 1))

    def to_widget(self, r: QRectF) -> QRectF:
        pr = self.page_rect()
        return QRectF(pr.x() + r.x() * pr.width(), pr.y() + r.y() * pr.height(), r.width() * pr.width(), r.height() * pr.height())

    def to_widget_pt(self, x: float, y: float) -> QPointF:
        pr = self.page_rect()
        return QPointF(pr.x() + x * pr.width(), pr.y() + y * pr.height())

    # --- crop ---------------------------------------------------------------------

    def set_aspect(self, ratio: float | None) -> None:
        self.aspect = ratio
        if ratio:
            img_ratio = self.image.width() / self.image.height()
            nr = ratio / img_ratio  # normalised w/h
            w, h = 1.0, 1.0 / nr
            if h > 1:
                w, h = nr, 1.0
            self.crop = QRectF((1 - w) / 2, (1 - h) / 2, w, h)
        else:
            self.crop = QRectF(0, 0, 1, 1)
        self.changed.emit()
        self.update()

    def _handle_at(self, p: QPointF) -> str | None:
        r = self.to_widget(self.crop)
        pts = {
            "tl": r.topLeft(), "tr": r.topRight(), "bl": r.bottomLeft(), "br": r.bottomRight(),
            "t": QPointF(r.center().x(), r.top()), "b": QPointF(r.center().x(), r.bottom()),
            "l": QPointF(r.left(), r.center().y()), "r": QPointF(r.right(), r.center().y()),
        }
        for name, q in pts.items():
            if abs(q.x() - p.x()) <= self.HANDLE + 3 and abs(q.y() - p.y()) <= self.HANDLE + 3:
                return name
        if r.contains(p):
            return "move"
        return None

    def _apply_crop_drag(self, p: QPointF) -> None:
        n = self.to_norm(p)
        o = self._crop_origin
        if self._drag_handle == "move":
            d = n - self.to_norm(self._drag_origin)
            x = min(max(o.x() + d.x(), 0), 1 - o.width())
            y = min(max(o.y() + d.y(), 0), 1 - o.height())
            self.crop = QRectF(x, y, o.width(), o.height())
            return
        x0, y0, x1, y1 = o.left(), o.top(), o.right(), o.bottom()
        h = self._drag_handle or ""
        if "l" in h:
            x0 = min(n.x(), x1 - 0.02)
        if "r" in h:
            x1 = max(n.x(), x0 + 0.02)
        if "t" in h:
            y0 = min(n.y(), y1 - 0.02)
        if "b" in h:
            y1 = max(n.y(), y0 + 0.02)
        if self.aspect:
            img_ratio = self.image.width() / self.image.height()
            nr = self.aspect / img_ratio
            w = x1 - x0
            hgt = w / nr
            if "t" in h:
                y0 = max(0.0, y1 - hgt)
            else:
                y1 = min(1.0, y0 + hgt)
            hgt = y1 - y0
            w = hgt * nr
            if "l" in h:
                x0 = x1 - w
            else:
                x1 = x0 + w
        self.crop = QRectF(QPointF(x0, y0), QPointF(x1, y1)).normalized()

    def crop_pixels(self) -> tuple[int, int]:
        w, h = self.image.width(), self.image.height()
        return round(self.crop.width() * w), round(self.crop.height() * h)

    # --- mouse ----------------------------------------------------------------------

    def mousePressEvent(self, e) -> None:
        p = e.position()
        if self.mode == "crop":
            self._drag_handle = self._handle_at(p)
            self._drag_origin = p
            self._crop_origin = QRectF(self.crop)
            if self._drag_handle is None and self.page_rect().contains(p):
                n = self.to_norm(p)
                self.crop = QRectF(n.x(), n.y(), 0.02, 0.02)
                self._crop_origin = QRectF(self.crop)
                self._drag_handle = "br"
        elif self.mode == "boxes":
            self._start = self.to_norm(p)
            self._live = QRectF(self._start, self._start)
        elif self.mode == "draw":
            n = self.to_norm(p)
            if self.tool == "text":
                self.text_requested.emit(n)
                return
            self._current = Mark(self.tool, [(n.x(), n.y())], color=self.color)
            if self.tool in ("rect", "arrow"):
                self._current.points.append((n.x(), n.y()))
        self.update()

    def mouseMoveEvent(self, e) -> None:
        p = e.position()
        if self.mode == "crop":
            if self._drag_handle and e.buttons():
                self._apply_crop_drag(p)
                self.changed.emit()
                self.update()
            else:
                h = self._handle_at(p)
                cursors = {
                    "tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
                    "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor,
                    "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
                    "l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
                    "move": Qt.CursorShape.SizeAllCursor,
                }
                self.setCursor(cursors.get(h, Qt.CursorShape.CrossCursor))
        elif self.mode == "boxes" and self._start is not None:
            self._live = QRectF(self._start, self.to_norm(p)).normalized()
            self.update()
        elif self.mode == "draw" and self._current is not None:
            n = self.to_norm(p)
            if self._current.kind in ("rect", "arrow"):
                self._current.points[-1] = (n.x(), n.y())
            else:
                self._current.points.append((n.x(), n.y()))
            self.update()

    def mouseReleaseEvent(self, e) -> None:
        if self.mode == "crop":
            self._drag_handle = None
        elif self.mode == "boxes" and self._live is not None:
            if self._live.width() > 0.004 and self._live.height() > 0.004:
                self.boxes.append(self._live)
                self.changed.emit()
            self._start = self._live = None
        elif self.mode == "draw" and self._current is not None:
            if len(self._current.points) > 1:
                self.marks.append(self._current)
                self.changed.emit()
            self._current = None
        self.update()

    def undo(self) -> None:
        if self.mode == "boxes" and self.boxes:
            self.boxes.pop()
        elif self.mode == "draw" and self.marks:
            self.marks.pop()
        self.changed.emit()
        self.update()

    # --- paint ------------------------------------------------------------------------

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        pr = self.page_rect()
        if self.image.isNull():
            return
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 30))
        p.drawRoundedRect(pr.adjusted(-1, 2, 1, 4), 3, 3)
        p.drawImage(pr, self.image)

        if self.mode == "crop":
            r = self.to_widget(self.crop)
            shade = QPainterPath()
            shade.addRect(pr)
            hole = QPainterPath()
            hole.addRect(r)
            p.fillPath(shade.subtracted(hole), QColor(0, 0, 0, 120))
            p.setPen(QPen(QColor("#e8442a"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(r)
            p.setPen(QPen(QColor(255, 255, 255, 90), 1))
            for k in (1, 2):
                p.drawLine(QPointF(r.left() + r.width() * k / 3, r.top()), QPointF(r.left() + r.width() * k / 3, r.bottom()))
                p.drawLine(QPointF(r.left(), r.top() + r.height() * k / 3), QPointF(r.right(), r.top() + r.height() * k / 3))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#e8442a"))
            for q in (r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight(),
                      QPointF(r.center().x(), r.top()), QPointF(r.center().x(), r.bottom()),
                      QPointF(r.left(), r.center().y()), QPointF(r.right(), r.center().y())):
                p.drawRect(QRectF(q.x() - 4, q.y() - 4, 8, 8))

        elif self.mode == "boxes":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 235))
            for b in self.boxes:
                p.drawRect(self.to_widget(b))
            if self._live is not None:
                p.setBrush(QColor(0, 0, 0, 140))
                p.setPen(QPen(QColor("#e8442a"), 1, Qt.PenStyle.DashLine))
                p.drawRect(self.to_widget(self._live))

        elif self.mode == "draw":
            for m in self.marks + ([self._current] if self._current else []):
                self._paint_mark(p, m, pr)
        p.end()

    def _paint_mark(self, p: QPainter, m: Mark, pr: QRectF) -> None:
        longest = max(pr.width(), pr.height())
        stroke = max(1.0, m.width * longest)
        pts = [self.to_widget_pt(x, y) for x, y in m.points]
        color = QColor(*m.color)
        if m.kind == "pen" and len(pts) > 1:
            p.setPen(QPen(color, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawPolyline(pts)
        elif m.kind == "highlight" and len(pts) > 1:
            c = QColor(color)
            c.setAlpha(110)
            p.setPen(QPen(c, stroke * 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawPolyline(pts)
        elif m.kind == "rect" and len(pts) >= 2:
            p.setPen(QPen(color, stroke))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(pts[0], pts[-1]).normalized())
        elif m.kind == "arrow" and len(pts) >= 2:
            from ..ops.markup import _arrow_head
            a, b = _arrow_head((pts[0].x(), pts[0].y()), (pts[-1].x(), pts[-1].y()), stroke * 5)
            p.setPen(QPen(color, stroke))
            p.drawLine(pts[0], pts[-1])
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawPolygon([pts[-1], QPointF(*a), QPointF(*b)])
        elif m.kind == "text" and pts:
            f = QFont()
            f.setPixelSize(max(6, round(m.size * longest)))
            p.setFont(f)
            p.setPen(color)
            p.drawText(QRectF(pts[0].x(), pts[0].y(), pr.width(), f.pixelSize() * 1.6),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, m.text)
