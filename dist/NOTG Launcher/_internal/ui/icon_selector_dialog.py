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
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.launcher import IconRecord, LauncherService
from ui.icon_utils import load_scaled_icon
from ui.responsive import fitted_window_size, scaled_px, screen_scale
from ui.theme import theme_palette
from ui.topbar import ModernButton, blend_colors


class IconTile(QWidget):
    clicked = Signal(str)

    def __init__(self, icon_record: IconRecord, parent: QWidget | None = None):
        super().__init__(parent)
        self.icon_record = icon_record
        self._side_length = 140
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
        return QSize(self._side_length, self._side_length)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def set_side_length(self, side_length: int) -> None:
        self._side_length = side_length
        self.setFixedSize(side_length, side_length)
        self.updateGeometry()
        self.update()

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
        palette = theme_palette(self)["icon_tile"]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        scale = screen_scale(self, minimum=0.9, maximum=1.05)

        inset = 8 * scale
        rect = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        rect.translate(0, -1.1 * self._hover + 0.8 * self._press)

        shadow_rect = rect.adjusted(0, 5 * scale + self._press, 0, 7 * scale + self._press)
        painter.setPen(Qt.NoPen)
        shadow = blend_colors(palette["shadow"], palette["shadow_hover"], self._hover)
        painter.setBrush(shadow)
        painter.drawRoundedRect(shadow_rect, 18 * scale, 18 * scale)

        fill_top = blend_colors(palette["outer_top"], palette["outer_top_hover"], self._hover)
        fill_top = blend_colors(fill_top, palette["outer_top_selected"], self._selected)
        fill_bottom = blend_colors(palette["outer_bottom"], palette["outer_bottom_hover"], self._hover)
        fill_bottom = blend_colors(fill_bottom, palette["outer_bottom_selected"], self._selected)
        border = blend_colors(palette["border"], palette["border_selected"], self._selected)
        border = blend_colors(border, palette["border_hover"], self._hover * 0.4)

        painter.setPen(QPen(border, max(1.0, 1.15 * scale)))
        painter.setBrush(fill_top)
        painter.drawRoundedRect(rect, 18 * scale, 18 * scale)

        inner = rect.adjusted(10 * scale, 10 * scale, -10 * scale, -10 * scale)
        inner_fill = blend_colors(palette["inner_fill"], palette["inner_fill_hover"], self._hover * 0.5)
        inner_fill = blend_colors(inner_fill, palette["inner_fill_selected"], self._selected * 0.7)
        painter.setPen(QPen(palette["inner_border"], max(1.0, scale)))
        painter.setBrush(inner_fill)
        painter.drawRoundedRect(inner, 16 * scale, 16 * scale)

        icon_side = scaled_px(self, 74, minimum=66, maximum=78, scale_min=0.9, scale_max=1.05)
        pixmap = load_scaled_icon(self.icon_record.absolute_path, icon_side, icon_side)
        if not pixmap.isNull():
            pix_x = inner.center().x() - (pixmap.width() / 2)
            pix_y = inner.center().y() - (pixmap.height() / 2)
            painter.drawPixmap(int(pix_x), int(pix_y), pixmap)

        if self._selected > 0.02:
            glow = rect.adjusted(2 * scale, 2 * scale, -2 * scale, -2 * scale)
            accent = blend_colors(palette["glow_start"], palette["glow_end"], self._selected)
            painter.setPen(QPen(accent, max(1.2, 1.8 * scale)))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(glow, 16 * scale, 16 * scale)


class IconSelectorDialog(QDialog):
    _GRID_COLUMNS = 5

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
        self.setMinimumSize(760, 700)
        self.resize(fitted_window_size(self.parentWidget() or self, 920, 860, minimum_width=760, minimum_height=700))

        self._build_ui()
        self._apply_responsive_layout()
        self._reload_icons(self.selected_icon_path)

    def showEvent(self, event) -> None:
        self._apply_responsive_layout()
        super().showEvent(event)

    def resizeEvent(self, event) -> None:
        self._apply_responsive_layout()
        super().resizeEvent(event)

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
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll_area.setWidget(self.grid_holder)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(10)
        root_layout.addLayout(footer)

        self.add_icon_button = ModernButton("Add Icon", role="sidebar", height=44, icon_size=0)
        self.add_icon_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.add_icon_button.clicked.connect(self._add_icon)
        footer.addWidget(self.add_icon_button)

        self.remove_icon_button = ModernButton("Remove Icon", role="danger", height=44, icon_size=0)
        self.remove_icon_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.remove_icon_button.clicked.connect(self._remove_selected_icon)
        footer.addWidget(self.remove_icon_button)

        self.open_folder_button = ModernButton("Open Folder", role="sidebar", height=44, icon_size=0)
        self.open_folder_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.open_folder_button.clicked.connect(self._open_folder)
        footer.addWidget(self.open_folder_button)

        footer.addStretch()

        self.ok_button = ModernButton("OK", role="accent", height=44, icon_size=0)
        self.ok_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.ok_button.clicked.connect(self._confirm_selection)
        footer.addWidget(self.ok_button)

        self.cancel_button = ModernButton("Cancel", role="sidebar", height=44, icon_size=0)
        self.cancel_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
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
            row = index // self._GRID_COLUMNS
            column = index % self._GRID_COLUMNS
            self.grid_layout.addWidget(tile, row, column)
            self._tiles[icon.relative_path] = tile

        for column in range(self._GRID_COLUMNS):
            self.grid_layout.setColumnStretch(column, 0)
        self._select_icon(selected_icon)

    def _apply_responsive_layout(self) -> None:
        layout = self.layout()
        if isinstance(layout, QVBoxLayout):
            margin = scaled_px(self, 20, minimum=16, maximum=24)
            layout.setContentsMargins(margin, margin, margin, margin)
            layout.setSpacing(scaled_px(self, 14, minimum=12, maximum=18))

        self.grid_layout.setHorizontalSpacing(scaled_px(self, 12, minimum=10, maximum=14))
        self.grid_layout.setVerticalSpacing(scaled_px(self, 12, minimum=10, maximum=14))
        tile_side = scaled_px(self, 156, minimum=132, maximum=164, scale_min=0.92, scale_max=1.0)
        for tile in self._tiles.values():
            tile.set_side_length(tile_side)
        self.add_icon_button.set_metrics(height=scaled_px(self, 46, minimum=42, maximum=48), icon_size=0)
        self.remove_icon_button.set_metrics(height=scaled_px(self, 46, minimum=42, maximum=48), icon_size=0)
        self.open_folder_button.set_metrics(height=scaled_px(self, 46, minimum=42, maximum=48), icon_size=0)
        self.ok_button.set_metrics(height=scaled_px(self, 46, minimum=42, maximum=48), icon_size=0)
        self.cancel_button.set_metrics(height=scaled_px(self, 46, minimum=42, maximum=48), icon_size=0)

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
