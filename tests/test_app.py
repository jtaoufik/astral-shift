import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QSettings
from PySide6.QtWidgets import QApplication, QDialog, QSystemTrayIcon

from astral_shift.gui import app as A
from astral_shift.gui import autostart, single
from astral_shift.gui.watcher import State


class FakeHotkey:
    def __init__(self):
        self.accept = True
        self.registered = None

    def register(self, key, mods):
        self.registered = (key, mods)
        return self.accept

    def unregister(self):
        self.registered = None


class Backend:
    def state(self):
        return State(False, False, 0)

    def drag_has_files(self):
        return False


@pytest.fixture
def core(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "entry_path", lambda: tmp_path / "autostart" / "astral-shift.desktop")
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    c = A.AstralShift(qapp, settings=settings, backend=Backend(), hotkey_backend=FakeHotkey())
    c.pool = type("Inline", (), {"start": staticmethod(lambda task: task.run())})()  # coverage can't see QThreads
    yield c
    c.watcher.stop()
    c.tray.hide()
    c.toast.hide()
    c.wheel.hide()


def menu_action(core, text):
    def walk(menu):
        for a in menu.actions():
            if a.text() == text:
                return a
            if a.menu():
                found = walk(a.menu())
                if found:
                    return found
    return walk(core._menu)


def wait_done(qtbot, core):
    qtbot.waitUntil(lambda: not core._tasks, timeout=15000)


def test_human_size():
    assert A.human_size(10) == "10 B"
    assert A.human_size(2048) == "2.0 KB"
    assert A.human_size(3 * 1024 ** 3) == "3.0 GB"
    assert A.human_size(5 * 1024 ** 4) == "5120.0 GB"


