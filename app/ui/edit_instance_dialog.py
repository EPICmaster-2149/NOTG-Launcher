from __future__ import annotations

from pathlib import Path
from typing import Any

import psutil

from PySide6.QtCore import QSize, QSortFilterProxyModel, QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QClipboard, QGuiApplication, QIcon, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSizePolicy,
    QStackedWidget,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QDesktopServices

from core.launcher import InstanceRecord, LauncherService
from ui.add_instance_dialog import (
    AccentLineEdit,
    CatalogTableModel,
    CatalogWorker,
    HeaderIconButton,
    LoaderPlaceholder,
    SearchFilterProxyModel,
    SearchableComboBox,
    VersionFilterProxyModel,
)
from ui.icon_selector_dialog import IconSelectorDialog
from ui.icon_utils import load_scaled_icon
from ui.install_progress_dialog import InstallProgressDialog
from ui.responsive import fitted_window_size, scaled_px
from ui.topbar import ModernButton


class EditInstanceDialog(QDialog):
    instance_changed = Signal(object)
    launch_requested = Signal(object)
    kill_requested = Signal(object)

    PAGE_NAMES = [
        "Minecraft Log",
        "Versions",
        "Mods",
        "Screenshots",
        "Advanced",
    ]

    def __init__(
        self,
        service: LauncherService,
        instance: InstanceRecord,
        parent: QWidget | None = None,
        *,
        initial_page: str = "Minecraft Log",
    ):
        super().__init__(parent)
        self.service = service
        self.instance = instance
        self._selected_icon_path = instance.icon_path
        self._current_loader_id = instance.mod_loader_id
        self._version_request_id = 0
        self._loader_request_id = 0
        self._workers: set[QThread] = set()
        self._progress_dialogs: list[InstallProgressDialog] = []
        self._mods_cache: list[dict[str, Any]] = []
        self._screenshots_cache: list[dict[str, Any]] = []
        self._copy_source_instances: list[dict[str, str]] = []
        self._ram_slider_step_mb = 256
        self._ram_selected_mb = instance.memory_mb
        self._current_log_path: Path | None = None
        self._log_read_position = 0
        self._log_placeholder_shown = False
        self._last_crash_report: Path | None = None
        self._versions_loaded = False
        self._mods_loaded = False
        self._screenshots_loaded = False
        self._advanced_loaded = False

        self.setObjectName("editInstanceDialog")
        self.setWindowTitle(f"Edit {instance.name}")
        self.setModal(False)
        self.setMinimumSize(920, 680)
        self.resize(fitted_window_size(self.parentWidget() or self, 1240, 800, minimum_width=920, minimum_height=680))

        self.log_timer = QTimer(self)
        self.log_timer.setInterval(1100)
        self.log_timer.timeout.connect(self._poll_log_output)

        self._build_ui()
        self._apply_responsive_layout()
        self._sync_header_icon()
        self._update_ram_slider_range()
        self._set_ram_value(instance.memory_mb)
        self._update_runtime_buttons()
        self._set_page(initial_page)
        self._sync_log_polling_state()

    def showEvent(self, event) -> None:
        self._apply_responsive_layout()
        self._sync_log_polling_state()
        super().showEvent(event)

    def resizeEvent(self, event) -> None:
        self._apply_responsive_layout()
        super().resizeEvent(event)

    def closeEvent(self, event) -> None:
        self.log_timer.stop()
        for worker in list(self._workers):
            if worker.isRunning():
                worker.wait()
        super().closeEvent(event)

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

        self.header_title = QLabel("EDIT INSTANCE")
        self.header_title.setObjectName("editorEyebrow")
        name_column.addWidget(self.header_title)

        self.name_edit = AccentLineEdit("Rename instance", large=True)
        self.name_edit.setMinimumHeight(66)
        self.name_edit.setText(self.instance.name)
        self.name_edit.editingFinished.connect(self._save_name_change)
        name_column.addWidget(self.name_edit)
        header_layout.addLayout(name_column, 1)
        root_layout.addWidget(header)

        shell = QFrame()
        shell.setObjectName("instanceEditorShell")
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        root_layout.addWidget(shell, 1)

        self.nav_frame = QFrame()
        self.nav_frame.setObjectName("instanceEditorNav")
        nav_layout = QVBoxLayout(self.nav_frame)
        nav_layout.setContentsMargins(14, 18, 14, 18)
        nav_layout.setSpacing(12)

        nav_title = QLabel("Sections")
        nav_title.setObjectName("editorNavTitle")
        nav_layout.addWidget(nav_title)

        self.nav_list = QListWidget()
        self.nav_list.setObjectName("instanceEditorNavList")
        self.nav_list.setSpacing(8)
        self.nav_list.setFrameShape(QFrame.NoFrame)
        self.nav_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.nav_list.currentRowChanged.connect(self._update_page_state)
        for title in self.PAGE_NAMES:
            self.nav_list.addItem(QListWidgetItem(title))
        nav_layout.addWidget(self.nav_list, 1)
        shell_layout.addWidget(self.nav_frame)

        content = QFrame()
        content.setObjectName("instanceEditorContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 20)
        content_layout.setSpacing(14)

        self.page_title = QLabel("Minecraft Log")
        self.page_title.setObjectName("editorCompactPageTitle")
        content_layout.addWidget(self.page_title)

        divider = QFrame()
        divider.setObjectName("editorPrimaryDivider")
        content_layout.addWidget(divider)

        self.page_scroll = QScrollArea()
        self.page_scroll.setObjectName("instanceEditorScroll")
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setFrameShape(QFrame.NoFrame)
        self.page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.page_scroll_container = QWidget()
        self.page_scroll_layout = QVBoxLayout(self.page_scroll_container)
        self.page_scroll_layout.setContentsMargins(0, 0, 6, 0)
        self.page_scroll_layout.setSpacing(0)

        self.page_stack = QStackedWidget()
        self.page_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.page_stack.addWidget(self._build_log_page())
        self.page_stack.addWidget(self._build_versions_page())
        self.page_stack.addWidget(self._build_mods_page())
        self.page_stack.addWidget(self._build_screenshots_page())
        self.page_stack.addWidget(self._build_advanced_page())
        self.page_scroll_layout.addWidget(self.page_stack)
        self.page_scroll.setWidget(self.page_scroll_container)
        content_layout.addWidget(self.page_scroll, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(12)
        footer.addStretch()

        self.launch_button = ModernButton("Launch", role="accent", height=42, icon_size=0)
        self.launch_button.clicked.connect(lambda: self.launch_requested.emit(self.instance))
        footer.addWidget(self.launch_button)

        self.kill_button = ModernButton("Force Stop", role="danger", height=42, icon_size=0)
        self.kill_button.clicked.connect(lambda: self.kill_requested.emit(self.instance))
        footer.addWidget(self.kill_button)

        self.ok_button = ModernButton("OK", role="sidebar", height=42, icon_size=0, minimum_width=106, horizontal_padding=26)
        self.ok_button.clicked.connect(self.accept)
        footer.addWidget(self.ok_button)
        content_layout.addLayout(footer)

        shell_layout.addWidget(content, 1)

    def _build_log_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(10)

        title = QLabel("Minecraft Log")
        title.setObjectName("editorSectionTitle")
        top_row.addWidget(title)
        top_row.addStretch()

        self.log_copy_button = ModernButton("Copy", role="sidebar", height=38, icon_size=0, minimum_width=92)
        self.log_copy_button.clicked.connect(self._copy_log_contents)
        top_row.addWidget(self.log_copy_button)

        self.log_clear_button = ModernButton("Clear", role="sidebar", height=38, icon_size=0, minimum_width=92)
        self.log_clear_button.clicked.connect(self._clear_log_view)
        top_row.addWidget(self.log_clear_button)
        layout.addLayout(top_row)

        self.log_status = QLabel("Waiting for log output...")
        self.log_status.setObjectName("editorStatusText")
        layout.addWidget(self.log_status)

        self.log_output = QPlainTextEdit()
        self.log_output.setObjectName("instanceLogOutput")
        self.log_output.setReadOnly(True)
        self.log_output.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.log_output.setMaximumBlockCount(5000)
        layout.addWidget(self.log_output, 1)

        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(10)

        self.log_search = AccentLineEdit("Search log text")
        self.log_search.returnPressed.connect(self._find_in_log)
        bottom_row.addWidget(self.log_search, 1)

        self.log_find_button = ModernButton("Find", role="sidebar", height=38, icon_size=0, minimum_width=90)
        self.log_find_button.clicked.connect(self._find_in_log)
        bottom_row.addWidget(self.log_find_button)

        self.log_bottom_button = ModernButton("Bottom", role="sidebar", height=38, icon_size=0, minimum_width=96)
        self.log_bottom_button.clicked.connect(self._scroll_log_to_bottom)
        bottom_row.addWidget(self.log_bottom_button)
        layout.addLayout(bottom_row)
        return page

    def _build_versions_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        info_label = QLabel("Select a different Minecraft version or mod loader, then reinstall this instance with the new stack.")
        info_label.setObjectName("editorStatusText")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        selection_surface = QFrame()
        selection_surface.setObjectName("editorSelectionSurface")
        selection_layout = QVBoxLayout(selection_surface)
        selection_layout.setContentsMargins(18, 18, 18, 18)
        selection_layout.setSpacing(18)
        selection_layout.addWidget(self._build_version_section(), 1)

        section_divider = QFrame()
        section_divider.setObjectName("editorSectionDivider")
        selection_layout.addWidget(section_divider)
        selection_layout.addWidget(self._build_loader_section(), 1)
        layout.addWidget(selection_surface, 1)

        install_row = QHBoxLayout()
        install_row.setContentsMargins(0, 0, 0, 0)
        install_row.setSpacing(12)

        self.version_notice = QLabel("The installed version is already selected.")
        self.version_notice.setObjectName("editorStatusText")
        install_row.addWidget(self.version_notice, 1)

        self.version_install_button = ModernButton("Install", role="accent", height=42, icon_size=0)
        self.version_install_button.setEnabled(False)
        self.version_install_button.clicked.connect(self._install_selected_version)
        install_row.addWidget(self.version_install_button)
        layout.addLayout(install_row)
        return page

    def _build_mods_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.mods_title = QLabel("Mods (0 installed)")
        self.mods_title.setObjectName("editorSectionTitle")
        layout.addWidget(self.mods_title)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(14)
        layout.addLayout(content_row, 1)

        self.mods_table = QTableWidget(0, 6)
        self.mods_table.setObjectName("modsTable")
        self.mods_table.setHorizontalHeaderLabels(["Enable", "Image", "Name", "Version", "Last Modified", "Provider"])
        self.mods_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.mods_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.mods_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.mods_table.setAlternatingRowColors(True)
        self.mods_table.verticalHeader().setVisible(False)
        self.mods_table.horizontalHeader().setHighlightSections(False)
        self.mods_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.mods_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.mods_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.mods_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.mods_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.mods_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.mods_table.itemSelectionChanged.connect(self._sync_mod_actions)
        content_row.addWidget(self.mods_table, 1)

        mod_actions = QFrame()
        mod_actions.setObjectName("editorSidePanel")
        mod_actions_layout = QVBoxLayout(mod_actions)
        mod_actions_layout.setContentsMargins(14, 14, 14, 14)
        mod_actions_layout.setSpacing(10)

        self.remove_mod_button = ModernButton("Remove", role="danger", height=40, icon_size=0)
        self.remove_mod_button.clicked.connect(self._remove_selected_mods)
        mod_actions_layout.addWidget(self.remove_mod_button)

        self.enable_mod_button = ModernButton("Enable", role="sidebar", height=40, icon_size=0)
        self.enable_mod_button.clicked.connect(lambda: self._set_selected_mods_enabled(True))
        mod_actions_layout.addWidget(self.enable_mod_button)

        self.disable_mod_button = ModernButton("Disable", role="sidebar", height=40, icon_size=0)
        self.disable_mod_button.clicked.connect(lambda: self._set_selected_mods_enabled(False))
        mod_actions_layout.addWidget(self.disable_mod_button)

        mod_actions_layout.addStretch()

        self.view_mods_folder_button = ModernButton("View Folder", role="sidebar", height=40, icon_size=0)
        self.view_mods_folder_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.service.get_instance_mods_dir(self.instance))))
        )
        mod_actions_layout.addWidget(self.view_mods_folder_button)

        self.view_configs_button = ModernButton("View Configs", role="sidebar", height=40, icon_size=0)
        self.view_configs_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.service.get_instance_configs_dir(self.instance))))
        )
        mod_actions_layout.addWidget(self.view_configs_button)
        content_row.addWidget(mod_actions)

        self.mods_search = AccentLineEdit("Search mods")
        self.mods_search.textChanged.connect(self._apply_mod_search)
        layout.addWidget(self.mods_search)
        return page

    def _build_screenshots_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.screenshots_title = QLabel("Screenshots")
        self.screenshots_title.setObjectName("editorSectionTitle")
        layout.addWidget(self.screenshots_title)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(14)
        layout.addLayout(content_row, 1)

        self.screenshots_list = QListWidget()
        self.screenshots_list.setObjectName("screenshotsGrid")
        self.screenshots_list.setViewMode(QListWidget.IconMode)
        self.screenshots_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.screenshots_list.setResizeMode(QListWidget.Adjust)
        self.screenshots_list.setMovement(QListWidget.Static)
        self.screenshots_list.setFlow(QListWidget.LeftToRight)
        self.screenshots_list.setWrapping(True)
        self.screenshots_list.setSpacing(14)
        self.screenshots_list.setFrameShape(QFrame.NoFrame)
        self.screenshots_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.screenshots_list.itemSelectionChanged.connect(self._sync_screenshot_actions)
        content_row.addWidget(self.screenshots_list, 1)

        screenshot_actions = QFrame()
        screenshot_actions.setObjectName("editorSidePanel")
        screenshot_actions_layout = QVBoxLayout(screenshot_actions)
        screenshot_actions_layout.setContentsMargins(14, 14, 14, 14)
        screenshot_actions_layout.setSpacing(10)

        self.copy_image_button = ModernButton("Copy Image", role="sidebar", height=40, icon_size=0)
        self.copy_image_button.clicked.connect(self._copy_selected_image)
        screenshot_actions_layout.addWidget(self.copy_image_button)

        self.delete_image_button = ModernButton("Delete", role="danger", height=40, icon_size=0)
        self.delete_image_button.clicked.connect(self._delete_selected_screenshots)
        screenshot_actions_layout.addWidget(self.delete_image_button)

        self.rename_image_button = ModernButton("Rename", role="sidebar", height=40, icon_size=0)
        self.rename_image_button.clicked.connect(self._rename_selected_screenshot)
        screenshot_actions_layout.addWidget(self.rename_image_button)

        screenshot_actions_layout.addStretch()

        self.view_screenshots_folder_button = ModernButton("View Folder", role="sidebar", height=40, icon_size=0)
        self.view_screenshots_folder_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.service.get_instance_screenshots_dir(self.instance))))
        )
        screenshot_actions_layout.addWidget(self.view_screenshots_folder_button)
        content_row.addWidget(screenshot_actions)
        return page

    def _build_advanced_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

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
        self.copy_available_list.itemDoubleClicked.connect(
            lambda *_: self._move_copy_items(self.copy_available_list, self.copy_selected_list)
        )

        self.copy_selected_list = QListWidget()
        self.copy_selected_list.setObjectName("editorTransferList")
        self.copy_selected_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.copy_selected_list.itemDoubleClicked.connect(
            lambda *_: self._move_copy_items(self.copy_selected_list, self.copy_available_list)
        )

        copy_lists_row.addWidget(self._build_transfer_column("Copy From", self.copy_available_list), 1)

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

        copy_lists_row.addWidget(self._build_transfer_column("Copy To", self.copy_selected_list), 1)

        copy_action_row = QHBoxLayout()
        copy_action_row.setContentsMargins(0, 0, 0, 0)
        copy_action_row.setSpacing(12)
        copy_action_row.addStretch()

        self.copy_execute_button = ModernButton("Copy", role="accent", height=40, icon_size=0)
        self.copy_execute_button.clicked.connect(self._copy_selected_instance_data)
        copy_action_row.addWidget(self.copy_execute_button)
        advanced_layout.addLayout(copy_action_row)

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
        self.ram_revert_button.clicked.connect(lambda: self._set_ram_value(self.instance.memory_mb))
        ram_actions.addWidget(self.ram_revert_button)

        self.ram_confirm_button = ModernButton("Confirm", role="accent", height=40, icon_size=0, radius=10, minimum_width=124, horizontal_padding=36)
        self.ram_confirm_button.clicked.connect(self._save_ram_value)
        ram_actions.addWidget(self.ram_confirm_button)
        ram_actions.addStretch()

        layout.addWidget(advanced_surface, 1)
        return page

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

        self.version_model = CatalogTableModel(["Version", "Released", "Type"], ["id", "release_display", "type_label"], self)
        self.version_proxy = VersionFilterProxyModel(self.service, self)
        self.version_proxy.setSourceModel(self.version_model)

        self.version_stack = QStackedWidget()
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
        self.version_table.selectionModel().selectionChanged.connect(lambda *_: self._on_version_selection_changed())
        self.version_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.version_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.version_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        version_table_layout.addWidget(self.version_table)
        self.version_stack.addWidget(version_table_holder)

        self.version_search = AccentLineEdit("Search versions")
        self.version_search.textChanged.connect(self._on_version_search_changed)
        self.version_search.setEnabled(False)
        left.addWidget(self.version_search)

        self.version_side_panel = QFrame()
        self.version_side_panel.setObjectName("editorSidePanel")
        side_layout = QVBoxLayout(self.version_side_panel)
        side_layout.setContentsMargins(14, 14, 14, 14)
        side_layout.setSpacing(10)
        row.addWidget(self.version_side_panel)

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

        self.version_refresh = ModernButton("Refresh", role="sidebar", height=38, icon_size=0, radius=10, minimum_width=108, horizontal_padding=22)
        self.version_refresh.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.version_refresh.clicked.connect(lambda: self._load_versions(force_refresh=True))
        self.version_refresh.setEnabled(False)
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

        self.loader_model = CatalogTableModel(["Version", "Loader", "Minecraft"], ["loader_version", "loader_name", "minecraft_version"], self)
        self.loader_proxy = SearchFilterProxyModel(["loader_version", "loader_name", "minecraft_version"], self)
        self.loader_proxy.setSourceModel(self.loader_model)

        self.loader_stack = QStackedWidget()
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
        self.loader_table.selectionModel().selectionChanged.connect(lambda *_: self._on_loader_selection_changed())
        self.loader_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.loader_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.loader_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table_layout.addWidget(self.loader_table)
        self.loader_stack.addWidget(table_holder)

        self.loader_search = AccentLineEdit("Search loader versions")
        self.loader_search.textChanged.connect(self._on_loader_search_changed)
        self.loader_search.setEnabled(False)
        left.addWidget(self.loader_search)

        self.loader_side_panel = QFrame()
        self.loader_side_panel.setObjectName("editorSidePanel")
        side_layout = QVBoxLayout(self.loader_side_panel)
        side_layout.setContentsMargins(14, 14, 14, 14)
        side_layout.setSpacing(10)
        row.addWidget(self.loader_side_panel)

        side_title = QLabel("Mod Loader")
        side_title.setObjectName("editorFilterTitle")
        side_layout.addWidget(side_title)

        self.loader_group = QButtonGroup(self)
        self.loader_group.setExclusive(True)
        self.loader_buttons: dict[str | None, QRadioButton] = {}

        side_layout.addWidget(self._build_loader_radio("None", None))
        for loader_id in ("neoforge", "forge", "fabric", "quilt"):
            side_layout.addWidget(self._build_loader_radio(self.service.get_mod_loader_name(loader_id), loader_id))

        side_layout.addStretch()

        self.loader_refresh = ModernButton("Refresh", role="sidebar", height=38, icon_size=0, radius=10, minimum_width=108, horizontal_padding=22)
        self.loader_refresh.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.loader_refresh.clicked.connect(lambda: self._refresh_loader_rows(force_refresh=True))
        self.loader_refresh.setEnabled(False)
        side_layout.addWidget(self.loader_refresh)
        self.loader_buttons[None].setChecked(self.instance.mod_loader_id is None)
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
        checkbox.setProperty("filterValue", value)
        checkbox.toggled.connect(lambda *_: self._update_version_filters())
        return checkbox

    def _build_loader_radio(self, text: str, value: str | None) -> QRadioButton:
        radio = QRadioButton(text)
        radio.setObjectName("editorFilterRadio")
        radio.toggled.connect(lambda checked, loader_id=value: self._on_loader_toggled(loader_id, checked))
        self.loader_group.addButton(radio)
        self.loader_buttons[value] = radio
        return radio

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

    def _apply_responsive_layout(self) -> None:
        root_margin = scaled_px(self, 22, minimum=14, maximum=24)
        layout = self.layout()
        if isinstance(layout, QVBoxLayout):
            layout.setContentsMargins(root_margin, root_margin, root_margin, scaled_px(self, 20, minimum=14, maximum=22))
            layout.setSpacing(scaled_px(self, 14, minimum=10, maximum=16))

        compact_layout = self.width() < 1220
        self.icon_button.set_side_length(scaled_px(self, 96, minimum=74, maximum=100))
        self.name_edit.setMinimumHeight(scaled_px(self, 54, minimum=44, maximum=56))
        self.nav_frame.setFixedWidth(scaled_px(self, 168 if compact_layout else 178, minimum=148, maximum=184))
        self.version_side_panel.setFixedWidth(scaled_px(self, 152 if compact_layout else 168, minimum=136, maximum=172))
        self.loader_side_panel.setFixedWidth(scaled_px(self, 152 if compact_layout else 168, minimum=136, maximum=172))

        for button in (
            self.launch_button,
            self.kill_button,
            self.ok_button,
            self.log_copy_button,
            self.log_clear_button,
            self.log_find_button,
            self.log_bottom_button,
            self.version_refresh,
            self.loader_refresh,
            self.version_install_button,
            self.remove_mod_button,
            self.enable_mod_button,
            self.disable_mod_button,
            self.view_mods_folder_button,
            self.view_configs_button,
            self.copy_image_button,
            self.delete_image_button,
            self.rename_image_button,
            self.view_screenshots_folder_button,
            self.copy_add_button,
            self.copy_remove_button,
            self.copy_all_button,
            self.copy_clear_button,
            self.copy_execute_button,
            self.ram_revert_button,
            self.ram_confirm_button,
        ):
            button.set_metrics(height=scaled_px(self, button.minimumHeight(), minimum=36, maximum=max(40, button.minimumHeight() + 2)), icon_size=0)

        self.ram_display.setMinimumWidth(scaled_px(self, 170, minimum=148, maximum=176))
        self.version_table.verticalHeader().setDefaultSectionSize(scaled_px(self, 34, minimum=30, maximum=36))
        self.loader_table.verticalHeader().setDefaultSectionSize(scaled_px(self, 34, minimum=30, maximum=36))
        self.mods_table.verticalHeader().setDefaultSectionSize(scaled_px(self, 40, minimum=36, maximum=44))
        self.version_stack.setMinimumHeight(scaled_px(self, 260, minimum=228, maximum=286))
        self.loader_stack.setMinimumHeight(scaled_px(self, 206, minimum=182, maximum=226))
        self.screenshots_list.setGridSize(QSize(scaled_px(self, 214, minimum=188, maximum=224), scaled_px(self, 178, minimum=164, maximum=190)))
        self.screenshots_list.setIconSize(QSize(scaled_px(self, 190, minimum=164, maximum=196), scaled_px(self, 108, minimum=96, maximum=114)))
        self.copy_available_list.setMinimumHeight(scaled_px(self, 220, minimum=180, maximum=260))
        self.copy_selected_list.setMinimumHeight(scaled_px(self, 220, minimum=180, maximum=260))
        self._sync_page_stack_height()

    def _set_page(self, page_name: str) -> None:
        target_index = self.PAGE_NAMES.index(page_name) if page_name in self.PAGE_NAMES else 0
        self.nav_list.setCurrentRow(target_index)

    def _update_page_state(self, index: int) -> None:
        target_index = max(0, index)
        self.page_stack.setCurrentIndex(target_index)
        page_name = self.PAGE_NAMES[target_index]
        self.page_title.setText(page_name)
        self._ensure_page_loaded(page_name)
        self._sync_page_stack_height()
        self.page_scroll.verticalScrollBar().setValue(0)
        self._sync_log_polling_state()
        if page_name == "Minecraft Log":
            self._poll_log_output()

    def _sync_page_stack_height(self) -> None:
        current_page = self.page_stack.currentWidget()
        if current_page is None:
            return
        current_page.adjustSize()
        self.page_stack.setMinimumHeight(max(0, current_page.sizeHint().height()))
        self.page_stack.updateGeometry()
        self.page_scroll_container.adjustSize()

    def _sync_header_icon(self) -> None:
        self.icon_button.set_icon_path(self.service.resolve_icon_path(self._selected_icon_path))

    def _save_name_change(self) -> None:
        new_name = self.name_edit.text().strip()
        if not new_name:
            self.name_edit.setText(self.instance.name)
            return
        if new_name == self.instance.name:
            return
        try:
            self._apply_instance(self.service.rename_instance(self.instance, new_name))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Rename Instance", str(exc))
            self.name_edit.setText(self.instance.name)

    def _open_icon_selector(self) -> None:
        dialog = IconSelectorDialog(self.service, self._selected_icon_path, self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            self._apply_instance(self.service.set_instance_icon(self.instance, dialog.selected_icon_path))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Change Icon", str(exc))
            return
        self._selected_icon_path = dialog.selected_icon_path
        self._sync_header_icon()

    def _apply_instance(self, instance: InstanceRecord) -> None:
        self.instance = instance
        self._selected_icon_path = instance.icon_path
        self.name_edit.setText(instance.name)
        self.setWindowTitle(f"Edit {instance.name}")
        self._sync_header_icon()
        self._update_runtime_buttons()
        self._set_ram_value(instance.memory_mb)
        if self._advanced_loaded:
            self._reload_copy_source_instances()
        if self._mods_loaded:
            self._reload_mods()
        if self._screenshots_loaded:
            self._reload_screenshots()
        if self._versions_loaded:
            self._sync_selected_version_to_instance()
        self.instance_changed.emit(instance)

    def sync_runtime_state(self, instance: InstanceRecord) -> None:
        self.instance = instance
        self._update_runtime_buttons()

    def notify_crash(self, return_code: int) -> None:
        self._set_page("Minecraft Log")
        self.show()
        self.raise_()
        self.activateWindow()
        self._append_log_text(f"[launcher] Instance exited unexpectedly with code {return_code}.")
        crash_report = self.service.get_latest_crash_report(self.instance)
        if crash_report and crash_report != self._last_crash_report:
            self._last_crash_report = crash_report
            try:
                self._append_log_text("")
                self._append_log_text(f"[crash-report] {crash_report.name}")
                self._append_log_text(crash_report.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass

    def _update_runtime_buttons(self) -> None:
        status_key = self.instance.status.lower()
        is_running = status_key in {"launched", "launching"}
        self.launch_button.setEnabled(not is_running)
        self.kill_button.setEnabled(is_running)

    def _ensure_page_loaded(self, page_name: str) -> None:
        if page_name == "Versions" and not self._versions_loaded:
            self._versions_loaded = True
            self._load_versions(force_refresh=False)
            return
        if page_name == "Mods" and not self._mods_loaded:
            self._mods_loaded = True
            self._reload_mods()
            return
        if page_name == "Screenshots" and not self._screenshots_loaded:
            self._screenshots_loaded = True
            self._reload_screenshots()
            return
        if page_name == "Advanced" and not self._advanced_loaded:
            self._advanced_loaded = True
            self._reload_copy_source_instances()

    def _sync_log_polling_state(self) -> None:
        if not hasattr(self, "log_timer"):
            return
        should_poll = self.isVisible() and self.page_stack.currentIndex() == 0
        if should_poll and not self.log_timer.isActive():
            self.log_timer.start()
        elif not should_poll and self.log_timer.isActive():
            self.log_timer.stop()

    def _poll_log_output(self) -> None:
        log_path = self.service.get_instance_latest_log_path(self.instance)
        if self._current_log_path != log_path:
            self._current_log_path = log_path
            self._log_read_position = 0
            self.log_output.clear()

        if log_path.is_file():
            self.log_status.setText(log_path.name)
            try:
                file_size = log_path.stat().st_size
                if file_size < self._log_read_position:
                    self.log_output.clear()
                    self._log_read_position = 0
                with log_path.open("r", encoding="utf-8", errors="replace") as handle:
                    handle.seek(self._log_read_position)
                    chunk = handle.read()
                    self._log_read_position = handle.tell()
            except OSError:
                chunk = ""
            if chunk:
                self._append_log_text(chunk.rstrip("\n"))
                self._scroll_log_to_bottom()
            self._log_placeholder_shown = False
            return

        crash_report = self.service.get_latest_crash_report(self.instance)
        if crash_report is not None:
            self.log_status.setText(crash_report.name)
        elif not self._log_placeholder_shown:
            self._append_log_text("No instance log has been created yet.")
            self._log_placeholder_shown = True

    def _append_log_text(self, text: str) -> None:
        if not text:
            return
        self.log_output.moveCursor(QTextCursor.End)
        self.log_output.insertPlainText(text)
        if not text.endswith("\n"):
            self.log_output.insertPlainText("\n")

    def _copy_log_contents(self) -> None:
        QGuiApplication.clipboard().setText(self.log_output.toPlainText(), QClipboard.Clipboard)

    def _clear_log_view(self) -> None:
        self.log_output.clear()
        if self._current_log_path and self._current_log_path.is_file():
            try:
                self._log_read_position = self._current_log_path.stat().st_size
            except OSError:
                self._log_read_position = 0

    def _find_in_log(self) -> None:
        query = self.log_search.text().strip()
        if not query:
            return
        if self.log_output.find(query):
            return
        cursor = self.log_output.textCursor()
        cursor.movePosition(QTextCursor.Start)
        self.log_output.setTextCursor(cursor)
        self.log_output.find(query)

    def _scroll_log_to_bottom(self) -> None:
        scrollbar = self.log_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _load_versions(self, force_refresh: bool) -> None:
        self._version_request_id += 1
        self.version_model.set_rows([])
        self.version_search.clear()
        self.version_search.setEnabled(False)
        self.version_refresh.setEnabled(False)
        self.version_placeholder.set_text("Loading Minecraft versions...")
        self.version_stack.setCurrentIndex(0)
        self._start_worker("versions", self._version_request_id, force_refresh=force_refresh)

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
        if isinstance(worker, QThread):
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
                self._select_current_version_row()
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
                self._select_current_loader_row()
            else:
                self.loader_model.set_rows([])
                self.loader_placeholder.set_text("No compatible loader versions were returned for this selection.")
                self.loader_stack.setCurrentIndex(0)
            self._sync_version_install_button()

    def _handle_catalog_failed(self, job: str, request_id: int, message: str) -> None:
        if job == "versions" and request_id == self._version_request_id:
            self.version_placeholder.set_text(message)
            self.version_stack.setCurrentIndex(0)
            self.version_refresh.setEnabled(True)
            return
        if job == "loader_versions" and request_id == self._loader_request_id:
            self.loader_placeholder.set_text(message)
            self.loader_stack.setCurrentIndex(0)
            self.loader_refresh.setEnabled(True)

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
        self._select_current_version_row()

    def _on_version_search_changed(self, text: str) -> None:
        self.version_proxy.set_search_text(text)
        self._select_current_version_row(preserve=True)

    def _on_loader_search_changed(self, text: str) -> None:
        self.loader_proxy.set_search_text(text)
        self._select_current_loader_row(preserve=True)

    def _on_version_selection_changed(self) -> None:
        self._refresh_loader_rows(force_refresh=False)
        self._sync_version_install_button()

    def _on_loader_selection_changed(self) -> None:
        self._sync_version_install_button()

    def _on_loader_toggled(self, loader_id: str | None, checked: bool) -> None:
        if not checked:
            return
        self._current_loader_id = loader_id
        self._refresh_loader_rows(force_refresh=False)
        self._sync_version_install_button()

    def _refresh_loader_rows(self, force_refresh: bool = False) -> None:
        version = self.current_version_id()
        if self._current_loader_id is None:
            self.loader_model.set_rows([])
            self.loader_search.clear()
            self.loader_search.setEnabled(False)
            self.loader_refresh.setEnabled(False)
            self.loader_placeholder.set_text("No mod loader is selected.")
            self.loader_stack.setCurrentIndex(0)
            self._sync_version_install_button()
            return
        if not version:
            self.loader_model.set_rows([])
            self.loader_search.clear()
            self.loader_search.setEnabled(False)
            self.loader_refresh.setEnabled(False)
            self.loader_placeholder.set_text("Select a Minecraft version first.")
            self.loader_stack.setCurrentIndex(0)
            self._sync_version_install_button()
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
        return str(row["id"]) if row else None

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

    def _select_current_version_row(self, preserve: bool = False) -> None:
        self._select_row_by_key(self.version_table, self.version_proxy, self.version_model, "id", self.instance.vanilla_version, preserve=preserve)

    def _select_current_loader_row(self, preserve: bool = False) -> None:
        target_loader_version = self.instance.mod_loader_version if self.current_version_id() == self.instance.vanilla_version else None
        self._select_row_by_key(self.loader_table, self.loader_proxy, self.loader_model, "loader_version", target_loader_version, preserve=preserve)

    def _select_row_by_key(
        self,
        table: QTableView,
        proxy: QSortFilterProxyModel,
        model: CatalogTableModel,
        key: str,
        value: str | None,
        *,
        preserve: bool = False,
    ) -> None:
        if proxy.rowCount() <= 0:
            table.clearSelection()
            return

        if preserve and table.currentIndex().isValid():
            table.selectRow(table.currentIndex().row())
            return

        target_row = 0
        if value:
            for row in range(proxy.rowCount()):
                source_index = proxy.mapToSource(proxy.index(row, 0))
                if source_index.isValid() and str(model.row(source_index.row()).get(key, "")) == value:
                    target_row = row
                    break

        index = proxy.index(target_row, 0)
        table.setCurrentIndex(index)
        table.selectRow(target_row)

    def _sync_selected_version_to_instance(self) -> None:
        if hasattr(self, "version_model") and self.version_model.rowCount() > 0:
            self._select_current_version_row()
        if hasattr(self, "loader_buttons"):
            self.loader_buttons.get(self.instance.mod_loader_id, self.loader_buttons[None]).setChecked(True)
        self._sync_version_install_button()

    def _sync_version_install_button(self) -> None:
        selected_version = self.current_version_id()
        if self._current_loader_id is None:
            selected_loader_version = None
        else:
            selected_loader = self.current_loader_row()
            selected_loader_version = str(selected_loader["loader_version"]) if selected_loader else None

        has_change = selected_version != self.instance.vanilla_version or self._current_loader_id != self.instance.mod_loader_id or selected_loader_version != self.instance.mod_loader_version
        can_install = bool(selected_version) and (self._current_loader_id is None or selected_loader_version)
        self.version_install_button.setEnabled(bool(has_change and can_install))
        self.version_notice.setText(
            "Reinstall to apply the selected version stack." if has_change else "The installed version is already selected."
        )

    def _install_selected_version(self) -> None:
        selected_version = self.current_version_id()
        if not selected_version:
            return
        loader_version = None
        if self._current_loader_id is not None:
            loader_row = self.current_loader_row()
            if loader_row is None:
                return
            loader_version = str(loader_row["loader_version"])

        answer = QMessageBox.question(
            self,
            "Reinstall Version",
            "This will replace the current version files for this instance while keeping user data. Continue?",
        )
        if answer != QMessageBox.Yes:
            return

        request = self.service.prepare_reinstall_request(
            self.instance,
            vanilla_version=selected_version,
            mod_loader_id=self._current_loader_id,
            mod_loader_version=loader_version,
        )
        progress_dialog = InstallProgressDialog(self.service, request, self)
        progress_dialog.installation_succeeded.connect(self._handle_install_success)
        progress_dialog.installation_failed.connect(lambda *_: None)
        progress_dialog.finished.connect(lambda *_: self._drop_progress_dialog(progress_dialog))
        self._progress_dialogs.append(progress_dialog)
        progress_dialog.show()

    def _drop_progress_dialog(self, dialog: InstallProgressDialog) -> None:
        self._progress_dialogs = [item for item in self._progress_dialogs if item is not dialog]

    def _handle_install_success(self, instance: InstanceRecord) -> None:
        self._apply_instance(instance)

    def _reload_mods(self) -> None:
        self._mods_cache = self.service.list_mods(self.instance)
        self.mods_title.setText(f"Mods ({len(self._mods_cache)} installed)")
        self._apply_mod_search()

    def _apply_mod_search(self) -> None:
        query = self.mods_search.text().strip().lower() if hasattr(self, "mods_search") else ""
        rows = [
            row
            for row in self._mods_cache
            if not query or query in " ".join(str(row.get(key, "")) for key in ("name", "version", "provider")).lower()
        ]
        self.mods_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            self._populate_mod_row(row_index, row)
        self._sync_mod_actions()

    def _populate_mod_row(self, row_index: int, row: dict[str, Any]) -> None:
        file_name = str(row["file_name"])

        checkbox = QCheckBox()
        checkbox.setChecked(bool(row["enabled"]))
        checkbox.toggled.connect(lambda checked, name=file_name: self._toggle_mod(name, checked))
        checkbox_container = QWidget()
        checkbox_layout = QHBoxLayout(checkbox_container)
        checkbox_layout.setContentsMargins(0, 0, 0, 0)
        checkbox_layout.setAlignment(Qt.AlignCenter)
        checkbox_layout.addWidget(checkbox)
        self.mods_table.setCellWidget(row_index, 0, checkbox_container)

        icon_item = QTableWidgetItem("")
        icon_path = row.get("icon_path")
        if icon_path:
            icon_item.setIcon(QIcon(load_scaled_icon(icon_path, 32, 32)))
        icon_item.setData(Qt.UserRole, file_name)
        self.mods_table.setItem(row_index, 1, icon_item)

        name_item = QTableWidgetItem(str(row["name"]))
        name_item.setData(Qt.UserRole, file_name)
        self.mods_table.setItem(row_index, 2, name_item)
        self.mods_table.setItem(row_index, 3, QTableWidgetItem(str(row["version"])))
        self.mods_table.setItem(row_index, 4, QTableWidgetItem(str(row["last_modified"])))
        self.mods_table.setItem(row_index, 5, QTableWidgetItem(str(row["provider"])))

    def _selected_mod_file_names(self) -> list[str]:
        selected_rows = sorted({index.row() for index in self.mods_table.selectionModel().selectedRows()})
        results: list[str] = []
        for row in selected_rows:
            item = self.mods_table.item(row, 2)
            if item is not None and item.data(Qt.UserRole):
                results.append(str(item.data(Qt.UserRole)))
        return results

    def _sync_mod_actions(self) -> None:
        selected = self._selected_mod_file_names()
        has_selected = bool(selected)
        self.remove_mod_button.setEnabled(has_selected)
        self.enable_mod_button.setEnabled(has_selected)
        self.disable_mod_button.setEnabled(has_selected)

    def _toggle_mod(self, file_name: str, enabled: bool) -> None:
        try:
            target_path = self.service.set_mod_enabled(self.instance, file_name, enabled)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Mods", str(exc))
            self._reload_mods()
            return
        self._reload_mods()
        self._select_mod_by_file_name(target_path.name)

    def _set_selected_mods_enabled(self, enabled: bool) -> None:
        selected = self._selected_mod_file_names()
        if not selected:
            return
        try:
            updated_names = [self.service.set_mod_enabled(self.instance, name, enabled).name for name in selected]
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Mods", str(exc))
            self._reload_mods()
            return
        self._reload_mods()
        for file_name in updated_names:
            self._select_mod_by_file_name(file_name)

    def _remove_selected_mods(self) -> None:
        selected = self._selected_mod_file_names()
        if not selected:
            return
        answer = QMessageBox.question(self, "Remove Mods", "Remove the selected mods from this instance?")
        if answer != QMessageBox.Yes:
            return
        try:
            self.service.remove_mods(self.instance, selected)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Mods", str(exc))
            return
        self._reload_mods()

    def _select_mod_by_file_name(self, file_name: str) -> None:
        for row in range(self.mods_table.rowCount()):
            item = self.mods_table.item(row, 2)
            if item is not None and item.data(Qt.UserRole) == file_name:
                self.mods_table.selectRow(row)
                break

    def _reload_screenshots(self) -> None:
        self._screenshots_cache = self.service.list_screenshots(self.instance)
        self.screenshots_title.setText(f"Screenshots ({len(self._screenshots_cache)})")
        self.screenshots_list.clear()
        for row in self._screenshots_cache:
            item = QListWidgetItem(row["label"])
            item.setData(Qt.UserRole, row["file_name"])
            item.setToolTip(str(row["path"]))
            item.setIcon(QIcon(load_scaled_icon(row["path"], self.screenshots_list.iconSize().width(), self.screenshots_list.iconSize().height())))
            self.screenshots_list.addItem(item)
        self._sync_screenshot_actions()

    def _selected_screenshot_names(self) -> list[str]:
        return [str(item.data(Qt.UserRole)) for item in self.screenshots_list.selectedItems() if item.data(Qt.UserRole)]

    def _sync_screenshot_actions(self) -> None:
        selected = self._selected_screenshot_names()
        has_selected = bool(selected)
        self.copy_image_button.setEnabled(has_selected)
        self.delete_image_button.setEnabled(has_selected)
        self.rename_image_button.setEnabled(len(selected) == 1)

    def _copy_selected_image(self) -> None:
        selected = self.screenshots_list.selectedItems()
        if not selected:
            return
        file_name = str(selected[0].data(Qt.UserRole))
        match = next((row for row in self._screenshots_cache if row["file_name"] == file_name), None)
        if match is None:
            return
        pixmap = load_scaled_icon(match["path"], 1600, 1600)
        if pixmap.isNull():
            return
        QGuiApplication.clipboard().setPixmap(pixmap, QClipboard.Clipboard)

    def _delete_selected_screenshots(self) -> None:
        selected = self._selected_screenshot_names()
        if not selected:
            return
        answer = QMessageBox.question(self, "Delete Screenshots", "Delete the selected screenshots?")
        if answer != QMessageBox.Yes:
            return
        try:
            self.service.delete_screenshots(self.instance, selected)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Screenshots", str(exc))
            return
        self._reload_screenshots()

    def _rename_selected_screenshot(self) -> None:
        selected = self._selected_screenshot_names()
        if len(selected) != 1:
            return
        current_name = Path(selected[0]).stem
        new_name, accepted = QInputDialog.getText(self, "Rename Screenshot", "New name:", text=current_name)
        if not accepted:
            return
        try:
            target = self.service.rename_screenshot(self.instance, selected[0], new_name)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Screenshots", str(exc))
            return
        self._reload_screenshots()
        for index in range(self.screenshots_list.count()):
            item = self.screenshots_list.item(index)
            if item.data(Qt.UserRole) == target.name:
                item.setSelected(True)
                break

    def _reload_copy_source_instances(self) -> None:
        current_value = self.copy_source_combo.selected_value() if hasattr(self, "copy_source_combo") else None
        self._copy_source_instances = [
            {"id": item.instance_id, "name": item.name}
            for item in self.service.load_instances()
            if item.instance_id != self.instance.instance_id
        ]
        if not hasattr(self, "copy_source_combo"):
            return

        self.copy_source_combo.blockSignals(True)
        self.copy_source_combo.clear()
        self.copy_source_combo.addItem("", None)
        for entry in self._copy_source_instances:
            self.copy_source_combo.addItem(entry["name"], entry["id"])
        self.copy_source_combo.blockSignals(False)

        if current_value:
            index = self.copy_source_combo.findData(current_value, role=Qt.UserRole)
            if index >= 0:
                self.copy_source_combo.setCurrentIndex(index)
        self._on_copy_source_changed()

    def _on_copy_source_changed(self) -> None:
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
        existing = {str(destination.item(index).data(Qt.UserRole)) for index in range(destination.count())}
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

    def _copy_selected_instance_data(self) -> None:
        source_instance_id = self.copy_source_combo.selected_value()
        selected_entries = self._selected_copy_entries()
        if not source_instance_id or not selected_entries:
            QMessageBox.warning(self, "Advanced Copy", "Choose a source instance and at least one entry to copy.")
            return
        answer = QMessageBox.question(
            self,
            "Replace Current Files",
            "This will replace the selected files in the current instance with the ones from the chosen source instance. Continue?",
        )
        if answer != QMessageBox.Yes:
            return

        request = self.service.prepare_copy_userdata_request(
            self.instance,
            source_instance_id=source_instance_id,
            copy_user_data=selected_entries,
        )
        progress_dialog = InstallProgressDialog(self.service, request, self)
        progress_dialog.installation_succeeded.connect(self._handle_install_success)
        progress_dialog.installation_failed.connect(lambda *_: None)
        progress_dialog.finished.connect(lambda *_: self._drop_progress_dialog(progress_dialog))
        self._progress_dialogs.append(progress_dialog)
        progress_dialog.show()

    def _set_ram_value(self, memory_mb: int) -> None:
        slider_max_mb = self.ram_slider.maximum() * self._ram_slider_step_mb
        self.ram_slider.blockSignals(True)
        self._ram_selected_mb = max(1024, min(slider_max_mb, int(memory_mb)))
        self.ram_slider.setValue(self._ram_selected_mb // self._ram_slider_step_mb)
        self.ram_slider.blockSignals(False)
        self.ram_display.setText(f"{self._ram_selected_mb} MB")

    def _on_ram_slider_changed(self, value: int) -> None:
        self._ram_selected_mb = value * self._ram_slider_step_mb
        self.ram_display.setText(f"{self._ram_selected_mb} MB")

    def _save_ram_value(self) -> None:
        if self._ram_selected_mb == self.instance.memory_mb:
            return
        try:
            self._apply_instance(self.service.set_instance_memory(self.instance, self._ram_selected_mb))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Memory", str(exc))
            self._set_ram_value(self.instance.memory_mb)

    def _update_ram_slider_range(self) -> None:
        total_mb = int(psutil.virtual_memory().total / (1024 * 1024))
        maximum_mb = max(self.instance.memory_mb, min(16384, (int(total_mb * 0.75) // 1024) * 1024))
        self.ram_slider.setMinimum(1024 // self._ram_slider_step_mb)
        self.ram_slider.setMaximum(maximum_mb // self._ram_slider_step_mb)
