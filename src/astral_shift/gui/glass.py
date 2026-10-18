"""Frosted-glass windows.

Every window is frameless and translucent and paints its own tinted,
rounded panel. Where the system can blur what is behind a window, we ask
it to: an ``NSVisualEffectView`` under the Qt view on macOS, the KWin blur
hint on KDE. Elsewhere the tint alone gives the glass look.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

RADIUS = 18


def paint_panel(p: QPainter, rect: QRectF, radius: float = RADIUS, blurred: bool = False) -> None:
    """Tinted glass: more opaque when nothing blurs the background."""
    alpha = 150 if blurred else 228
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    g = QLinearGradient(rect.topLeft(), rect.bottomRight())
    g.setColorAt(0.0, QColor(255, 246, 240, alpha))
    g.setColorAt(1.0, QColor(255, 222, 205, alpha))
    p.fillPath(path, g)
    sheen = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.top() + rect.height() * 0.35))
    sheen.setColorAt(0.0, QColor(255, 255, 255, 90))
    sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillPath(path, sheen)
    p.setPen(QPen(QColor(255, 255, 255, 190), 1.2))
    p.drawPath(path)


def blur_behind(widget: QWidget, radius: float = RADIUS, inset: float = 0.0) -> bool:
    """Ask the window system to blur behind ``widget``. Returns True if it will."""
    platform = QGuiApplication.platformName()  # "offscreen", "wayland"… have no native blur to ask for
    if platform == "cocoa":
        return _mac_blur(widget, radius, inset)
    if platform == "xcb":
        return _kwin_blur(widget)
    return False


def _mac_blur(widget: QWidget, radius: float, inset: float) -> bool:
    try:
        import objc  # type: ignore[import-not-found]
        from AppKit import (  # type: ignore[import-not-found]
            NSAppearance, NSMakeRect, NSViewHeightSizable, NSViewWidthSizable, NSVisualEffectView, NSWindowBelow,
        )
    except ImportError:
        return False
    view = objc.objc_object(c_void_p=int(widget.winId()))
    window = view.window()
    if window is None:
        return False
    content = window.contentView()
    frame = content.frame()
    w, h = frame.size.width, frame.size.height
    effect = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(inset, inset, w - 2 * inset, h - 2 * inset))
    effect.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
    effect.setBlendingMode_(0)  # behind window
    effect.setMaterial_(6)  # popover: frosted glass
    effect.setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameAqua"))  # light, to match the tint
    effect.setState_(1)  # always active, also when the app is not frontmost
    effect.setWantsLayer_(True)
    effect.layer().setCornerRadius_(radius)
    effect.layer().setMasksToBounds_(True)
    # Below Qt's view inside the window's frame view, so Qt still paints on top.
    content.superview().addSubview_positioned_relativeTo_(effect, NSWindowBelow, content)
    window.setOpaque_(False)
    return True


def _kwin_blur(widget: QWidget) -> bool:
    try:
        from Xlib import Xatom, display  # type: ignore[import-not-found]
        d = display.Display()
        win = d.create_resource_object("window", int(widget.winId()))
        win.change_property(d.intern_atom("_KDE_NET_WM_BLUR_BEHIND_REGION"), Xatom.CARDINAL, 32, [])
        d.flush()
        return True
    except Exception:
        return False


class GlassDialog(QDialog):
    """Frameless glass dialog: × at the top left, centred title, drag anywhere
    on the title row to move it."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(title)
        self.blurred = False
        self._drag_from: QPoint | None = None

        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(18, 12, 18, 16)
        self.layout_.setSpacing(10)
        head = QHBoxLayout()
        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("Close")
        self.close_btn.setFixedSize(22, 22)
        self.close_btn.clicked.connect(self.reject)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("Title")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(self.close_btn)
        head.addWidget(self.title_label, 1)
        spacer = QWidget()
        spacer.setFixedSize(22, 22)
        head.addWidget(spacer)
        self.layout_.addLayout(head)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if not self.blurred:
            # The native window exists only once shown.
            QTimer.singleShot(0, self._blur)

    def _blur(self) -> None:
        self.blurred = blur_behind(self)
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_panel(p, QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), blurred=self.blurred)
        p.end()

    def mousePressEvent(self, e) -> None:
        if e.position().y() <= 44:
            self._drag_from = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e) -> None:
        if self._drag_from is not None and e.buttons():
            self.move(e.globalPosition().toPoint() - self._drag_from)

    def mouseReleaseEvent(self, e) -> None:
        self._drag_from = None
