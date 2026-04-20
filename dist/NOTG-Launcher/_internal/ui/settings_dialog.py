from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEasingCurve, QRectF, QSize, Qt, Signal, QVariantAnimation, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QAbstractButton,
    QCheckBox,
    QFileDialog,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.launcher import LauncherService
from ui.app_icon import application_icon
from ui.responsive import fitted_window_size, scaled_px
from ui.theme import apply_theme, theme_palette
from ui.topbar import ModernButton, blend_colors


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
        palette = theme_palette(self)["background_preview"]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        outer = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(palette["outer_border"], 1.2))
        painter.setBrush(palette["outer_fill"])
        painter.drawRoundedRect(outer, 18, 18)

        inner = outer.adjusted(12, 12, -12, -12)
        painter.setPen(Qt.NoPen)
        painter.setBrush(palette["inner_fill"])
        painter.drawRoundedRect(inner, 14, 14)

        if self._pixmap.isNull():
            painter.setPen(palette["text"])
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


class ToggleSwitch(QAbstractButton):
    def __init__(self, checked: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self._progress = 1.0 if checked else 0.0
        self._animation = QVariantAnimation(
            self,
            duration=160,
            easingCurve=QEasingCurve.OutCubic,
            valueChanged=self._set_progress,
        )
        self.toggled.connect(self._animate_toggle)
        self.setChecked(checked)

    def sizeHint(self) -> QSize:
        return QSize(56, 30)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _set_progress(self, value: float) -> None:
        self._progress = float(value)
        self.update()

    def _animate_toggle(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._progress)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def paintEvent(self, event) -> None:
        del event
        palette = theme_palette(self)
        accent = palette["buttons"]["accent"]
        sidebar = palette["buttons"]["sidebar"]
        track_fill = blend_colors(sidebar["bg"], accent["bg"], self._progress)
        track_border = blend_colors(sidebar["border"], accent["border"], self._progress)
        thumb_fill = QColor("#fdfefe") if self.isChecked() else QColor(palette["line_edit"]["background_focus"])

        if not self.isEnabled():
            track_fill.setAlpha(int(track_fill.alpha() * 0.4))
            track_border.setAlpha(int(track_border.alpha() * 0.45))

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        painter.setPen(QPen(track_border, 1.1))
        painter.setBrush(track_fill)
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)

        knob_margin = 3.0
        knob_size = rect.height() - (knob_margin * 2)
        knob_x = rect.left() + knob_margin + ((rect.width() - knob_size - (knob_margin * 2)) * self._progress)
        knob_rect = QRectF(knob_x, rect.top() + knob_margin, knob_size, knob_size)
        painter.setPen(Qt.NoPen)
        painter.setBrush(thumb_fill)
        painter.drawEllipse(knob_rect)


