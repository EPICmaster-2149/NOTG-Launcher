from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMessageBox, QWidget

from core.launcher import JAVA_DOWNLOAD_URL


def show_java_error(parent: QWidget | None, title: str, message: str) -> None:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Critical)
    box.setWindowTitle(title)
    box.setTextFormat(Qt.RichText)
    box.setTextInteractionFlags(Qt.TextBrowserInteraction)
    box.setText(
        f"{escape(message)}<br><br>"
        f'<a href="{JAVA_DOWNLOAD_URL}">Install Java</a>'
    )
    box.setStandardButtons(QMessageBox.Ok)
    for label in box.findChildren(QLabel):
        label.setOpenExternalLinks(True)
    box.exec()
