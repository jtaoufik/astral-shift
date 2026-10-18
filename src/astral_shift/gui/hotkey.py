"""A system-wide keyboard shortcut, with no special permission.

* macOS: Carbon ``RegisterEventHotKey`` through ctypes (the same API the
  Spotlight-style launchers use; it needs no Accessibility access).
* X11: ``XGrabKey`` on the root window.
* Wayland: not possible for an app; bind ``astral-shift wheel`` in the
  desktop's own keyboard settings instead.
"""
from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QObject, QSocketNotifier, Qt, Signal
from PySide6.QtGui import QKeySequence

DEFAULT = "Meta+Alt+Space" if sys.platform == "darwin" else "Ctrl+Alt+Space"  # mac: Control+Option+Space

# Qt key -> macOS virtual key code (kVK_*).
MAC_KEYS = {
    **{getattr(Qt.Key, f"Key_{c}"): code for c, code in zip(
        "ASDFHGZXCVBQWERYT123465", [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23])},
    Qt.Key.Key_9: 25, Qt.Key.Key_7: 26, Qt.Key.Key_8: 28, Qt.Key.Key_0: 29, Qt.Key.Key_O: 31, Qt.Key.Key_U: 32,
    Qt.Key.Key_I: 34, Qt.Key.Key_P: 35, Qt.Key.Key_L: 37, Qt.Key.Key_J: 38, Qt.Key.Key_K: 40, Qt.Key.Key_N: 45,
    Qt.Key.Key_M: 46, Qt.Key.Key_Space: 49, Qt.Key.Key_Return: 36, Qt.Key.Key_Tab: 48,
    Qt.Key.Key_F1: 122, Qt.Key.Key_F2: 120, Qt.Key.Key_F3: 99, Qt.Key.Key_F4: 118, Qt.Key.Key_F5: 96,
    Qt.Key.Key_F6: 97, Qt.Key.Key_F7: 98, Qt.Key.Key_F8: 100, Qt.Key.Key_F9: 101, Qt.Key.Key_F10: 109,
    Qt.Key.Key_F11: 103, Qt.Key.Key_F12: 111,
}

# Carbon modifier bits.
CMD, SHIFT, OPTION, CONTROL = 256, 512, 2048, 4096
# X11 modifier masks.
X_SHIFT, X_LOCK, X_CONTROL, X_ALT, X_NUMLOCK, X_SUPER = 1, 2, 4, 8, 16, 64


def parse(text: str) -> tuple[Qt.Key, Qt.KeyboardModifier] | None:
    """``"Ctrl+Alt+Space"`` -> (key, modifiers); None if empty or modifier-only."""
    seq = QKeySequence(text)
    if seq.isEmpty():
        return None
    combo = seq[0]
    key = combo.key()
    if key in (Qt.Key.Key_unknown, Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
        return None
    return key, combo.keyboardModifiers()


def mac_modifiers(mods: Qt.KeyboardModifier) -> int:
    # In Qt on macOS, ControlModifier is Command and MetaModifier is Control.
    out = 0
    if mods & Qt.KeyboardModifier.ControlModifier:
        out |= CMD
    if mods & Qt.KeyboardModifier.MetaModifier:
        out |= CONTROL
    if mods & Qt.KeyboardModifier.AltModifier:
        out |= OPTION
    if mods & Qt.KeyboardModifier.ShiftModifier:
        out |= SHIFT
    return out


def x11_modifiers(mods: Qt.KeyboardModifier) -> int:
    out = 0
    if mods & Qt.KeyboardModifier.ControlModifier:
        out |= X_CONTROL
    if mods & Qt.KeyboardModifier.MetaModifier:
        out |= X_SUPER
    if mods & Qt.KeyboardModifier.AltModifier:
        out |= X_ALT
    if mods & Qt.KeyboardModifier.ShiftModifier:
        out |= X_SHIFT
    return out


def x11_keysym_name(key: Qt.Key) -> str:
    text = QKeySequence(key).toString(QKeySequence.SequenceFormat.PortableText)
    names = {"Space": "space", "Esc": "Escape", "Del": "Delete", "Ins": "Insert", "PgUp": "Prior",
             "PgDown": "Next", "Backspace": "BackSpace"}
    return names.get(text, text.lower() if len(text) == 1 else text)


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)


