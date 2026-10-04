from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMessageBox, QWidget

from core.launcher import JAVA_DOWNLOAD_URL
from ui.errors import present_error


def show_java_error(parent: QWidget | None, title: str, message: str) -> None:
    error = present_error(title, message)
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Critical)
    box.setWindowTitle(f"{title} ({error.code})")
    box.setTextFormat(Qt.RichText)
    box.setTextInteractionFlags(Qt.TextBrowserInteraction)
    box.setText(
        f"<b>{escape(error.heading)}</b><br>{escape(error.guidance)}<br><br>"
        f'<a href="{JAVA_DOWNLOAD_URL}">Install Java</a>'
    )
    box.setStandardButtons(QMessageBox.Ok)
    for label in box.findChildren(QLabel):
        label.setOpenExternalLinks(True)
    box.exec()
