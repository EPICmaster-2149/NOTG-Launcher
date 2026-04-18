from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRectF, QSortFilterProxyModel, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QDialog,
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
    QSizePolicy,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from core.launcher import LauncherService
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


class AddInstanceDialog(QDialog):
    def __init__(self, service: LauncherService, parent: QWidget | None = None):
        super().__init__(parent)
        self.service = service
        self.selection: dict[str, Any] | None = None
        self._current_loader_id: str | None = None

        self.setObjectName("instanceEditor")
        self.setWindowTitle("Create New Instance")
        self.setModal(True)
        self.resize(1120, 780)
        self.setMinimumSize(1040, 720)

        self._asset_root = Path(__file__).resolve().parents[2] / "assets"
        self._build_ui()
        self._load_versions(force_refresh=False)

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(22, 22, 22, 20)
        root_layout.setSpacing(14)

        header = QFrame()
        header.setObjectName("instanceEditorHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(22, 18, 22, 18)
        header_layout.setSpacing(18)

        self.icon_label = QLabel()
        self.icon_label.setObjectName("editorInstanceIcon")
        self.icon_label.setFixedSize(92, 92)
        icon = QPixmap(str(self._asset_root / "Dirt.png"))
        self.icon_label.setPixmap(icon.scaled(74, 74, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.icon_label.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(self.icon_label)

        name_column = QVBoxLayout()
        name_column.setSpacing(10)

        header_title = QLabel("Create A New Instance")
        header_title.setObjectName("editorEyebrow")
        name_column.addWidget(header_title)

        self.name_edit = AccentLineEdit("Enter a name or use the selected version", large=True)
        self.name_edit.setMinimumHeight(66)
        name_column.addWidget(self.name_edit)

        subtitle = QLabel("Isolated installs, real version metadata, and live mod-loader integration.")
        subtitle.setObjectName("editorSubtitle")
        name_column.addWidget(subtitle)
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
        nav_frame.setFixedWidth(212)
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
        create_item = QListWidgetItem("Create")
        create_item.setSizeHint(create_item.sizeHint().expandedTo(create_item.sizeHint()))
        self.nav_list.addItem(create_item)
        self.nav_list.setCurrentRow(0)
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
        content_layout.addWidget(scroll_area, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(12)
        footer.addStretch()

        self.cancel_button = ModernButton("Cancel", role="sidebar", height=44, icon_size=0)
        self.cancel_button.clicked.connect(self.reject)
        footer.addWidget(self.cancel_button)

        self.ok_button = ModernButton("OK", role="accent", height=44, icon_size=0)
        self.ok_button.clicked.connect(self._accept_selection)
        footer.addWidget(self.ok_button)
        content_layout.addLayout(footer)
        shell_layout.addWidget(content, 1)

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

        self.version_table = self._build_table_view()
        self.version_table.setObjectName("versionCatalogTable")
        self.version_table.setModel(self.version_proxy)
        self.version_table.selectionModel().selectionChanged.connect(
            lambda *_: self._on_version_selection_changed()
        )
        self.version_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.version_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.version_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        left.addWidget(self.version_table, 1)

        self.version_search = AccentLineEdit("Search versions")
        self.version_search.textChanged.connect(self._on_version_search_changed)
        left.addWidget(self.version_search)

        side = QFrame()
        side.setObjectName("editorSidePanel")
        side.setFixedWidth(184)
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
        side_layout.addWidget(self.version_refresh)
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
        side.setFixedWidth(184)
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
        side_layout.addWidget(self.loader_refresh)
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
        try:
            rows = self.service.get_version_catalog(force_refresh=force_refresh)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Version List Error", str(exc))
            return

        self.version_model.set_rows(rows)
        self._update_version_filters()
        self._select_first_row(self.version_table, self.version_proxy)

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
        version = self.current_version_id()
        for loader_id, button in self.loader_buttons.items():
            if loader_id is None:
                button.setEnabled(True)
                button.setToolTip("")
                continue

            supported = bool(version) and version in self.service.get_loader_supported_versions(loader_id)
            button.setEnabled(True)
            if supported:
                button.setToolTip("")
            else:
                button.setToolTip("This loader does not support the currently selected Minecraft version.")

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

        if version not in self.service.get_loader_supported_versions(self._current_loader_id):
            self.loader_model.set_rows([])
            self.loader_search.clear()
            self.loader_search.setEnabled(False)
            self.loader_refresh.setEnabled(False)
            self.loader_placeholder.set_text("The selected version is not supported by this mod loader.")
            self.loader_stack.setCurrentIndex(0)
            return

        try:
            rows = self.service.get_loader_versions(
                self._current_loader_id,
                version,
                force_refresh=force_refresh,
            )
        except Exception as exc:  # noqa: BLE001
            self.loader_placeholder.set_text(str(exc))
            self.loader_stack.setCurrentIndex(0)
            self.loader_refresh.setEnabled(True)
            return

        self.loader_model.set_rows(rows)
        self.loader_search.setEnabled(True)
        self.loader_refresh.setEnabled(True)
        self.loader_stack.setCurrentIndex(1)
        self._select_first_row(self.loader_table, self.loader_proxy)

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
        version = self.current_version_id() or "New Instance"
        placeholder = self.service.default_instance_name(version, self._current_loader_id)
        self.name_edit.setPlaceholderText(placeholder)

    def _accept_selection(self) -> None:
        version_row = self.current_version_row()
        if version_row is None:
            QMessageBox.warning(self, "Missing Version", "Select a Minecraft version to continue.")
            return

        loader_version = None
        if self._current_loader_id:
            loader_row = self.current_loader_row()
            if loader_row is None:
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
        }
        self.accept()
