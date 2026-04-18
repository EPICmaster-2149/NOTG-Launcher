from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEasingCurve, QRectF, QSize, Qt, QUrl, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.launcher import IconRecord, LauncherService
from ui.icon_utils import load_scaled_icon
from ui.topbar import ModernButton, blend_colors


class IconTile(QWidget):
    clicked = Signal(str)

    def __init__(self, icon_record: IconRecord, parent: QWidget | None = None):
        super().__init__(parent)
        self.icon_record = icon_record
        self._hover = 0.0
        self._press = 0.0
        self._selected = 0.0

        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setMouseTracking(True)

        self._hover_animation = QVariantAnimation(
            self,
            duration=170,
            easingCurve=QEasingCurve.OutCubic,
            valueChanged=self._set_hover,
        )
        self._press_animation = QVariantAnimation(
            self,
            duration=120,
            easingCurve=QEasingCurve.OutCubic,
            valueChanged=self._set_press,
        )
        self._selected_animation = QVariantAnimation(
            self,
            duration=180,
            easingCurve=QEasingCurve.OutCubic,
            valueChanged=self._set_selected,
        )

    def sizeHint(self) -> QSize:
        return QSize(132, 132)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def set_selected(self, selected: bool) -> None:
        self._selected_animation.stop()
        self._selected_animation.setStartValue(self._selected)
        self._selected_animation.setEndValue(1.0 if selected else 0.0)
        self._selected_animation.start()

    def _set_hover(self, value: float) -> None:
        self._hover = float(value)
        self.update()

    def _set_press(self, value: float) -> None:
        self._press = float(value)
        self.update()

    def _set_selected(self, value: float) -> None:
        self._selected = float(value)
        self.update()

    def enterEvent(self, event) -> None:
        self._hover_animation.stop()
        self._hover_animation.setStartValue(self._hover)
        self._hover_animation.setEndValue(1.0)
        self._hover_animation.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_animation.stop()
        self._hover_animation.setStartValue(self._hover)
        self._hover_animation.setEndValue(0.0)
        self._hover_animation.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press_animation.stop()
            self._press_animation.setStartValue(self._press)
            self._press_animation.setEndValue(1.0)
            self._press_animation.start()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._press_animation.stop()
        self._press_animation.setStartValue(self._press)
        self._press_animation.setEndValue(0.0)
        self._press_animation.start()
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.icon_record.relative_path)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        rect.translate(0, -1.3 * self._hover + 0.9 * self._press)

        shadow_rect = rect.adjusted(0, 6 + self._press, 0, 8 + self._press)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(4, 8, 17, int(44 + (28 * self._hover))))
        painter.drawRoundedRect(shadow_rect, 22, 22)

        fill_top = blend_colors(QColor("#101a2d"), QColor("#162540"), self._hover)
        fill_top = blend_colors(fill_top, QColor("#1b345d"), self._selected)
        fill_bottom = blend_colors(QColor("#0b1423"), QColor("#122037"), self._hover)
        fill_bottom = blend_colors(fill_bottom, QColor("#132a4b"), self._selected)
        border = blend_colors(QColor("#253a5d"), QColor("#4f7dd0"), self._selected)
        border = blend_colors(border, QColor("#6a9cff"), self._hover * 0.4)

        painter.setPen(QPen(border, 1.25))
        painter.setBrush(fill_top)
        painter.drawRoundedRect(rect, 22, 22)

        inner = rect.adjusted(10, 10, -10, -10)
        inner_fill = blend_colors(QColor("#15243a"), QColor("#1a2e4b"), self._hover * 0.5)
        inner_fill = blend_colors(inner_fill, QColor("#1d3760"), self._selected * 0.7)
        painter.setPen(QPen(QColor("#2f486f"), 1.0))
        painter.setBrush(inner_fill)
        painter.drawRoundedRect(inner, 18, 18)

        pixmap = load_scaled_icon(self.icon_record.absolute_path, 74, 74)
        if not pixmap.isNull():
            pix_x = inner.center().x() - (pixmap.width() / 2)
            pix_y = inner.center().y() - (pixmap.height() / 2)
            painter.drawPixmap(int(pix_x), int(pix_y), pixmap)

        if self._selected > 0.02:
            glow = rect.adjusted(2, 2, -2, -2)
            accent = blend_colors(QColor(92, 162, 255, 0), QColor(128, 201, 255, 72), self._selected)
            painter.setPen(QPen(accent, 2.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(glow, 20, 20)


class IconSelectorDialog(QDialog):
    def __init__(
        self,
        service: LauncherService,
        selected_icon_path: str | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.service = service
        self.selected_icon_path = selected_icon_path or self.service.default_icon
        self._tiles: dict[str, IconTile] = {}

        self.setObjectName("iconSelectorDialog")
        self.setWindowTitle("Pick Icon")
        self.setModal(True)
        self.resize(560, 620)
        self.setMinimumSize(520, 560)

        self._build_ui()
        self._reload_icons(self.selected_icon_path)

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(20, 20, 20, 20)
        root_layout.setSpacing(14)

        presentation = QFrame()
        presentation.setObjectName("iconPresentationSurface")
        presentation_layout = QVBoxLayout(presentation)
        presentation_layout.setContentsMargins(14, 14, 14, 14)
        presentation_layout.setSpacing(0)
        root_layout.addWidget(presentation, 1)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setObjectName("iconPresentationScroll")
        presentation_layout.addWidget(self.scroll_area)

        self.grid_holder = QWidget()
        self.grid_layout = QGridLayout(self.grid_holder)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setHorizontalSpacing(12)
        self.grid_layout.setVerticalSpacing(12)
        self.scroll_area.setWidget(self.grid_holder)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(10)
        root_layout.addLayout(footer)

        self.add_icon_button = ModernButton("Add Icon", role="sidebar", height=44, icon_size=0)
        self.add_icon_button.clicked.connect(self._add_icon)
        footer.addWidget(self.add_icon_button)

        self.remove_icon_button = ModernButton("Remove Icon", role="danger", height=44, icon_size=0)
        self.remove_icon_button.clicked.connect(self._remove_selected_icon)
        footer.addWidget(self.remove_icon_button)

        self.open_folder_button = ModernButton("Open Folder", role="sidebar", height=44, icon_size=0)
        self.open_folder_button.clicked.connect(self._open_folder)
        footer.addWidget(self.open_folder_button)

        footer.addStretch()

        self.ok_button = ModernButton("OK", role="accent", height=44, icon_size=0)
        self.ok_button.clicked.connect(self._confirm_selection)
        footer.addWidget(self.ok_button)

        self.cancel_button = ModernButton("Cancel", role="sidebar", height=44, icon_size=0)
        self.cancel_button.clicked.connect(self.reject)
        footer.addWidget(self.cancel_button)

    def _reload_icons(self, preferred_icon: str | None = None) -> None:
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._tiles.clear()
        icons = self.service.list_instance_icons()
        selected_icon = preferred_icon or self.selected_icon_path or self.service.default_icon
        available_paths = {icon.relative_path for icon in icons}
        if selected_icon not in available_paths:
            selected_icon = self.service.default_icon

        for index, icon in enumerate(icons):
            tile = IconTile(icon, self.grid_holder)
            tile.clicked.connect(self._select_icon)
            row = index // 3
            column = index % 3
            self.grid_layout.addWidget(tile, row, column)
            self._tiles[icon.relative_path] = tile

        self.grid_layout.setColumnStretch(0, 1)
        self.grid_layout.setColumnStretch(1, 1)
        self.grid_layout.setColumnStretch(2, 1)
        self._select_icon(selected_icon)

    def _select_icon(self, relative_path: str) -> None:
        if relative_path not in self._tiles:
            return

        self.selected_icon_path = relative_path
        for icon_path, tile in self._tiles.items():
            tile.set_selected(icon_path == relative_path)

    def _add_icon(self) -> None:
        start_dir = str(self.service.project_root)
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Add Custom Icon",
            start_dir,
            "PNG Image (*.png)",
        )
        if not file_path:
            return

        try:
            relative_path = self.service.store_user_icon(file_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Icon Error", str(exc))
            return

        self._reload_icons(relative_path)

    def _remove_selected_icon(self) -> None:
        selected_tile = self._tiles.get(self.selected_icon_path)
        if selected_tile is None:
            self.remove_icon_button.flash_invalid()
            return
        if selected_tile.icon_record.is_default:
            self.remove_icon_button.flash_invalid()
            return

        try:
            removed = self.service.remove_user_icon(self.selected_icon_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Icon Error", str(exc))
            return

        if not removed:
            self.remove_icon_button.flash_invalid()
            return

        self._reload_icons(self.service.default_icon)

    def _open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.service.icons_folder())))

    def _confirm_selection(self) -> None:
        if self.selected_icon_path not in self._tiles:
            self.ok_button.flash_invalid()
            return
        self.accept()
