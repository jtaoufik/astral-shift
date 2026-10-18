import sys
import types

import pytest
from PySide6.QtCore import Qt

from astral_shift.gui import hotkey as H

M = Qt.KeyboardModifier


def test_parse():
    assert H.parse("Ctrl+Alt+Space") == (Qt.Key.Key_Space, M.ControlModifier | M.AltModifier)
    assert H.parse("") is None
    assert H.parse("Ctrl+") is None


def test_modifier_maps():
    allmods = M.ControlModifier | M.MetaModifier | M.AltModifier | M.ShiftModifier
    assert H.mac_modifiers(allmods) == H.CMD | H.CONTROL | H.OPTION | H.SHIFT
    assert H.mac_modifiers(M.NoModifier) == 0
    assert H.x11_modifiers(allmods) == H.X_CONTROL | H.X_SUPER | H.X_ALT | H.X_SHIFT
    assert H.x11_modifiers(M.NoModifier) == 0


def test_keysym_names():
    assert H.x11_keysym_name(Qt.Key.Key_Space) == "space"
    assert H.x11_keysym_name(Qt.Key.Key_K) == "k"
    assert H.x11_keysym_name(Qt.Key.Key_F5) == "F5"
    assert H.x11_keysym_name(Qt.Key.Key_Escape) == "Escape"


def test_mac_keycodes():
    assert H.MAC_KEYS[Qt.Key.Key_A] == 0 and H.MAC_KEYS[Qt.Key.Key_5] == 23 and H.MAC_KEYS[Qt.Key.Key_Space] == 49


class FakeCarbon:
    def __init__(self, err=0):
        self.err = err
        self.calls = []
        self.handler = None
        self.GetApplicationEventTarget = types.SimpleNamespace(restype=None)
        self.GetApplicationEventTarget = _Callable(lambda: 1234)

    def InstallEventHandler(self, target, handler, n, spec, data, ref):
        self.handler = handler
        return 0

    def RegisterEventHotKey(self, code, mods, hk, target, opts, ref):
        self.calls.append(("register", code.value, mods.value))
        ref._obj.value = 99
        return self.err

    def UnregisterEventHotKey(self, ref):
        self.calls.append(("unregister", ref.value))


class _Callable:
    def __init__(self, fn):
        self.fn = fn
        self.restype = None

    def __call__(self, *a):
        return self.fn(*a)


def test_mac_hotkey_register_and_fire():
    fired = []
    carbon = FakeCarbon()
    hk = H.MacHotkey(lambda: fired.append(1), carbon=carbon)
    assert hk.register(Qt.Key.Key_Space, M.MetaModifier | M.AltModifier)
    assert carbon.calls[-1] == ("register", 49, H.CONTROL | H.OPTION)
    assert carbon.handler(None, None, None) == 0 and fired == [1]
    assert hk.register(Qt.Key.Key_K, M.ControlModifier)  # replaces the previous one
    assert ("unregister", 99) in carbon.calls
    assert not hk.register(Qt.Key.Key_Escape, M.ControlModifier)  # no key code for it
    hk.unregister()  # nothing registered: no call
    carbon.err = -9878
    assert not hk.register(Qt.Key.Key_K, M.ControlModifier)


class FakeRoot:
    def __init__(self, fail=False):
        self.grabs, self.ungrabs, self.fail = [], [], fail

    def grab_key(self, code, mods, owner, pm, km, onerror=None):
        self.grabs.append((code, mods))
        if self.fail:
            onerror("BadAccess")

    def ungrab_key(self, code, mods):
        self.ungrabs.append((code, mods))


class FakeDisplay:
    def __init__(self, root):
        self.root = root
        self.events = []

    def screen(self):
        return types.SimpleNamespace(root=self.root)

    def fileno(self):
        return 0

    def keysym_to_keycode(self, sym):
        return 65 if sym else 0

    def sync(self):
        pass

    def pending_events(self):
        return len(self.events)

    def next_event(self):
        return self.events.pop(0)


@pytest.fixture
def xlib(monkeypatch):
    mod = types.ModuleType("Xlib")
    mod.X = types.SimpleNamespace(GrabModeAsync=1, KeyPress=2)
    mod.XK = types.SimpleNamespace(string_to_keysym=lambda name: 0 if name == "Escape" else 32)
    mod.display = types.SimpleNamespace(Display=lambda: FakeDisplay(FakeRoot()))
    monkeypatch.setitem(sys.modules, "Xlib", mod)
    return mod


def test_x11_hotkey(qapp, xlib):
    fired = []
    root = FakeRoot()
    d = FakeDisplay(root)
    hk = H.X11Hotkey(lambda: fired.append(1), display=d)
    assert hk.register(Qt.Key.Key_Space, M.ControlModifier | M.AltModifier)
    assert len(root.grabs) == 4 and root.grabs[0] == (65, H.X_CONTROL | H.X_ALT)
    d.events = [types.SimpleNamespace(type=2), types.SimpleNamespace(type=3)]
    hk._drain()
    assert fired == [1]
    assert hk.register(Qt.Key.Key_K, M.ControlModifier)
    assert len(root.ungrabs) == 4
    hk.unregister()
    hk.unregister()  # already off
    assert not hk.register(Qt.Key.Key_Escape, M.ControlModifier)
    taken = H.X11Hotkey(lambda: None, display=FakeDisplay(FakeRoot(fail=True)))
    assert not taken.register(Qt.Key.Key_Space, M.ControlModifier)
    assert H.X11Hotkey(lambda: None)._d is not None  # opens its own display


def test_make_backend(monkeypatch, xlib):
    monkeypatch.setattr(H, "MacHotkey", lambda cb: "mac")
    monkeypatch.setattr(H, "X11Hotkey", lambda cb: "x11")
    monkeypatch.setattr(sys, "platform", "darwin")
    assert H.make_backend(print) == "mac"

    def nope(cb):
        raise OSError
    monkeypatch.setattr(H, "MacHotkey", nope)
    assert H.make_backend(print) is None
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    assert H.make_backend(print) == "x11"
    monkeypatch.setattr(H, "X11Hotkey", lambda cb: (_ for _ in ()).throw(RuntimeError()))
    assert H.make_backend(print) is None
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    assert H.make_backend(print) is None


def test_real_mac_backend_loads_carbon():
    if sys.platform != "darwin":
        pytest.skip("macOS only")
    hk = H.MacHotkey(lambda: None)
    assert hk.register(Qt.Key.Key_F12, M.MetaModifier | M.AltModifier | M.ShiftModifier)
    hk.unregister()


def test_hotkey_object(qapp):
    class B:
        def __init__(self):
            self.on = None

        def register(self, key, mods):
            self.on = key
            return True

        def unregister(self):
            self.on = None

    b = B()
    h = H.Hotkey(backend=b)
    assert h.available and h.set("Ctrl+K") and b.on == Qt.Key.Key_K
    assert not h.set("") and b.on is None
    none = H.Hotkey(backend=None)
    assert not none.available and not none.set("Ctrl+K")


def test_auto_backend(qapp, monkeypatch):
    monkeypatch.setattr(H, "make_backend", lambda cb: "B")
    assert H.Hotkey().backend == "B"
