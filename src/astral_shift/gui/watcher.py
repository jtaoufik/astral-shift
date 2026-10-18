"""Notice "a file is being dragged while Shift is held", system-wide.

No input-monitoring or accessibility permission is needed: we only poll
state the OS already exposes to every app.

* macOS: ``NSEvent.pressedMouseButtons`` / ``modifierFlags`` and the change
  count of the drag pasteboard, which bumps when any app starts a drag.
* X11: ``XQueryPointer`` (buttons + modifiers) and the owner of the
  ``XdndSelection``, which the drag source takes when a drag starts.
* Wayland: nothing global is readable, so there is no backend; the wheel is
  opened from the tray or with ``astral-shift wheel``.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from PySide6.QtCore import QObject, QPoint, QTimer, Signal
from PySide6.QtGui import QCursor


@dataclass
class State:
    button: bool  # primary button held
    shift: bool
    drag_token: int  # changes when a new drag starts somewhere


class MacBackend:
    SHIFT = 1 << 17  # NSEventModifierFlagShift

    def __init__(self) -> None:
        from AppKit import NSEvent, NSPasteboard  # type: ignore[import-not-found]

        self._event = NSEvent
        self._board = NSPasteboard.pasteboardWithName_("Apple CFPasteboard drag")

    def state(self) -> State:
        return State(
            bool(self._event.pressedMouseButtons() & 1),
            bool(self._event.modifierFlags() & self.SHIFT),
            int(self._board.changeCount()),
        )

    def drag_has_files(self) -> bool:
        types = self._board.types() or []
        return any(str(t) in ("public.file-url", "NSFilenamesPboardType") for t in types)


class X11Backend:
    def __init__(self) -> None:
        from Xlib import X, display  # type: ignore[import-not-found]

        self._X = X
        self._d = display.Display()
        self._root = self._d.screen().root
        self._xdnd = self._d.intern_atom("XdndSelection")
        self._seen_owner = 0
        self._token = 0

    def state(self) -> State:
        q = self._root.query_pointer()
        owner = self._d.get_selection_owner(self._xdnd)
        owner_id = owner.id if owner else 0
        if owner_id != self._seen_owner:
            self._seen_owner = owner_id
            self._token += 1
        return State(bool(q.mask & self._X.Button1Mask), bool(q.mask & self._X.ShiftMask), self._token)

    # Some toolkits keep owning XdndSelection between drags, so a new drag does
    # not always change the owner: any owner counts, the drop handler filters.
    loose = True

    def drag_has_files(self) -> bool:
        return self._seen_owner != 0


def make_backend():
    if sys.platform == "darwin":
        return MacBackend()
    if sys.platform.startswith("linux") and os.environ.get("DISPLAY") and os.environ.get("XDG_SESSION_TYPE") != "wayland":
        try:
            return X11Backend()
        except Exception:
            return None
    return None


class DragWatcher(QObject):
    """Emits ``shift_drag(pos)`` once per drag when Shift joins a file drag,
    and ``released()`` when the mouse button comes back up."""

    shift_drag = Signal(QPoint)
    released = Signal()

    INTERVAL_MS = 30
    MIN_DISTANCE = 8  # px moved since press before it counts as a drag

    def __init__(self, parent: QObject | None = None, backend="auto") -> None:
        super().__init__(parent)
        self.backend = make_backend() if backend == "auto" else backend
        self._timer = QTimer(self)
        self._timer.setInterval(self.INTERVAL_MS)
        self._timer.timeout.connect(self.poll)
        self._was_down = False
        self._press_pos = QPoint()
        self._press_token = 0
        self._fired = False
        self.enabled = True

    @property
    def available(self) -> bool:
        return self.backend is not None

    def start(self) -> None:
        if self.backend is not None:
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def poll(self, pos: QPoint | None = None) -> None:
        s = self.backend.state()
        pos = pos if pos is not None else QCursor.pos()
        if s.button and not self._was_down:
            self._press_pos = pos
            self._press_token = s.drag_token
            self._fired = False
        elif s.button and not self._fired and self.enabled:
            moved = (pos - self._press_pos).manhattanLength() >= self.MIN_DISTANCE
            new_drag = s.drag_token != self._press_token or getattr(self.backend, "loose", False)
            if s.shift and moved and new_drag and self.backend.drag_has_files():
                self._fired = True
                self.shift_drag.emit(pos)
        elif not s.button and self._was_down:
            if self._fired:
                self.released.emit()
            self._fired = False
        self._was_down = s.button
