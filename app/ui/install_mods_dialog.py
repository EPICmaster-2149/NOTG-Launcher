from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import requests
from PySide6.QtCore import QEasingCurve, QRectF, QSize, Qt, QThread, QTimer, Signal, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.launcher import InstanceRecord, LauncherService
from ui.add_instance_dialog import AccentLineEdit
from ui.app_icon import application_icon
from ui.responsive import fitted_window_size, scaled_px
from ui.topbar import ModernButton


_ICON_BYTES_CACHE: dict[str, bytes] = {}


class RemoteContentWorker(QThread):
    loaded = Signal(str, object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(
        self,
        service: LauncherService,
        instance: InstanceRecord,
        job: str,
        *,
        provider: str,
        content_type: str,
        query: str = "",
        project: dict[str, Any] | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._service = service
        self._instance = instance
        self._job = job
        self._provider = provider
        self._content_type = content_type
        self._query = query
        self._project = dict(project or {})

    def run(self) -> None:
        try:
            if self._job == "search":
                projects = self._service.search_remote_content(
                    self._instance,
                    provider=self._provider,
                    content_type=self._content_type,
                    query=self._query,
                    limit=24,
                )
                installed = self._service.remote_content_installed_index(self._instance, self._content_type)
                payload = {
                    "projects": projects,
                    "installed": list(installed),
                }
            elif self._job == "details":
                payload = self._service.get_remote_content_details(self._instance, self._project)
            elif self._job == "install":
                payload = self._service.install_remote_content(
                    self._instance,
                    self._project,
                    progress_callback=self.progress.emit,
                )
            else:
                raise ValueError(f"Unsupported remote content job: {self._job}")
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return

        if not self.isInterruptionRequested():
            self.loaded.emit(self._job, payload)


class RemoteIconWorker(QThread):
    icon_loaded = Signal(str, object)

    def __init__(self, targets: list[tuple[str, str]], cache_dir: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self._targets = list(targets)
        self._cache_dir = cache_dir

    def run(self) -> None:
        for key, url in self._targets:
            if self.isInterruptionRequested():
                return
            data = _icon_bytes_for_url(url, self._cache_dir)
            if data:
                self.icon_loaded.emit(key, data)


class ProviderLogo(QLabel):
    def __init__(self, text: str, color: str, parent: QWidget | None = None):
        super().__init__(text, parent)
        self._color = QColor(color)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(28, 28)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 7, 7)
        font = QFont(self.font())
        font.setWeight(QFont.Black)
        painter.setFont(font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(self.rect(), Qt.AlignCenter, self.text())


class ProjectIcon(QLabel):
    def __init__(self, project: dict[str, Any], parent: QWidget | None = None):
        super().__init__(parent)
        self._fallback: ProviderLogo | None = None
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
            self._fallback = ProviderLogo("M" if provider == "modrinth" else "C", "#30B27B" if provider == "modrinth" else "#FF6432", self)
            self._fallback.move(8, 8)


def _provider_icon(text: str, color: str) -> QIcon:
    pixmap = QPixmap(28, 28)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(pixmap.rect().adjusted(1, 1, -1, -1), 7, 7)
    font = QFont()
    font.setWeight(QFont.Black)
    font.setPointSize(11)
    painter.setFont(font)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(pixmap.rect(), Qt.AlignCenter, text)
    painter.end()
    return QIcon(pixmap)


class RemoteContentRow(QWidget):
    install_requested = Signal(object)

    def __init__(self, project: dict[str, Any], parent: QWidget | None = None):
        super().__init__(parent)
        self.project = project
        self._hover = 0.0
        self._active = 0.0
        self.setObjectName("remoteContentRow")
        self.setMinimumHeight(86)
        self.setMouseTracking(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(14)

        self.icon = ProjectIcon(project)
        layout.addWidget(self.icon, 0, Qt.AlignVCenter)

        text_column = QVBoxLayout()
        text_column.setSpacing(3)
        self.title = QLabel(str(project.get("title") or "Untitled"))
        self.title.setObjectName("musicTrackName")
        self.title.setWordWrap(False)
        text_column.addWidget(self.title)
        author = str(project.get("author") or "Unknown author")
        self.description = QLabel(author)
        self.description.setObjectName("editorStatusText")
        self.description.setWordWrap(False)
        text_column.addWidget(self.description)
        provider = "Modrinth" if project.get("provider") == "modrinth" else "CurseForge"
        downloads = int(project.get("downloads") or 0)
        self.metadata = QLabel(f"{provider}  /  {downloads:,} downloads")
        self.metadata.setObjectName("remoteContentMeta")
        self.metadata.setWordWrap(False)
        text_column.addWidget(self.metadata)
        layout.addLayout(text_column, 1)

        self.install_button = ModernButton("Install", role="accent", height=34, icon_size=0, minimum_width=98, horizontal_padding=18)
        self.install_button.clicked.connect(lambda: self.install_requested.emit(self.project))
        layout.addWidget(self.install_button)
        self._hover_animation = QVariantAnimation(self, duration=150, easingCurve=QEasingCurve.OutCubic)
        self._hover_animation.valueChanged.connect(lambda value: self._set_value("_hover", value))
        self._active_animation = QVariantAnimation(self, duration=180, easingCurve=QEasingCurve.OutCubic)
        self._active_animation.valueChanged.connect(lambda value: self._set_value("_active", value))

    def set_icon_data(self, icon_data: bytes) -> None:
        self.project["icon_data"] = icon_data
        self.icon.set_icon_data(icon_data, str(self.project.get("provider") or ""))

    def set_selected(self, selected: bool) -> None:
        self._animate(self._active_animation, self._active, 1.0 if selected else 0.0)

    def set_state(self, state: str) -> None:
        if state == "installing":
            self.install_button.setText("Installing...")
            self.install_button.set_role("warning")
            self.install_button.setEnabled(False)
        elif state == "installed":
            self.install_button.setText("Installed")
            self.install_button.set_role("sidebar")
            self.install_button.setEnabled(False)
        else:
            self.install_button.setText("Install")
            self.install_button.set_role("accent")
            self.install_button.setEnabled(True)

    def enterEvent(self, event) -> None:
        self._animate(self._hover_animation, self._hover, 1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate(self._hover_animation, self._hover, 0.0)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        del event
        accent = _provider_accent(str(self.project.get("provider") or ""))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        base = QColor(9, 15, 25, 186)
        hover = QColor(accent)
        hover.setAlpha(38)
        active = QColor(accent)
        active.setAlpha(62)
        bg = _blend(base, hover, self._hover)
        bg = _blend(bg, active, self._active)
        border = QColor(accent)
        border.setAlpha(int(58 + (self._hover * 44) + (self._active * 70)))
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 8, 8)

    def _animate(self, animation: QVariantAnimation, start: float, end: float) -> None:
        animation.stop()
        animation.setStartValue(float(start))
        animation.setEndValue(float(end))
        animation.start()

    def _set_value(self, attribute: str, value) -> None:
        setattr(self, attribute, float(value))
        self.update()


class InstallModsDialog(QDialog):
    def __init__(self, service: LauncherService, instance: InstanceRecord, parent: QWidget | None = None):
        super().__init__(parent)
        self.service = service
        self.instance = instance
        self._provider = "modrinth"
        self._content_type = "mods"
        self._projects: list[dict[str, Any]] = []
        self._rows: dict[str, RemoteContentRow] = {}
        self._installed: set[str] = set()
        self._worker: RemoteContentWorker | None = None
        self._icon_worker: RemoteIconWorker | None = None
        self._active_job: str | None = None
        self._selected_project: dict[str, Any] | None = None
        self._installing_project_key: str | None = None
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._run_search)
        self._icon_cache_dir = self.service.cache_root / "remote-content-icons"

        self.setObjectName("editInstanceDialog")
        self.setWindowTitle(f"Install Mods - {instance.name}")
        self.setWindowIcon(application_icon(self.service.project_root))
        self.setModal(False)
        self.setMinimumSize(900, 620)
        self.resize(fitted_window_size(self.parentWidget() or self, 1120, 720, minimum_width=900, minimum_height=620))

        self._build_ui()
        self._apply_responsive_layout()
        self._apply_provider_theme()
        self._run_search()

    def resizeEvent(self, event) -> None:
        self._apply_responsive_layout()
        super().resizeEvent(event)

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.requestInterruption()
            self._worker.wait()
        if self._icon_worker is not None and self._icon_worker.isRunning():
            self._icon_worker.requestInterruption()
            self._icon_worker.wait()
        super().closeEvent(event)

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("instanceEditorNav")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 14, 12, 14)
        sidebar_layout.setSpacing(10)
        sidebar_layout.addWidget(QLabel("Sources"))

        self.modrinth_button = ModernButton(
            "Modrinth",
            icon=QIcon(str(self.service.project_root / "assets" / "Modrinth Logo.png")),
            role="accent",
            height=48,
            icon_size=24,
            minimum_width=180,
            horizontal_padding=16,
        )
        self.modrinth_button.clicked.connect(lambda: self._set_provider("modrinth"))
        sidebar_layout.addWidget(self.modrinth_button)
        self.curseforge_button = ModernButton(
            "CurseForge",
            icon=QIcon(str(self.service.project_root / "assets" / "Curseforge Logo.png")),
            role="sidebar",
            height=48,
            icon_size=24,
            minimum_width=180,
            horizontal_padding=16,
        )
        self.curseforge_button.clicked.connect(lambda: self._set_provider("curseforge"))
        sidebar_layout.addWidget(self.curseforge_button)
        sidebar_layout.addStretch()
        root.addWidget(sidebar)
        self.sidebar = sidebar

        content = QFrame()
        content.setObjectName("instanceEditorContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(18, 16, 18, 16)
        content_layout.setSpacing(12)
        root.addWidget(content, 1)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        self.search_input = AccentLineEdit("Browse marketplace content...")
        self.search_input.textChanged.connect(self._schedule_search)
        self.search_input.returnPressed.connect(self._run_search)
        top_row.addWidget(self.search_input, 1)
        self.loader_badge = QLabel(f"")
        self.loader_badge.setObjectName("editorStatusText")
        top_row.addWidget(self.loader_badge)
        self.version_badge = QLabel(f"")
        self.version_badge.setObjectName("editorStatusText")
        top_row.addWidget(self.version_badge)
        self.content_type_combo = QComboBox()
        self.content_type_combo.setObjectName("editorComboBox")
        self.content_type_combo.addItem("Mods", "mods")
        self.content_type_combo.addItem("Resource Packs", "resourcepacks")
        self.content_type_combo.currentIndexChanged.connect(self._handle_content_type_changed)
        top_row.addWidget(self.content_type_combo)
        content_layout.addLayout(top_row)

        self.filter_label = QLabel("")
        self.filter_label.setObjectName("editorStatusText")
        content_layout.addWidget(self.filter_label)

        self.result_list = QListWidget()
        self.result_list.setObjectName("musicTrackList")
        self.result_list.setFrameShape(QFrame.NoFrame)
        self.result_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.result_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.result_list.setUniformItemSizes(True)
        self.result_list.setLayoutMode(QListView.LayoutMode.Batched)
        self.result_list.setBatchSize(10)
        self.result_list.currentItemChanged.connect(self._handle_current_item_changed)
        content_layout.addWidget(self.result_list, 2)

        self.details_scroll = QScrollArea()
        self.details_scroll.setObjectName("instanceEditorScroll")
        self.details_scroll.setWidgetResizable(True)
        self.details_scroll.setFrameShape(QFrame.NoFrame)
        self.details_scroll.setFixedHeight(200)
        self.details_widget = QWidget()
        details_layout = QVBoxLayout(self.details_widget)
        details_layout.setContentsMargins(0, 0, 6, 0)
        details_layout.setSpacing(8)
        self.details_title = QLabel("Select an item")
        self.details_title.setObjectName("editorSectionTitle")
        details_layout.addWidget(self.details_title)
        self.details_text = QLabel("")
        self.details_text.setObjectName("editorStatusText")
        self.details_text.setWordWrap(True)
        details_layout.addWidget(self.details_text)
        self.details_install_button = ModernButton("Install", role="accent", height=38, icon_size=0, minimum_width=106, horizontal_padding=22)
        self.details_install_button.clicked.connect(lambda: self._install_project(self._selected_project))
        details_layout.addWidget(self.details_install_button, 0, Qt.AlignRight)
        self.details_scroll.setWidget(self.details_widget)
        content_layout.addWidget(self.details_scroll, 1)

    def _apply_responsive_layout(self) -> None:
        self.sidebar.setFixedWidth(scaled_px(self, 240, minimum=210, maximum=250))
        self.result_list.setSpacing(scaled_px(self, 7, minimum=5, maximum=9))
        self.modrinth_button.set_metrics(height=scaled_px(self, 48, minimum=42, maximum=50), icon_size=scaled_px(self, 24, minimum=22, maximum=26))
        self.curseforge_button.set_metrics(height=scaled_px(self, 48, minimum=42, maximum=50), icon_size=scaled_px(self, 24, minimum=22, maximum=26))
        self.details_install_button.set_metrics(height=scaled_px(self, 38, minimum=34, maximum=40), icon_size=0)

    def _set_provider(self, provider: str) -> None:
        if provider == self._provider:
            return
        self._provider = provider
        self.modrinth_button.set_role("accent" if provider == "modrinth" else "sidebar")
        self.curseforge_button.set_role("accent" if provider == "curseforge" else "sidebar")
        self._apply_provider_theme()
        self._run_search()

    def _handle_content_type_changed(self) -> None:
        self._content_type = str(self.content_type_combo.currentData(Qt.UserRole) or "mods")
        self._run_search()

    def _schedule_search(self) -> None:
        if self._active_job == "install":
            return
        self._search_timer.start()

    def _run_search(self) -> None:
        if self._active_job == "install":
            return
        self._search_timer.stop()
        self._content_type = str(self.content_type_combo.currentData(Qt.UserRole) or "mods")
        self.filter_label.setText(f"Filtering {self._content_type_label()} for Minecraft {self.instance.vanilla_version} and {self.instance.loader_name}.")
        self.result_list.clear()
        self._rows.clear()
        if self._icon_worker is not None and self._icon_worker.isRunning():
            self._icon_worker.requestInterruption()
        self.details_title.setText("Loading...")
        self.details_text.setText("")
        self._start_worker("search", query=self.search_input.text())

    def _start_worker(self, job: str, *, query: str = "", project: dict[str, Any] | None = None) -> None:
        if self._worker is not None and self._worker.isRunning():
            if self._active_job == "install":
                return
            self._worker.requestInterruption()
            self._worker.wait()
        self._active_job = job
        self._worker = RemoteContentWorker(
            self.service,
            self.instance,
            job,
            provider=self._provider,
            content_type=self._content_type,
            query=query,
            project=project,
            parent=self,
        )
        self._worker.loaded.connect(self._handle_worker_loaded)
        self._worker.failed.connect(self._handle_worker_failed)
        self._worker.progress.connect(self._handle_install_progress)
        self._worker.finished.connect(self._handle_worker_finished)
        self._worker.start()

    def _handle_worker_loaded(self, job: str, payload: object) -> None:
        if job == "search":
            if isinstance(payload, dict):
                self._projects = list(payload.get("projects")) if isinstance(payload.get("projects"), list) else []
                self._installed = {str(item) for item in payload.get("installed", []) if item}
            else:
                self._projects = list(payload) if isinstance(payload, list) else []
            self._populate_results()
            return
        if job == "details":
            if isinstance(payload, dict):
                self._show_details(payload)
            return
        if job == "install":
            key = self._installing_project_key
            if key:
                self._installed.add(key)
                if self._selected_project is not None:
                    self._installed.update(self._project_key_candidates(self._selected_project))
                self._set_row_state(key, "installed")
                if self._selected_project is not None and self._project_key(self._selected_project) == key:
                    self._set_details_install_state("installed")
            installed = ", ".join(str(item) for item in payload) if isinstance(payload, list) else ""
            if installed:
                self.details_text.setText(f"{self.details_text.text()}\n\nInstalled: {installed}")

    def _handle_worker_failed(self, message: str) -> None:
        self.details_title.setText("Could not load content")
        self.details_text.setText(message)
        QMessageBox.warning(self, "Install Mods", message)
        failed_key = self._installing_project_key
        if failed_key:
            self._set_row_state(failed_key, "ready")
        if self._selected_project is not None and self._project_key(self._selected_project) == failed_key:
            self._set_details_install_state("ready")

    def _handle_worker_finished(self) -> None:
        finished_job = self._active_job
        self._active_job = None
        if finished_job == "install":
            self._installing_project_key = None
            self._set_controls_enabled(True)

    def _handle_install_progress(self, message: str) -> None:
        if message:
            self.details_title.setText(message)

    def _populate_results(self) -> None:
        self.result_list.clear()
        self._rows.clear()
        if not self._projects:
            self.details_title.setText("No results")
            self.details_text.setText("No compatible content was returned for this instance.")
            return
        for project in self._projects:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, project)
            item.setSizeHint(QSize(0, 94))
            self.result_list.addItem(item)
            row = RemoteContentRow(project)
            row.install_requested.connect(self._install_project)
            state = "installed" if self._is_project_installed(project) else "ready"
            row.set_state(state)
            self.result_list.setItemWidget(item, row)
            self._rows[self._project_key(project)] = row
        self.result_list.setCurrentRow(0)
        self._sync_row_selection()
        self._start_icon_worker()

    def _handle_current_item_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        del previous
        if current is None:
            return
        project = current.data(Qt.UserRole)
        if not isinstance(project, dict):
            return
        self._selected_project = project
        self._show_details(project)
        self._sync_row_selection()
        if self._active_job == "install":
            return
        self._start_worker("details", project=project)

    def _sync_row_selection(self) -> None:
        current = self.result_list.currentItem()
        for index in range(self.result_list.count()):
            item = self.result_list.item(index)
            row = self.result_list.itemWidget(item)
            if isinstance(row, RemoteContentRow):
                row.set_selected(item is current)

    def _start_icon_worker(self) -> None:
        targets: list[tuple[str, str]] = []
        for project in self._projects:
            url = str(project.get("icon_url") or "")
            if url.startswith(("http://", "https://")):
                targets.append((self._project_key(project), url))
        if not targets:
            return
        worker = RemoteIconWorker(targets, self._icon_cache_dir, self)
        worker.icon_loaded.connect(self._handle_icon_loaded)
        worker.finished.connect(lambda worker=worker: self._handle_icon_worker_finished(worker))
        self._icon_worker = worker
        worker.start()

    def _handle_icon_loaded(self, key: str, icon_data: object) -> None:
        if not isinstance(icon_data, (bytes, bytearray)):
            return
        row = self._rows.get(key)
        if row is not None:
            row.set_icon_data(bytes(icon_data))

    def _handle_icon_worker_finished(self, worker: RemoteIconWorker) -> None:
        if self._icon_worker is worker:
            self._icon_worker = None

    def _show_details(self, project: dict[str, Any]) -> None:
        self._selected_project = project
        self.details_title.setText(str(project.get("title") or "Untitled"))
        lines = [
            str(project.get("description") or ""),
            f"Provider: {'Modrinth' if project.get('provider') == 'modrinth' else 'CurseForge'}",
            f"Type: {self._content_type_label()}",
            f"Downloads: {int(project.get('downloads') or 0):,}",
        ]
        if project.get("author"):
            lines.append(f"Author: {project['author']}")
        if project.get("version_name"):
            lines.append(f"Selected file: {project['version_name']}")
        if project.get("file_name"):
            lines.append(f"Filename: {project['file_name']}")
        if project.get("dependencies_count") is not None:
            lines.append(f"Required dependencies: {project['dependencies_count']}")
        self.details_text.setText("\n".join(line for line in lines if line))
        state = "installed" if self._is_project_installed(project) else "ready"
        self._set_details_install_state(state)

    def _install_project(self, project: dict[str, Any] | None) -> None:
        if self._active_job == "install":
            return
        if not project:
            return
        self._selected_project = project
        key = self._project_key(project)
        if self._is_project_installed(project):
            return
        self._installing_project_key = key
        self._set_row_state(key, "installing")
        self._set_details_install_state("installing")
        self._set_controls_enabled(False)
        self._start_worker("install", project=project)

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.search_input.setEnabled(enabled)
        self.content_type_combo.setEnabled(enabled)
        self.modrinth_button.setEnabled(enabled)
        self.curseforge_button.setEnabled(enabled)
        self.result_list.setEnabled(enabled)

    def _set_row_state(self, key: str, state: str) -> None:
        row = self._rows.get(key)
        if row is not None:
            row.set_state(state)

    def _set_details_install_state(self, state: str) -> None:
        if state == "installing":
            self.details_install_button.setText("Installing...")
            self.details_install_button.set_role("warning")
            self.details_install_button.setEnabled(False)
        elif state == "installed":
            self.details_install_button.setText("Installed")
            self.details_install_button.set_role("sidebar")
            self.details_install_button.setEnabled(False)
        else:
            self.details_install_button.setText("Install")
            self.details_install_button.set_role("accent")
            self.details_install_button.setEnabled(True)

    def _project_key(self, project: dict[str, Any]) -> str:
        candidates = sorted(self._project_key_candidates(project))
        return candidates[0] if candidates else f"{project.get('provider')}:{project.get('project_id') or project.get('slug')}"

    def _project_key_candidates(self, project: dict[str, Any]) -> set[str]:
        provider = str(project.get("provider") or "").lower()
        candidates: set[str] = set()
        for key_name in ("project_id", "slug"):
            value = str(project.get(key_name) or "").strip()
            if value:
                candidates.add(f"{provider}:{value.lower()}")
                normalized = _slug(value)
                if normalized:
                    candidates.add(f"{provider}:{normalized}")
        title = str(project.get("title") or "").strip()
        if title:
            normalized = _slug(title)
            if normalized:
                candidates.add(f"{provider}:{normalized}")
        return candidates

    def _is_project_installed(self, project: dict[str, Any]) -> bool:
        return bool(self._project_key_candidates(project) & self._installed)

    def _content_type_label(self) -> str:
        return {
            "mods": "mods",
            "resourcepacks": "resource packs",
        }.get(self._content_type, self._content_type)

    def _apply_provider_theme(self) -> None:
        accent = _provider_accent(self._provider)
        accent_hex = accent.name()
        tint = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.24)"
        self.setStyleSheet(
            f"""
            QDialog#editInstanceDialog {{
                background-color: qradialgradient(
                    cx: 0.16,
                    cy: 0.08,
                    radius: 1.12,
                    fx: 0.16,
                    fy: 0.08,
                    stop: 0 #14243a,
                    stop: 0.42 #09111d,
                    stop: 1 #050911
                );
            }}
            QFrame#instanceEditorContent {{
                background-color: rgba(7, 12, 20, 0.88);
                border: 1px solid {accent_hex};
                border-radius: 8px;
            }}
            QFrame#instanceEditorNav {{
                background-color: rgba(8, 15, 26, 0.90);
                border: 1px solid rgba(88, 122, 174, 0.34);
                border-top-left-radius: 12px;
                border-bottom-left-radius: 12px;
            }}
            QListWidget#musicTrackList {{
                background-color: rgba(5, 10, 18, 0.58);
                border: 1px solid {tint};
                border-radius: 12px;
                padding: 8px;
            }}
            QLabel#editorStatusText {{
                color: #B8C7DA;
            }}
            QLabel#remoteContentMeta {{
                color: rgba(190, 207, 232, 0.72);
                background: transparent;
                font-size: 11px;
                font-weight: 600;
            }}
            """
        )


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return text


def _provider_accent(provider: str) -> QColor:
    return QColor("#30D18A") if provider == "modrinth" else QColor("#FF7442")


def _blend(start: QColor, end: QColor, factor: float) -> QColor:
    factor = max(0.0, min(1.0, factor))
    return QColor(
        int(start.red() + (end.red() - start.red()) * factor),
        int(start.green() + (end.green() - start.green()) * factor),
        int(start.blue() + (end.blue() - start.blue()) * factor),
        int(start.alpha() + (end.alpha() - start.alpha()) * factor),
    )


def _icon_bytes_for_url(url: str, cache_dir: Path) -> bytes | None:
    cached = _ICON_BYTES_CACHE.get(url)
    if cached:
        return cached
    target = _icon_cache_path(url, cache_dir)
    if target.is_file():
        try:
            data = target.read_bytes()
        except OSError:
            data = b""
        if data:
            _ICON_BYTES_CACHE[url] = data
            return data
    try:
        response = requests.get(url, timeout=8)
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
    _ICON_BYTES_CACHE[url] = data
    return data


def _icon_cache_path(url: str, cache_dir: Path) -> Path:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.img"
