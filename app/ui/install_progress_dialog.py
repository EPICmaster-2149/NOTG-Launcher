from __future__ import annotations

import multiprocessing
from queue import Empty
from typing import Any

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from core.launcher import InstallRequest, LauncherService, run_install_task
from ui.topbar import ModernButton


class InstallProgressDialog(QDialog):
    installation_succeeded = Signal(object)
    installation_failed = Signal(str)

    def __init__(
        self,
        service: LauncherService,
        request: InstallRequest,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.service = service
        self.request = request
        self._process: multiprocessing.Process | None = None
        self._queue: Any | None = None
        self._completed = False
        self._aborting = False
        self._last_status = ""

        self.setObjectName("installProgressDialog")
        self.setWindowTitle("Installing Instance")
        self.resize(760, 420)
        self.setMinimumSize(660, 380)

        self._build_ui()

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(90)
        self._poll_timer.timeout.connect(self._poll_events)
        self._start_install()

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(22, 20, 22, 20)
        root_layout.setSpacing(14)

        header = QFrame()
        header.setObjectName("installProgressHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 16, 18, 16)
        header_layout.setSpacing(16)

        text_column = QVBoxLayout()
        text_column.setSpacing(6)
        self.title_label = QLabel(f"Installing {self.request.name}")
        self.title_label.setObjectName("installProgressTitle")
        text_column.addWidget(self.title_label)

        self.status_label = QLabel("Preparing instance directory")
        self.status_label.setObjectName("installProgressStatus")
        text_column.addWidget(self.status_label)
        header_layout.addLayout(text_column, 1)
        root_layout.addWidget(header)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("installProgressBar")
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        root_layout.addWidget(self.progress_bar)

        self.log_output = QPlainTextEdit()
        self.log_output.setObjectName("installLogOutput")
        self.log_output.setReadOnly(True)
        self.log_output.setLineWrapMode(QPlainTextEdit.NoWrap)
        root_layout.addWidget(self.log_output, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addStretch()

        self.abort_button = ModernButton("Abort", role="danger", height=44, icon_size=0)
        self.abort_button.clicked.connect(self._confirm_abort)
        footer.addWidget(self.abort_button)
        root_layout.addLayout(footer)

    def _start_install(self) -> None:
        context = multiprocessing.get_context("spawn")
        self._queue = context.Queue()
        self._process = context.Process(
            target=run_install_task,
            args=(self.request.to_payload(), self._queue),
        )
        self._process.start()
        self._poll_timer.start()
        self._append_log(f"Starting install for {self.request.name}")

    def _poll_events(self) -> None:
        if self._queue is not None:
            while True:
                try:
                    event = self._queue.get_nowait()
                except Empty:
                    break
                self._handle_event(event)

        if self._process is None or self._completed:
            return

        if not self._process.is_alive() and self._process.exitcode not in (None, 0):
            self._handle_failure("Installation ended unexpectedly.")

    def _handle_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "status":
            text = str(event.get("text", ""))
            self.status_label.setText(text)
            self._last_status = text
            return

        if event_type == "log":
            text = str(event.get("text", ""))
            if text:
                self._append_log(text)
            return

        if event_type == "max":
            maximum = max(1, int(event.get("value", 1)))
            self.progress_bar.setMaximum(maximum)
            return

        if event_type == "progress":
            value = max(0, int(event.get("value", 0)))
            self.progress_bar.setValue(value)
            return

        if event_type == "complete":
            self._handle_success(str(event.get("installed_version", self.request.vanilla_version)))
            return

        if event_type == "error":
            message = str(event.get("message", "Unknown error"))
            trace = str(event.get("traceback", ""))
            if trace:
                self._append_log(trace)
            self._handle_failure(message)

    def _handle_success(self, installed_version: str) -> None:
        if self._completed:
            return

        self._completed = True
        self._poll_timer.stop()
        try:
            instance = self.service.finalize_install(self.request, installed_version)
        except Exception as exc:  # noqa: BLE001
            self.service.cleanup_install(self.request)
            self.installation_failed.emit(str(exc))
            QMessageBox.critical(self, "Finalize Error", str(exc))
            self.close()
            return

        self._append_log("Install finished successfully.")
        self.installation_succeeded.emit(instance)
        self.close()

    def _handle_failure(self, message: str) -> None:
        if self._completed:
            return

        self._completed = True
        self._poll_timer.stop()
        self._terminate_process()
        self.service.cleanup_install(self.request)
        self.installation_failed.emit(message)
        QMessageBox.critical(self, "Installation Failed", message)
        self.close()

    def _confirm_abort(self) -> None:
        if self._completed:
            self.close()
            return

        answer = QMessageBox.question(
            self,
            "Abort Installation",
            "Abort this installation and remove the instance being created?",
        )
        if answer != QMessageBox.Yes:
            return

        self._abort_install()

    def _abort_install(self) -> None:
        self._aborting = True
        self.status_label.setText("Cancelling installation…")
        self._append_log("Abort requested by user.")
        self._terminate_process()
        self.service.cleanup_install(self.request)
        self._completed = True
        self._poll_timer.stop()
        self.close()

    def _terminate_process(self) -> None:
        if self._process is None:
            return
        if self._process.pid:
            self.service.terminate_process_tree(self._process.pid)
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=1.5)

    def _append_log(self, text: str) -> None:
        self.log_output.appendPlainText(text)
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())

    def closeEvent(self, event) -> None:
        if not self._completed and not self._aborting:
            answer = QMessageBox.question(
                self,
                "Abort Installation",
                "Closing this window will abort the installation. Continue?",
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self._abort_install()

        self._terminate_process()
        super().closeEvent(event)
