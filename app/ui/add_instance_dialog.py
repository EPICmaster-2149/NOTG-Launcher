from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

import requests
from PySide6.QtCore import (
    QAbstractTableModel,
    QEasingCurve,
    QEvent,
    QModelIndex,
    QRectF,
    QSize,
    QSortFilterProxyModel,
    QThread,
    QTimer,
    QUrl,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPen, QPixmap
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
    QPlainTextEdit,
    QProgressBar,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QTableView,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

import psutil

from core.launcher import LauncherService
from ui.icon_selector_dialog import IconSelectorDialog
from ui.modrinth_modpack_browser import ModrinthModpackBrowser
from ui.icon_utils import load_scaled_icon
from ui.responsive import fitted_window_size, scaled_px, screen_scale
from ui.theme import theme_palette
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
        palette = theme_palette(self)["line_edit"]
        border = blend_colors(palette["border"], palette["border_focus"], self._focus_progress)
        background = blend_colors(palette["background"], palette["background_focus"], self._focus_progress * 0.55)
        shadow_base = QColor(palette["shadow"])
        shadow = QColor(shadow_base.red(), shadow_base.green(), shadow_base.blue(), int(shadow_base.alpha() * self._focus_progress))
        self._shadow.setBlurRadius(24 * self._focus_progress)
        self._shadow.setColor(shadow)

        font_size = 22 if self._large else 13
        padding = "16px 18px" if self._large else "12px 14px"
        radius = 12 if self._large else 10
        text = palette["text"]
        placeholder = palette["placeholder"]
        selection = palette["selection"]
        self.setStyleSheet(
            f"""
            QLineEdit {{
                background-color: rgba({background.red()}, {background.green()}, {background.blue()}, {background.alpha()});
                border: 1px solid rgba({border.red()}, {border.green()}, {border.blue()}, {border.alpha()});
                border-radius: {radius}px;
                color: rgba({text.red()}, {text.green()}, {text.blue()}, {text.alpha()});
                padding: {padding};
                font-size: {font_size}px;
                font-weight: {'700' if self._large else '500'};
                selection-background-color: rgba({selection.red()}, {selection.green()}, {selection.blue()}, {selection.alpha()});
            }}
            QLineEdit::placeholder {{
                color: rgba({placeholder.red()}, {placeholder.green()}, {placeholder.blue()}, {placeholder.alpha()});
            }}
            """
        )

    def refresh_theme(self) -> None:
        self._apply_style()

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


class ModrinthModpackWorker(QThread):
    loaded = Signal(str, object)
    failed = Signal(str)

    def __init__(
        self,
        service: LauncherService,
        job: str,
        *,
        query: str = "",
        project_id: str = "",
        version: dict[str, Any] | None = None,
        icon_url: str = "",
        limit: int = 24,
        offset: int = 0,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._service = service
        self._job = job
        self._query = query
        self._project_id = project_id
        self._version = dict(version or {})
        self._icon_url = icon_url
        self._limit = max(1, int(limit))
        self._offset = max(0, int(offset))

    def run(self) -> None:
        try:
            if self._job == "search":
                payload = self._service.search_modrinth_modpacks(self._query, self._limit, self._offset)
            elif self._job == "details":
                payload = self._service.get_modrinth_modpack_details(self._project_id)
            elif self._job == "versions":
                payload = self._service.get_modrinth_modpack_versions(self._project_id)
            elif self._job == "inspect":
                payload = self._service.inspect_modrinth_modpack_version(self._version)
            elif self._job == "download":
                payload = str(self._service.download_modrinth_modpack_version(self._version))
            elif self._job == "icon":
                response = requests.get(self._icon_url, timeout=20)
                response.raise_for_status()
                payload = response.content
            else:
                raise ValueError(f"Unsupported Modrinth modpack job: {self._job}")
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return
        if not self.isInterruptionRequested():
            self.loaded.emit(self._job, payload)


class ModpackVersionDialog(QDialog):
    def __init__(self, versions: list[dict[str, Any]], parent: QWidget | None = None):
        super().__init__(parent)
        self.selected_version: dict[str, Any] | None = None
        self._versions = list(versions)
        self.setObjectName("editInstanceDialog")
        self.setWindowTitle("Select Version")
        self.setModal(True)
        self.setMinimumSize(520, 420)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(12)
        title = QLabel("Select a version to install:")
        title.setObjectName("editorSectionTitle")
        root.addWidget(title)
        self.version_list = QListWidget()
        self.version_list.setObjectName("musicTrackList")
        self.version_list.setFrameShape(QFrame.NoFrame)
        for version in self._versions:
            game_versions = version.get("game_versions") if isinstance(version.get("game_versions"), list) else []
            minecraft_versions = ", ".join(str(item) for item in game_versions[:4])
            label = str(version.get("name") or version.get("version_number") or "Version")
            version_number = str(version.get("version_number") or "")
            item = QListWidgetItem(f"{label}\n{version_number} - Minecraft {minecraft_versions}")
            item.setData(Qt.UserRole, version)
            item.setSizeHint(QSize(0, 58))
            self.version_list.addItem(item)
        root.addWidget(self.version_list, 1)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_button = ModernButton("Cancel", role="sidebar", height=38, icon_size=0, minimum_width=96)
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(cancel_button)
        confirm_button = ModernButton("Install", role="accent", height=38, icon_size=0, minimum_width=106)
        confirm_button.clicked.connect(self._confirm)
        buttons.addWidget(confirm_button)
        root.addLayout(buttons)
        if self.version_list.count():
            self.version_list.setCurrentRow(0)

    def _confirm(self) -> None:
        item = self.version_list.currentItem()
        if item is None:
            return
        version = item.data(Qt.UserRole)
        if isinstance(version, dict):
            self.selected_version = version
            self.accept()


_MODPACK_ICON_BYTES_CACHE: dict[str, bytes] = {}


class ModrinthModpackIcon(QLabel):
    def __init__(self, project: dict[str, Any], parent: QWidget | None = None):
        super().__init__(parent)
        self._fallback: QLabel | None = None
        self.setFixedSize(44, 44)
        self.setAlignment(Qt.AlignCenter)
        self.set_icon_data(project.get("icon_data"), str(project.get("provider") or ""))

    def set_icon_data(self, icon_data: object, provider: str = "") -> None:
        pixmap = QPixmap()
        if isinstance(icon_data, (bytes, bytearray)):
            pixmap.loadFromData(bytes(icon_data))
        if not pixmap.isNull():
            if self._fallback is not None:
                self._fallback.hide()
                self._fallback.deleteLater()
                self._fallback = None
            self.setPixmap(pixmap.scaled(44, 44, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
            return
        self.clear()
        if self._fallback is None:
            self._fallback = QLabel("M" if provider == "modrinth" else "C", self)
            self._fallback.setAlignment(Qt.AlignCenter)
            self._fallback.setFixedSize(28, 28)
            self._fallback.move(8, 8)
            self._fallback.setStyleSheet(
                "background-color: #30B27B; color: white; border-radius: 7px; font-weight: 800;"
                if provider == "modrinth"
                else "background-color: #FF6432; color: white; border-radius: 7px; font-weight: 800;"
            )
        self._fallback.show()


class ModrinthModpackRow(QWidget):
    def __init__(self, project: dict[str, Any], parent: QWidget | None = None):
        super().__init__(parent)
        self.project = dict(project)
        self._hover = 0.0
        self._selected = 0.0
        self.setObjectName("remoteContentRow")
        self.setMinimumHeight(90)
        self.setMouseTracking(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(14)

        self.icon = ModrinthModpackIcon(project)
        layout.addWidget(self.icon, 0, Qt.AlignVCenter)

        text_column = QVBoxLayout()
        text_column.setSpacing(3)
        self.title = QLabel(str(project.get("title") or "Untitled Modpack"))
        self.title.setObjectName("musicTrackName")
        self.title.setWordWrap(False)
        text_column.addWidget(self.title)
        self.description = QLabel(str(project.get("description") or ""))
        self.description.setObjectName("editorStatusText")
        self.description.setWordWrap(False)
        text_column.addWidget(self.description)
        author = str(project.get("author") or "Unknown author")
        downloads = int(project.get("downloads") or 0)
        self.metadata = QLabel(f"Modrinth  /  {author}  /  {downloads:,} downloads")
        self.metadata.setObjectName("remoteContentMeta")
        self.metadata.setWordWrap(False)
        text_column.addWidget(self.metadata)
        layout.addLayout(text_column, 1)
        self._hover_animation = QVariantAnimation(self, duration=150, easingCurve=QEasingCurve.OutCubic)
        self._hover_animation.valueChanged.connect(lambda value: self._set_value("_hover", value))
        self._selected_animation = QVariantAnimation(self, duration=180, easingCurve=QEasingCurve.OutCubic)
        self._selected_animation.valueChanged.connect(lambda value: self._set_value("_selected", value))

    def set_icon_data(self, icon_data: object) -> None:
        self.project["icon_data"] = icon_data
        self.icon.set_icon_data(icon_data, str(self.project.get("provider") or ""))

    def set_selected(self, selected: bool) -> None:
        self._animate(self._selected_animation, self._selected, 1.0 if selected else 0.0)

    def enterEvent(self, event) -> None:
        self._animate(self._hover_animation, self._hover, 1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate(self._hover_animation, self._hover, 0.0)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        del event
        accent = QColor("#30D18A")
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        base = QColor(8, 14, 23, 184)
        hover = QColor(accent)
        hover.setAlpha(34)
        active = QColor(accent)
        active.setAlpha(58)
        bg = QColor(
            int(base.red() + (hover.red() - base.red()) * self._hover),
            int(base.green() + (hover.green() - base.green()) * self._hover),
            int(base.blue() + (hover.blue() - base.blue()) * self._hover),
            int(base.alpha() + (hover.alpha() - base.alpha()) * self._hover),
        )
        bg = QColor(
            int(bg.red() + (active.red() - bg.red()) * self._selected),
            int(bg.green() + (active.green() - bg.green()) * self._selected),
            int(bg.blue() + (active.blue() - bg.blue()) * self._selected),
            int(bg.alpha() + (active.alpha() - bg.alpha()) * self._selected),
        )
        border = QColor(accent)
        border.setAlpha(int(74 + (self._hover * 46) + (self._selected * 60)))
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 9, 9)

    def _animate(self, animation: QVariantAnimation, start: float, end: float) -> None:
        animation.stop()
        animation.setStartValue(float(start))
        animation.setEndValue(float(end))
        animation.start()

    def _set_value(self, attribute: str, value) -> None:
        setattr(self, attribute, float(value))
        self.update()


class ModrinthModpackIconWorker(QThread):
    icon_loaded = Signal(str, object)

    def __init__(self, targets: list[tuple[str, str]], cache_dir: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self._targets = list(targets)
        self._cache_dir = cache_dir

    def run(self) -> None:
        for key, url in self._targets:
            if self.isInterruptionRequested():
                return
            data = _modpack_icon_bytes_for_url(url, self._cache_dir)
            if data:
                self.icon_loaded.emit(key, data)


class ModrinthModpackSelectorDialog(QDialog):
    install_ready = Signal(str, str)

    def __init__(self, service: LauncherService, parent: QWidget | None = None):
        super().__init__(parent)
        self.service = service
        self._query = ""
        self._page_size = 24
        self._offset = 0
        self._has_more = True
        self._loading = False
        self._projects: list[dict[str, Any]] = []
        self._project_rows: dict[str, ModrinthModpackRow] = {}
        self._search_worker: ModrinthModpackWorker | None = None
        self._icon_worker: ModrinthModpackIconWorker | None = None
        self._icon_workers: list[ModrinthModpackIconWorker] = []
        self.setObjectName("instanceEditor")
        self.setWindowTitle("Modrinth Modpacks")
        self.setModal(True)
        self.setMinimumSize(1180, 820)
        self.resize(fitted_window_size(self.parentWidget() or self, 1320, 900, minimum_width=1180, minimum_height=820))
        self._build_ui()
        QTimer.singleShot(0, self._load_initial_page)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 20)
        root.setSpacing(14)

        header = QFrame()
        header.setObjectName("modrinthSelectorHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(22, 18, 22, 18)
        header_layout.setSpacing(10)

        title = QLabel("Modrinth")
        title.setObjectName("editorPageTitle")
        header_layout.addWidget(title)

        root.addWidget(header)

        surface = QFrame()
        surface.setObjectName("modrinthSelectionSurface")
        surface_layout = QVBoxLayout(surface)
        surface_layout.setContentsMargins(18, 18, 18, 18)
        surface_layout.setSpacing(12)
        surface.setStyleSheet(
            """
            QFrame#modrinthSelectionSurface,
            QFrame#modrinthSelectorHeader {
                background-color: rgba(5, 11, 18, 0.90);
                border: 1px solid rgba(48, 209, 138, 0.66);
                border-radius: 14px;
            }
            QLabel#editorStatusText {
                color: #B8E8D7;
                background: transparent;
            }
            QListWidget#musicTrackList {
                background-color: rgba(3, 8, 14, 0.48);
                border: 1px solid rgba(48, 209, 138, 0.24);
                border-radius: 12px;
                padding: 8px;
            }
            """
        )

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        self.search_edit = AccentLineEdit("Search Modrinth modpacks...")
        self.search_edit.returnPressed.connect(self._begin_new_search)
        top_row.addWidget(self.search_edit, 1)
        self.search_button = ModernButton("Search", role="accent", height=40, icon_size=0, minimum_width=104)
        self.search_button.clicked.connect(self._begin_new_search)
        top_row.addWidget(self.search_button)
        surface_layout.addLayout(top_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("editorStatusText")
        surface_layout.addWidget(self.status_label)

        self.results = QListWidget()
        self.results.setObjectName("musicTrackList")
        self.results.setFrameShape(QFrame.NoFrame)
        self.results.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.results.setSpacing(10)
        self.results.setUniformItemSizes(False)
        self.results.itemClicked.connect(self._open_selected_modpack)
        self.results.verticalScrollBar().valueChanged.connect(self._maybe_load_more)
        surface_layout.addWidget(self.results, 1)
        root.addWidget(surface, 1)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        footer.addStretch()
        cancel_button = ModernButton("Cancel", role="sidebar", height=38, icon_size=0, minimum_width=98)
        cancel_button.clicked.connect(self.reject)
        footer.addWidget(cancel_button)
        root.addLayout(footer)

    def _load_initial_page(self) -> None:
        if not self._projects:
            self._begin_new_search()

    def _begin_new_search(self) -> None:
        self._query = self.search_edit.text().strip()
        self._offset = 0
        self._has_more = True
        self._projects.clear()
        self._project_rows.clear()
        self.results.clear()
        self._request_page(reset=True)

    def _request_page(self, *, reset: bool) -> None:
        if self._loading or not self._has_more and not reset:
            return
        if self._search_worker is not None and self._search_worker.isRunning():
            self._search_worker.requestInterruption()
            self._search_worker.wait(1200)
        self._loading = True
        worker = ModrinthModpackWorker(
            self.service,
            "search",
            query=self._query,
            limit=self._page_size,
            offset=self._offset,
            parent=self,
        )
        worker.loaded.connect(self._handle_search_loaded)
        worker.failed.connect(self._handle_search_failed)
        worker.finished.connect(lambda: setattr(self, "_search_worker", None))
        self._search_worker = worker
        worker.start()

    def _handle_search_loaded(self, job: str, payload: object) -> None:
        if job != "search":
            return
        self._loading = False
        projects = [project for project in payload if isinstance(project, dict)] if isinstance(payload, list) else []
        if self._offset == 0:
            self.results.clear()
            self._projects.clear()
            self._project_rows.clear()
        if not projects and not self._projects:
            self._has_more = False
            return

        self._append_projects(projects)
        self._offset += len(projects)
        self._has_more = len(projects) >= self._page_size
        self._start_icon_worker(projects)
        self._maybe_load_more()

    def _handle_search_failed(self, message: str) -> None:
        self._loading = False
        QMessageBox.warning(self, "Modrinth Modpacks", message)

    def _append_projects(self, projects: list[dict[str, Any]]) -> None:
        for project in projects:
            key = self._project_key(project)
            if key in self._project_rows:
                continue
            self._projects.append(project)
            item = QListWidgetItem()
            item.setData(Qt.UserRole, project)
            item.setSizeHint(QSize(0, 94))
            self.results.addItem(item)
            row = ModrinthModpackRow(project)
            self.results.setItemWidget(item, row)
            self._project_rows[key] = row

    def _start_icon_worker(self, projects: list[dict[str, Any]]) -> None:
        targets: list[tuple[str, str]] = []
        for project in projects:
            url = str(project.get("icon_url") or "")
            if url.startswith(("http://", "https://")):
                targets.append((self._project_key(project), url))
        if not targets:
            return
        worker = ModrinthModpackIconWorker(targets, self.service.cache_root / "modrinth-modpack-icons", self)
        worker.icon_loaded.connect(self._handle_icon_loaded)
        worker.finished.connect(lambda worker=worker: self._handle_icon_worker_finished(worker))
        self._icon_worker = worker
        self._icon_workers.append(worker)
        worker.start()

    def _handle_icon_loaded(self, key: str, icon_data: object) -> None:
        if not isinstance(icon_data, (bytes, bytearray)):
            return
        row = self._project_rows.get(key)
        if row is not None:
            row.set_icon_data(bytes(icon_data))

    def _handle_icon_worker_finished(self, worker: ModrinthModpackIconWorker) -> None:
        if self._icon_worker is worker:
            self._icon_worker = None
        if worker in self._icon_workers:
            self._icon_workers.remove(worker)
        worker.deleteLater()

    def _maybe_load_more(self, *_args) -> None:
        if self._loading or not self._has_more:
            return
        scrollbar = self.results.verticalScrollBar()
        if scrollbar.maximum() <= 0:
            return
        if scrollbar.value() >= scrollbar.maximum() - 140:
            self._request_page(reset=False)

    def _open_selected_modpack(self, item: QListWidgetItem) -> None:
        project = item.data(Qt.UserRole)
        if not isinstance(project, dict):
            return
        details = ModrinthModpackDetailsDialog(self.service, project, self)
        details.install_ready.connect(self._handle_install_ready)
        details.exec()

    def _handle_install_ready(self, suggested_name: str, modpack_path: str) -> None:
        self.install_ready.emit(suggested_name, modpack_path)
        self.accept()

    def _project_key(self, project: dict[str, Any]) -> str:
        provider = str(project.get("provider") or "modrinth")
        value = str(project.get("project_id") or project.get("slug") or project.get("title") or "modpack")
        return f"{provider}:{_modpack_slug(value)}"

    def closeEvent(self, event) -> None:
        if self._search_worker is not None and self._search_worker.isRunning():
            self._search_worker.requestInterruption()
            self._search_worker.wait(1500)
        for worker in list(self._icon_workers):
            if worker.isRunning():
                worker.requestInterruption()
                worker.wait(1500)
        super().closeEvent(event)


class ModrinthModpackDetailsDialog(QDialog):
    """Lightweight API-driven modpack detail dialog (no heavy WebEngine browser)."""
    install_ready = Signal(str, str)

    def __init__(self, service: LauncherService, project: dict[str, Any], parent: QWidget | None = None):
        super().__init__(parent)
        self.service = service
        self.project = dict(project)
        self._project_id = str(project.get("project_id") or project.get("slug") or "")
        self._versions: list[dict[str, Any]] = []
        self._workers: list[ModrinthModpackWorker] = []
        self._icon_worker: ModrinthModpackIconWorker | None = None
        self._download_worker: ModrinthModpackWorker | None = None
        self._icon_cache_dir = self.service.cache_root / "modrinth-modpack-icons"
        self.setObjectName("editInstanceDialog")
        self.setWindowTitle(str(project.get("title") or "Modrinth Modpack"))
        self.setModal(True)
        self.setMinimumSize(640, 520)
        self.resize(fitted_window_size(self.parentWidget() or self, 780, 600, minimum_width=640, minimum_height=520))
        self._build_ui()
        self._load()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(12)

        # Info card
        info_card = QFrame()
        info_card.setObjectName("modrinthBrowserCard")
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(18, 16, 18, 16)
        info_layout.setSpacing(10)
        info_card.setStyleSheet(
            """
            QFrame#modrinthBrowserCard {
                background-color: rgba(5, 11, 18, 0.92);
                border: 1px solid rgba(48, 209, 138, 0.72);
                border-radius: 14px;
            }
            """
        )

        # Project title
        self.project_title = QLabel(str(self.project.get("title") or "Untitled Modpack"))
        self.project_title.setObjectName("editorPageTitle")
        info_layout.addWidget(self.project_title)

        # Description
        desc_text = str(self.project.get("description") or "No description available.")
        self.desc_label = QLabel(desc_text)
        self.desc_label.setObjectName("editorStatusText")
        self.desc_label.setWordWrap(True)
        info_layout.addWidget(self.desc_label)

        # Author / downloads
        author = str(self.project.get("author") or "Unknown")
        downloads = int(self.project.get("downloads") or 0)
        meta_text = f"Author: {author}  |  Downloads: {downloads:,}"
        self.meta_label = QLabel(meta_text)
        self.meta_label.setObjectName("remoteContentMeta")
        info_layout.addWidget(self.meta_label)

        # Version list
        version_label = QLabel("Versions:")
        version_label.setObjectName("editorSectionTitle")
        info_layout.addWidget(version_label)

        self.version_list = QListWidget()
        self.version_list.setObjectName("musicTrackList")
        self.version_list.setFrameShape(QFrame.NoFrame)
        self.version_list.setMinimumHeight(180)
        info_layout.addWidget(self.version_list, 1)

        # Loading/progress label
        self.status_label = QLabel("Loading versions...")
        self.status_label.setObjectName("editorStatusText")
        info_layout.addWidget(self.status_label)

        root.addWidget(info_card, 1)

        # Footer
        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.install_button = ModernButton("Install Selected", role="accent", height=38, icon_size=0, minimum_width=160)
        self.install_button.clicked.connect(self._install_selected_version)
        self.install_button.setEnabled(False)
        footer.addWidget(self.install_button)
        footer.addStretch()
        cancel_button = ModernButton("Cancel", role="sidebar", height=38, icon_size=0, minimum_width=98)
        cancel_button.clicked.connect(self.reject)
        footer.addWidget(cancel_button)
        root.addLayout(footer)

        self.setStyleSheet(
            """
            QDialog#editInstanceDialog {
                background-color: qradialgradient(
                    cx: 0.16, cy: 0.08, radius: 1.12,
                    fx: 0.16, fy: 0.08,
                    stop: 0 #0f241c, stop: 0.42 #08140f, stop: 1 #040806
                );
            }
            QLabel#editorSectionTitle, QLabel#editorStatusText {
                background: transparent; color: #D9F7E9;
            }
            QLabel#remoteContentMeta {
                background: transparent; color: #7CB8A0; font-size: 12px;
            }
            """
        )

    def _load(self) -> None:
        if not self._project_id:
            QMessageBox.warning(self, "Modrinth Modpack", "Cannot open this pack because the project id is missing.")
            self.reject()
            return
        self.status_label.setText("Loading versions...")
        self._start_worker("versions", project_id=self._project_id)
        icon_url = str(self.project.get("icon_url") or "")
        if icon_url.startswith(("http://", "https://")):
            self._start_icon_worker(icon_url)

    def _start_worker(self, job: str, *, project_id: str = "", version: dict[str, Any] | None = None, icon_url: str = "") -> None:
        worker = ModrinthModpackWorker(self.service, job, project_id=project_id, version=version, icon_url=icon_url, parent=self)
        worker.loaded.connect(self._handle_worker_loaded)
        worker.failed.connect(self._handle_worker_failed)
        worker.finished.connect(lambda w=worker: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(worker)
        worker.start()

    def _start_icon_worker(self, icon_url: str) -> None:
        worker = ModrinthModpackIconWorker([(self._project_id or str(self.project.get("slug") or "project"), icon_url)], self._icon_cache_dir, self)
        worker.icon_loaded.connect(self._handle_icon_loaded)
        worker.finished.connect(lambda w=worker: setattr(self, "_icon_worker", None) if self._icon_worker is w else None)
        self._icon_worker = worker
        worker.start()

    def _handle_icon_loaded(self, key: str, icon_data: object) -> None:
        del key
        if isinstance(icon_data, (bytes, bytearray)):
            pixmap = QPixmap()
            if pixmap.loadFromData(bytes(icon_data)):
                self.setWindowIcon(QIcon(pixmap))

    def _handle_worker_loaded(self, job: str, payload: object) -> None:
        if job == "versions":
            self._versions = list(payload) if isinstance(payload, list) else []
            self._populate_version_list()
            if self._versions:
                self.install_button.setEnabled(True)
                self.status_label.setText(f"{len(self._versions)} versions available. Select one and click Install.")
                self.version_list.setCurrentRow(0)
            else:
                self.status_label.setText("No versions found for this modpack.")
        elif job == "download" and isinstance(payload, str):
            self.install_button.setText("Installing...")
            self.install_button.setEnabled(False)
            self.status_label.setText("Download complete! Creating instance...")
            self.install_ready.emit(str(self.project.get("title") or "Modrinth Modpack"), payload)
            self.accept()

    def _handle_worker_failed(self, message: str) -> None:
        self.install_button.setText("Install Selected")
        self.install_button.setEnabled(bool(self._versions))
        error_text = str(message)
        self.status_label.setText(f"Error loading: {error_text}")
        QMessageBox.warning(self, "Modrinth Modpack", f"Could not load modpack data:\n{error_text}")

    def _populate_version_list(self) -> None:
        self.version_list.clear()
        for version in self._versions:
            game_versions = version.get("game_versions") if isinstance(version.get("game_versions"), list) else []
            minecraft_versions = ", ".join(str(v) for v in game_versions[:4])
            label = str(version.get("name") or version.get("version_number") or "Version")
            version_number = str(version.get("version_number") or "")
            loaders = version.get("loaders") if isinstance(version.get("loaders"), list) else []
            loader_str = ", ".join(str(l) for l in loaders[:2])
            item_text = f"{label}"
            if version_number:
                item_text += f"\n{version_number}"
            if minecraft_versions:
                item_text += f"  |  MC {minecraft_versions}"
            if loader_str:
                item_text += f"  |  {loader_str}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, version)
            item.setSizeHint(QSize(0, 52))
            self.version_list.addItem(item)

    def _install_selected_version(self) -> None:
        item = self.version_list.currentItem()
        if item is None:
            QMessageBox.information(self, "Select Version", "Please select a version from the list first.")
            return
        version = item.data(Qt.UserRole)
        if not isinstance(version, dict):
            return
        if self._download_worker is not None and self._download_worker.isRunning():
            QMessageBox.information(self, "Downloading", "A download is already in progress.")
            return
        self.install_button.setText("Downloading...")
        self.install_button.setEnabled(False)
        self.status_label.setText("Downloading modpack...")
        self._download_worker = ModrinthModpackWorker(self.service, "download", version=version, parent=self)
        self._download_worker.loaded.connect(self._handle_worker_loaded)
        self._download_worker.failed.connect(self._handle_worker_failed)
        self._download_worker.finished.connect(lambda: setattr(self, "_download_worker", None))
        self._download_worker.start()

    def closeEvent(self, event) -> None:
        for worker in list(self._workers):
            if worker.isRunning():
                worker.requestInterruption()
                worker.wait(1500)
        if self._icon_worker is not None and self._icon_worker.isRunning():
            self._icon_worker.requestInterruption()
            self._icon_worker.wait(1500)
        if self._download_worker is not None and self._download_worker.isRunning():
            self._download_worker.requestInterruption()
            self._download_worker.wait(1500)
        super().closeEvent(event)


def _modpack_icon_bytes_for_url(url: str, cache_dir: Path) -> bytes | None:
    cached = _MODPACK_ICON_BYTES_CACHE.get(url)
    if cached:
        return cached
    target = _modpack_icon_cache_path(url, cache_dir)
    if target.is_file():
        try:
            data = target.read_bytes()
        except OSError:
            data = b""
        if data:
            _MODPACK_ICON_BYTES_CACHE[url] = data
            return data
    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": "NOTG-Launcher/Modrinth-Modpacks",
                "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*,*/*;q=0.8",
            },
            timeout=12,
        )
    except requests.RequestException:
        return None
    if not response.ok or not response.content:
        return None
    data = response.content[:1_500_000]
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    except OSError:
        pass
    _MODPACK_ICON_BYTES_CACHE[url] = data
    return data


def _modpack_icon_cache_path(url: str, cache_dir: Path) -> Path:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.img"


def _modpack_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _is_modrinth_modpack_download_url(url_text: str) -> bool:
    text = url_text.lower()
    return "modrinth.com" in text and ("/version/" in text or text.endswith(".mrpack") or "/download" in text)


def _match_modrinth_version_from_url(
    url_text: str,
    versions: list[dict[str, Any]],
    *,
    file_name: str = "",
) -> dict[str, Any] | None:
    normalized = url_text.split("?", 1)[0].rstrip("/")
    version_id_match = re.search(r"/version/([^/?#]+)", normalized, re.IGNORECASE)
    version_id = version_id_match.group(1).lower() if version_id_match else ""
    filename = (file_name.strip() or Path(normalized).name).lower()
    normalized_tokens = {
        token
        for token in {
            _modpack_slug(version_id),
            _modpack_slug(filename),
            Path(filename).stem.lower(),
        }
        if token
    }
    for version in versions:
        if not isinstance(version, dict):
            continue
        version_tokens = {
            token
            for token in {
                _modpack_slug(str(version.get("id") or "")),
                _modpack_slug(str(version.get("version_number") or "")),
                _modpack_slug(str(version.get("name") or "")),
            }
            if token
        }
        if version_id and _modpack_slug(version_id) in version_tokens:
            return version
        files = version.get("files")
        if not isinstance(files, list):
            continue
        for file_info in files:
            if not isinstance(file_info, dict):
                continue
            file_url = str(file_info.get("url") or "").split("?", 1)[0].rstrip("/")
            file_tokens = {
                token
                for token in {
                    _modpack_slug(str(file_info.get("filename") or "")),
                    _modpack_slug(Path(str(file_info.get("filename") or "")).stem),
                    _modpack_slug(Path(file_url).name),
                }
                if token
            }
            if normalized == file_url:
                return version
            if normalized_tokens & (version_tokens | file_tokens):
                return version
    return None


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
        palette = theme_palette(self)["loader_placeholder"]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        outer = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(palette["outer_border"], 1.2))
        painter.setBrush(palette["outer_fill"])
        painter.drawRoundedRect(outer, 12, 12)

        box = QRectF(
            self.width() * 0.08,
            self.height() * 0.24,
            self.width() * 0.84,
            self.height() * 0.52,
        )
        painter.setPen(QPen(palette["inner_border"], 1.0))
        painter.setBrush(palette["inner_fill"])
        painter.drawRoundedRect(box, 10, 10)

        font = QFont(self.font())
        font.setPointSize(12)
        font.setWeight(QFont.Bold)
        painter.setFont(font)
        painter.setPen(palette["text"])
        text_rect = box.adjusted(16, 12, -16, -12)
        painter.drawText(text_rect, Qt.AlignCenter | Qt.TextWordWrap, self._text)


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


class MinecraftImportSelectionDialog(QDialog):
    def __init__(self, source_dir: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.source_dir = source_dir.resolve()
        self.selected_entries: list[str] = []
        self._syncing_checks = False
        self.setObjectName("instanceEditor")
        self.setWindowTitle("Select .minecraft Files")
        self.setModal(True)
        self.setMinimumSize(720, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(12)

        title = QLabel("Select files to import")
        title.setObjectName("editorSectionTitle")
        layout.addWidget(title)

        self.tree = QTreeWidget()
        self.tree.setObjectName("modsTable")
        self.tree.setHeaderLabels(["Name", "Details"])
        self.tree.setFrameShape(QFrame.NoFrame)
        self.tree.setColumnWidth(0, 420)
        self.tree.itemChanged.connect(self._handle_item_changed)
        layout.addWidget(self.tree, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(12)
        footer.addStretch()
        cancel_button = ModernButton("Cancel", role="sidebar", height=40, icon_size=0, minimum_width=104)
        cancel_button.clicked.connect(self.reject)
        footer.addWidget(cancel_button)
        import_button = ModernButton("Import", role="accent", height=40, icon_size=0, minimum_width=104)
        import_button.clicked.connect(self._accept_checked)
        footer.addWidget(import_button)
        layout.addLayout(footer)

        self._populate_tree()

    def _populate_tree(self) -> None:
        self.tree.clear()
        for entry in sorted(self.source_dir.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            self.tree.addTopLevelItem(self._build_item(entry))
        self.tree.collapseAll()

    def _build_item(self, path: Path) -> QTreeWidgetItem:
        relative = path.relative_to(self.source_dir).as_posix()
        details = "Folder" if path.is_dir() else _format_import_file_size(path)
        item = QTreeWidgetItem([path.name, details])
        item.setData(0, Qt.UserRole, relative)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(0, Qt.Checked)
        if path.is_dir():
            item.setFlags(item.flags() | Qt.ItemIsAutoTristate)
            for child in sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
                item.addChild(self._build_item(child))
        return item

    def _handle_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._syncing_checks or column != 0:
            return
        state = item.checkState(0)
        if state == Qt.PartiallyChecked:
            return
        self._syncing_checks = True
        self._set_children_state(item, state)
        self._syncing_checks = False

    def _set_children_state(self, item: QTreeWidgetItem, state: Qt.CheckState) -> None:
        for index in range(item.childCount()):
            child = item.child(index)
            child.setCheckState(0, state)
            self._set_children_state(child, state)

    def _accept_checked(self) -> None:
        entries: list[str] = []
        for index in range(self.tree.topLevelItemCount()):
            self._collect_checked_entries(self.tree.topLevelItem(index), entries)
        if not entries:
            QMessageBox.warning(self, "Import .minecraft", "Select at least one file or folder to import.")
            return
        self.selected_entries = entries
        self.accept()

    def _collect_checked_entries(self, item: QTreeWidgetItem, entries: list[str]) -> None:
        state = item.checkState(0)
        relative = str(item.data(0, Qt.UserRole) or "")
        if state == Qt.Checked:
            entries.append(relative)
            return
        if state == Qt.Unchecked:
            return
        for index in range(item.childCount()):
            self._collect_checked_entries(item.child(index), entries)


def _format_import_file_size(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        return "File"
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


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
        palette = theme_palette(self)["header_icon"]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        scale = screen_scale(self, minimum=0.78, maximum=1.05)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rect.translate(0, -1.0 * self._hover + 0.8 * self._press)

        top_fill = blend_colors(palette["outer_top"], palette["outer_top_hover"], self._hover)
        bottom_fill = blend_colors(palette["outer_bottom"], palette["outer_bottom_hover"], self._hover)
        border = blend_colors(palette["border"], palette["border_hover"], self._hover)
        border = blend_colors(border, palette["border_press"], self._press * 0.5)

        painter.setPen(QPen(border, max(1.0, 1.25 * scale)))
        painter.setBrush(top_fill)
        painter.drawRoundedRect(rect, 16 * scale, 16 * scale)

        inset = 8 * scale
        inner = rect.adjusted(inset, inset, -inset, -inset)
        painter.setPen(QPen(palette["inner_border"], max(1.0, scale)))
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
            glow_color = QColor(palette["glow"])
            accent = QColor(glow_color.red(), glow_color.green(), glow_color.blue(), int(glow_color.alpha() * self._hover))
            painter.setPen(QPen(accent, max(1.2, 2.0 * scale)))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(glow, 14 * scale, 14 * scale)


class AddInstanceDialog(QDialog):
    PAGE_CREATE = 0
    PAGE_IMPORT = 1
    PAGE_MODRINTH = 2

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
        self._minecraft_import_entries: list[str] = []
        self._minecraft_import_source_dir: str | None = None
        self._manual_import_version_requested = False
        self._ram_default_mb = self.service.recommended_minecraft_memory_mb()
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
        self.nav_list.setIconSize(QSize(22, 22))
        for title in ("Create", "Import", "Modpacks"):
            item = QListWidgetItem(title)
            item.setSizeHint(item.sizeHint().expandedTo(item.sizeHint()))
            if title == "Modpacks":
                item.setIcon(QIcon(str(self.service.project_root / "assets" / "Modrinth Logo.png")))
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
        self.page_stack.addWidget(self._build_modrinth_page())
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

        self.copy_add_button = ModernButton(">", role="sidebar", height=38, icon_size=0, radius=10, minimum_width=70, horizontal_padding=16)
        self.copy_add_button.clicked.connect(lambda: self._move_copy_items(self.copy_available_list, self.copy_selected_list))
        transfer_controls.addWidget(self.copy_add_button)

        self.copy_remove_button = ModernButton("<", role="sidebar", height=38, icon_size=0, radius=10, minimum_width=70, horizontal_padding=16)
        self.copy_remove_button.clicked.connect(lambda: self._move_copy_items(self.copy_selected_list, self.copy_available_list))
        transfer_controls.addWidget(self.copy_remove_button)

        self.copy_all_button = ModernButton(">>", role="accent", height=38, icon_size=0, radius=10, minimum_width=76, horizontal_padding=18)
        self.copy_all_button.clicked.connect(self._move_all_copy_items)
        transfer_controls.addWidget(self.copy_all_button)

        self.copy_clear_button = ModernButton("<<", role="sidebar", height=38, icon_size=0, radius=10, minimum_width=76, horizontal_padding=18)
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

        self.optimize_minecraft_checkbox = QCheckBox("Optimize Minecraft")
        self.optimize_minecraft_checkbox.setObjectName("editorFilterCheck")
        self.optimize_minecraft_checkbox.setChecked(True)
        advanced_layout.addWidget(self.optimize_minecraft_checkbox)

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

        self.ram_go_beyond_checkbox = QCheckBox("Go Beyond")
        self.ram_go_beyond_checkbox.setObjectName("editorFilterCheck")
        self.ram_go_beyond_checkbox.setChecked(False)
        self.ram_go_beyond_checkbox.toggled.connect(self._on_ram_go_beyond_toggled)
        advanced_layout.addWidget(self.ram_go_beyond_checkbox)

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

        version_divider = QFrame()
        version_divider.setObjectName("editorSectionDivider")
        import_layout.addWidget(version_divider)

        version_row = QHBoxLayout()
        version_row.setContentsMargins(0, 0, 0, 0)
        version_row.setSpacing(12)
        import_layout.addLayout(version_row)
        version_text = QVBoxLayout()
        version_text.setSpacing(4)
        version_title = QLabel("Manual Version")
        version_title.setObjectName("editorImportCaption")
        version_text.addWidget(version_title)
        self.import_version_summary = QLabel("Select a version in case the launcher cannot identify it by itself.")
        self.import_version_summary.setObjectName("editorStatusText")
        self.import_version_summary.setWordWrap(True)
        version_text.addWidget(self.import_version_summary)
        version_row.addLayout(version_text, 1)
        self.import_choose_version_button = ModernButton("Choose Version", role="sidebar", height=40, icon_size=0, minimum_width=150, horizontal_padding=20)
        self.import_choose_version_button.clicked.connect(self._show_version_selector_for_import)
        version_row.addWidget(self.import_choose_version_button, 0, Qt.AlignVCenter)
        import_layout.addStretch()

        scroll_layout.addWidget(import_surface)
        scroll_area.setWidget(scroll_widget)
        return scroll_area

    def _build_modrinth_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(12)

        surface = QFrame()
        surface.setObjectName("modrinthSelectionSurface")
        surface_layout = QVBoxLayout(surface)
        surface_layout.setContentsMargins(22, 22, 22, 22)
        surface_layout.setSpacing(16)
        surface.setStyleSheet(
            """
            QFrame#modrinthSelectionSurface {
                background-color: rgba(5, 11, 18, 0.90);
                border: 1px solid rgba(48, 209, 138, 0.66);
                border-radius: 14px;
            }
            QLabel#editorStatusText {
                color: #B8E8D7;
                background: transparent;
            }
            """
        )

        title = QLabel("Modrinth Modpacks")
        title.setObjectName("editorSectionTitle")
        surface_layout.addWidget(title)

        open_selector_button = ModernButton("Open Modpacks", role="accent", height=44, icon_size=0, minimum_width=220)
        open_selector_button.clicked.connect(self._open_modrinth_selector)
        surface_layout.addWidget(open_selector_button, 0, Qt.AlignLeft)

        surface_layout.addStretch()
        layout.addWidget(surface, 1)
        return page

    def _open_modrinth_selector(self) -> None:
        browser = ModrinthModpackBrowser(self.service, self)
        browser.install_ready.connect(self._accept_modrinth_modpack)
        browser.exec()

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
        if target_index == self.PAGE_MODRINTH:
            QTimer.singleShot(0, self._open_modrinth_selector)
        self.ok_button.setVisible(target_index != self.PAGE_MODRINTH)
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
        self.import_choose_version_button.set_metrics(height=scaled_px(self, 40, minimum=36, maximum=42), icon_size=0)
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
        self._sync_import_version_summary()

    def _on_loader_selection_changed(self) -> None:
        self._update_name_placeholder()
        self._sync_import_version_summary()

    def _on_loader_toggled(self, loader_id: str | None, checked: bool) -> None:
        if not checked:
            return

        self._current_loader_id = loader_id
        self._update_name_placeholder()
        self._refresh_loader_rows(force_refresh=False)
        self._sync_import_version_summary()

    def _sync_loader_availability(self) -> None:
        for loader_id, button in self.loader_buttons.items():
            button.setEnabled(True)
            button.setToolTip("")

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
        self._sync_import_version_summary()

    def _sync_import_version_summary(self) -> None:
        if not hasattr(self, "import_version_summary"):
            return
        if not self._manual_import_version_requested:
            self.import_version_summary.setText("Select a version in case the launcher cannot identify it by itself.")
            return
        version = self.current_version_id()
        if not version:
            self.import_version_summary.setText("Select a version in case the launcher cannot identify it by itself.")
            return
        if self._current_loader_id is None:
            stack_text = version
        else:
            loader_row = self.current_loader_row()
            loader_name = self.service.get_mod_loader_name(self._current_loader_id)
            loader_version = str(loader_row["loader_version"]) if loader_row else ""
            loader_text = f"{loader_name} {loader_version}".strip()
            stack_text = f"{version} and {loader_text}" if loader_text else version
        self.import_version_summary.setText(f"This {stack_text} will be downloaded if the version is not found.")

    def _show_version_selector_for_import(self) -> None:
        self._manual_import_version_requested = True
        self._sync_import_version_summary()
        self.nav_list.setCurrentRow(self.PAGE_CREATE)
        if hasattr(self, "create_tabs"):
            self.create_tabs.setCurrentIndex(0)

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
        maximum_mb = self._ram_slider_limit_mb()
        minimum_mb = 1024
        self.ram_slider.setMinimum(minimum_mb // self._ram_slider_step_mb)
        self.ram_slider.setMaximum(maximum_mb // self._ram_slider_step_mb)

    def _system_ram_limit_mb(self) -> int:
        total_mb = int(psutil.virtual_memory().total / (1024 * 1024))
        return max(1024, (total_mb // self._ram_slider_step_mb) * self._ram_slider_step_mb)

    def _safe_ram_limit_mb(self) -> int:
        total_mb = int(psutil.virtual_memory().total / (1024 * 1024))
        safe_mb = (int(total_mb * 0.75) // 1024) * 1024
        return max(self._ram_default_mb, min(16384, safe_mb))

    def _ram_slider_limit_mb(self) -> int:
        if getattr(self, "ram_go_beyond_checkbox", None) is not None and self.ram_go_beyond_checkbox.isChecked():
            return self._system_ram_limit_mb()
        return self._safe_ram_limit_mb()

    def _slider_to_mb(self, slider_value: int) -> int:
        return slider_value * self._ram_slider_step_mb

    def _mb_to_slider(self, memory_mb: int) -> int:
        return max(self.ram_slider.minimum(), min(self.ram_slider.maximum(), memory_mb // self._ram_slider_step_mb))

    def _snap_memory_mb(self, memory_mb: int) -> int:
        snapped = int(round(memory_mb / self._ram_slider_step_mb) * self._ram_slider_step_mb)
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

    def _on_ram_go_beyond_toggled(self, checked: bool) -> None:
        selected_mb = self._ram_selected_mb
        self._update_ram_slider_range()
        if not checked:
            selected_mb = min(selected_mb, self._slider_to_mb(self.ram_slider.maximum()))
        self._set_ram_value(selected_mb, animate=False)

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
            "optimize_minecraft": self.optimize_minecraft_checkbox.isChecked(),
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

        source_dir = None
        if modpack_path and not Path(modpack_path).is_file():
            self.ok_button.flash_invalid()
            QMessageBox.warning(self, "Missing Modpack", "Select a valid modpack archive to continue.")
            return
        if minecraft_path:
            valid, message = self.service.is_valid_minecraft_dir(minecraft_path)
            if not valid:
                self.ok_button.flash_invalid()
                QMessageBox.warning(self, "Invalid .minecraft Folder", message)
                return

            source_dir = self.service.resolve_minecraft_import_source(minecraft_path)
            if source_dir is None:
                self.ok_button.flash_invalid()
                QMessageBox.warning(self, "Invalid .minecraft Folder", message)
                return

        preview_metadata = self.service.preview_import_metadata(
            modpack_path=modpack_path or None,
            minecraft_import_dir=minecraft_path or None,
        )
        selected_loader_version = None
        selected_version = None
        if self._manual_import_version_requested:
            version_row = self.current_version_row()
            if version_row is None:
                self.ok_button.flash_invalid()
                QMessageBox.warning(self, "Missing Version", "Select a Minecraft version for the imported instance.")
                self._show_version_selector_for_import()
                return
            selected_version = str(version_row["id"])
        elif preview_metadata is None:
            self._manual_import_version_requested = True
            self.ok_button.flash_invalid()
            QMessageBox.warning(
                self,
                "Choose Version",
                "The launcher could not detect a Minecraft version from this import. Choose the Minecraft version and mod loader to install for it.",
            )
            self._show_version_selector_for_import()
            return

        if self._manual_import_version_requested and self._current_loader_id:
            loader_row = self.current_loader_row()
            if loader_row is None:
                self.ok_button.flash_invalid()
                QMessageBox.warning(self, "Missing Loader Version", "Select a mod loader version or switch the loader back to None.")
                self._show_version_selector_for_import()
                return
            selected_loader_version = str(loader_row["loader_version"])

        if modpack_path:
            self.selection = {
                "name": self.name_edit.text().strip(),
                "vanilla_version": selected_version,
                "mod_loader_id": self._current_loader_id if self._manual_import_version_requested else None,
                "mod_loader_version": selected_loader_version,
                "icon_path": self._selected_icon_path,
                "memory_mb": self._ram_selected_mb,
                "optimize_minecraft": self.optimize_minecraft_checkbox.isChecked(),
                "operation": "import_modpack",
                "modpack_path": modpack_path,
                "minecraft_import_dir": None,
                "minecraft_import_entries": [],
                "copy_source_instance_id": None,
                "copy_user_data": [],
            }
            self.accept()
            return

        if source_dir is None:
            return
        resolved_source = str(source_dir.resolve())
        if not self._minecraft_import_entries or self._minecraft_import_source_dir != resolved_source:
            selection_dialog = MinecraftImportSelectionDialog(source_dir, self)
            if selection_dialog.exec() != QDialog.Accepted:
                return
            self._minecraft_import_entries = list(selection_dialog.selected_entries)
            self._minecraft_import_source_dir = resolved_source

        self.selection = {
            "name": self.name_edit.text().strip(),
            "vanilla_version": selected_version,
            "mod_loader_id": self._current_loader_id if self._manual_import_version_requested else None,
            "mod_loader_version": selected_loader_version,
            "icon_path": self._selected_icon_path,
            "memory_mb": self._ram_selected_mb,
            "optimize_minecraft": self.optimize_minecraft_checkbox.isChecked(),
            "operation": "import_minecraft",
            "modpack_path": None,
            "minecraft_import_dir": minecraft_path,
            "minecraft_import_entries": list(self._minecraft_import_entries),
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
        self._minecraft_import_entries = []
        self._minecraft_import_source_dir = None
        self._manual_import_version_requested = False
        self._sync_import_version_summary()
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

        source_dir = self.service.resolve_minecraft_import_source(folder_path)
        if source_dir is None:
            self.ok_button.flash_invalid()
            QMessageBox.warning(self, "Invalid .minecraft Folder", message)
            return

        selection_dialog = MinecraftImportSelectionDialog(source_dir, self)
        if selection_dialog.exec() != QDialog.Accepted:
            return

        self._minecraft_import_entries = list(selection_dialog.selected_entries)
        self._minecraft_import_source_dir = str(source_dir.resolve())
        self._manual_import_version_requested = False
        self._sync_import_version_summary()
        self.minecraft_input.setText(folder_path)
        if self.modpack_input.text():
            self.modpack_input.clear()

    def _accept_modrinth_modpack(self, suggested_name: str, modpack_path: str) -> None:
        if suggested_name and not self.name_edit.text().strip():
            self.name_edit.setText(suggested_name)
        self.selection = {
            "name": self.name_edit.text().strip() or suggested_name,
            "vanilla_version": None,
            "mod_loader_id": None,
            "mod_loader_version": None,
            "icon_path": self._selected_icon_path,
            "memory_mb": self._ram_selected_mb,
            "optimize_minecraft": self.optimize_minecraft_checkbox.isChecked(),
            "operation": "import_modpack",
            "modpack_path": modpack_path,
            "minecraft_import_dir": None,
            "minecraft_import_entries": [],
            "copy_source_instance_id": None,
            "copy_user_data": [],
        }
        self.accept()

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
            self._sync_import_version_summary()
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
            self._sync_import_version_summary()

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