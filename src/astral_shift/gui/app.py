"""Tray app: watches for Shift+drag and the shortcut, shows the wheel, runs the action."""
from __future__ import annotations

import os
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QPoint, QRectF, QRunnable, QSettings, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMenu, QPushButton, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from .. import APP_ID, APP_NAME, ops
from . import autostart, icons, integrations, selection
from .dialogs import DIALOGS, MergeDialog
from .glass import blur_behind, paint_panel
from .hotkey import DEFAULT as DEFAULT_HOTKEY, Hotkey
from .settings import GITHUB, TOOLS, SettingsDialog, ToolsDialog, mark_tips_shown, open_url, tips_due
from .single import Server, send_to_running
from .style import QSS
from .watcher import DragWatcher
from .wheel import Wheel

VERBS = {
    "convert": "Converting", "compress": "Compressing", "rotate": "Rotating", "crop": "Cropping",
    "background": "Adding background", "redact": "Redacting", "annotate": "Saving annotations",
    "edit": "Saving edits", "metadata": "Cleaning metadata", "merge": "Merging",
}

TIPS_CHECK_MS = 6 * 60 * 60 * 1000  # the app runs for weeks: look again every 6 hours


def human_size(n: float) -> str:
    unit = "B"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            break
        n /= 1024
    return f"{n:.0f} B" if unit == "B" else f"{n:.1f} {unit}"


def reveal(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])


def is_wayland() -> bool:
    return sys.platform.startswith("linux") and os.environ.get("XDG_SESSION_TYPE") == "wayland"


# --- background work -----------------------------------------------------------------

class _Signals(QObject):
    progress = Signal(int, int)
    done = Signal(list)
    failed = Signal(str)


class Task(QRunnable):
    def __init__(self, fn: Callable[[Callable[[int, int], None]], list[Path]]) -> None:
        super().__init__()
        self.fn = fn
        self.signals = _Signals()

    def run(self) -> None:
        try:
            self.signals.done.emit(self.fn(self.signals.progress.emit))
        except Exception as e:
            traceback.print_exc()
            self.signals.failed.emit(str(e) or e.__class__.__name__)


# --- toast ------------------------------------------------------------------------------

class Toast(QWidget):
    """Small glass status card: "Converting to JPG… / 1 of 1 saved"."""

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 14, 12)
        lay.setSpacing(2)
        self.title = QLabel()
        self.title.setStyleSheet("font-weight: 600;")
        self.detail = QLabel()
        self.detail.setObjectName("Muted")
        row = QHBoxLayout()
        row.addWidget(self.detail, 1)
        self.show_btn = QPushButton("Show")
        self.show_btn.setObjectName("Chip")
        self.show_btn.clicked.connect(self._reveal)
        row.addWidget(self.show_btn)
        lay.addWidget(self.title)
        lay.addLayout(row)
        self.setFixedWidth(320)
        self.blurred = False
        self._path: Path | None = None
        self._hide = QTimer(self)
        self._hide.setSingleShot(True)
        self._hide.timeout.connect(self.hide)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_panel(p, QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 14, self.blurred)
        p.end()

    def _reveal(self) -> None:
        if self._path:
            reveal(self._path)
        self.hide()

    def show_message(self, title: str, detail: str = "", path: Path | None = None, sticky: bool = False) -> None:
        self.title.setText(title)
        self.detail.setText(detail)
        self._path = path
        self.show_btn.setVisible(path is not None)
        self.adjustSize()
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 18, screen.top() + 18)
        self.show()
        self.raise_()
        if not self.blurred:
            self.blurred = blur_behind(self, 14)
        if sticky:
            self._hide.stop()
        else:
            self._hide.start(5000)


# --- app ----------------------------------------------------------------------------------

def tray_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if sys.platform == "darwin":
        p.drawImage(pm.rect(), icons.image("astral", 64, "#000000", 2.2))
    else:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#e8442a"))
        p.drawEllipse(2, 2, 60, 60)
        p.drawImage(pm.rect().adjusted(10, 10, -10, -10), icons.image("astral", 44, "#ffffff", 2.2))
    p.end()
    ic = QIcon(pm)
    if sys.platform == "darwin":
        ic.setIsMask(True)  # template image: follows the light/dark menu bar
    return ic


