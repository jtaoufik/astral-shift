"""One running copy per user. A second launch, or ``astral-shift wheel``,
talks to the first one over a local socket."""
from __future__ import annotations

import getpass

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

NAME = f"astral-shift-{getpass.getuser()}"


def send_to_running(message: str, timeout_ms: int = 800) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(NAME)
    if not sock.waitForConnected(timeout_ms):
        return False
    sock.write(message.encode() + b"\n")
    sock.flush()
    sock.waitForBytesWritten(timeout_ms)
    sock.disconnectFromServer()
    return True


class Server(QObject):
    message = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._accept)

    def listen(self) -> bool:
        if self._server.listen(NAME):
            return True
        QLocalServer.removeServer(NAME)  # stale socket from a crash
        return self._server.listen(NAME)

    def _accept(self) -> None:
        sock = self._server.nextPendingConnection()
        sock.readyRead.connect(lambda: self._read(sock))

    def _read(self, sock: QLocalSocket) -> None:
        for line in bytes(sock.readAll()).decode(errors="ignore").splitlines():
            if line.strip():
                self.message.emit(line.strip())
