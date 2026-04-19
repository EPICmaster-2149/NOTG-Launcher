from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QFileDialog, QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QVBoxLayout, QWidget

from core.launcher import LauncherService
from ui.responsive import fitted_window_size, scaled_px
from ui.topbar import ModernButton


class BackgroundPreview(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._pixmap = QPixmap()
        self.setMinimumHeight(260)

    def set_image_path(self, image_path: str | None) -> None:
        self._pixmap = QPixmap(image_path) if image_path else QPixmap()
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        outer = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor(84, 122, 177, 90), 1.2))
        painter.setBrush(QColor(8, 14, 25, 220))
        painter.drawRoundedRect(outer, 18, 18)

        inner = outer.adjusted(12, 12, -12, -12)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(16, 26, 43, 210))
        painter.drawRoundedRect(inner, 14, 14)

        if self._pixmap.isNull():
            painter.setPen(QColor("#dce9ff"))
            painter.drawText(inner, Qt.AlignCenter, "No background image selected")
            return

        scaled = self._pixmap.scaled(
            int(inner.width()),
            int(inner.height()),
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        source_x = max(0, int((scaled.width() - inner.width()) / 2))
        source_y = max(0, int((scaled.height() - inner.height()) / 2))
        painter.drawPixmap(
            int(inner.left()),
            int(inner.top()),
            scaled,
            source_x,
            source_y,
            int(inner.width()),
            int(inner.height()),
        )


class SettingsDialog(QDialog):
    background_changed = Signal(str)

    def __init__(self, service: LauncherService, parent: QWidget | None = None):
        super().__init__(parent)
        self.service = service

        self.setObjectName("settingsDialog")
        self.setWindowTitle("Settings")
        self.setModal(False)
        self.setMinimumSize(640, 520)
        self.resize(fitted_window_size(self.parentWidget() or self, 860, 640, minimum_width=640, minimum_height=520))

        self._build_ui()
        self._apply_responsive_layout()
        self._refresh_preview()

    def showEvent(self, event) -> None:
        self._apply_responsive_layout()
        super().showEvent(event)

    def resizeEvent(self, event) -> None:
        self._apply_responsive_layout()
        super().resizeEvent(event)

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(22, 22, 22, 20)
        root_layout.setSpacing(14)

        header = QFrame()
        header.setObjectName("settingsHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(18, 16, 18, 16)
        header_layout.setSpacing(6)

        title = QLabel("Insert background")
        title.setObjectName("settingsTitle")
        header_layout.addWidget(title)

        subtitle = QLabel("Preview the active background, add a custom image, or switch back to the default one.")
        subtitle.setObjectName("settingsSubtitle")
        subtitle.setWordWrap(True)
        header_layout.addWidget(subtitle)
        root_layout.addWidget(header)

        preview_card = QFrame()
        preview_card.setObjectName("settingsPreviewCard")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(18, 18, 18, 18)
        preview_layout.setSpacing(12)

        self.preview = BackgroundPreview()
        preview_layout.addWidget(self.preview, 1)

        self.caption = QLabel("")
        self.caption.setObjectName("settingsCaption")
        self.caption.setWordWrap(True)
        preview_layout.addWidget(self.caption)
        root_layout.addWidget(preview_card, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(12)

        self.add_button = ModernButton("Add", role="accent", height=42, icon_size=0)
        self.add_button.clicked.connect(self._add_background)
        footer.addWidget(self.add_button)

        self.reset_button = ModernButton("Default", role="sidebar", height=42, icon_size=0)
        self.reset_button.clicked.connect(self._reset_background)
        footer.addWidget(self.reset_button)

        footer.addStretch()

        self.close_button = ModernButton("Close", role="sidebar", height=42, icon_size=0)
        self.close_button.clicked.connect(self.close)
        footer.addWidget(self.close_button)
        root_layout.addLayout(footer)

    def _apply_responsive_layout(self) -> None:
        layout = self.layout()
        if isinstance(layout, QVBoxLayout):
            margin = scaled_px(self, 22, minimum=16, maximum=24)
            layout.setContentsMargins(margin, margin, margin, scaled_px(self, 20, minimum=14, maximum=22))
            layout.setSpacing(scaled_px(self, 14, minimum=10, maximum=16))

        self.add_button.set_metrics(height=scaled_px(self, 42, minimum=38, maximum=44), icon_size=0)
        self.reset_button.set_metrics(height=scaled_px(self, 42, minimum=38, maximum=44), icon_size=0)
        self.close_button.set_metrics(height=scaled_px(self, 42, minimum=38, maximum=44), icon_size=0)
        self.preview.setMinimumHeight(scaled_px(self, 300, minimum=220, maximum=340))

    def _refresh_preview(self) -> None:
        background_path = self.service.get_active_background_path()
        self.preview.set_image_path(background_path)
        if background_path:
            self.caption.setText(Path(background_path).name)
        else:
            self.caption.setText("Add a default or custom image to show it across the launcher.")

    def _add_background(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Background",
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)",
        )
        if not file_path:
            return
        try:
            resolved = self.service.set_custom_background(file_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Background", str(exc))
            return
        self._refresh_preview()
        self.background_changed.emit(resolved)

    def _reset_background(self) -> None:
        self.service.reset_background()
        self._refresh_preview()
        self.background_changed.emit(self.service.get_active_background_path() or "")
