from __future__ import annotations

import json
import socket
import threading
import uuid
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal


class LauncherIpcServer(QObject):
    message_received = Signal(dict)

    def __init__(self, state_file: Path, parent: QObject | None = None):
        super().__init__(parent)
        self._state_file = state_file
        self._token = uuid.uuid4().hex
        self._server_socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if self._server_socket is not None:
            return

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(5)
        server.settimeout(0.5)

        self._server_socket = server
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(
            json.dumps(
                {
                    "host": "127.0.0.1",
                    "port": int(server.getsockname()[1]),
                    "token": self._token,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        self._thread = threading.Thread(target=self._serve, name="notg-launcher-ipc", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        server = self._server_socket
        self._server_socket = None
        if server is not None:
            try:
                server.close()
            except OSError:
                pass
        if self._state_file.exists():
            self._state_file.unlink(missing_ok=True)
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def _serve(self) -> None:
        server = self._server_socket
        if server is None:
            return

        while not self._stop_event.is_set():
            try:
                client, _ = server.accept()
            except TimeoutError:
                continue
            except OSError:
                return

            with client:
                try:
                    raw = client.recv(65536)
                    payload = json.loads(raw.decode("utf-8")) if raw else {}
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    continue

                if not isinstance(payload, dict) or payload.get("token") != self._token:
                    continue
                message = payload.get("message")
                if isinstance(message, dict):
                    self.message_received.emit(message)


def send_ipc_message(state_file: Path, message: dict[str, Any], timeout: float = 1.2) -> bool:
    if not state_file.is_file():
        return False

    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(state, dict):
        return False

    host = str(state.get("host") or "127.0.0.1")
    token = str(state.get("token") or "")
    try:
        port = int(state.get("port"))
    except (TypeError, ValueError):
        return False

    try:
        with socket.create_connection((host, port), timeout=timeout) as client:
            client.sendall(json.dumps({"token": token, "message": message}).encode("utf-8"))
        return True
    except OSError:
        return False