def test_reveal(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(A.subprocess, "Popen", calls.append)
    monkeypatch.setattr(sys, "platform", "darwin")
    A.reveal(tmp_path / "a.jpg")
    monkeypatch.setattr(sys, "platform", "linux")
    A.reveal(tmp_path / "a.jpg")
    assert calls == [["open", "-R", str(tmp_path / "a.jpg")], ["xdg-open", str(tmp_path)]]


def test_task_signals(qtbot):
    ok = A.Task(lambda progress: [Path("x")])
    with qtbot.waitSignal(ok.signals.done) as s:
        ok.run()
    assert s.args == [[Path("x")]]

    def boom(progress):
        raise RuntimeError("bad")
    bad = A.Task(boom)
    with qtbot.waitSignal(bad.signals.failed) as s:
        bad.run()
    assert s.args == ["bad"]


def test_toast(qtbot, monkeypatch, tmp_path):
    t = A.Toast()
    qtbot.addWidget(t)
    t.show_message("Hi", "there")
    assert t.isVisible() and t.show_btn.isHidden() and t._hide.isActive()
    t.show_message("Done", "1 saved", path=tmp_path / "a.jpg", sticky=True)
    assert not t.show_btn.isHidden() and not t._hide.isActive()
    seen = []
    monkeypatch.setattr(A, "reveal", seen.append)
    t.show_btn.click()
    assert seen == [tmp_path / "a.jpg"] and not t.isVisible()
    t._path = None
    t._reveal()
    assert seen == [tmp_path / "a.jpg"]


def test_tray_icon_per_platform(qapp, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert not A.tray_icon().isNull()
    monkeypatch.setattr(sys, "platform", "linux")
    assert not A.tray_icon().isNull()


def test_tray_menu(core, monkeypatch):
    opened = []
    monkeypatch.setattr(A, "open_url", opened.append)
    for name, url, _ in A.TOOLS:
        menu_action(core, name).trigger()
    menu_action(core, "Astral Shift on GitHub").trigger()
    assert opened == [u for _, u, _ in A.TOOLS] + [A.GITHUB]

    shown = []
    monkeypatch.setattr(core, "show_wheel", lambda sticky=False, files=None: shown.append((sticky, files)))
    menu_action(core, "Show Wheel").trigger()
    monkeypatch.setattr(sys, "platform", "linux")
    core._tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
    core._tray_activated(QSystemTrayIcon.ActivationReason.Context)
    monkeypatch.setattr(sys, "platform", "darwin")
    core._tray_activated(QSystemTrayIcon.ActivationReason.Trigger)  # macOS opens the menu instead
    assert shown == [(True, None), (True, None)]

    quits = []
    monkeypatch.setattr(core.app, "quit", lambda: quits.append(1))
    menu_action(core, "Quit").trigger()
    assert quits == [1]


def test_messages_and_hotkey(core, monkeypatch, jpg, tmp_path):
    shown = []
    monkeypatch.setattr(core, "show_wheel", lambda sticky=False, files=None: shown.append((sticky, files)))
    core.on_message("wheel")
    core.on_message(f"wheel\t{jpg}\t{tmp_path / 'notes.txt'}")
    core.on_message("other")
    monkeypatch.setattr(A.selection, "finder_selection", lambda: [jpg])
    core.on_hotkey()
    monkeypatch.setattr(A.selection, "finder_selection", lambda: [])
    core.on_hotkey()
    assert shown == [(True, None), (True, [jpg]), (True, [jpg]), (True, None)]


def test_settings_window_applies_changes(core, qtbot, monkeypatch, tmp_path):
    installed = []
    monkeypatch.setattr(A.integrations, "set_installed", installed.append)
    monkeypatch.setattr(A.integrations, "is_installed", lambda: False)
    core.open_settings()
    dlg = core.settings_dialog
    assert dlg is not None and dlg.isVisible()
    core.open_settings()  # second call reuses the window
    assert core.settings_dialog is dlg

    dlg.combos["convert/pdf"].setCurrentIndex(1)
    assert core.wheel.convert_target["pdf"] == "png"
    dlg.combos["compress/level"].setCurrentIndex(2)
    assert core.compress_level == "high"
    dlg.checks["enabled"].setChecked(False)
    assert core.watcher.enabled is False
    dlg.checks["context_menu"].setChecked(True)
    assert installed == [True]
    dlg.checks["login"].setChecked(True)
    assert A.autostart.entry_path().exists()
    dlg.checks["login"].setChecked(False)

    from PySide6.QtGui import QKeySequence
    dlg.shortcut.setKeySequence(QKeySequence("Ctrl+Alt+K"))
    dlg._shortcut_done()
    assert core.hotkey.text == "Ctrl+Alt+K"
    assert dlg.shortcut_status.text() == core.hotkey_status()
    dlg.close_btn.click()
    assert core.settings_dialog is None
    core.apply_setting("hotkey", "")  # no window open: still applied
    assert core.hotkey.text == ""


def test_hotkey_status_texts(core, monkeypatch):
    core.hotkey.backend = None
    assert "not available" in core.hotkey_status()
    core.hotkey.backend = FakeHotkey()
    core.hotkey.set("")
    assert core.hotkey_status() == "No shortcut set."
    core.hotkey.backend.accept = False
    core.hotkey.set("Ctrl+K")
    assert "taken" in core.hotkey_status()
    core.hotkey.backend.accept = True
    core.hotkey.set("Ctrl+K")
    monkeypatch.setattr(sys, "platform", "darwin")
    assert "Finder" in core.hotkey_status()
    monkeypatch.setattr(sys, "platform", "linux")
    assert "drop" in core.hotkey_status()


def test_tips_every_two_months(core, monkeypatch):
    from datetime import datetime, timedelta
    shown = []
    monkeypatch.setattr(A, "tips_due", lambda s: True)
    core.maybe_show_tips()
    assert core.tools_dialog is not None and core.tools_dialog.isVisible()
    core.show_tips()  # already open: reused
    core.tools_dialog.reject()
    assert core.tools_dialog is None
    assert core.settings.value("tips/last_shown")
    monkeypatch.setattr(A, "tips_due", lambda s: False)
    core.maybe_show_tips()
    assert core.tools_dialog is None


def test_is_wayland(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    assert A.is_wayland()
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    assert not A.is_wayland()


def test_unavailable_watcher_says_so(qapp, tmp_path):
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    c = A.AstralShift(qapp, settings=settings, backend=None, hotkey_backend=None)
    assert menu_action(c, "Shift+drag is unavailable here: use Show Wheel") is not None
    c.tray.hide()


def test_wheel_follows_the_drag(core, qtbot):
    core._on_shift_drag(QPoint(500, 500))
    assert core.wheel.isVisible()
    core.wheel.dismiss()
    core.show_wheel(sticky=True)
    assert core.wheel.isVisible() and core.wheel._sticky


def test_convert_compress_rotate_run_in_background(core, qtbot, pdf, jpg, tmp_path):
    core.run_action("convert", [pdf])
    qtbot.waitUntil(lambda: bool(core._tasks) or core.toast.title.text().endswith("done"), timeout=5000)
    wait_done(qtbot, core)
    assert core.toast.title.text() == "Converting to JPG done"
    assert (tmp_path / "Page 001 p1.jpg").exists()

    core.wheel.convert_target["image"] = "jpg"  # own format: falls back to PDF
    assert core.convert_target(jpg) == "pdf"

    core._run("compress", [jpg])
    wait_done(qtbot, core)
    assert "→" in core.toast.detail.text() and "-" in core.toast.detail.text()

    core._run("rotate", [jpg, pdf])
    wait_done(qtbot, core)
    assert core.toast.detail.text() == "2 files saved"
    core._run("nonsense", [jpg])  # unknown key: nothing happens


def test_compress_already_optimal_and_failures(core, qtbot, tmp_path):
    tiny = tmp_path / "tiny.png"
    from PIL import Image
    Image.new("RGB", (2, 2)).save(tiny)
    core._run("compress", [tiny])
    wait_done(qtbot, core)
    assert "already optimal" in core.toast.detail.text()

    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    core._run("rotate", [broken])
    wait_done(qtbot, core)
    assert core.toast.title.text() == "Nothing saved"

    core._run("rotate", [tiny, broken])
    wait_done(qtbot, core)
    assert core.toast.detail.text() == "1 file saved, 1 failed"


def test_finish_with_empty_original(core, tmp_path):
    empty = tmp_path / "e.png"
    empty.write_bytes(b"")
    out = tmp_path / "o.png"
    out.write_bytes(b"x")
    core._finish("compress", "Compressing…", [empty], [out], [])
    assert core.toast.detail.text() == "0 B → 1 B (already optimal)"


def test_dialog_actions(core, qtbot, jpg, tmp_path):
    core.run_action("metadata", [jpg])
    qtbot.waitUntil(lambda: bool(core._open_dialogs))
    dlg = core._open_dialogs[0]
    dlg.done_with(lambda: [jpg.with_name("x.jpg")])
    wait_done(qtbot, core)
    assert core._open_dialogs == []
    assert core.toast.title.text() == "Cleaning metadata done"

    core._open_dialog("crop", jpg)
    core._open_dialogs[0].reject()
    assert core._open_dialogs == []

    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"nope")
    core._open_dialog("crop", broken)
    assert core.toast.title.text() == "Could not open broken.pdf"


def test_merge_action(core, qtbot, pdf, png, tmp_path):
    core.run_action("merge", [pdf, png])
    qtbot.waitUntil(lambda: bool(core._open_dialogs))
    dlg = core._open_dialogs[0]
    dlg._apply()
    wait_done(qtbot, core)
    assert core.toast.title.text() == "Merging done"
    assert (tmp_path / "Page 001 Merged.pdf").exists()


def test_task_failure_reaches_the_toast(core, qtbot, monkeypatch):
    class Exploding(A.Task):
        def run(self):
            self.signals.failed.emit("kaboom")
    monkeypatch.setattr(A, "Task", Exploding)
    core._start("rotate", "Rotating…", [Path("a.jpg")], lambda p, f: [])
    wait_done(qtbot, core)
    assert core.toast.title.text() == "Something went wrong" and core.toast.detail.text() == "kaboom"


def test_run_app(qapp, monkeypatch, tmp_path, capsys, jpg):
    sent = []
    monkeypatch.setattr(A, "send_to_running", lambda msg: sent.append(msg) or True)
    assert A.run_app([jpg]) == 0
    assert sent == [f"wheel\t{jpg}"]

    monkeypatch.setattr(A, "send_to_running", lambda msg: False)
    monkeypatch.setattr(single, "NAME", f"astral-test-{tmp_path.name}")
    monkeypatch.setattr(A.QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: False))
    monkeypatch.setattr(A, "QSettings", lambda *a: QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    monkeypatch.setattr(A.DragWatcher, "start", lambda self: None)
    monkeypatch.setattr(A, "Hotkey", lambda parent, backend="auto": _NoHotkey(parent))
    shown, messages = [], []
    monkeypatch.setattr(A.AstralShift, "show_wheel", lambda self, sticky=False, files=None: shown.append(sticky))
    monkeypatch.setattr(A.AstralShift, "on_message", lambda self, m: messages.append(m))

    def exec_briefly(self):
        QApplication.processEvents()
        qwait(400)
        return 0
    monkeypatch.setattr(QApplication, "exec", exec_briefly)
    monkeypatch.setenv("ASTRAL_SHIFT_SHOW_WHEEL", "1")
    assert A.run_app() == 0
    assert shown == [True]
    assert A.run_app([jpg]) == 0
    assert messages == [f"wheel\t{jpg}"]
    assert "no system tray" in capsys.readouterr().err


def qwait(ms):
    from PySide6.QtTest import QTest
    QTest.qWait(ms)


class _NoHotkey(A.QObject):
    activated = A.Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.text, self.ok, self.available = "", False, False

    def set(self, text):
        self.text = text
        return False
