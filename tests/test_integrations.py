import plistlib
import subprocess
import sys
import types
from datetime import datetime, timedelta

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QWidget

from astral_shift.gui import glass, integrations, selection, settings as S


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(integrations.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    calls = []
    monkeypatch.setattr(integrations.subprocess, "run", lambda *a, **k: calls.append(a[0]))
    return tmp_path, calls


def test_wheel_command(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert integrations.wheel_command()[-3:] == ["-m", "astral_shift", "wheel"]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/Applications/Astral Shift.app/Contents/MacOS/Astral Shift")
    assert integrations.wheel_command() == ["/Applications/Astral Shift.app/Contents/MacOS/Astral Shift", "wheel"]


def test_finder_quick_action(home, monkeypatch):
    tmp, calls = home
    monkeypatch.setattr(sys, "platform", "darwin")
    assert not integrations.is_installed()
    [bundle] = integrations.install()
    assert bundle == tmp / "Library/Services/Astral Shift.workflow"
    info = plistlib.loads((bundle / "Contents/Info.plist").read_bytes())
    assert info["NSServices"][0]["NSMenuItem"]["default"] == "Astral Shift"
    doc = plistlib.loads((bundle / "Contents/document.wflow").read_bytes())
    command = doc["actions"][0]["action"]["ActionParameters"]["COMMAND_STRING"]
    assert command.endswith('wheel "$@" >/dev/null 2>&1 &')
    assert integrations.is_installed()
    integrations.set_installed(False)
    assert not bundle.exists()
    assert calls == [["/System/Library/CoreServices/pbs", "-update"]] * 2


def test_linux_file_managers(home, monkeypatch):
    tmp, calls = home
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp / "data"))
    integrations.set_installed(True)
    nautilus, dolphin, nemo = integrations.entry_paths()
    assert nautilus.read_text().startswith("#!/bin/sh") and nautilus.stat().st_mode & 0o111
    assert "Exec=" in dolphin.read_text() and "%F" in dolphin.read_text()
    assert "Selection=notnone" in nemo.read_text()
    integrations.uninstall()
    assert not integrations.is_installed() and calls == []


