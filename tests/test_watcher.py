import sys
import types

import pytest
from PySide6.QtCore import QPoint

from astral_shift.gui import watcher as W


class FakeBackend:
    loose = False

    def __init__(self):
        self.s = W.State(False, False, 0)
        self.files = True

    def state(self):
        return self.s

    def drag_has_files(self):
        return self.files


@pytest.fixture
def fake(qapp):
    b = FakeBackend()
    w = W.DragWatcher(backend=b)
    fired, released = [], []
    w.shift_drag.connect(fired.append)
    w.released.connect(lambda: released.append(1))
    return b, w, fired, released


def step(w, b, button, shift, token, pos):
    b.s = W.State(button, shift, token)
    w.poll(QPoint(*pos))


def test_shift_file_drag_fires_once_then_releases(fake):
    b, w, fired, released = fake
    step(w, b, True, False, 1, (0, 0))  # press
    step(w, b, True, False, 2, (20, 0))  # drag started, no shift yet
    assert fired == []
    step(w, b, True, True, 2, (30, 0))  # shift joins the drag
    step(w, b, True, True, 2, (40, 0))
    assert fired == [QPoint(30, 0)]
    step(w, b, False, True, 2, (40, 0))
    assert released == [1]
    step(w, b, False, False, 2, (40, 0))
    assert released == [1]


@pytest.mark.parametrize("token, pos, files, enabled", [
    (1, (20, 0), True, True),  # no new drag (a selection rectangle, say)
    (2, (3, 0), True, True),  # barely moved
    (2, (20, 0), False, True),  # dragging text, not files
    (2, (20, 0), True, False),  # turned off from the tray
])
def test_no_wheel_when(fake, token, pos, files, enabled):
    b, w, fired, released = fake
    b.files = files
    w.enabled = enabled
    step(w, b, True, True, 1, (0, 0))
    step(w, b, True, True, token, pos)
    step(w, b, False, False, token, pos)
    assert fired == [] and released == []


def test_loose_backend_needs_no_new_token(fake):
    b, w, fired, _ = fake
    b.loose = True
    step(w, b, True, True, 1, (0, 0))
    step(w, b, True, True, 1, (20, 0))
    assert len(fired) == 1


def test_start_stop_and_cursor_poll(qapp):
    b = FakeBackend()
    w = W.DragWatcher(backend=b)
    assert w.available
    w.start()
    assert w._timer.isActive()
    w.poll()  # uses the real cursor position
    w.stop()
    assert not w._timer.isActive()
    none = W.DragWatcher(backend=None)
    assert not none.available
    none.start()
    assert not none._timer.isActive()


def test_mac_backend(monkeypatch):
    board = types.SimpleNamespace(changeCount=lambda: 7, types=lambda: ["public.file-url"])
    event = types.SimpleNamespace(pressedMouseButtons=lambda: 1, modifierFlags=lambda: 1 << 17)
    appkit = types.SimpleNamespace(NSEvent=event, NSPasteboard=types.SimpleNamespace(pasteboardWithName_=lambda n: board))
    monkeypatch.setitem(sys.modules, "AppKit", appkit)
    b = W.MacBackend()
    assert b.state() == W.State(True, True, 7)
    assert b.drag_has_files()
    board.types = lambda: None
    assert not b.drag_has_files()


def test_x11_backend(monkeypatch):
    owners = [None, types.SimpleNamespace(id=5), types.SimpleNamespace(id=5), types.SimpleNamespace(id=9)]

    class Display:
        def screen(self):
            return types.SimpleNamespace(root=types.SimpleNamespace(query_pointer=lambda: types.SimpleNamespace(mask=256 | 1)))

        def intern_atom(self, name):
            return 1

        def get_selection_owner(self, atom):
            return owners.pop(0)

    xlib = types.ModuleType("Xlib")
    xlib.X = types.SimpleNamespace(Button1Mask=256, ShiftMask=1)
    xlib.display = types.SimpleNamespace(Display=Display)
    monkeypatch.setitem(sys.modules, "Xlib", xlib)
    b = W.X11Backend()
    assert b.state() == W.State(True, True, 0) and not b.drag_has_files()
    assert b.state().drag_token == 1 and b.drag_has_files()
    assert b.state().drag_token == 1
    assert b.state().drag_token == 2
    assert b.loose


def test_make_backend(monkeypatch):
    monkeypatch.setattr(W, "MacBackend", lambda: "mac")
    monkeypatch.setattr(W, "X11Backend", lambda: "x11")
    monkeypatch.setattr(sys, "platform", "darwin")
    assert W.make_backend() == "mac"
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    assert W.make_backend() == "x11"
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    assert W.make_backend() is None
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")

    def broken():
        raise RuntimeError("no X")
    monkeypatch.setattr(W, "X11Backend", broken)
    assert W.make_backend() is None
    monkeypatch.setattr(sys, "platform", "win32")
    assert W.make_backend() is None