class SettingsDialog(QDialog):
    background_changed = Signal(str)

    def __init__(self, service: LauncherService, parent: QWidget | None = None):
        super().__init__(parent)
        self.service = service

        self.setObjectName("settingsDialog")
        self.setWindowTitle("Settings")
        self.setWindowIcon(application_icon(self.service.project_root))
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
        root_layout.setContentsMargins(18, 18, 18, 16)
        root_layout.setSpacing(12)

        title = QLabel("Settings")
        title.setObjectName("editorCompactPageTitle")
        root_layout.addWidget(title)

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("settingsScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setAutoFillBackground(False)
        root_layout.addWidget(self.scroll_area, 1)

        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("settingsScrollContent")
        self.scroll_content.setAutoFillBackground(False)
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 6, 0)
        self.scroll_layout.setSpacing(18)
        self.scroll_area.setWidget(self.scroll_content)
        self.scroll_area.viewport().setAutoFillBackground(False)
        self.scroll_area.viewport().setAttribute(Qt.WA_StyledBackground, False)

        background_title = QLabel("Add Background")
        background_title.setObjectName("editorSectionTitle")
        self.scroll_layout.addWidget(background_title)

        background_actions = QHBoxLayout()
        background_actions.setContentsMargins(0, 0, 0, 0)
        background_actions.setSpacing(10)

        self.add_button = ModernButton("Add", role="accent", height=36, icon_size=0, minimum_width=82, horizontal_padding=20, font_point_size=10)
        self.add_button.clicked.connect(self._add_background)
        background_actions.addWidget(self.add_button)

        self.reset_button = ModernButton("Revert", role="sidebar", height=36, icon_size=0, minimum_width=86, horizontal_padding=20, font_point_size=10)
        self.reset_button.clicked.connect(self._reset_background)
        background_actions.addWidget(self.reset_button)

        self.folder_button = ModernButton("Folder", role="sidebar", height=36, icon_size=0, minimum_width=86, horizontal_padding=20, font_point_size=10)
        self.folder_button.clicked.connect(self._open_background_folder)
        background_actions.addWidget(self.folder_button)
        background_actions.addStretch()
        self.scroll_layout.addLayout(background_actions)

        preview_card = QFrame()
        preview_card.setObjectName("settingsPreviewCard")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(16, 16, 16, 16)
        preview_layout.setSpacing(10)

        self.preview = BackgroundPreview()
        preview_layout.addWidget(self.preview, 1)

        self.caption = QLabel("")
        self.caption.setObjectName("settingsCaption")
        self.caption.setWordWrap(True)
        preview_layout.addWidget(self.caption)
        self.scroll_layout.addWidget(preview_card)

        divider = QFrame()
        divider.setObjectName("editorSectionDivider")
        self.scroll_layout.addWidget(divider)

        general_title = QLabel("General")
        general_title.setObjectName("editorSectionTitle")
        self.scroll_layout.addWidget(general_title)

        theme_row = QHBoxLayout()
        theme_row.setContentsMargins(0, 0, 0, 0)
        theme_row.setSpacing(12)

        self.theme_switch = ToggleSwitch(checked=self.service.get_theme_mode() == "light")
        self.theme_switch.toggled.connect(self._set_light_theme)
        theme_row.addWidget(self.theme_switch, alignment=Qt.AlignLeft | Qt.AlignVCenter)

        self.theme_label = QLabel("Dark Mode/Light Mode")
        theme_row.addWidget(self.theme_label, 1, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        self.scroll_layout.addLayout(theme_row)

        self.close_on_launch_checkbox = QCheckBox("Close the launcher after game launch")
        self.close_on_launch_checkbox.setObjectName("editorFilterCheck")
        self.close_on_launch_checkbox.setChecked(self.service.get_close_ui_on_launch())
        self.close_on_launch_checkbox.toggled.connect(self._set_close_on_launch)
        self.scroll_layout.addWidget(self.close_on_launch_checkbox)
        self.scroll_layout.addStretch()

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(10)
        footer.addStretch()

        self.ok_button = ModernButton("OK", role="accent", height=38, icon_size=0, minimum_width=88, horizontal_padding=24, font_point_size=10)
        self.ok_button.clicked.connect(self.accept)
        footer.addWidget(self.ok_button)
        root_layout.addLayout(footer)

    def _apply_responsive_layout(self) -> None:
        layout = self.layout()
        if isinstance(layout, QVBoxLayout):
            margin = scaled_px(self, 18, minimum=14, maximum=20)
            layout.setContentsMargins(margin, margin, margin, scaled_px(self, 16, minimum=12, maximum=18))
            layout.setSpacing(scaled_px(self, 12, minimum=8, maximum=14))

        if isinstance(self.scroll_layout, QVBoxLayout):
            self.scroll_layout.setSpacing(scaled_px(self, 18, minimum=12, maximum=20))

        self.add_button.set_metrics(height=scaled_px(self, 36, minimum=32, maximum=38), icon_size=0)
        self.reset_button.set_metrics(height=scaled_px(self, 36, minimum=32, maximum=38), icon_size=0)
        self.folder_button.set_metrics(height=scaled_px(self, 36, minimum=32, maximum=38), icon_size=0)
        self.ok_button.set_metrics(height=scaled_px(self, 38, minimum=34, maximum=40), icon_size=0)
        self.preview.setMinimumHeight(scaled_px(self, 300, minimum=220, maximum=340))

    def _refresh_preview(self) -> None:
        background_path = self.service.get_active_background_path()
        self.preview.set_image_path(background_path)
        self.caption.setText(Path(background_path).name if background_path else "Default background")

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

    def _open_background_folder(self) -> None:
        self.service.backgrounds_root.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.service.backgrounds_root)))

    def _set_close_on_launch(self, checked: bool) -> None:
        try:
            self.service.set_close_ui_on_launch(checked)
        except Exception as exc:  # noqa: BLE001
            self.close_on_launch_checkbox.blockSignals(True)
            self.close_on_launch_checkbox.setChecked(not checked)
            self.close_on_launch_checkbox.blockSignals(False)
            QMessageBox.warning(self, "Gameplay behaviour", str(exc))

    def _set_light_theme(self, checked: bool) -> None:
        try:
            mode = self.service.set_theme_mode("light" if checked else "dark")
        except Exception as exc:  # noqa: BLE001
            self.theme_switch.blockSignals(True)
            self.theme_switch.setChecked(not checked)
            self.theme_switch.blockSignals(False)
            QMessageBox.warning(self, "Appearance", str(exc))
            return

        app = QApplication.instance()
        if app is not None:
            apply_theme(app, mode)