def test_refresh_services_tolerates_errors(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired("pbs", 10)
    monkeypatch.setattr(integrations.subprocess, "run", boom)
    integrations.refresh_services()


# --- Finder selection --------------------------------------------------------------------

def test_finder_selection(monkeypatch, jpg, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    assert selection.finder_selection() == []
    monkeypatch.setattr(sys, "platform", "darwin")
    txt = tmp_path / "notes.txt"
    txt.write_text("x")
    out = f"{jpg}\n{txt}\n{tmp_path / 'gone.pdf'}\n\n"
    monkeypatch.setattr(selection.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=out))
    assert selection.finder_selection() == [jpg]
    monkeypatch.setattr(selection.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(returncode=1, stdout=""))
    assert selection.finder_selection() == []

    def denied(*a, **k):
        raise subprocess.TimeoutExpired("osascript", 3)
    monkeypatch.setattr(selection.subprocess, "run", denied)
    assert selection.finder_selection() == []


# --- glass --------------------------------------------------------------------------------

def test_blur_behind_dispatch(qtbot, monkeypatch):
    w = QWidget()
    qtbot.addWidget(w)
    assert glass.blur_behind(w) is False  # offscreen: nothing to ask
    monkeypatch.setattr(glass.QGuiApplication, "platformName", staticmethod(lambda: "cocoa"))
    monkeypatch.setattr(glass, "_mac_blur", lambda *a: "mac")
    assert glass.blur_behind(w) == "mac"
    monkeypatch.setattr(glass.QGuiApplication, "platformName", staticmethod(lambda: "xcb"))
    monkeypatch.setattr(glass, "_kwin_blur", lambda *a: "kwin")
    assert glass.blur_behind(w) == "kwin"


class Obj:
    """Records every Objective-C style call made on it."""

    def __init__(self, name, log, **returns):
        self._name, self._log, self._returns = name, log, returns

    def __getattr__(self, attr):
        def call(*a):
            self._log.append((self._name, attr, a))
            r = self._returns.get(attr)
            return r() if callable(r) else r
        return call


def test_mac_blur_inserts_an_effect_view(qtbot, monkeypatch):
    log = []
    layer = Obj("layer", log)
    effect = Obj("effect", log, layer=lambda: layer)
    frame = types.SimpleNamespace(size=types.SimpleNamespace(width=300, height=200))
    superview = Obj("superview", log)
    content = Obj("content", log, frame=lambda: frame, superview=lambda: superview)
    window = Obj("window", log, contentView=lambda: content)
    view = Obj("view", log, window=lambda: window)
    effect_cls = types.SimpleNamespace(alloc=lambda: types.SimpleNamespace(initWithFrame_=lambda r: effect))
    appkit = types.SimpleNamespace(
        NSAppearance=types.SimpleNamespace(appearanceNamed_=lambda n: n), NSMakeRect=lambda *r: r,
        NSViewHeightSizable=16, NSViewWidthSizable=2, NSVisualEffectView=effect_cls, NSWindowBelow=-1)
    monkeypatch.setitem(sys.modules, "AppKit", appkit)
    monkeypatch.setitem(sys.modules, "objc", types.SimpleNamespace(objc_object=lambda c_void_p: view))
    w = QWidget()
    qtbot.addWidget(w)
    assert glass._mac_blur(w, 18, 4)
    assert ("superview", "addSubview_positioned_relativeTo_", (effect, -1, content)) in log
    assert ("layer", "setCornerRadius_", (18,)) in log
    view._returns["window"] = None
    assert not glass._mac_blur(w, 18, 0)
    monkeypatch.setitem(sys.modules, "AppKit", None)  # pyobjc missing
    assert not glass._mac_blur(w, 18, 0)


def test_kwin_blur(qtbot, monkeypatch):
    props = []
    win = types.SimpleNamespace(change_property=lambda *a: props.append(a))
    disp = types.SimpleNamespace(create_resource_object=lambda kind, wid: win, intern_atom=lambda n: 7, flush=lambda: None)
    xlib = types.ModuleType("Xlib")
    xlib.Xatom = types.SimpleNamespace(CARDINAL=6)
    xlib.display = types.SimpleNamespace(Display=lambda: disp)
    monkeypatch.setitem(sys.modules, "Xlib", xlib)
    w = QWidget()
    qtbot.addWidget(w)
    assert glass._kwin_blur(w) and props == [(7, 6, 32, [])]
    xlib.display = types.SimpleNamespace(Display=lambda: (_ for _ in ()).throw(RuntimeError("no X")))
    assert not glass._kwin_blur(w)


def test_glass_dialog_moves_and_blurs(qtbot, monkeypatch):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    monkeypatch.setattr(glass, "blur_behind", lambda *a: True)
    d = glass.GlassDialog("Hello")
    qtbot.addWidget(d)
    d.resize(300, 200)
    d.show()
    qtbot.waitUntil(lambda: d.blurred)
    d.grab()
    d.hide()
    d.show()  # already blurred: no second request

    def ev(kind, local, glob, buttons=Qt.MouseButton.LeftButton):
        return QMouseEvent(kind, QPointF(*local), QPointF(*glob), Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier)
    start = d.pos()
    d.mousePressEvent(ev(QEvent.Type.MouseButtonPress, (50, 20), (start.x() + 50, start.y() + 20)))
    d.mouseMoveEvent(ev(QEvent.Type.MouseMove, (60, 30), (start.x() + 150, start.y() + 120)))
    assert d.pos() == start + type(start)(100, 100)
    d.mouseReleaseEvent(ev(QEvent.Type.MouseButtonRelease, (0, 0), (0, 0)))
    d.mousePressEvent(ev(QEvent.Type.MouseButtonPress, (50, 150), (0, 0)))  # below the title row: no drag
    d.mouseMoveEvent(ev(QEvent.Type.MouseMove, (60, 160), (500, 500)))
    assert d.pos() == start + type(start)(100, 100)


# --- settings helpers ------------------------------------------------------------------------

def test_tips_schedule(tmp_path):
    s = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    day0 = datetime(2026, 1, 1)
    assert not S.tips_due(s, day0)  # first run only records the date
    assert not S.tips_due(s, day0 + timedelta(days=59))
    assert S.tips_due(s, day0 + timedelta(days=60))
    S.mark_tips_shown(s, day0 + timedelta(days=60))
    assert not S.tips_due(s, day0 + timedelta(days=100))
    assert S.tips_due(s, day0 + timedelta(days=120))
    s.setValue("tips", False)
    assert not S.tips_due(s, day0 + timedelta(days=500))
    S.mark_tips_shown(s)
    assert S.tips_due(QSettings(str(tmp_path / "u.ini"), QSettings.Format.IniFormat)) is False


def test_settings_dialog_bits(qtbot, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(S, "open_url", opened.append)
    s = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    d = S.SettingsDialog(s, "status", wayland_hint=True)
    qtbot.addWidget(d)
    assert any("astral-shift wheel" in l.text() for l in d.findChildren(S.QLabel))
    d._shortcut_default()
    assert s.value("hotkey") == S.hotkey.DEFAULT
    buttons = {b.text(): b for b in d.findChildren(S.QPushButton)}
    buttons["GitHub"].click()
    t = S.ToolsDialog()
    qtbot.addWidget(t)
    for b in t.findChildren(S.QPushButton):
        if b.text() in ("Open", "Star Astral Shift on GitHub"):
            b.click()
    assert opened == [S.GITHUB] + [u for _, u, _ in S.TOOLS] + [S.GITHUB]


def test_open_url(monkeypatch):
    got = []
    monkeypatch.setattr(S.QDesktopServices, "openUrl", lambda u: got.append(u.toString()))
    S.open_url("https://astralpdf.com")
    assert got == ["https://astralpdf.com"]