class AstralShift(QObject):
    def __init__(self, app: QApplication, settings: QSettings | None = None, backend="auto", hotkey_backend="auto") -> None:
        super().__init__()
        self.app = app
        self.settings = settings if settings is not None else QSettings("AstralPDF", "Astral Shift")
        self.pool = QThreadPool.globalInstance()
        self.wheel = Wheel()
        self.wheel.dropped.connect(self.run_action)
        self.toast = Toast()
        self.watcher = DragWatcher(self, backend=backend)
        self.watcher.shift_drag.connect(self._on_shift_drag)
        self.watcher.released.connect(self.wheel.drag_released)
        self.hotkey = Hotkey(self, backend=hotkey_backend)
        self.hotkey.activated.connect(self.on_hotkey)
        self._open_dialogs: list = []
        self._tasks: list[Task] = []
        self.settings_dialog: SettingsDialog | None = None
        self.tools_dialog: ToolsDialog | None = None
        self._load_settings()
        self.hotkey.set(str(self.settings.value("hotkey", DEFAULT_HOTKEY)))
        self._build_tray()
        self.watcher.start()
        self._tips_timer = QTimer(self)
        self._tips_timer.setInterval(TIPS_CHECK_MS)
        self._tips_timer.timeout.connect(self.maybe_show_tips)
        self._tips_timer.start()
        QTimer.singleShot(4000, self.maybe_show_tips)

    # --- settings ---------------------------------------------------------------

    def _load_settings(self) -> None:
        self.wheel.convert_target = {
            "pdf": str(self.settings.value("convert/pdf", "jpg")),
            "image": str(self.settings.value("convert/image", "pdf")),
        }
        self.compress_level = str(self.settings.value("compress/level", "medium"))
        self.watcher.enabled = self.settings.value("enabled", True, type=bool)

    def hotkey_status(self) -> str:
        if not self.hotkey.available:
            return "A global shortcut is not available in this session."
        if not self.hotkey.text:
            return "No shortcut set."
        if not self.hotkey.ok:
            return "That shortcut is taken by another app or not supported. Try another one."
        what = "selected Finder files" if sys.platform == "darwin" else "files you then drop on it"
        return f"Opens the wheel for the {what}."

    def apply_setting(self, key: str, value) -> None:
        """Called by the settings window after it stored ``value``."""
        if key == "hotkey":
            self.hotkey.set(str(value))
            if self.settings_dialog:
                self.settings_dialog.set_shortcut_status(self.hotkey_status())
        elif key == "context_menu":
            integrations.set_installed(bool(value))
        elif key == "login":
            autostart.set_enabled(bool(value))
        self._load_settings()

    def open_settings(self) -> None:
        # The OS is the source of truth for these two.
        self.settings.setValue("login", autostart.is_enabled())
        self.settings.setValue("context_menu", integrations.is_installed())
        if self.settings_dialog is None:
            self.settings_dialog = SettingsDialog(self.settings, self.hotkey_status(), is_wayland())
            self.settings_dialog.changed.connect(self.apply_setting)
            self.settings_dialog.finished.connect(self._settings_closed)
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def _settings_closed(self, _result: int) -> None:
        self.settings_dialog.deleteLater()
        self.settings_dialog = None

    # --- Astral tools reminder ---------------------------------------------------------

    def maybe_show_tips(self) -> None:
        if tips_due(self.settings):
            self.show_tips()

    def show_tips(self) -> None:
        mark_tips_shown(self.settings)
        if self.tools_dialog is None:
            self.tools_dialog = ToolsDialog()
            self.tools_dialog.finished.connect(self._tips_closed)
        self.tools_dialog.show()
        self.tools_dialog.raise_()

    def _tips_closed(self, _result: int) -> None:
        self.tools_dialog.deleteLater()
        self.tools_dialog = None

    # --- tray -------------------------------------------------------------------

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(tray_icon(), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        status = menu.addAction(
            "Hold Shift while dragging a file" if self.watcher.available
            else "Shift+drag is unavailable here: use Show Wheel")
        status.setEnabled(False)
        menu.addAction(icons.icon("astral"), "Show Wheel").triggered.connect(lambda: self.show_wheel(sticky=True))
        menu.addAction(icons.icon("settings"), "Settings…").triggered.connect(self.open_settings)
        menu.addSeparator()
        tools = menu.addMenu(icons.icon("globe"), "Astral Tools")
        for name, url, _blurb in TOOLS:
            tools.addAction(name).triggered.connect(lambda _c=False, u=url: open_url(u))
        tools.addSeparator()
        tools.addAction("Astral Shift on GitHub").triggered.connect(lambda: open_url(GITHUB))
        menu.addSeparator()
        menu.addAction("Quit").triggered.connect(lambda: self.app.quit())
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self._menu = menu
        self.tray.show()

    def _tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger and sys.platform != "darwin":
            self.show_wheel(sticky=True)

    # --- wheel ---------------------------------------------------------------------

    def _on_shift_drag(self, pos: QPoint) -> None:
        self.wheel.popup(pos)

    def show_wheel(self, sticky: bool = False, files: list[Path] | None = None) -> None:
        self.wheel.popup(QCursor.pos(), sticky=sticky, files=files)

    def on_hotkey(self) -> None:
        self.show_wheel(sticky=True, files=selection.finder_selection() or None)

    def on_message(self, msg: str) -> None:
        parts = msg.split("\t")
        if parts[0] == "wheel":
            files = [Path(p) for p in parts[1:] if p and ops.is_supported(Path(p))]
            self.show_wheel(sticky=True, files=files or None)

    # --- actions ------------------------------------------------------------------

    def run_action(self, key: str, files: list[Path]) -> None:
        # Let the drop finish in the source app before any window appears.
        QTimer.singleShot(0, lambda: self._run(key, files))

    def _run(self, key: str, files: list[Path]) -> None:
        if key == "merge":
            self._open_merge(files)
            return
        if key in DIALOGS:
            for f in files:
                self._open_dialog(key, f)
            return
        if key == "convert":
            def job(progress, f):
                return ops.convert(f, self.convert_target(f), progress=progress)
            title = f"Converting to {self.convert_target(files[0]).upper()}…"
        elif key == "compress":
            level = self.compress_level
            def job(progress, f):
                return [ops.compress(f, level)]
            title = "Compressing…"
        elif key == "rotate":
            def job(progress, f):
                return [ops.rotate(f, 90)]
            title = "Rotating…"
        else:
            return
        self._start(key, title, files, job)

    def convert_target(self, f: Path) -> str:
        target = self.wheel.convert_target[ops.kind(f)]
        return target if target in ops.targets_for(f) else ops.default_target(f)

    def _show_dialog(self, key: str, dlg, files: list[Path]) -> None:
        self._open_dialogs.append(dlg)

        def finished(result: int) -> None:
            self._open_dialogs.remove(dlg)
            if result and dlg.job:
                job = dlg.job
                self._start(key, f"{VERBS[key]}…", files[:1], lambda progress, _f: job())
            dlg.deleteLater()

        dlg.finished.connect(finished)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _open_dialog(self, key: str, f: Path) -> None:
        try:
            dlg = DIALOGS[key](f)
        except Exception as e:
            self.toast.show_message(f"Could not open {f.name}", str(e))
            return
        self._show_dialog(key, dlg, [f])

    def _open_merge(self, files: list[Path]) -> None:
        self._show_dialog("merge", MergeDialog(files), files)

    def _start(self, key: str, title: str, files: list[Path], job) -> None:
        total = len(files)
        self.toast.show_message(title, f"0 of {total} saved", sticky=True)
        outputs: list[Path] = []
        errors: list[str] = []

        def run_all(progress):
            for i, f in enumerate(files):
                try:
                    outputs.extend(job(lambda a, b: None, f))
                except Exception as e:
                    errors.append(f"{f.name}: {e}")
                progress(i + 1, total)
            return outputs

        task = Task(run_all)
        task.signals.progress.connect(lambda i, n: self.toast.show_message(title, f"{i} of {n} saved", sticky=True))
        task.signals.done.connect(lambda outs: self._finish(key, title, files, outs, errors))
        task.signals.failed.connect(lambda msg: self.toast.show_message("Something went wrong", msg))
        self._tasks.append(task)  # keep the signals objects alive until done
        task.signals.done.connect(lambda _o: self._tasks.remove(task))
        task.signals.failed.connect(lambda _m: self._tasks.remove(task))
        self.pool.start(task)

    def _finish(self, key: str, title: str, files: list[Path], outs: list[Path], errors: list[str]) -> None:
        if errors and not outs:
            self.toast.show_message("Nothing saved", errors[0])
            return
        detail = f"{len(outs)} file{'s' if len(outs) != 1 else ''} saved"
        if key == "compress" and len(files) == 1 and outs:
            before, after = files[0].stat().st_size, outs[0].stat().st_size
            saved = 100 - round(after * 100 / before) if before else 0
            detail = f"{human_size(before)} → {human_size(after)}" + (f" (-{saved}%)" if saved > 0 else " (already optimal)")
        if errors:
            detail += f", {len(errors)} failed"
        self.toast.show_message(title.rstrip("…") + " done", detail, path=outs[0] if outs else None)


def run_app(files: list[Path] | None = None) -> int:
    message = "\t".join(["wheel", *map(str, files or [])])
    if send_to_running(message):
        return 0  # already running: the second launch just opens the wheel
    QApplication.setApplicationName(APP_NAME)
    QApplication.setOrganizationName("AstralPDF")
    QApplication.setDesktopFileName(APP_ID)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(QSS)
    app.setWindowIcon(tray_icon())
    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("astral-shift: no system tray found; the wheel still works with `astral-shift wheel`", file=sys.stderr)
    core = AstralShift(app)
    server = Server(app)
    server.message.connect(core.on_message)
    server.listen()
    if files:
        QTimer.singleShot(300, lambda: core.on_message(message))
    elif os.environ.get("ASTRAL_SHIFT_SHOW_WHEEL"):
        QTimer.singleShot(300, lambda: core.show_wheel(sticky=True))
    return app.exec()
