"""The radial wheel: a translucent, focus-less window that pops up around the
cursor and takes the dropped file(s)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QDragEnterEvent, QGuiApplication, QDragMoveEvent, QDropEvent, QFont, QPainter, QPainterPath,
    QPen, QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from .. import ops
from . import icons
from .glass import blur_behind


@dataclass(frozen=True)
class Action:
    key: str
    label: str


# Clockwise from the top. The centre is ANNOTATE.
RING = [
    Action("compress", "COMPRESS"),
    Action("metadata", "METADATA"),
    Action("edit", "EDIT"),
    Action("convert", "CONVERT"),
    Action("rotate", "ROTATE"),
    Action("background", "ADD BG"),
    Action("crop", "CROP"),
    Action("redact", "REDACT"),
]
CENTER = Action("annotate", "ANNOTATE")
MERGE = Action("merge", "MERGE")  # the centre when several files are dropped
ALL = RING + [CENTER, MERGE]

SIZE = 360
OUTER = 168
INNER = 58
GAP_DEG = 2.4


def local_files(event) -> list[Path]:
    md = event.mimeData()
    if not md.hasUrls():
        return []
    return [Path(u.toLocalFile()) for u in md.urls() if u.isLocalFile() and ops.is_supported(Path(u.toLocalFile()))]


def hit_test(p: QPointF, center: QPointF, many: bool = False) -> Action | None:
    """Which action sits under ``p`` (widget coordinates)."""
    dx, dy = p.x() - center.x(), p.y() - center.y()
    r = math.hypot(dx, dy)
    if r <= INNER:
        return MERGE if many else CENTER
    if r > OUTER + 6:
        return None
    # 0 deg = top, clockwise.
    ang = (math.degrees(math.atan2(dx, -dy)) + 360 + 22.5) % 360
    return RING[int(ang // 45)]


class Wheel(QWidget):
    dropped = Signal(str, list)  # action key, [Path]
    dismissed = Signal()

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAcceptDrops(True)
        self.setFixedSize(SIZE, SIZE)
        self.setWindowTitle("Astral Shift")
        self.hover: Action | None = None
        self.hint = ""  # e.g. "Page 001.jpg", shown on the hovered wedge
        self._files: list[Path] = []
        self._preset = False
        self.convert_target = {"pdf": "jpg", "image": "pdf"}
        self._opacity = 0.0
        self._fade = QTimer(self)
        self._fade.setInterval(12)
        self._fade.timeout.connect(self._step_fade)
        self._sticky = False  # opened from the tray: stay until Esc / click outside
        self.blurred = False
        self.setMouseTracking(True)

    # --- showing --------------------------------------------------------------

    def popup(self, global_pos: QPoint, sticky: bool = False, files: list[Path] | None = None) -> None:
        """Show at ``global_pos``. With ``files``, a click on a wedge acts on them."""
        self._sticky = sticky or bool(files)
        self._preset = bool(files)
        self._files = list(files or [])
        self.hover = None
        self.hint = ""
        target = QGuiApplication.screenAt(global_pos)  # multi-monitor: the screen under the cursor
        screen = target.availableGeometry() if target else None
        x, y = global_pos.x() - SIZE // 2, global_pos.y() - SIZE // 2
        if screen is not None:
            x = max(screen.left(), min(x, screen.right() - SIZE))
            y = max(screen.top(), min(y, screen.bottom() - SIZE))
        self.move(x, y)
        self._opacity = 0.0
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._fade.start()
        if not self.blurred:
            ring = OUTER + 10
            self.blurred = blur_behind(self, ring, SIZE / 2 - ring)
        if self._sticky:
            self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, False)
            self.show()
            self.activateWindow()

    def _step_fade(self) -> None:
        self._opacity = min(1.0, self._opacity + 0.12)
        self.setWindowOpacity(self._opacity)
        if self._opacity >= 1.0:
            self._fade.stop()

    def dismiss(self) -> None:
        if self.isVisible():
            self.hide()
            self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
            self.dismissed.emit()

    def drag_released(self) -> None:
        """Mouse came up. If the drop landed on us, dropEvent already ran."""
        if not self._sticky:
            QTimer.singleShot(120, self.dismiss)

    # --- hints ------------------------------------------------------------------

    def _hint_for(self, action: Action | None) -> str:
        if not action or not self._files:
            return ""
        f = self._files[0]
        extra = f" +{len(self._files) - 1}" if len(self._files) > 1 else ""
        if action.key == "merge":
            return f"{f.stem} Merged.pdf"
        if action.key == "convert":
            target = self.convert_target[ops.kind(f)]
            if target not in ops.targets_for(f):
                target = ops.default_target(f)
            return f"{f.stem}.{target}{extra}"
        return f.name + extra

    # --- drag and drop --------------------------------------------------------

    def dragEnterEvent(self, e: QDragEnterEvent) -> None:
        files = local_files(e)
        if files:
            self._files = files
            e.acceptProposedAction()
        else:
            e.ignore()

    def _hit(self, pos: QPointF) -> Action | None:
        return hit_test(pos, QPointF(SIZE / 2, SIZE / 2), many=len(self._files) > 1)

    def _set_hover(self, action: Action | None) -> None:
        if action != self.hover:
            self.hover = action
            self.hint = self._hint_for(action)
            self.update()

    def dragMoveEvent(self, e: QDragMoveEvent) -> None:
        action = self._hit(e.position())
        self._set_hover(action)
        if action:
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragLeaveEvent(self, e) -> None:
        self.hover = None
        self.hint = ""
        self.update()

    def dropEvent(self, e: QDropEvent) -> None:
        files = local_files(e)
        action = hit_test(e.position(), QPointF(SIZE / 2, SIZE / 2), many=len(files) > 1)
        if action and files:
            e.acceptProposedAction()
            self.dropped.emit(action.key, files)
        self.dismiss()

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.dismiss()

    def mouseMoveEvent(self, e) -> None:
        if self._preset:
            self._set_hover(self._hit(e.position()))

    def mousePressEvent(self, e) -> None:
        action = self._hit(e.position())
        if action is None:
            self.dismiss()
        elif self._preset:
            files = list(self._files)
            self.dismiss()
            self.dropped.emit(action.key, files)

    def focusOutEvent(self, e) -> None:
        if self._sticky:
            self.dismiss()

    # --- painting -------------------------------------------------------------

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(SIZE / 2, SIZE / 2)

        # Soft glass disc.
        glow = QRadialGradient(c, OUTER + 10)
        glow.setColorAt(0.0, QColor(255, 255, 255, 120))
        glow.setColorAt(0.85, QColor(255, 236, 225, 90 if self.blurred else 150))
        glow.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(c, OUTER + 10, OUTER + 10)
        p.setPen(QPen(QColor(255, 255, 255, 170), 1.2))
        p.setBrush(QColor(255, 244, 236, 70))
        p.drawEllipse(c, OUTER + 4, OUTER + 4)

        label_font = QFont()
        label_font.setPixelSize(10)
        label_font.setBold(True)
        label_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)

        for i, action in enumerate(RING):
            start = 90 - (i * 45 - 22.5) - GAP_DEG / 2  # Qt: 0 deg = 3 o'clock, counter-clockwise
            span = -(45 - GAP_DEG)
            path = QPainterPath()
            outer = QRectF(c.x() - OUTER, c.y() - OUTER, 2 * OUTER, 2 * OUTER)
            inner_r = INNER + 6
            inner = QRectF(c.x() - inner_r, c.y() - inner_r, 2 * inner_r, 2 * inner_r)
            path.arcMoveTo(outer, start)
            path.arcTo(outer, start, span)
            path.arcTo(inner, start + span, -span)
            path.closeSubpath()
            hovered = action == self.hover
            p.setPen(QPen(QColor(255, 255, 255, 200), 1))
            p.setBrush(QColor(232, 68, 40, 235) if hovered else QColor(255, 214, 190, 215))
            p.drawPath(path)

            mid = math.radians(i * 45)
            r = (OUTER + inner_r) / 2
            pos = QPointF(c.x() + r * math.sin(mid), c.y() - r * math.cos(mid))
            color = "#ffffff" if hovered else "#4a2c22"
            p.drawImage(QRectF(pos.x() - 11, pos.y() - 20, 22, 22), icons.image(action.key, 44, color, 1.9))
            p.setFont(label_font)
            p.setPen(QColor(color))
            p.drawText(QRectF(pos.x() - 45, pos.y() + 4, 90, 14), Qt.AlignmentFlag.AlignCenter, action.label)

        # Centre button: annotate one file, merge several.
        centre = MERGE if len(self._files) > 1 else CENTER
        hovered = self.hover == centre
        p.setPen(QPen(QColor(255, 255, 255, 220), 1.2))
        p.setBrush(QColor(232, 68, 40, 240) if hovered else QColor(255, 236, 224, 235))
        p.drawEllipse(c, INNER, INNER)
        color = "#ffffff" if hovered else "#4a2c22"
        p.drawImage(QRectF(c.x() - 11, c.y() - 22, 22, 22), icons.image(centre.key, 44, color, 1.9))
        p.setFont(label_font)
        p.setPen(QColor(color))
        p.drawText(QRectF(c.x() - 50, c.y() + 2, 100, 14), Qt.AlignmentFlag.AlignCenter, centre.label)

        # File-name pill on the hovered wedge, like the result's name.
        if self.hint:
            f = QFont()
            f.setPixelSize(12)
            f.setBold(True)
            p.setFont(f)
            w = min(SIZE - 20, p.fontMetrics().horizontalAdvance(self.hint) + 18)
            rect = QRectF(c.x() - w / 2, SIZE - 30, w, 22)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(38, 99, 235, 235))
            p.drawRoundedRect(rect, 6, 6)
            p.setPen(QColor("white"))
            text = p.fontMetrics().elidedText(self.hint, Qt.TextElideMode.ElideMiddle, int(w - 12))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        p.end()
