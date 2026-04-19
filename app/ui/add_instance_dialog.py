from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QEasingCurve,
    QEvent,
    QModelIndex,
    QRectF,
    QSortFilterProxyModel,
    QThread,
    QTimer,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

import psutil

from core.launcher import LauncherService
from ui.icon_selector_dialog import IconSelectorDialog
from ui.icon_utils import load_scaled_icon
from ui.responsive import fitted_window_size, scaled_px, screen_scale
from ui.topbar import ModernButton, blend_colors


class AccentLineEdit(QLineEdit):
    def __init__(self, placeholder: str, large: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._large = large
        self._focus_progress = 0.0
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setOffset(0, 0)
        self._shadow.setBlurRadius(0)
        self._shadow.setColor(QColor(124, 199, 255, 0))
        self.setGraphicsEffect(self._shadow)
        self.setPlaceholderText(placeholder)
        self.setObjectName("accentLineEdit")

        self._focus_animation = QVariantAnimation(
            self,
            duration=180,
            valueChanged=self._set_focus_progress,
        )
        self._apply_style()

    def _set_focus_progress(self, value: Any) -> None:
        self._focus_progress = float(value)
        self._apply_style()

    def _animate_to(self, target: float) -> None:
        self._focus_animation.stop()
        self._focus_animation.setStartValue(self._focus_progress)
        self._focus_animation.setEndValue(target)
        self._focus_animation.start()

    def _apply_style(self) -> None:
        border = blend_colors(QColor("#2f496e"), QColor("#7bc4ff"), self._focus_progress)
        background = blend_colors(QColor("#101a2d"), QColor("#12213a"), self._focus_progress * 0.55)
        shadow = QColor(123, 196, 255, int(120 * self._focus_progress))
        self._shadow.setBlurRadius(24 * self._focus_progress)
        self._shadow.setColor(shadow)

        font_size = 22 if self._large else 13
        padding = "16px 18px" if self._large else "12px 14px"
        radius = 12 if self._large else 10
        self.setStyleSheet(
            f"""
            QLineEdit {{
                background-color: rgba({background.red()}, {background.green()}, {background.blue()}, {background.alpha()});
                border: 1px solid rgba({border.red()}, {border.green()}, {border.blue()}, {border.alpha()});
                border-radius: {radius}px;
                color: #f1f6ff;
                padding: {padding};
                font-size: {font_size}px;
                font-weight: {'700' if self._large else '500'};
                selection-background-color: rgba(124, 199, 255, 0.35);
            }}
            QLineEdit::placeholder {{
                color: rgba(186, 205, 235, 0.55);
            }}
            """
        )

    def focusInEvent(self, event) -> None:
        self._animate_to(1.0)
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        self._animate_to(0.0)
        super().focusOutEvent(event)


class CatalogTableModel(QAbstractTableModel):
    def __init__(self, headers: list[str], key_order: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        self._headers = headers
        self._key_order = key_order
        self._rows: list[dict[str, Any]] = []

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def row(self, row: int) -> dict[str, Any]:
        return self._rows[row]

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._headers)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None

        row = self._rows[index.row()]
        key = self._key_order[index.column()]

        if role == Qt.DisplayRole:
            value = row.get(key, "")
            return "" if value is None else str(value)

        if role == Qt.UserRole:
            return row

        if role == Qt.TextAlignmentRole:
            if index.column() == 0:
                return Qt.AlignVCenter | Qt.AlignLeft
            return Qt.AlignCenter

        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if role != Qt.DisplayRole:
            return None

        if orientation == Qt.Horizontal:
            return self._headers[section]

        return str(section + 1)


class VersionFilterProxyModel(QSortFilterProxyModel):
    def __init__(self, service: LauncherService, parent: QWidget | None = None):
        super().__init__(parent)
        self._service = service
        self._search_text = ""
        self._enabled_types = {"release"}

    def set_search_text(self, text: str) -> None:
        self._search_text = text.strip().lower()
        self.invalidateFilter()

    def set_enabled_types(self, enabled_types: set[str]) -> None:
        self._enabled_types = set(enabled_types)
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        if model is None:
            return False

        row = model.row(source_row)
        version_type = str(row["type"]).lower()
        allowed = version_type in self._enabled_types
        if not allowed and "__experiments__" in self._enabled_types:
            allowed = self._service.is_experiment_type(version_type)
        if not allowed:
            return False

        if not self._search_text:
            return True

        search_blob = " ".join(
            [
                str(row.get("id", "")),
                str(row.get("type_label", "")),
                str(row.get("release_display", "")),
            ]
        ).lower()
        return self._search_text in search_blob


class SearchFilterProxyModel(QSortFilterProxyModel):
    def __init__(self, keys: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        self._keys = keys
        self._search_text = ""

    def set_search_text(self, text: str) -> None:
        self._search_text = text.strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        if not self._search_text:
            return True

        model = self.sourceModel()
        if model is None:
            return False

        row = model.row(source_row)
        search_blob = " ".join(str(row.get(key, "")) for key in self._keys).lower()
        return self._search_text in search_blob


class CatalogWorker(QThread):
    loaded = Signal(str, int, object)
    failed = Signal(str, int, str)

    def __init__(
        self,
        service: LauncherService,
        job: str,
        request_id: int,
        *,
        force_refresh: bool = False,
        loader_id: str | None = None,
        minecraft_version: str | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._service = service
        self._job = job
        self._request_id = request_id
        self._force_refresh = force_refresh
        self._loader_id = loader_id
        self._minecraft_version = minecraft_version

    def run(self) -> None:
        try:
            if self._job == "versions":
                payload = self._service.get_version_catalog(force_refresh=self._force_refresh)
            elif self._job == "loader_versions":
                if not self._loader_id or not self._minecraft_version:
                    raise ValueError("Missing mod loader request context.")
                payload = self._service.get_loader_versions(
                    self._loader_id,
                    self._minecraft_version,
                    force_refresh=self._force_refresh,
                )
            else:
                raise ValueError(f"Unsupported catalog job: {self._job}")
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(self._job, self._request_id, str(exc))
            return

        self.loaded.emit(self._job, self._request_id, payload)


class LoaderPlaceholder(QWidget):
    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._text = text
        self.setObjectName("loaderPlaceholder")

    def set_text(self, text: str) -> None:
        self._text = text
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        outer = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor("#253756"), 1.2))
        painter.setBrush(QColor(11, 18, 30, 180))
        painter.drawRoundedRect(outer, 12, 12)

        box = QRectF(
            self.width() * 0.12,
            self.height() * 0.38,
            self.width() * 0.76,
            min(96.0, self.height() * 0.28),
        )
        painter.setPen(QPen(QColor("#d5ebff"), 1.0))
        painter.setBrush(QColor(235, 244, 255, 235))
        painter.drawRoundedRect(box, 10, 10)

        font = QFont(self.font())
        font.setPointSize(13)
        font.setWeight(QFont.Bold)
        painter.setFont(font)
        painter.setPen(QColor("#3f5778"))
        painter.drawText(box, Qt.AlignCenter, self._text)


class ClickableAccentLineEdit(AccentLineEdit):
    clicked = Signal()

    def mouseReleaseEvent(self, event) -> None:
        if self.isReadOnly() and event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class BrowseInput(QWidget):
    browse_requested = Signal()

    def __init__(self, placeholder: str, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.line_edit = ClickableAccentLineEdit(placeholder)
        self.line_edit.setReadOnly(True)
        self.line_edit.clicked.connect(self.browse_requested)
        layout.addWidget(self.line_edit, 1)

        self.browse_button = ModernButton("Browse", role="sidebar", height=46, icon_size=0)
        self.browse_button.clicked.connect(self.browse_requested)
        layout.addWidget(self.browse_button)

    def text(self) -> str:
        return self.line_edit.text().strip()

    def setText(self, text: str) -> None:
        self.line_edit.setText(text)

    def clear(self) -> None:
        self.line_edit.clear()

    def focus_field(self) -> None:
        self.line_edit.setFocus()


class SearchableComboBox(QComboBox):
    def __init__(self, placeholder: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("editorComboBox")
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setSizeAdjustPolicy(QComboBox.AdjustToContentsOnFirstShow)
        self.setMaxVisibleItems(10)
        self.lineEdit().setPlaceholderText(placeholder)
        self.lineEdit().installEventFilter(self)

        completer = QCompleter(self.model(), self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        self.setCompleter(completer)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.lineEdit() and event.type() == QEvent.MouseButtonPress and self.count():
            self.showPopup()
        return super().eventFilter(watched, event)

    def selected_value(self) -> str | None:
        value = self.currentData(Qt.UserRole)
        if value:
            return str(value)
        typed_text = self.currentText().strip().lower()
        if not typed_text:
            return None
        for index in range(self.count()):
            if self.itemText(index).strip().lower() == typed_text:
                match = self.itemData(index, Qt.UserRole)
                return str(match) if match else None
        return None


class HeaderIconButton(QWidget):
    clicked = Signal()

    def __init__(self, icon_path: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._icon_path = icon_path
        self._hover = 0.0
        self._press = 0.0
        self._side_length = 104

        self.setObjectName("editorInstanceIcon")
        self.setFixedSize(self._side_length, self._side_length)
        self.setCursor(Qt.PointingHandCursor)
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

    def set_icon_path(self, icon_path: str) -> None:
        self._icon_path = icon_path
        self.update()

    def set_side_length(self, side_length: int) -> None:
        self._side_length = side_length
        self.setFixedSize(side_length, side_length)
        self.update()

    def _set_hover(self, value: Any) -> None:
        self._hover = float(value)
        self.update()

    def _set_press(self, value: Any) -> None:
        self._press = float(value)
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
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        scale = screen_scale(self, minimum=0.78, maximum=1.05)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rect.translate(0, -1.0 * self._hover + 0.8 * self._press)

        top_fill = blend_colors(QColor("#17263d"), QColor("#1d3354"), self._hover)
        bottom_fill = blend_colors(QColor("#112036"), QColor("#182c47"), self._hover)
        border = blend_colors(QColor("#43618c"), QColor("#7bc4ff"), self._hover)
        border = blend_colors(border, QColor("#9bd4ff"), self._press * 0.5)

        painter.setPen(QPen(border, max(1.0, 1.25 * scale)))
        painter.setBrush(top_fill)
        painter.drawRoundedRect(rect, 16 * scale, 16 * scale)

        inset = 8 * scale
        inner = rect.adjusted(inset, inset, -inset, -inset)
        painter.setPen(QPen(QColor("#2e4669"), max(1.0, scale)))
        painter.setBrush(bottom_fill)
        painter.drawRoundedRect(inner, 14 * scale, 14 * scale)

        icon_side = max(48, int(min(inner.width(), inner.height()) * 0.82))
        icon = load_scaled_icon(self._icon_path, icon_side, icon_side)
        if not icon.isNull():
            icon_x = inner.center().x() - (icon.width() / 2)
            icon_y = inner.center().y() - (icon.height() / 2)
            painter.drawPixmap(int(icon_x), int(icon_y), icon)

        if self._hover > 0.04:
            glow_inset = 2 * scale
            glow = rect.adjusted(glow_inset, glow_inset, -glow_inset, -glow_inset)
            accent = QColor(126, 194, 255, int(54 * self._hover))
            painter.setPen(QPen(accent, max(1.2, 2.0 * scale)))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(glow, 14 * scale, 14 * scale)


class AddInstanceDialog(QDialog):
    PAGE_CREATE = 0
    PAGE_IMPORT = 1

    def __init__(self, service: LauncherService, parent: QWidget | None = None):
        super().__init__(parent)
        self.service = service
        self.selection: dict[str, Any] | None = None
        self._current_loader_id: str | None = None
        self._selected_icon_path = self.service.default_icon
        self._version_request_id = 0
        self._loader_request_id = 0
        self._workers: set[QThread] = set()
        self._copy_source_instances: list[dict[str, str]] = []
        self._ram_default_mb = 2048
        self._ram_slider_step_mb = 256
        self._ram_selected_mb = self._ram_default_mb
        self._ram_displayed_mb = self._ram_default_mb

        self.setObjectName("instanceEditor")
        self.setWindowTitle("Create New Instance")
        self.setModal(True)
        self.setMinimumSize(860, 620)
        self.resize(fitted_window_size(self.parentWidget() or self, 1120, 780, minimum_width=860, minimum_height=620))

        self._build_ui()
        self._apply_responsive_layout()
        self._sync_header_icon()
        self._reload_copy_source_instances()
        self._update_ram_slider_range()
        self._set_ram_value(self._ram_default_mb, animate=False)
        self._update_page_state(self.PAGE_CREATE)
        QTimer.singleShot(0, lambda: self._load_versions(force_refresh=False))

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
        header.setObjectName("instanceEditorHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(22, 18, 22, 18)
        header_layout.setSpacing(18)

        self.icon_button = HeaderIconButton(self.service.resolve_icon_path(self._selected_icon_path))
        self.icon_button.clicked.connect(self._open_icon_selector)
        header_layout.addWidget(self.icon_button)

        name_column = QVBoxLayout()
        name_column.setSpacing(10)

        self.header_title = QLabel("Create A New Instance")
        self.header_title.setObjectName("editorEyebrow")
        name_column.addWidget(self.header_title)

        self.name_edit = AccentLineEdit("Enter a name or use the selected version", large=True)
        self.name_edit.setMinimumHeight(66)
        name_column.addWidget(self.name_edit)
        header_layout.addLayout(name_column, 1)
        root_layout.addWidget(header)

        shell = QFrame()
        shell.setObjectName("instanceEditorShell")
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        root_layout.addWidget(shell, 1)

        nav_frame = QFrame()
        nav_frame.setObjectName("instanceEditorNav")
        self.nav_frame = nav_frame
        nav_layout = QVBoxLayout(nav_frame)
        nav_layout.setContentsMargins(14, 18, 14, 18)
        nav_layout.setSpacing(12)

        nav_title = QLabel("Options")
        nav_title.setObjectName("editorNavTitle")
        nav_layout.addWidget(nav_title)

        self.nav_list = QListWidget()
        self.nav_list.setObjectName("instanceEditorNavList")
        self.nav_list.setSpacing(8)
        self.nav_list.setFrameShape(QFrame.NoFrame)
        self.nav_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        for title in ("Create", "Import"):
            item = QListWidgetItem(title)
            item.setSizeHint(item.sizeHint().expandedTo(item.sizeHint()))
            self.nav_list.addItem(item)
        self.nav_list.currentRowChanged.connect(self._update_page_state)
        nav_layout.addWidget(self.nav_list, 1)
        shell_layout.addWidget(nav_frame)

        content = QFrame()
        content.setObjectName("instanceEditorContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 20)
        content_layout.setSpacing(14)

        self.page_title = QLabel("Create")
        self.page_title.setObjectName("editorPageTitle")
        content_layout.addWidget(self.page_title)

        divider = QFrame()
        divider.setObjectName("editorPrimaryDivider")
        content_layout.addWidget(divider)

        self.page_stack = QStackedWidget()
        self.page_stack.addWidget(self._build_create_page())
        self.page_stack.addWidget(self._build_import_page())
        content_layout.addWidget(self.page_stack, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(12)
        footer.addStretch()

        self.cancel_button = ModernButton("Cancel", role="sidebar", height=44, icon_size=0)
        self.cancel_button.clicked.connect(self.reject)
        footer.addWidget(self.cancel_button)

        self.ok_button = ModernButton("Install", role="accent", height=44, icon_size=0)
        self.ok_button.clicked.connect(self._accept_selection)
        footer.addWidget(self.ok_button)
        content_layout.addLayout(footer)
        shell_layout.addWidget(content, 1)
        self.nav_list.setCurrentRow(0)

    def _build_create_page(self) -> QWidget:
        self.create_tabs = QTabWidget()
        self.create_tabs.setObjectName("editorCreateTabs")
        self.create_tabs.addTab(self._build_general_tab(), "General")
        self.create_tabs.addTab(self._build_advanced_tab(), "Advanced")
        return self.create_tabs

    def _build_general_tab(self) -> QWidget:
        scroll_area = QScrollArea()
        scroll_area.setObjectName("instanceEditorScroll")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 6, 0)
        scroll_layout.setSpacing(14)

        selection_surface = QFrame()
        selection_surface.setObjectName("editorSelectionSurface")
        selection_layout = QVBoxLayout(selection_surface)
        selection_layout.setContentsMargins(18, 18, 18, 18)
        selection_layout.setSpacing(18)

        version_section = self._build_version_section()
        loader_section = self._build_loader_section()
        selection_layout.addWidget(version_section, 1)

        section_divider = QFrame()
        section_divider.setObjectName("editorSectionDivider")
        selection_layout.addWidget(section_divider)
        selection_layout.addWidget(loader_section, 1)

        scroll_layout.addWidget(selection_surface)
        scroll_area.setWidget(scroll_widget)
        return scroll_area

    def _build_advanced_tab(self) -> QWidget:
        scroll_area = QScrollArea()
        scroll_area.setObjectName("instanceEditorScroll")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 6, 0)
        scroll_layout.setSpacing(14)

        advanced_surface = QFrame()
        advanced_surface.setObjectName("editorSelectionSurface")
        advanced_layout = QVBoxLayout(advanced_surface)
        advanced_layout.setContentsMargins(18, 18, 18, 18)
        advanced_layout.setSpacing(18)

        copy_title = QLabel("Copy From Instance")
        copy_title.setObjectName("editorSectionTitle")
        advanced_layout.addWidget(copy_title)

        self.copy_source_combo = SearchableComboBox("Search or select an existing instance")
        self.copy_source_combo.currentIndexChanged.connect(self._on_copy_source_changed)
        advanced_layout.addWidget(self.copy_source_combo)

        copy_lists_row = QHBoxLayout()
        copy_lists_row.setContentsMargins(0, 0, 0, 0)
        copy_lists_row.setSpacing(12)
        advanced_layout.addLayout(copy_lists_row)

        self.copy_available_list = QListWidget()
        self.copy_available_list.setObjectName("editorTransferList")
        self.copy_available_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.copy_available_list.itemDoubleClicked.connect(lambda *_: self._move_copy_items(self.copy_available_list, self.copy_selected_list))

        self.copy_selected_list = QListWidget()
        self.copy_selected_list.setObjectName("editorTransferList")
        self.copy_selected_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.copy_selected_list.itemDoubleClicked.connect(lambda *_: self._move_copy_items(self.copy_selected_list, self.copy_available_list))

        available_column = self._build_transfer_column("Copy From", self.copy_available_list)
        selected_column = self._build_transfer_column("Copy To", self.copy_selected_list)
        copy_lists_row.addWidget(available_column, 1)

        transfer_controls = QVBoxLayout()
        transfer_controls.setContentsMargins(0, 22, 0, 0)
        transfer_controls.setSpacing(10)
        copy_lists_row.addLayout(transfer_controls)

        self.copy_add_button = ModernButton(">", role="sidebar", height=38, icon_size=0, radius=10, minimum_width=56, horizontal_padding=24)
        self.copy_add_button.clicked.connect(lambda: self._move_copy_items(self.copy_available_list, self.copy_selected_list))
        transfer_controls.addWidget(self.copy_add_button)

        self.copy_remove_button = ModernButton("<", role="sidebar", height=38, icon_size=0, radius=10, minimum_width=56, horizontal_padding=24)
        self.copy_remove_button.clicked.connect(lambda: self._move_copy_items(self.copy_selected_list, self.copy_available_list))
        transfer_controls.addWidget(self.copy_remove_button)

        self.copy_all_button = ModernButton(">>", role="accent", height=38, icon_size=0, radius=10, minimum_width=56, horizontal_padding=24)
        self.copy_all_button.clicked.connect(self._move_all_copy_items)
        transfer_controls.addWidget(self.copy_all_button)

        self.copy_clear_button = ModernButton("<<", role="sidebar", height=38, icon_size=0, radius=10, minimum_width=56, horizontal_padding=24)
        self.copy_clear_button.clicked.connect(self._clear_copy_selection)
        transfer_controls.addWidget(self.copy_clear_button)
        transfer_controls.addStretch()

        copy_lists_row.addWidget(selected_column, 1)

        divider = QFrame()
        divider.setObjectName("editorSectionDivider")
        advanced_layout.addWidget(divider)

        ram_title = QLabel("Memory")
        ram_title.setObjectName("editorSectionTitle")
        advanced_layout.addWidget(ram_title)

        ram_row = QHBoxLayout()
        ram_row.setContentsMargins(0, 0, 0, 0)
        ram_row.setSpacing(14)
        advanced_layout.addLayout(ram_row)

        self.ram_slider = QSlider(Qt.Horizontal)
        self.ram_slider.setObjectName("editorRamSlider")
        self.ram_slider.setSingleStep(1)
        self.ram_slider.setPageStep(4)
        self.ram_slider.valueChanged.connect(self._on_ram_slider_changed)
        ram_row.addWidget(self.ram_slider, 1)

        self.ram_display = AccentLineEdit("RAM (MB)")
        self.ram_display.setReadOnly(True)
        self.ram_display.setMinimumWidth(180)
        ram_row.addWidget(self.ram_display)

        ram_actions = QHBoxLayout()
        ram_actions.setContentsMargins(0, 0, 0, 0)
        ram_actions.setSpacing(12)
        advanced_layout.addLayout(ram_actions)

        self.ram_revert_button = ModernButton("Revert", role="sidebar", height=40, icon_size=0, radius=10, minimum_width=118, horizontal_padding=34)
        self.ram_revert_button.clicked.connect(self._revert_ram_value)
        ram_actions.addWidget(self.ram_revert_button)

        self.ram_confirm_button = ModernButton("Confirm", role="accent", height=40, icon_size=0, radius=10, minimum_width=124, horizontal_padding=36)
        self.ram_confirm_button.clicked.connect(self._confirm_ram_value)
        ram_actions.addWidget(self.ram_confirm_button)
        ram_actions.addStretch()

        advanced_layout.addStretch()
        scroll_layout.addWidget(advanced_surface)
        scroll_area.setWidget(scroll_widget)
        return scroll_area

    def _build_import_page(self) -> QWidget:
        scroll_area = QScrollArea()
        scroll_area.setObjectName("instanceEditorScroll")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 6, 0)
        scroll_layout.setSpacing(14)

        import_surface = QFrame()
        import_surface.setObjectName("editorSelectionSurface")
        import_layout = QVBoxLayout(import_surface)
        import_layout.setContentsMargins(22, 22, 22, 22)
        import_layout.setSpacing(20)

        self.modpack_input = BrowseInput("Select a modpack archive (.mrpack or .zip)")
        self.modpack_input.browse_requested.connect(self._browse_modpack)
        import_layout.addWidget(self.modpack_input)

        modpack_caption = QLabel("EXPORT MODPACKS")
        modpack_caption.setObjectName("editorImportCaption")
        modpack_caption.setAlignment(Qt.AlignLeft)
        import_layout.addWidget(modpack_caption)

        import_divider = QFrame()
        import_divider.setObjectName("editorSectionDivider")
        import_layout.addWidget(import_divider)

        self.minecraft_input = BrowseInput("Select a .minecraft folder to import")
        self.minecraft_input.browse_requested.connect(self._browse_minecraft_folder)
        import_layout.addWidget(self.minecraft_input)

        minecraft_caption = QLabel("IMPORT .minecraft folder")
        minecraft_caption.setObjectName("editorImportCaption")
        minecraft_caption.setAlignment(Qt.AlignLeft)
        import_layout.addWidget(minecraft_caption)
        import_layout.addStretch()

        scroll_layout.addWidget(import_surface)
        scroll_area.setWidget(scroll_widget)
        return scroll_area

    def _build_transfer_column(self, title_text: str, list_widget: QListWidget) -> QWidget:
        column = QWidget()
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel(title_text)
        title.setObjectName("editorFilterTitle")
        layout.addWidget(title)
        layout.addWidget(list_widget, 1)
        return column

    def _update_page_state(self, index: int) -> None:
        target_index = self.PAGE_CREATE if index < 0 else index
        self.page_stack.setCurrentIndex(target_index)
        page_name = self.nav_list.item(target_index).text()
        self.page_title.setText(page_name)
        self.header_title.setText(f"{page_name.upper()} A NEW INSTANCE")
        self._update_name_placeholder()

    def _build_version_section(self) -> QWidget:
        section = QFrame()
        section.setObjectName("editorSectionCard")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        title = QLabel("Version")
        title.setObjectName("editorSectionTitle")
        layout.addWidget(title)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(16)
        layout.addLayout(row, 1)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(12)
        row.addLayout(left, 1)

        self.version_model = CatalogTableModel(
            ["Version", "Released", "Type"],
            ["id", "release_display", "type_label"],
            self,
        )
        self.version_proxy = VersionFilterProxyModel(self.service, self)
        self.version_proxy.setSourceModel(self.version_model)

        self.version_stack = QStackedWidget()
        self.version_stack.setObjectName("versionStack")
        left.addWidget(self.version_stack, 1)

        self.version_placeholder = LoaderPlaceholder("Loading Minecraft versions...")
        self.version_stack.addWidget(self.version_placeholder)

        version_table_holder = QWidget()
        version_table_layout = QVBoxLayout(version_table_holder)
        version_table_layout.setContentsMargins(0, 0, 0, 0)
        version_table_layout.setSpacing(0)
        self.version_table = self._build_table_view()
        self.version_table.setObjectName("versionCatalogTable")
        self.version_table.setModel(self.version_proxy)
        self.version_table.selectionModel().selectionChanged.connect(
            lambda *_: self._on_version_selection_changed()
        )
        self.version_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.version_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.version_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        version_table_layout.addWidget(self.version_table)
        self.version_stack.addWidget(version_table_holder)

        self.version_search = AccentLineEdit("Search versions")
        self.version_search.textChanged.connect(self._on_version_search_changed)
        self.version_search.setEnabled(False)
        left.addWidget(self.version_search)

        side = QFrame()
        side.setObjectName("editorSidePanel")
        self.version_side_panel = side
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(14, 14, 14, 14)
        side_layout.setSpacing(10)
        row.addWidget(side)

        filters_title = QLabel("Filter")
        filters_title.setObjectName("editorFilterTitle")
        side_layout.addWidget(filters_title)

        self.release_checkbox = self._build_checkbox("Releases", True, "release")
        self.snapshot_checkbox = self._build_checkbox("Snapshots", False, "snapshot")
        self.beta_checkbox = self._build_checkbox("Betas", False, "old_beta")
        self.alpha_checkbox = self._build_checkbox("Alphas", False, "old_alpha")
        self.experiments_checkbox = self._build_checkbox("Experiments", False, "__experiments__")

        for widget in (
            self.release_checkbox,
            self.snapshot_checkbox,
            self.beta_checkbox,
            self.alpha_checkbox,
            self.experiments_checkbox,
        ):
            side_layout.addWidget(widget)

        side_layout.addStretch()

        self.version_refresh = ModernButton("Refresh", role="sidebar", height=42, icon_size=0)
        self.version_refresh.clicked.connect(lambda: self._load_versions(force_refresh=True))
        self.version_refresh.setEnabled(False)
        side_layout.addWidget(self.version_refresh, alignment=Qt.AlignHCenter)
        return section

    def _build_loader_section(self) -> QWidget:
        section = QFrame()
        section.setObjectName("editorSectionCard")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        title = QLabel("Mod Loader")
        title.setObjectName("editorSectionTitle")
        layout.addWidget(title)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(16)
        layout.addLayout(row, 1)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(12)
        row.addLayout(left, 1)

        self.loader_model = CatalogTableModel(
            ["Version", "Loader", "Minecraft"],
            ["loader_version", "loader_name", "minecraft_version"],
            self,
        )
        self.loader_proxy = SearchFilterProxyModel(
            ["loader_version", "loader_name", "minecraft_version"],
            self,
        )
        self.loader_proxy.setSourceModel(self.loader_model)

        self.loader_stack = QStackedWidget()
        self.loader_stack.setObjectName("loaderStack")
        left.addWidget(self.loader_stack, 1)

        self.loader_placeholder = LoaderPlaceholder("No mod loader is selected.")
        self.loader_stack.addWidget(self.loader_placeholder)

        table_holder = QWidget()
        table_layout = QVBoxLayout(table_holder)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)
        self.loader_table = self._build_table_view()
        self.loader_table.setObjectName("loaderCatalogTable")
        self.loader_table.setModel(self.loader_proxy)
        self.loader_table.selectionModel().selectionChanged.connect(
            lambda *_: self._on_loader_selection_changed()
        )
        self.loader_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.loader_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.loader_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table_layout.addWidget(self.loader_table)
        self.loader_stack.addWidget(table_holder)

        self.loader_search = AccentLineEdit("Search loader versions")
        self.loader_search.textChanged.connect(self._on_loader_search_changed)
        self.loader_search.setEnabled(False)
        left.addWidget(self.loader_search)

        side = QFrame()
        side.setObjectName("editorSidePanel")
        self.loader_side_panel = side
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(14, 14, 14, 14)
        side_layout.setSpacing(10)
        row.addWidget(side)

        side_title = QLabel("Mod Loader")
        side_title.setObjectName("editorFilterTitle")
        side_layout.addWidget(side_title)

        self.loader_group = QButtonGroup(self)
        self.loader_group.setExclusive(True)
        self.loader_buttons: dict[str | None, QRadioButton] = {}

        none_button = self._build_loader_radio("None", None)
        side_layout.addWidget(none_button)

        ordered_loaders = ["neoforge", "forge", "fabric", "quilt"]
        for loader_id in ordered_loaders:
            radio = self._build_loader_radio(self.service.get_mod_loader_name(loader_id), loader_id)
            side_layout.addWidget(radio)

        side_layout.addStretch()

        self.loader_refresh = ModernButton("Refresh", role="sidebar", height=42, icon_size=0)
        self.loader_refresh.clicked.connect(lambda: self._refresh_loader_rows(force_refresh=True))
        self.loader_refresh.setEnabled(False)
        side_layout.addWidget(self.loader_refresh, alignment=Qt.AlignHCenter)
        none_button.setChecked(True)
        return section

    def _build_table_view(self) -> QTableView:
        table = QTableView()
        table.setObjectName("catalogTable")
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.setFrameShape(QFrame.NoFrame)
        table.setFocusPolicy(Qt.NoFocus)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(36)
        table.horizontalHeader().setHighlightSections(False)
        table.horizontalHeader().setStretchLastSection(False)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return table

    def _apply_responsive_layout(self) -> None:
        root_margin = scaled_px(self, 22, minimum=14, maximum=24)
        layout = self.layout()
        if isinstance(layout, QVBoxLayout):
            layout.setContentsMargins(root_margin, root_margin, root_margin, scaled_px(self, 20, minimum=14, maximum=22))
            layout.setSpacing(scaled_px(self, 14, minimum=10, maximum=16))

        self.icon_button.set_side_length(scaled_px(self, 104, minimum=76, maximum=108))
        self.name_edit.setMinimumHeight(scaled_px(self, 66, minimum=52, maximum=68))
        self.nav_frame.setFixedWidth(scaled_px(self, 212, minimum=160, maximum=220))
        self.version_side_panel.setFixedWidth(scaled_px(self, 184, minimum=150, maximum=190))
        self.loader_side_panel.setFixedWidth(scaled_px(self, 184, minimum=150, maximum=190))

        self.cancel_button.set_metrics(height=scaled_px(self, 44, minimum=38, maximum=46), icon_size=0)
        self.ok_button.set_metrics(height=scaled_px(self, 44, minimum=38, maximum=46), icon_size=0)
        self.version_refresh.set_metrics(height=scaled_px(self, 42, minimum=38, maximum=44), icon_size=0)
        self.loader_refresh.set_metrics(height=scaled_px(self, 42, minimum=38, maximum=44), icon_size=0)
        self.modpack_input.browse_button.set_metrics(height=scaled_px(self, 46, minimum=40, maximum=48), icon_size=0)
        self.minecraft_input.browse_button.set_metrics(height=scaled_px(self, 46, minimum=40, maximum=48), icon_size=0)
        self.copy_add_button.set_metrics(height=scaled_px(self, 38, minimum=36, maximum=40), icon_size=0)
        self.copy_remove_button.set_metrics(height=scaled_px(self, 38, minimum=36, maximum=40), icon_size=0)
        self.copy_all_button.set_metrics(height=scaled_px(self, 38, minimum=36, maximum=40), icon_size=0)
        self.copy_clear_button.set_metrics(height=scaled_px(self, 38, minimum=36, maximum=40), icon_size=0)
        self.ram_revert_button.set_metrics(height=scaled_px(self, 40, minimum=36, maximum=42), icon_size=0)
        self.ram_confirm_button.set_metrics(height=scaled_px(self, 40, minimum=36, maximum=42), icon_size=0)
        self.ram_display.setMinimumWidth(scaled_px(self, 180, minimum=156, maximum=188))

        row_height = scaled_px(self, 36, minimum=32, maximum=38)
        self.version_table.verticalHeader().setDefaultSectionSize(row_height)
        self.loader_table.verticalHeader().setDefaultSectionSize(row_height)
        self.copy_available_list.setMinimumHeight(scaled_px(self, 220, minimum=180, maximum=260))
        self.copy_selected_list.setMinimumHeight(scaled_px(self, 220, minimum=180, maximum=260))

    def _build_checkbox(self, text: str, checked: bool, value: str) -> QCheckBox:
        checkbox = QCheckBox(text)
        checkbox.setObjectName("editorFilterCheck")
        checkbox.setChecked(checked)
        checkbox.toggled.connect(lambda _: self._update_version_filters())
        checkbox.setProperty("filterValue", value)
        return checkbox

    def _build_loader_radio(self, text: str, value: str | None) -> QRadioButton:
        radio = QRadioButton(text)
        radio.setObjectName("editorFilterRadio")
        radio.toggled.connect(lambda checked, loader_id=value: self._on_loader_toggled(loader_id, checked))
        self.loader_group.addButton(radio)
        self.loader_buttons[value] = radio
        return radio

    def _load_versions(self, force_refresh: bool) -> None:
        self._version_request_id += 1
        self.version_model.set_rows([])
        self.version_search.clear()
        self.version_search.setEnabled(False)
        self.version_refresh.setEnabled(False)
        self.version_placeholder.set_text("Loading Minecraft versions...")
        self.version_stack.setCurrentIndex(0)
        self._start_worker("versions", self._version_request_id, force_refresh=force_refresh)

    def _update_version_filters(self) -> None:
        enabled = set()
        for checkbox in (
            self.release_checkbox,
            self.snapshot_checkbox,
            self.beta_checkbox,
            self.alpha_checkbox,
            self.experiments_checkbox,
        ):
            if checkbox.isChecked():
                enabled.add(str(checkbox.property("filterValue")))

        if not enabled:
            enabled.add("release")
            self.release_checkbox.setChecked(True)

        self.version_proxy.set_enabled_types(enabled)
        self._select_first_row(self.version_table, self.version_proxy, preserve=True)

    def _on_version_search_changed(self, text: str) -> None:
        self.version_proxy.set_search_text(text)
        self._select_first_row(self.version_table, self.version_proxy, preserve=True)

    def _on_loader_search_changed(self, text: str) -> None:
        self.loader_proxy.set_search_text(text)
        self._select_first_row(self.loader_table, self.loader_proxy, preserve=True)

    def _on_version_selection_changed(self) -> None:
        self._update_name_placeholder()
        self._sync_loader_availability()
        self._refresh_loader_rows(force_refresh=False)

    def _on_loader_selection_changed(self) -> None:
        self._update_name_placeholder()

    def _on_loader_toggled(self, loader_id: str | None, checked: bool) -> None:
        if not checked:
            return

        self._current_loader_id = loader_id
        self._update_name_placeholder()
        self._refresh_loader_rows(force_refresh=False)

    def _sync_loader_availability(self) -> None:
        for loader_id, button in self.loader_buttons.items():
            button.setEnabled(True)
            if loader_id is None:
                button.setToolTip("")
            else:
                button.setToolTip("Choose a version to fetch compatible loader builds.")

    def _refresh_loader_rows(self, force_refresh: bool = False) -> None:
        version = self.current_version_id()
        if self._current_loader_id is None:
            self.loader_model.set_rows([])
            self.loader_search.clear()
            self.loader_search.setEnabled(False)
            self.loader_refresh.setEnabled(False)
            self.loader_placeholder.set_text("No mod loader is selected.")
            self.loader_stack.setCurrentIndex(0)
            return

        if not version:
            self.loader_model.set_rows([])
            self.loader_search.clear()
            self.loader_search.setEnabled(False)
            self.loader_refresh.setEnabled(False)
            self.loader_placeholder.set_text("Select a Minecraft version first.")
            self.loader_stack.setCurrentIndex(0)
            return

        self._loader_request_id += 1
        self.loader_model.set_rows([])
        self.loader_search.clear()
        self.loader_search.setEnabled(False)
        self.loader_refresh.setEnabled(False)
        loader_name = self.service.get_mod_loader_name(self._current_loader_id)
        self.loader_placeholder.set_text(f"Loading {loader_name} versions...")
        self.loader_stack.setCurrentIndex(0)
        self._start_worker(
            "loader_versions",
            self._loader_request_id,
            force_refresh=force_refresh,
            loader_id=self._current_loader_id,
            minecraft_version=version,
        )

    def current_version_row(self) -> dict[str, Any] | None:
        return self._current_proxy_row(self.version_table, self.version_proxy, self.version_model)

    def current_version_id(self) -> str | None:
        row = self.current_version_row()
        if row is None:
            return None
        return str(row["id"])

    def current_loader_row(self) -> dict[str, Any] | None:
        if self.loader_stack.currentIndex() != 1:
            return None
        return self._current_proxy_row(self.loader_table, self.loader_proxy, self.loader_model)

    def _current_proxy_row(
        self,
        table: QTableView,
        proxy: QSortFilterProxyModel,
        model: CatalogTableModel,
    ) -> dict[str, Any] | None:
        index = table.currentIndex()
        if not index.isValid():
            return None
        source_index = proxy.mapToSource(index)
        if not source_index.isValid():
            return None
        return model.row(source_index.row())

    def _select_first_row(
        self,
        table: QTableView,
        proxy: QSortFilterProxyModel,
        preserve: bool = False,
    ) -> None:
        target_row = 0
        if preserve and table.currentIndex().isValid():
            current_id = proxy.mapToSource(table.currentIndex())
            if current_id.isValid():
                target_row = table.currentIndex().row()

        if proxy.rowCount() <= 0:
            table.clearSelection()
            return

        if target_row >= proxy.rowCount():
            target_row = 0

        index = proxy.index(target_row, 0)
        table.setCurrentIndex(index)
        table.selectRow(target_row)

    def _update_name_placeholder(self) -> None:
        if self.page_stack.currentIndex() == self.PAGE_IMPORT:
            placeholder = "Leave blank to use the imported pack or folder name"
        else:
            version = self.current_version_id() or "New Instance"
            placeholder = self.service.default_instance_name(version, self._current_loader_id)
        self.name_edit.setPlaceholderText(placeholder)

    def _reload_copy_source_instances(self) -> None:
        current_value = self.copy_source_combo.selected_value() if hasattr(self, "copy_source_combo") else None
        instances = self.service.load_instances()
        self._copy_source_instances = [
            {"id": instance.instance_id, "name": instance.name}
            for instance in instances
        ]

        if not hasattr(self, "copy_source_combo"):
            return

        self.copy_source_combo.blockSignals(True)
        self.copy_source_combo.clear()
        self.copy_source_combo.addItem("", None)
        for instance in self._copy_source_instances:
            self.copy_source_combo.addItem(instance["name"], instance["id"])
        self.copy_source_combo.blockSignals(False)

        if current_value:
            index = self.copy_source_combo.findData(current_value, role=Qt.UserRole)
            if index >= 0:
                self.copy_source_combo.setCurrentIndex(index)
        self._on_copy_source_changed()

    def _on_copy_source_changed(self) -> None:
        if not hasattr(self, "copy_available_list"):
            return

        self.copy_available_list.clear()
        self.copy_selected_list.clear()
        instance_id = self.copy_source_combo.selected_value()
        if not instance_id:
            return

        for entry in self.service.list_copyable_user_data(instance_id):
            item = QListWidgetItem(entry["label"])
            item.setData(Qt.UserRole, entry["path"])
            self.copy_available_list.addItem(item)

    def _move_copy_items(self, source: QListWidget, destination: QListWidget) -> None:
        selected_items = source.selectedItems()
        if not selected_items:
            return

        existing = {
            str(destination.item(index).data(Qt.UserRole))
            for index in range(destination.count())
        }
        for item in selected_items:
            entry_path = str(item.data(Qt.UserRole))
            if entry_path in existing:
                source.takeItem(source.row(item))
                continue
            clone = QListWidgetItem(item.text())
            clone.setData(Qt.UserRole, entry_path)
            destination.addItem(clone)
            source.takeItem(source.row(item))

    def _move_all_copy_items(self) -> None:
        while self.copy_available_list.count():
            item = self.copy_available_list.takeItem(0)
            if item is None:
                break
            clone = QListWidgetItem(item.text())
            clone.setData(Qt.UserRole, item.data(Qt.UserRole))
            self.copy_selected_list.addItem(clone)

    def _clear_copy_selection(self) -> None:
        while self.copy_selected_list.count():
            item = self.copy_selected_list.takeItem(0)
            if item is None:
                break
            clone = QListWidgetItem(item.text())
            clone.setData(Qt.UserRole, item.data(Qt.UserRole))
            self.copy_available_list.addItem(clone)

    def _selected_copy_entries(self) -> list[str]:
        return [
            str(self.copy_selected_list.item(index).data(Qt.UserRole))
            for index in range(self.copy_selected_list.count())
            if self.copy_selected_list.item(index).data(Qt.UserRole)
        ]

    def _update_ram_slider_range(self) -> None:
        total_mb = int(psutil.virtual_memory().total / (1024 * 1024))
        maximum_mb = max(self._ram_default_mb, min(16384, (int(total_mb * 0.75) // 1024) * 1024))
        minimum_mb = 1024
        self.ram_slider.setMinimum(minimum_mb // self._ram_slider_step_mb)
        self.ram_slider.setMaximum(maximum_mb // self._ram_slider_step_mb)

    def _slider_to_mb(self, slider_value: int) -> int:
        return slider_value * self._ram_slider_step_mb

    def _mb_to_slider(self, memory_mb: int) -> int:
        return max(self.ram_slider.minimum(), min(self.ram_slider.maximum(), memory_mb // self._ram_slider_step_mb))

    def _snap_memory_mb(self, memory_mb: int) -> int:
        snapped = int(round(memory_mb / 1024.0) * 1024)
        minimum = self._slider_to_mb(self.ram_slider.minimum())
        maximum = self._slider_to_mb(self.ram_slider.maximum())
        return max(minimum, min(maximum, snapped))

    def _set_ram_value(self, memory_mb: int, *, animate: bool) -> None:
        self._ram_selected_mb = self._snap_memory_mb(memory_mb)
        self.ram_slider.blockSignals(True)
        self.ram_slider.setValue(self._mb_to_slider(self._ram_selected_mb))
        self.ram_slider.blockSignals(False)
        existing_animation = getattr(self, "_ram_animation", None)
        if isinstance(existing_animation, QVariantAnimation):
            existing_animation.stop()
        if animate:
            start_value = self._ram_displayed_mb
            animation = QVariantAnimation(
                self,
                duration=220,
                easingCurve=QEasingCurve.OutCubic,
                startValue=start_value,
                endValue=self._ram_selected_mb,
                valueChanged=lambda value: self.ram_display.setText(f"{int(value)} MB"),
            )
            animation.finished.connect(lambda: setattr(self, "_ram_displayed_mb", self._ram_selected_mb))
            animation.start()
            self._ram_animation = animation
        else:
            self._ram_displayed_mb = self._ram_selected_mb
            self.ram_display.setText(f"{self._ram_selected_mb} MB")

    def _on_ram_slider_changed(self, value: int) -> None:
        self._set_ram_value(self._slider_to_mb(value), animate=False)

    def _revert_ram_value(self) -> None:
        self._set_ram_value(self._ram_default_mb, animate=True)

    def _confirm_ram_value(self) -> None:
        self._set_ram_value(self._ram_selected_mb, animate=True)

    def _accept_selection(self) -> None:
        if self.page_stack.currentIndex() == self.PAGE_IMPORT:
            self._accept_import_selection()
            return

        version_row = self.current_version_row()
        if version_row is None:
            self.ok_button.flash_invalid()
            QMessageBox.warning(self, "Missing Version", "Select a Minecraft version to continue.")
            return

        loader_version = None
        if self._current_loader_id:
            loader_row = self.current_loader_row()
            if loader_row is None:
                self.ok_button.flash_invalid()
                QMessageBox.warning(
                    self,
                    "Missing Loader Version",
                    "Select a mod loader version or switch the loader back to None.",
                )
                return
            loader_version = str(loader_row["loader_version"])

        self.selection = {
            "name": self.name_edit.text().strip(),
            "vanilla_version": str(version_row["id"]),
            "mod_loader_id": self._current_loader_id,
            "mod_loader_version": loader_version,
            "icon_path": self._selected_icon_path,
            "memory_mb": self._ram_selected_mb,
            "operation": "create",
            "modpack_path": None,
            "minecraft_import_dir": None,
            "copy_source_instance_id": self.copy_source_combo.selected_value(),
            "copy_user_data": self._selected_copy_entries(),
        }
        self.accept()

    def _accept_import_selection(self) -> None:
        modpack_path = self.modpack_input.text()
        minecraft_path = self.minecraft_input.text()

        if modpack_path and minecraft_path:
            self.ok_button.flash_invalid()
            QMessageBox.warning(
                self,
                "Choose One Import Source",
                "Select either a modpack archive or a .minecraft folder, not both at the same time.",
            )
            return

        if not modpack_path and not minecraft_path:
            self.ok_button.flash_invalid()
            self.modpack_input.focus_field()
            return

        if modpack_path:
            if not Path(modpack_path).is_file():
                self.ok_button.flash_invalid()
                QMessageBox.warning(self, "Missing Modpack", "Select a valid modpack archive to continue.")
                return
            self.selection = {
                "name": self.name_edit.text().strip(),
                "vanilla_version": None,
                "mod_loader_id": None,
                "mod_loader_version": None,
                "icon_path": self._selected_icon_path,
                "memory_mb": self._ram_default_mb,
                "operation": "import_modpack",
                "modpack_path": modpack_path,
                "minecraft_import_dir": None,
                "copy_source_instance_id": None,
                "copy_user_data": [],
            }
            self.accept()
            return

        valid, message = self.service.is_valid_minecraft_dir(minecraft_path)
        if not valid:
            self.ok_button.flash_invalid()
            QMessageBox.warning(self, "Invalid .minecraft Folder", message)
            return

        self.selection = {
            "name": self.name_edit.text().strip(),
            "vanilla_version": None,
            "mod_loader_id": None,
            "mod_loader_version": None,
            "icon_path": self._selected_icon_path,
            "memory_mb": self._ram_default_mb,
            "operation": "import_minecraft",
            "modpack_path": None,
            "minecraft_import_dir": minecraft_path,
            "copy_source_instance_id": None,
            "copy_user_data": [],
        }
        self.accept()

    def _open_icon_selector(self) -> None:
        dialog = IconSelectorDialog(self.service, self._selected_icon_path, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._selected_icon_path = dialog.selected_icon_path
        self._sync_header_icon()

    def _sync_header_icon(self) -> None:
        resolved_icon = self.service.resolve_icon_path(self._selected_icon_path)
        self.icon_button.set_icon_path(resolved_icon)

    def _browse_modpack(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Modpack",
            str((Path.home() / "Downloads") if (Path.home() / "Downloads").exists() else Path.home()),
            "Modpack Archives (*.mrpack *.zip)",
        )
        if not file_path:
            return
        self.modpack_input.setText(file_path)
        if self.minecraft_input.text():
            self.minecraft_input.clear()

    def _browse_minecraft_folder(self) -> None:
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Import .minecraft Folder",
            str(Path.home()),
        )
        if not folder_path:
            return

        valid, message = self.service.is_valid_minecraft_dir(folder_path)
        if not valid:
            self.ok_button.flash_invalid()
            QMessageBox.warning(self, "Invalid .minecraft Folder", message)
            return

        self.minecraft_input.setText(folder_path)
        if self.modpack_input.text():
            self.modpack_input.clear()

    def _start_worker(
        self,
        job: str,
        request_id: int,
        *,
        force_refresh: bool = False,
        loader_id: str | None = None,
        minecraft_version: str | None = None,
    ) -> None:
        worker = CatalogWorker(
            self.service,
            job,
            request_id,
            force_refresh=force_refresh,
            loader_id=loader_id,
            minecraft_version=minecraft_version,
        )
        self._workers.add(worker)
        worker.loaded.connect(self._handle_catalog_loaded)
        worker.failed.connect(self._handle_catalog_failed)
        worker.finished.connect(self._finalize_worker)
        worker.start()

    def _finalize_worker(self) -> None:
        worker = self.sender()
        if not isinstance(worker, QThread):
            return
        self._workers.discard(worker)
        worker.deleteLater()

    def _handle_catalog_loaded(self, job: str, request_id: int, payload: object) -> None:
        if job == "versions":
            if request_id != self._version_request_id:
                return
            rows = list(payload) if isinstance(payload, list) else []
            self.version_model.set_rows(rows)
            self.version_search.setEnabled(True)
            self.version_refresh.setEnabled(True)
            if rows:
                self.version_stack.setCurrentIndex(1)
                self._update_version_filters()
                self._select_first_row(self.version_table, self.version_proxy)
            else:
                self.version_placeholder.set_text("No Minecraft versions were returned.")
                self.version_stack.setCurrentIndex(0)
            return

        if job == "loader_versions":
            if request_id != self._loader_request_id:
                return
            rows = list(payload) if isinstance(payload, list) else []
            self.loader_refresh.setEnabled(True)
            if rows:
                self.loader_model.set_rows(rows)
                self.loader_search.setEnabled(True)
                self.loader_stack.setCurrentIndex(1)
                self._select_first_row(self.loader_table, self.loader_proxy)
            else:
                self.loader_model.set_rows([])
                self.loader_placeholder.set_text("No compatible loader versions were returned for this selection.")
                self.loader_stack.setCurrentIndex(0)

    def _handle_catalog_failed(self, job: str, request_id: int, message: str) -> None:
        if job == "versions":
            if request_id != self._version_request_id:
                return
            self.version_placeholder.set_text(message)
            self.version_stack.setCurrentIndex(0)
            self.version_refresh.setEnabled(True)
            return

        if job == "loader_versions":
            if request_id != self._loader_request_id:
                return
            self.loader_placeholder.set_text(message)
            self.loader_stack.setCurrentIndex(0)
            self.loader_refresh.setEnabled(True)

    def closeEvent(self, event) -> None:
        for worker in list(self._workers):
            if worker.isRunning():
                worker.wait()
        super().closeEvent(event)
