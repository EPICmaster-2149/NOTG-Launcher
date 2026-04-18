from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.launcher import InstanceRecord, LauncherService
from ui.add_instance_dialog import AddInstanceDialog
from ui.install_progress_dialog import InstallProgressDialog
from ui.instance_card import InstanceCard
from ui.sidebar import SideBar
from ui.topbar import TopBar


class LaunchWorker(QThread):
    launched = Signal(object, object)
    failed = Signal(str, str)

    def __init__(self, service: LauncherService, instance: InstanceRecord, player_name: str):
        super().__init__()
        self.service = service
        self.instance = instance
        self.player_name = player_name

    def run(self) -> None:
        try:
            process = self.service.launch_instance(self.instance, self.player_name)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(self.instance.instance_id, str(exc))
            return

        self.launched.emit(self.instance, process)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.service = LauncherService()
        self._cards: list[tuple[QListWidgetItem, InstanceCard, InstanceRecord]] = []
        self._selected_item: QListWidgetItem | None = None
        self._launch_threads: dict[str, LaunchWorker] = {}
        self._running_processes: dict[str, Any] = {}
        self._progress_dialogs: list[InstallProgressDialog] = []

        self.setObjectName("appRoot")
        self.setWindowTitle("NOTG Launcher")
        self.setMinimumSize(1320, 820)
        self.resize(1420, 860)

        self._build_ui()
        self.refresh_instances()

        self.process_monitor = QTimer(self)
        self.process_monitor.setInterval(1500)
        self.process_monitor.timeout.connect(self._poll_running_processes)
        self.process_monitor.start()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(8)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(10)

        self.brand_panel = QFrame()
        self.brand_panel.setObjectName("brandPanel")
        brand_layout = QHBoxLayout(self.brand_panel)
        brand_layout.setContentsMargins(14, 10, 16, 10)
        brand_layout.setSpacing(10)

        self.brand_mark = QFrame()
        self.brand_mark.setObjectName("brandMark")
        brand_layout.addWidget(self.brand_mark)

        self.branding_label = QLabel("NOTGlauncher")
        self.branding_label.setObjectName("brandWordmark")
        brand_layout.addWidget(self.branding_label)
        brand_layout.addStretch()

        header_row.addWidget(self.brand_panel)
        header_row.addStretch()
        main_layout.addLayout(header_row)

        self.topbar = TopBar()
        self.topbar.account_name.setText(self.service.get_player_name())
        self.topbar.account_avatar.setText(self.service.get_player_name()[:1].upper())
        self.topbar.action_requested.connect(self._handle_topbar_action)
        main_layout.addWidget(self.topbar)

        self.menu_divider = QFrame()
        self.menu_divider.setObjectName("menuDivider")
        main_layout.addWidget(self.menu_divider)

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(16)
        content_layout.setAlignment(Qt.AlignTop)
        main_layout.addLayout(content_layout, 1)

        self.sidebar = SideBar()
        self.sidebar.action_requested.connect(self._handle_sidebar_action)
        content_layout.addWidget(self.sidebar)

        self.content_surface = QFrame()
        self.content_surface.setObjectName("contentSurface")
        content_layout.addWidget(self.content_surface, 1)

        surface_layout = QVBoxLayout(self.content_surface)
        surface_layout.setContentsMargins(22, 22, 22, 22)
        surface_layout.setSpacing(8)

        self.content_stack = QStackedWidget()
        self.content_stack.setObjectName("instanceContentStack")
        surface_layout.addWidget(self.content_stack, 1)

        list_page = QWidget()
        list_layout = QVBoxLayout(list_page)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(0)

        self.instance_list = QListWidget()
        self.instance_list.setObjectName("instanceGrid")
        self.instance_list.setFlow(QListWidget.LeftToRight)
        self.instance_list.setWrapping(True)
        self.instance_list.setSpacing(20)
        self.instance_list.setMovement(QListWidget.Static)
        self.instance_list.setResizeMode(QListWidget.Adjust)
        self.instance_list.setViewMode(QListWidget.IconMode)
        self.instance_list.setSelectionMode(QListWidget.SingleSelection)
        self.instance_list.setFrameShape(QFrame.NoFrame)
        self.instance_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.instance_list.setGridSize(QSize(202, 226))
        self.instance_list.currentItemChanged.connect(self._handle_current_item_changed)
        self.instance_list.itemDoubleClicked.connect(self._handle_instance_double_clicked)
        list_layout.addWidget(self.instance_list, 1)
        self.content_stack.addWidget(list_page)

        empty_page = QWidget()
        empty_layout = QVBoxLayout(empty_page)
        empty_layout.setContentsMargins(26, 26, 26, 26)
        empty_layout.setSpacing(12)
        empty_layout.addStretch()

        empty_card = QFrame()
        empty_card.setObjectName("emptyStateCard")
        empty_card_layout = QVBoxLayout(empty_card)
        empty_card_layout.setContentsMargins(26, 26, 26, 26)
        empty_card_layout.setSpacing(10)

        empty_title = QLabel("No instances yet")
        empty_title.setObjectName("emptyStateTitle")
        empty_title.setAlignment(Qt.AlignCenter)
        empty_card_layout.addWidget(empty_title)

        empty_text = QLabel("Create your first instance from the top bar to install and launch Minecraft here.")
        empty_text.setObjectName("emptyStateText")
        empty_text.setWordWrap(True)
        empty_text.setAlignment(Qt.AlignCenter)
        empty_card_layout.addWidget(empty_text)

        empty_layout.addWidget(empty_card, alignment=Qt.AlignCenter)
        empty_layout.addStretch()
        self.content_stack.addWidget(empty_page)

    def refresh_instances(self, select_instance_id: str | None = None) -> None:
        instances = self.service.load_instances()
        self.instance_list.clear()
        self._cards.clear()
        self._selected_item = None

        if not instances:
            self.content_stack.setCurrentIndex(1)
            self.sidebar.clear_instance()
            return

        self.content_stack.setCurrentIndex(0)
        for instance in instances:
            if instance.instance_id in self._launch_threads:
                instance.status = "Launching"
            elif instance.instance_id in self._running_processes:
                instance.status = "Launched"
            item = QListWidgetItem()
            card = InstanceCard(instance.name, instance.version_label, instance.icon_path)
            item.setSizeHint(card.sizeHint())
            item.setData(Qt.UserRole, instance)

            self.instance_list.addItem(item)
            self.instance_list.setItemWidget(item, card)
            card.clicked.connect(lambda item_ref=item: self.instance_list.setCurrentItem(item_ref))
            self._cards.append((item, card, instance))

        selected_row = 0
        if select_instance_id:
            for row in range(self.instance_list.count()):
                candidate = self.instance_list.item(row).data(Qt.UserRole)
                if candidate.instance_id == select_instance_id:
                    selected_row = row
                    break
        self.instance_list.setCurrentRow(selected_row)

    def _handle_topbar_action(self, action: str) -> None:
        if action == "Add Instance":
            self._open_add_instance_dialog()
            return

        if action == "Folders":
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.service.instances_root)))
            return

        if action == "Settings":
            QMessageBox.information(self, "Settings", "Settings are not implemented yet.")

    def _open_add_instance_dialog(self) -> None:
        dialog = AddInstanceDialog(self.service, self)
        if dialog.exec() != QDialog.Accepted or dialog.selection is None:
            return

        request = self.service.prepare_install_request(**dialog.selection)
        progress_dialog = InstallProgressDialog(self.service, request, self)
        progress_dialog.installation_succeeded.connect(self._handle_install_success)
        progress_dialog.installation_failed.connect(self._handle_install_failure)
        progress_dialog.finished.connect(lambda _: self._drop_progress_dialog(progress_dialog))
        self._progress_dialogs.append(progress_dialog)
        progress_dialog.show()

    def _drop_progress_dialog(self, dialog: InstallProgressDialog) -> None:
        self._progress_dialogs = [item for item in self._progress_dialogs if item is not dialog]

    def _handle_install_success(self, instance: InstanceRecord) -> None:
        self.refresh_instances(select_instance_id=instance.instance_id)

    def _handle_install_failure(self, message: str) -> None:
        del message

    def _handle_current_item_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        del previous
        if current is None:
            self.sidebar.clear_instance()
            return

        self._selected_item = current
        selected_instance = current.data(Qt.UserRole)

        for item, card, instance in self._cards:
            del instance
            card.set_selected(item is current)

        self.sidebar.set_instance(selected_instance)

    def _handle_instance_double_clicked(self, item: QListWidgetItem) -> None:
        self.instance_list.setCurrentItem(item)
        self._launch_selected_instance()

    def _handle_sidebar_action(self, action: str) -> None:
        if self._selected_item is None:
            return

        if action == "Launch":
            self._launch_selected_instance()
            return

        if action == "Kill":
            self._kill_selected_instance()
            return

        if action == "Folder":
            instance = self._selected_item.data(Qt.UserRole)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(instance.root_dir)))
            return

        if action == "Delete":
            QMessageBox.information(self, "Delete", "Delete is not implemented yet.")
            return

    def _launch_selected_instance(self) -> None:
        if self._selected_item is None:
            return

        instance = self._selected_item.data(Qt.UserRole)
        if instance.instance_id in self._running_processes or instance.instance_id in self._launch_threads:
            return

        self._set_instance_status(instance.instance_id, "Launching")
        worker = LaunchWorker(self.service, instance, self.service.get_player_name())
        worker.launched.connect(self._handle_launch_success)
        worker.failed.connect(self._handle_launch_failure)
        worker.finished.connect(lambda instance_id=instance.instance_id: self._launch_threads.pop(instance_id, None))
        self._launch_threads[instance.instance_id] = worker
        worker.start()

    def _kill_selected_instance(self) -> None:
        if self._selected_item is None:
            return

        instance = self._selected_item.data(Qt.UserRole)
        process = self._running_processes.get(instance.instance_id)
        if process is None:
            return

        if process.pid:
            self.service.terminate_process_tree(process.pid)
        self._running_processes.pop(instance.instance_id, None)
        self._set_instance_status(instance.instance_id, "Quit")

    def _handle_launch_success(self, instance: InstanceRecord, process: Any) -> None:
        self._running_processes[instance.instance_id] = process
        instance.pid = getattr(process, "pid", None)
        try:
            updated = self.service.refresh_instance_last_played(instance)
        except Exception:
            updated = instance

        updated.pid = instance.pid
        updated.status = "Launched"
        self._replace_instance(updated)
        self._set_instance_status(updated.instance_id, "Launched")

    def _handle_launch_failure(self, instance_id: str, message: str) -> None:
        self._set_instance_status(instance_id, "Crashed")
        QMessageBox.critical(self, "Launch Failed", message)

    def _replace_instance(self, updated: InstanceRecord) -> None:
        for item, card, instance in self._cards:
            if instance.instance_id != updated.instance_id:
                continue

            item.setData(Qt.UserRole, updated)
            card.name = updated.name
            card.version = updated.version_label
            card.icon_path = updated.icon_path
            card.update()
            if item is self._selected_item:
                self.sidebar.set_instance(updated)
            break

    def _set_instance_status(self, instance_id: str, status: str) -> None:
        for item, card, instance in self._cards:
            del card
            if instance.instance_id != instance_id:
                continue

            updated = item.data(Qt.UserRole)
            updated.status = status
            item.setData(Qt.UserRole, updated)
            if item is self._selected_item:
                self.sidebar.update_status(status)
            break

    def _poll_running_processes(self) -> None:
        finished: list[tuple[str, int]] = []
        for instance_id, process in list(self._running_processes.items()):
            return_code = process.poll()
            if return_code is None:
                continue
            finished.append((instance_id, return_code))

        for instance_id, return_code in finished:
            self._running_processes.pop(instance_id, None)
            status = "Quit" if return_code == 0 else "Crashed"
            self._set_instance_status(instance_id, status)
