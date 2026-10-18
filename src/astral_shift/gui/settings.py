"""Settings window and the Astral tools reminder."""
from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QSettings, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QKeySequenceEdit, QLabel, QPushButton, QVBoxLayout,
    QWidget,
)

from .. import __version__
from . import hotkey
from .glass import GlassDialog

GITHUB = "https://github.com/jtaoufik/astral-shift"

TOOLS = [
    ("AstralPDF", "https://astralpdf.com", "Merge, split, compress, unlock and watermark PDFs"),
    ("AstralText", "https://astraltext.com", "Clean AI text, strip Markdown, fix spacing"),
    ("AstralJSON", "https://astraljson.com", "Prettify, compare and validate JSON"),
    ("AstralBatch", "https://astralbatch.com", "Batch image tools: backgrounds, formats, renaming"),
]

REMIND_EVERY = timedelta(days=60)


def open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


def _section(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("font-weight: 600; margin-top: 6px;")
    return label


class SettingsDialog(GlassDialog):
    """Everything the tray menu used to hold, plus the shortcut."""

    changed = Signal(str, object)  # settings key, new value

    def __init__(self, settings: QSettings, hotkey_status: str, wayland_hint: bool, parent: QWidget | None = None) -> None:
        super().__init__("Astral Shift Settings", parent)
        self.settings = settings
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        row = 0

        grid.addWidget(_section("Shortcut"), row, 0, 1, 3)
        row += 1
        self.shortcut = QKeySequenceEdit(QKeySequence(str(settings.value("hotkey", hotkey.DEFAULT))))
        self.shortcut.setMaximumSequenceLength(1)
        self.shortcut.editingFinished.connect(self._shortcut_done)
        reset = QPushButton("Default")
        reset.clicked.connect(self._shortcut_default)
        grid.addWidget(QLabel("Open the wheel"), row, 0)
        grid.addWidget(self.shortcut, row, 1)
        grid.addWidget(reset, row, 2)
        row += 1
        self.shortcut_status = QLabel(hotkey_status)
        self.shortcut_status.setObjectName("Muted")
        self.shortcut_status.setWordWrap(True)
        grid.addWidget(self.shortcut_status, row, 0, 1, 3)
        row += 1
        if wayland_hint:
            hint = QLabel("On Wayland, add a shortcut in your desktop's keyboard settings that runs: astral-shift wheel")
            hint.setObjectName("Muted")
            hint.setWordWrap(True)
            hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(hint, row, 0, 1, 3)
            row += 1

        grid.addWidget(_section("Behaviour"), row, 0, 1, 3)
        row += 1
        self.checks: dict[str, QCheckBox] = {}
        for key, label, default in [
            ("enabled", "Show the wheel when I hold Shift while dragging a file", True),
            ("context_menu", "Add Astral Shift to the right-click menu", False),
            ("login", "Open at login", False),
            ("tips", "Show Astral tools tips every 2 months", True),
        ]:
            box = QCheckBox(label)
            box.setChecked(settings.value(key, default, type=bool))
            box.toggled.connect(lambda v, k=key: self._emit(k, v))
            grid.addWidget(box, row, 0, 1, 3)
            self.checks[key] = box
            row += 1

        grid.addWidget(_section("Defaults"), row, 0, 1, 3)
        row += 1
        self.combos: dict[str, QComboBox] = {}
        for key, label, options, default in [
            ("convert/pdf", "PDFs convert to", [("jpg", "JPG"), ("png", "PNG"), ("webp", "WebP")], "jpg"),
            ("convert/image", "Images convert to", [("pdf", "PDF"), ("png", "PNG"), ("jpg", "JPG"), ("webp", "WebP")], "pdf"),
            ("compress/level", "Compression", [("low", "Light (best quality)"), ("medium", "Balanced"),
                                               ("high", "Strong (smallest)")], "medium"),
        ]:
            combo = QComboBox()
            for value, text in options:
                combo.addItem(text, value)
            combo.setCurrentIndex(max(0, combo.findData(str(settings.value(key, default)))))
            combo.currentIndexChanged.connect(lambda _i, k=key, c=combo: self._emit(k, c.currentData()))
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(combo, row, 1, 1, 2)
            self.combos[key] = combo
            row += 1
        self.layout_.addLayout(grid)

        about = QLabel(f"Astral Shift {__version__} · free and open source (AGPL-3.0)")
        about.setObjectName("Muted")
        github = QPushButton("GitHub")
        github.clicked.connect(lambda: open_url(GITHUB))
        done = QPushButton("Done")
        done.setObjectName("Primary")
        done.clicked.connect(self.accept)
        foot = QHBoxLayout()
        foot.addWidget(about, 1)
        foot.addWidget(github)
        foot.addWidget(done)
        self.layout_.addLayout(foot)
        self.resize(520, 0)

    def _emit(self, key: str, value) -> None:
        self.settings.setValue(key, value)
        self.changed.emit(key, value)

    def _shortcut_done(self) -> None:
        self._emit("hotkey", self.shortcut.keySequence().toString(QKeySequence.SequenceFormat.PortableText))

    def _shortcut_default(self) -> None:
        self.shortcut.setKeySequence(QKeySequence(hotkey.DEFAULT))
        self._shortcut_done()

    def set_shortcut_status(self, text: str) -> None:
        self.shortcut_status.setText(text)


class ToolsDialog(GlassDialog):
    """The every-two-months reminder of the other free Astral tools."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("More free Astral tools", parent)
        intro = QLabel("Astral Shift is free. These sister tools are too, and they run in your browser.")
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        self.layout_.addWidget(intro)
        for name, url, blurb in TOOLS:
            card = QFrame()
            card.setObjectName("Card")
            lay = QHBoxLayout(card)
            lay.setContentsMargins(12, 8, 8, 8)
            text = QVBoxLayout()
            title = QLabel(name)
            title.setStyleSheet("font-weight: 600;")
            sub = QLabel(blurb)
            sub.setObjectName("Muted")
            text.addWidget(title)
            text.addWidget(sub)
            lay.addLayout(text, 1)
            go = QPushButton("Open")
            go.clicked.connect(lambda _c=False, u=url: open_url(u))
            lay.addWidget(go)
            self.layout_.addWidget(card)
        star = QPushButton("Star Astral Shift on GitHub")
        star.clicked.connect(lambda: open_url(GITHUB))
        close = QPushButton("Close")
        close.setObjectName("Primary")
        close.clicked.connect(self.accept)
        foot = QHBoxLayout()
        foot.addWidget(star)
        foot.addStretch(1)
        foot.addWidget(close)
        self.layout_.addLayout(foot)
        self.resize(460, 0)


def tips_due(settings: QSettings, now: datetime | None = None) -> bool:
    """Every 60 days, counted from the first run (never on day one)."""
    now = now or datetime.now()
    if not settings.value("tips", True, type=bool):
        return False
    first = settings.value("tips/first_run")
    if not first:
        settings.setValue("tips/first_run", now.isoformat())
        return False
    last = settings.value("tips/last_shown") or first
    return now - datetime.fromisoformat(str(last)) >= REMIND_EVERY


def mark_tips_shown(settings: QSettings, now: datetime | None = None) -> None:
    settings.setValue("tips/last_shown", (now or datetime.now()).isoformat())