class MacHotkey:
    SIGNATURE = int.from_bytes(b"ASft", "big")

    def __init__(self, callback, carbon=None) -> None:
        self._carbon = carbon or ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
        self._carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
        self._ref = ctypes.c_void_p()
        self._handler = HANDLER(lambda *_a: (callback(), 0)[1])  # kept alive on self
        target = self._carbon.GetApplicationEventTarget()
        spec = _EventTypeSpec(int.from_bytes(b"keyb", "big"), 5)  # kEventHotKeyPressed
        self._carbon.InstallEventHandler(ctypes.c_void_p(target), self._handler, 1, ctypes.byref(spec), None, None)
        self._target = target

    def register(self, key: Qt.Key, mods: Qt.KeyboardModifier) -> bool:
        self.unregister()
        code = MAC_KEYS.get(key)
        if code is None:
            return False
        hk = _EventHotKeyID(self.SIGNATURE, 1)
        err = self._carbon.RegisterEventHotKey(
            ctypes.c_uint32(code), ctypes.c_uint32(mac_modifiers(mods)), hk,
            ctypes.c_void_p(self._target), ctypes.c_uint32(0), ctypes.byref(self._ref))
        return err == 0

    def unregister(self) -> None:
        if self._ref.value:
            self._carbon.UnregisterEventHotKey(self._ref)
            self._ref = ctypes.c_void_p()


class X11Hotkey:
    def __init__(self, callback, display=None) -> None:
        from Xlib import X, XK, display as xdisplay  # type: ignore[import-not-found]

        self._X, self._XK = X, XK
        self._d = display or xdisplay.Display()
        self._root = self._d.screen().root
        self._callback = callback
        self._grab: tuple[int, int] | None = None
        self._notifier = QSocketNotifier(self._d.fileno(), QSocketNotifier.Type.Read)
        self._notifier.activated.connect(self._drain)

    def register(self, key: Qt.Key, mods: Qt.KeyboardModifier) -> bool:
        self.unregister()
        keysym = self._XK.string_to_keysym(x11_keysym_name(key))
        code = self._d.keysym_to_keycode(keysym) if keysym else 0
        if not code:
            return False
        base = x11_modifiers(mods)
        failed = []
        for extra in (0, X_LOCK, X_NUMLOCK, X_LOCK | X_NUMLOCK):  # work with Caps/Num Lock on
            self._root.grab_key(code, base | extra, True, self._X.GrabModeAsync, self._X.GrabModeAsync,
                                onerror=lambda *a: failed.append(a))
        self._d.sync()
        if failed:
            self.unregister(code, base)
            return False
        self._grab = (code, base)
        return True

    def unregister(self, code: int | None = None, base: int | None = None) -> None:
        if code is None:
            if self._grab is None:
                return
            code, base = self._grab
        for extra in (0, X_LOCK, X_NUMLOCK, X_LOCK | X_NUMLOCK):
            self._root.ungrab_key(code, base | extra)
        self._d.sync()
        self._grab = None

    def _drain(self, *_a) -> None:
        while self._d.pending_events():
            e = self._d.next_event()
            if e.type == self._X.KeyPress:
                self._callback()


def make_backend(callback):
    import os
    if sys.platform == "darwin":
        try:
            return MacHotkey(callback)
        except OSError:
            return None
    if os.environ.get("DISPLAY") and os.environ.get("XDG_SESSION_TYPE") != "wayland":
        try:
            return X11Hotkey(callback)
        except Exception:
            return None
    return None


class Hotkey(QObject):
    """Holds one shortcut; ``set(text)`` swaps it. ``activated`` fires on press."""

    activated = Signal()

    def __init__(self, parent: QObject | None = None, backend="auto") -> None:
        super().__init__(parent)
        self.backend = make_backend(self.activated.emit) if backend == "auto" else backend
        self.text = ""
        self.ok = False

    @property
    def available(self) -> bool:
        return self.backend is not None

    def set(self, text: str) -> bool:
        self.text = text
        parsed = parse(text) if text else None
        if self.backend is None:
            self.ok = False
        elif parsed is None:
            self.backend.unregister()
            self.ok = False
        else:
            self.ok = self.backend.register(*parsed)
        return self.ok
