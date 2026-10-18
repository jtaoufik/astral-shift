import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QSettings
from PySide6.QtWidgets import QApplication, QDialog, QSystemTrayIcon

from astral_shift.gui import app as A
from astral_shift.gui import autostart, single
from astral_shift.gui.watcher import State


class Backend:
    def state(self):
        return State(False, False, 0)

    def drag_has_files(self):
        return False


@pytest.fixture
def core(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "entry_path", lambda: tmp_path / "autostart" / "astral-shift.desktop")
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    c = A.AstralShift(qapp, settings=settings, backend=Backend())
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


def test_menu_settings(core, tmp_path, monkeypatch):
    menu_action(core, "PNG").trigger()
    assert core.wheel.convert_target["pdf"] == "png"
    menu_action(core, "Strong (smallest)").trigger()
    assert core.compress_level == "high"
    enabled = menu_action(core, "Enabled")
    enabled.setChecked(False)
    assert core.watcher.enabled is False
    login = menu_action(core, "Open at Login")
    login.setChecked(True)
    assert autostart.entry_path().exists()
    login.setChecked(False)
    assert not autostart.entry_path().exists()

    about = []
    monkeypatch.setattr(A.QMessageBox, "about", lambda *a: about.append(a))
    menu_action(core, f"About Astral Shift {A.__version__}").trigger()
    assert "github.com/jtaoufik/astral-shift" in about[0][2]

    shown = []
    monkeypatch.setattr(core, "show_wheel", lambda sticky=False: shown.append(sticky))
    menu_action(core, "Show Wheel").trigger()
    monkeypatch.setattr(sys, "platform", "linux")
    core._tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
    core._tray_activated(QSystemTrayIcon.ActivationReason.Context)
    monkeypatch.setattr(sys, "platform", "darwin")
    core._tray_activated(QSystemTrayIcon.ActivationReason.Trigger)  # macOS opens the menu instead
    core.on_message("wheel")
    core.on_message("other")
    assert shown == [True, True, True]

    quits = []
    monkeypatch.setattr(core.app, "quit", lambda: quits.append(1))
    menu_action(core, "Quit").trigger()
    assert quits == [1]


def test_unavailable_watcher_says_so(qapp, tmp_path):
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    c = A.AstralShift(qapp, settings=settings, backend=None)
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


def test_task_failure_reaches_the_toast(core, qtbot, monkeypatch):
    class Exploding(A.Task):
        def run(self):
            self.signals.failed.emit("kaboom")
    monkeypatch.setattr(A, "Task", Exploding)
    core._start("rotate", "Rotating…", [Path("a.jpg")], lambda p, f: [])
    wait_done(qtbot, core)
    assert core.toast.title.text() == "Something went wrong" and core.toast.detail.text() == "kaboom"


def test_run_app(qapp, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(A, "send_to_running", lambda msg: True)
    assert A.run_app() == 0

    monkeypatch.setattr(A, "send_to_running", lambda msg: False)
    monkeypatch.setattr(single, "NAME", f"astral-test-{tmp_path.name}")
    monkeypatch.setattr(A.QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: False))
    monkeypatch.setattr(A, "QSettings", lambda *a: QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    monkeypatch.setattr(A.DragWatcher, "start", lambda self: None)
    monkeypatch.setenv("ASTRAL_SHIFT_SHOW_WHEEL", "1")
    shown = []
    monkeypatch.setattr(A.AstralShift, "show_wheel", lambda self, sticky=False: shown.append(sticky))
    monkeypatch.setattr(QApplication, "exec", lambda self: (QApplication.processEvents(), 0)[1])
    assert A.run_app() == 0
    assert "no system tray" in capsys.readouterr().err
