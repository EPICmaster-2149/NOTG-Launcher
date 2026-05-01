from __future__ import annotations

from datetime import datetime
from time import monotonic
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QStackedWidget, QVBoxLayout, QWidget

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
except ImportError:  # pragma: no cover - depends on the local Qt build
    QAudioOutput = None
    QMediaPlayer = None
    QVideoSink = None

from core.launcher import InstanceRecord, JavaCompatibilityError, LauncherService, VIDEO_SUFFIXES
from ui.instance_card import InstanceCard
from ui.message_utils import show_java_error
from ui.responsive import fitted_window_size, scaled_px
from ui.sidebar import SideBar
from ui.app_icon import application_icon
from ui.theme import theme_palette
from ui.topbar import ActionPopup, PopupAction, TopBar
from ui.version_display import format_launcher_version_label

if TYPE_CHECKING:
    from ui.accounts_dialog import AccountsDialog
    from ui.add_instance_dialog import AddInstanceDialog
    from ui.edit_instance_dialog import EditInstanceDialog
    from ui.install_progress_dialog import InstallProgressDialog
    from ui.settings_dialog import SettingsDialog


class LaunchWorker(QThread):
    launched = Signal(object, int)
    failed = Signal(str, str)

    def __init__(self, service: LauncherService, instance: InstanceRecord, player_name: str):
        super().__init__()
        self.service = service
        self.instance = instance
        self.player_name = player_name

    def run(self) -> None:
        try:
            process = self.service.launch_instance(self.instance, self.player_name)
            pid = int(getattr(process, "pid", 0) or 0)
            if pid <= 0:
                raise RuntimeError("Minecraft started without a valid process id.")

            self.service.register_runtime_session(
                self.instance,
                pid=pid,
                player_name=self.player_name,
                close_ui_on_launch=self.service.get_close_ui_on_launch(),
            )
            monitor_pid = self.service.spawn_session_monitor(self.instance.instance_id, pid, self.player_name)
            self.service.attach_runtime_monitor(self.instance.instance_id, monitor_pid)
            try:
                updated = self.service.refresh_instance_last_played(self.instance)
            except Exception:
                updated = self.instance
            updated.pid = pid
            updated.status = "Launching"
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(self.instance.instance_id, str(exc))
            return

        self.launched.emit(updated, pid)


class MainWindow(QWidget):
    def __init__(self, *, service: LauncherService | None = None, restore_request: dict[str, Any] | None = None):
        super().__init__()

        self.service = service or LauncherService()
        self._restore_request = restore_request or {}
        self._cards: list[tuple[QListWidgetItem, InstanceCard, InstanceRecord]] = []
        self._selected_item: QListWidgetItem | None = None
        self._launch_threads: dict[str, LaunchWorker] = {}
        self._progress_dialogs: list["InstallProgressDialog"] = []
        self._edit_dialogs: dict[str, "EditInstanceDialog"] = {}
        self._settings_dialog: "SettingsDialog | None" = None
        self._instance_popup_target_id: str | None = None
        self._background_pixmap = QPixmap()
        self._background_path: str | None = None
        self._background_is_video = False
        self._background_cache = QPixmap()
        self._background_cache_size = QSize()
        self._background_video_player = None
        self._background_audio_output = None
        self._background_video_sink = None
        self._background_video_source: str | None = None
        self._background_video_last_frame_at = 0.0
        self._background_video_min_frame_interval = 1.0 / 24.0
        self._screen_connected = False
        self._runtime_sessions: dict[str, dict[str, Any]] = {}
        self._runtime_session_snapshot: tuple[tuple[str, str, int | None, int | None, bool], ...] = ()

        self.setObjectName("appRoot")
        self.setWindowTitle("NOTG Launcher")
        self.setWindowIcon(application_icon(self.service.project_root))
        self.setMinimumSize(980, 640)
        self.resize(fitted_window_size(self, 1420, 860, minimum_width=980, minimum_height=640))

        self._build_ui()
        self._refresh_background()
        self._apply_responsive_layout()
        self.refresh_instances()

        self.runtime_timer = QTimer(self)
        self.runtime_timer.setInterval(1000)
        self.runtime_timer.timeout.connect(self._sync_runtime_sessions)
        self.runtime_timer.timeout.connect(self._update_playtime_bar)
        self.runtime_timer.start()

        QTimer.singleShot(0, self._apply_initial_restore_request)

    def showEvent(self, event) -> None:
        self._ensure_screen_tracking()
        self._apply_responsive_layout()
        super().showEvent(event)

    def resizeEvent(self, event) -> None:
        self._apply_responsive_layout()
        self._invalidate_background_cache()
        super().resizeEvent(event)

    def paintEvent(self, event) -> None:
        del event
        palette = theme_palette(self)["window"]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        if not self._background_pixmap.isNull():
            self._ensure_background_cache()
            if not self._background_cache.isNull():
                painter.drawPixmap(0, 0, self._background_cache)
        else:
            gradient = QLinearGradient(0, 0, 0, self.height())
            top, middle, bottom = palette["gradient"]
            gradient.setColorAt(0.0, QColor(top))
            gradient.setColorAt(0.35, QColor(middle))
            gradient.setColorAt(1.0, QColor(bottom))
            painter.fillRect(self.rect(), gradient)

    def handle_ipc_message(self, payload: dict[str, Any]) -> None:
        action = str(payload.get("action") or "")
        if action not in {"activate", "session-sync"}:
            return

        instance_id = _optional_text(payload.get("instance_id"))
        page = _optional_text(payload.get("page"))

        self._sync_runtime_sessions(force_refresh=True)
        if instance_id:
            item = self._item_for_instance_id(instance_id)
            if item is not None:
                self.instance_list.setCurrentItem(item)
            if page:
                instance = self.service.get_instance(instance_id)
                if instance is not None:
                    self._open_edit_dialog(instance, page=page)

        if bool(payload.get("activate", True)):
            self._activate_window()

    def _ensure_screen_tracking(self) -> None:
        handle = self.windowHandle()
        if handle is None or self._screen_connected:
            return
        handle.screenChanged.connect(lambda *_: self._apply_responsive_layout())
        self._screen_connected = True

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(8)

        self.topbar = TopBar()
        self.topbar.set_accounts(self.service.list_accounts(), self.service.get_player_name())
        self.topbar.action_requested.connect(self._handle_topbar_action)
        main_layout.addWidget(self.topbar)

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(16)
        content_layout.setAlignment(Qt.AlignTop)
        main_layout.addLayout(content_layout, 1)
        self.content_layout = content_layout

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
        list_page.setObjectName("instanceListPage")
        list_page.setAttribute(Qt.WA_StyledBackground, False)
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
        self.instance_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.instance_list.setUniformItemSizes(True)
        self.instance_list.setGridSize(QSize(218, 234))
        self.instance_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.instance_list.setAutoFillBackground(False)
        self.instance_list.viewport().setAutoFillBackground(False)
        self.instance_list.viewport().setAttribute(Qt.WA_StyledBackground, False)
        self.instance_list.currentItemChanged.connect(self._handle_current_item_changed)
        self.instance_list.itemDoubleClicked.connect(self._handle_instance_double_clicked)
        self.instance_list.customContextMenuRequested.connect(self._show_instance_context_menu)
        list_layout.addWidget(self.instance_list, 1)
        self.content_stack.addWidget(list_page)

        empty_page = QWidget()
        empty_page.setObjectName("instanceEmptyPage")
        empty_page.setAttribute(Qt.WA_StyledBackground, False)
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

        self.playtime_bar = QFrame()
        self.playtime_bar.setObjectName("playtimeBar")
        playtime_layout = QHBoxLayout(self.playtime_bar)
        playtime_layout.setContentsMargins(12, 6, 12, 6)
        playtime_layout.setSpacing(14)

        self.playtime_primary = QLabel("Select an instance to see playtime details.")
        self.playtime_primary.setObjectName("playtimePrimary")
        playtime_layout.addWidget(self.playtime_primary, 1)

        self.playtime_session = QLabel("Session: 0s")
        self.playtime_session.setObjectName("playtimeSecondary")
        playtime_layout.addWidget(self.playtime_session)

        self.playtime_total = QLabel("Total playtime: 0s")
        self.playtime_total.setObjectName("playtimeTotal")
        playtime_layout.addWidget(self.playtime_total)

        main_layout.addWidget(self.playtime_bar)

        self.instance_popup = ActionPopup(self)
        self.instance_popup.action_triggered.connect(self._handle_instance_popup_action)

    def _apply_responsive_layout(self) -> None:
        outer_margin = scaled_px(self, 20, minimum=12, maximum=24)
        content_spacing = scaled_px(self, 16, minimum=10, maximum=18)

        root_layout = self.layout()
        if isinstance(root_layout, QVBoxLayout):
            root_layout.setContentsMargins(outer_margin, outer_margin, outer_margin, outer_margin)
            root_layout.setSpacing(scaled_px(self, 8, minimum=6, maximum=10))

        self.sidebar.setFixedWidth(scaled_px(self, 284, minimum=220, maximum=300))
        self.instance_list.setSpacing(scaled_px(self, 18, minimum=12, maximum=20))
        self.instance_list.setGridSize(
            QSize(
                scaled_px(self, 212, minimum=186, maximum=220),
                scaled_px(self, 228, minimum=196, maximum=236),
            )
        )

        surface_layout = self.content_surface.layout()
        if isinstance(surface_layout, QVBoxLayout):
            surface_margin = scaled_px(self, 22, minimum=14, maximum=24)
            surface_layout.setContentsMargins(surface_margin, surface_margin, surface_margin, surface_margin)
            surface_layout.setSpacing(scaled_px(self, 8, minimum=6, maximum=10))

        self.content_layout.setSpacing(content_spacing)

    def refresh_instances(self, select_instance_id: str | None = None) -> None:
        instances = self.service.load_instances()
        self._runtime_sessions = self.service.list_runtime_sessions()
        self._runtime_session_snapshot = self._build_runtime_session_snapshot(self._runtime_sessions)
        self.instance_list.clear()
        self._cards.clear()
        self._selected_item = None

        if not instances:
            self.content_stack.setCurrentIndex(1)
            self.sidebar.clear_instance()
            self._update_playtime_bar()
            return

        self.content_stack.setCurrentIndex(0)
        for instance in instances:
            if instance.instance_id in self._launch_threads and instance.status == "Quit":
                instance.status = "Launching"
            item = QListWidgetItem()
            card = InstanceCard(
                instance.name,
                format_launcher_version_label(instance.vanilla_version, instance.loader_name),
                instance.icon_path,
            )
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
        self._update_playtime_bar()
        self._sync_open_edit_dialogs(instances)

    def _handle_topbar_action(self, action: str) -> None:
        if action == "Add Instance":
            self._open_add_instance_dialog()
            return

        if action == "Folders":
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.service.instances_root)))
            return

        if action == "Settings":
            self._open_settings_dialog()
            return

        if action == "Manage Accounts":
            self._open_manage_accounts_dialog()
            return

        if action.startswith("Account:"):
            account_name = action.split(":", 1)[1]
            try:
                self.service.set_active_account(account_name)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, "Accounts", str(exc))
                return
            self._sync_accounts_ui()

    def _open_add_instance_dialog(self) -> None:
        from ui.add_instance_dialog import AddInstanceDialog
        from ui.install_progress_dialog import InstallProgressDialog

        dialog = AddInstanceDialog(self.service, self)
        if dialog.exec() != QDialog.Accepted or dialog.selection is None:
            return

        try:
            request = self.service.prepare_install_request(**dialog.selection)
            self.service.validate_install_request(request)
        except JavaCompatibilityError as exc:
            show_java_error(self, "Java Required", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Install Instance", str(exc))
            return

        progress_dialog = InstallProgressDialog(self.service, request, self)
        progress_dialog.installation_succeeded.connect(self._handle_install_success)
        progress_dialog.installation_failed.connect(self._handle_install_failure)
        progress_dialog.finished.connect(lambda _: self._drop_progress_dialog(progress_dialog))
        self._progress_dialogs.append(progress_dialog)
        progress_dialog.show()

    def _drop_progress_dialog(self, dialog: "InstallProgressDialog") -> None:
        self._progress_dialogs = [item for item in self._progress_dialogs if item is not dialog]

    def _handle_install_success(self, instance: InstanceRecord) -> None:
        self.refresh_instances(select_instance_id=instance.instance_id)

    def _handle_install_failure(self, message: str) -> None:
        del message

    def _handle_current_item_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        del previous
        if current is None:
            self.sidebar.clear_instance()
            self._update_playtime_bar()
            return

        self._selected_item = current
        selected_instance = current.data(Qt.UserRole)

        for item, card, instance in self._cards:
            del instance
            card.set_selected(item is current)

        self.sidebar.set_instance(selected_instance)
        self._update_playtime_bar()

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

        if action == "Edit":
            instance = self._selected_item.data(Qt.UserRole)
            self._open_edit_dialog(instance)
            return

        if action == "Copy":
            self._copy_selected_instance()
            return

        if action == "Delete":
            self._delete_selected_instance()
            return

    def _launch_selected_instance(self) -> None:
        if self._selected_item is None:
            return

        instance = self._selected_item.data(Qt.UserRole)
        if self._instance_is_active(instance.instance_id) or instance.instance_id in self._launch_threads:
            return

        try:
            self.service.select_java_runtime(instance.installed_version, instance.minecraft_dir)
        except JavaCompatibilityError as exc:
            show_java_error(self, "Java Required", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Launch Failed", str(exc))
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
        self.service.terminate_runtime_session(instance.instance_id)

    def _copy_selected_instance(self) -> None:
        if self._selected_item is None:
            return
        instance = self._selected_item.data(Qt.UserRole)
        from ui.install_progress_dialog import InstallProgressDialog

        try:
            request = self.service.prepare_duplicate_request(instance)
            self.service.validate_install_request(request)
        except JavaCompatibilityError as exc:
            show_java_error(self, "Java Required", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Copy Instance", str(exc))
            return

        progress_dialog = InstallProgressDialog(self.service, request, self)
        progress_dialog.installation_succeeded.connect(self._handle_install_success)
        progress_dialog.installation_failed.connect(self._handle_install_failure)
        progress_dialog.finished.connect(lambda _: self._drop_progress_dialog(progress_dialog))
        self._progress_dialogs.append(progress_dialog)
        progress_dialog.show()

    def _delete_selected_instance(self) -> None:
        if self._selected_item is None:
            return

        instance = self._selected_item.data(Qt.UserRole)
        if self._instance_is_active(instance.instance_id) or instance.instance_id in self._launch_threads:
            QMessageBox.warning(self, "Delete Instance", "Stop the instance before deleting it.")
            return

        answer = QMessageBox.question(
            self,
            "Delete Instance",
            f"Delete '{instance.name}' and all of its files?",
        )
        if answer != QMessageBox.Yes:
            return

        try:
            self.service.delete_instance(instance)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Delete Instance", str(exc))
            return

        dialog = self._edit_dialogs.pop(instance.instance_id, None)
        if dialog is not None:
            dialog.close()
        self.refresh_instances()

    def _handle_launch_success(self, instance: InstanceRecord, pid: int) -> None:
        instance.pid = pid
        instance.status = "Launching"
        self._replace_instance(instance)
        self._sync_runtime_sessions(force_refresh=True)
        if self.service.get_close_ui_on_launch():
            self._close_for_running_session()

    def _handle_launch_failure(self, instance_id: str, message: str) -> None:
        self._set_instance_status(instance_id, "Crashed")
        if "Java" in message and "required" in message:
            show_java_error(self, "Java Required", message)
            return
        QMessageBox.critical(self, "Launch Failed", message)

    def _replace_instance(self, updated: InstanceRecord) -> None:
        for index, (item, card, instance) in enumerate(self._cards):
            if instance.instance_id != updated.instance_id:
                continue

            item.setData(Qt.UserRole, updated)
            self._cards[index] = (item, card, updated)
            card.name = updated.name
            card.version = format_launcher_version_label(updated.vanilla_version, updated.loader_name)
            card.icon_path = updated.icon_path
            card.update()
            dialog = self._edit_dialogs.get(updated.instance_id)
            if dialog is not None:
                dialog.sync_runtime_state(updated)
            if item is self._selected_item:
                self.sidebar.set_instance(updated)
                self._update_playtime_bar()
            break

    def _set_instance_status(self, instance_id: str, status: str) -> None:
        for index, (item, card, instance) in enumerate(self._cards):
            del card
            if instance.instance_id != instance_id:
                continue

            updated = item.data(Qt.UserRole)
            updated.status = status
            item.setData(Qt.UserRole, updated)
            self._cards[index] = (item, self._cards[index][1], updated)
            dialog = self._edit_dialogs.get(updated.instance_id)
            if dialog is not None:
                dialog.sync_runtime_state(updated)
            if item is self._selected_item:
                self.sidebar.update_status(status)
                self._update_playtime_bar()
            break

    def _sync_accounts_ui(self) -> None:
        self.topbar.set_accounts(self.service.list_accounts(), self.service.get_player_name())

    def _open_manage_accounts_dialog(self) -> None:
        from ui.accounts_dialog import AccountsDialog

        dialog = AccountsDialog(self.service, self)
        dialog.exec()
        self._sync_accounts_ui()

    def _open_settings_dialog(self) -> None:
        from ui.settings_dialog import SettingsDialog

        if self._settings_dialog is None:
            self._settings_dialog = SettingsDialog(self.service, self)
            self._settings_dialog.background_changed.connect(lambda *_: self._refresh_background())
            self._settings_dialog.destroyed.connect(lambda *_: setattr(self, "_settings_dialog", None))
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()

    def _refresh_background(self) -> None:
        self._background_path = self.service.get_active_background_path()
        self._background_is_video = bool(self._background_path and self._background_path.lower().endswith(tuple(VIDEO_SUFFIXES)))
        if self._background_is_video and self._background_path:
            self._background_pixmap = QPixmap()
            self._set_video_background(self._background_path)
        else:
            self._clear_video_background()
            self._background_pixmap = QPixmap(self._background_path) if self._background_path else QPixmap()
        self._invalidate_background_cache()
        self.update()

    def _set_video_background(self, video_path: str) -> None:
        if QMediaPlayer is None or QVideoSink is None:
            return
        if self._background_video_player is None:
            self._background_video_player = QMediaPlayer(self)
            if QAudioOutput is not None:
                self._background_audio_output = QAudioOutput(self)
                self._background_audio_output.setMuted(True)
                self._background_audio_output.setVolume(0)
                self._background_video_player.setAudioOutput(self._background_audio_output)
            self._background_video_sink = QVideoSink(self)
            self._background_video_sink.videoFrameChanged.connect(self._handle_background_video_frame)
            self._background_video_player.setVideoSink(self._background_video_sink)
            self._background_video_player.mediaStatusChanged.connect(self._handle_background_media_status)
            try:
                self._background_video_player.setLoops(QMediaPlayer.Loops.Infinite)
            except Exception:  # noqa: BLE001
                pass

        if self._background_video_source != video_path:
            self._background_video_source = video_path
            self._background_video_last_frame_at = 0.0
            self._background_video_player.stop()
            self._background_video_player.setSource(QUrl.fromLocalFile(video_path))
        self._background_video_player.play()

    def _clear_video_background(self) -> None:
        if self._background_video_player is not None:
            self._background_video_player.stop()
            if self._background_video_source is not None:
                self._background_video_player.setSource(QUrl())
        self._background_video_source = None
        self._background_video_last_frame_at = 0.0

    def _sync_background_video_geometry(self) -> None:
        self._invalidate_background_cache()

    def _handle_background_media_status(self, status) -> None:
        if QMediaPlayer is None or self._background_video_player is None:
            return
        if status == QMediaPlayer.MediaStatus.EndOfMedia and self._background_is_video:
            self._background_video_player.setPosition(0)
            self._background_video_player.play()

    def _handle_background_video_frame(self, frame) -> None:
        if not self._background_is_video:
            return
        now = monotonic()
        if now - self._background_video_last_frame_at < self._background_video_min_frame_interval:
            return
        try:
            image = frame.toImage()
        except Exception:  # noqa: BLE001
            return
        if image.isNull():
            return
        self._background_video_last_frame_at = now
        self._background_pixmap = QPixmap.fromImage(image)
        self._invalidate_background_cache()
        self.update()

    def _open_edit_dialog(self, instance: InstanceRecord, *, page: str = "Minecraft Log") -> None:
        from ui.edit_instance_dialog import EditInstanceDialog

        dialog = self._edit_dialogs.get(instance.instance_id)
        if dialog is None:
            dialog = EditInstanceDialog(self.service, instance, self, initial_page=page)
            dialog.instance_changed.connect(self._handle_dialog_instance_changed)
            dialog.launch_requested.connect(lambda current_instance: self._launch_instance_by_id(current_instance.instance_id))
            dialog.kill_requested.connect(lambda current_instance: self._kill_instance_by_id(current_instance.instance_id))
            dialog.destroyed.connect(lambda *_, instance_id=instance.instance_id: self._edit_dialogs.pop(instance_id, None))
            self._edit_dialogs[instance.instance_id] = dialog
        else:
            dialog._set_page(page)
            dialog.sync_runtime_state(instance)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _handle_dialog_instance_changed(self, instance: InstanceRecord) -> None:
        self.refresh_instances(select_instance_id=instance.instance_id)
        dialog = self._edit_dialogs.get(instance.instance_id)
        if dialog is not None:
            dialog.sync_runtime_state(instance)

    def _launch_instance_by_id(self, instance_id: str) -> None:
        item = self._item_for_instance_id(instance_id)
        if item is None:
            return
        self.instance_list.setCurrentItem(item)
        self._launch_selected_instance()

    def _kill_instance_by_id(self, instance_id: str) -> None:
        item = self._item_for_instance_id(instance_id)
        if item is None:
            return
        self.instance_list.setCurrentItem(item)
        self._kill_selected_instance()

    def _item_for_instance_id(self, instance_id: str) -> QListWidgetItem | None:
        for item, _, instance in self._cards:
            if instance.instance_id == instance_id:
                return item
        return None

    def _sync_open_edit_dialogs(self, instances: list[InstanceRecord]) -> None:
        instances_by_id = {instance.instance_id: instance for instance in instances}
        for instance_id, dialog in list(self._edit_dialogs.items()):
            updated = instances_by_id.get(instance_id)
            if updated is None:
                dialog.close()
                continue
            dialog.sync_runtime_state(updated)

    def _show_instance_context_menu(self, pos) -> None:
        item = self.instance_list.itemAt(pos)
        if item is None:
            return
        self.instance_list.setCurrentItem(item)
        instance = item.data(Qt.UserRole)
        self._instance_popup_target_id = instance.instance_id
        self.instance_popup.set_actions(
            [
                PopupAction("Edit", "Edit"),
                PopupAction("Folder", "Folder"),
                PopupAction("Copy", "Copy"),
                PopupAction("Delete", "Delete", role="danger", bold=True),
            ]
        )
        self.instance_popup.show_at_global(self.instance_list.viewport().mapToGlobal(pos))

    def _handle_instance_popup_action(self, action: str) -> None:
        target_id = self._instance_popup_target_id
        if not target_id:
            return
        item = self._item_for_instance_id(target_id)
        if item is None:
            return
        self.instance_list.setCurrentItem(item)
        if action == "Edit":
            self._open_edit_dialog(item.data(Qt.UserRole))
        elif action == "Folder":
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(item.data(Qt.UserRole).root_dir)))
        elif action == "Copy":
            self._copy_selected_instance()
        elif action == "Delete":
            self._delete_selected_instance()

    def _sync_runtime_sessions(self, force_refresh: bool = False) -> None:
        sessions = self.service.list_runtime_sessions()
        snapshot = self._build_runtime_session_snapshot(sessions)
        self._runtime_sessions = sessions

        if force_refresh or snapshot != self._runtime_session_snapshot:
            selected_id = self._selected_item.data(Qt.UserRole).instance_id if self._selected_item is not None else None
            self._runtime_session_snapshot = snapshot
            self.refresh_instances(select_instance_id=selected_id)

        self._process_runtime_attention()

    def _process_runtime_attention(self) -> None:
        attention_items = self.service.claim_runtime_attention()
        if not attention_items:
            return

        for payload in attention_items:
            instance_id = _optional_text(payload.get("instance_id"))
            if not instance_id:
                continue
            self.refresh_instances(select_instance_id=instance_id)
            instance = self.service.get_instance(instance_id)
            if instance is None:
                continue
            page = _optional_text(payload.get("attention_page")) or "Minecraft Log"
            self._open_edit_dialog(instance, page=page)
            dialog = self._edit_dialogs.get(instance_id)
            if dialog is not None:
                exit_code = payload.get("exit_code")
                dialog.notify_crash(int(exit_code) if isinstance(exit_code, int) else -1)
        self._activate_window()

    def _close_for_running_session(self) -> None:
        if self._settings_dialog is not None:
            self._settings_dialog.close()
        for dialog in list(self._edit_dialogs.values()):
            dialog.close()
        for dialog in list(self._progress_dialogs):
            dialog.close()
        self.hide()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _instance_is_active(self, instance_id: str) -> bool:
        session = self._runtime_sessions.get(instance_id) or self.service.get_runtime_session(instance_id)
        status = str(session.get("status") or "") if session else ""
        return status in {"launching", "running"}

    def _build_runtime_session_snapshot(
        self,
        sessions: dict[str, dict[str, Any]],
    ) -> tuple[tuple[str, str, int | None, int | None, bool], ...]:
        snapshot: list[tuple[str, str, int | None, int | None, bool]] = []
        for instance_id, payload in sorted(sessions.items()):
            pid = payload.get("pid")
            exit_code = payload.get("exit_code")
            snapshot.append(
                (
                    instance_id,
                    str(payload.get("status") or ""),
                    int(pid) if isinstance(pid, int) else None,
                    int(exit_code) if isinstance(exit_code, int) else None,
                    bool(payload.get("attention_needed")),
                )
            )
        return tuple(snapshot)

    def _current_session_seconds(self, instance_id: str) -> int:
        session = self._runtime_sessions.get(instance_id)
        if not session:
            return 0
        if str(session.get("status") or "") not in {"launching", "running"}:
            return 0
        started_at = _parse_runtime_timestamp(session.get("started_at"))
        if started_at is None:
            return 0
        return max(0, int((datetime.now().astimezone() - started_at).total_seconds()))

    def _update_playtime_bar(self) -> None:
        selected_instance = self._selected_item.data(Qt.UserRole) if self._selected_item is not None else None
        aggregate_total = sum(
            int(item.data(Qt.UserRole).total_played_seconds) + self._current_session_seconds(item.data(Qt.UserRole).instance_id)
            for item, _, _ in self._cards
        )

        if selected_instance is None:
            self.playtime_primary.setText("Select an instance to see session and instance playtime.")
            self.playtime_session.setText("Session: 0s")
            self.playtime_total.setText(f"Total playtime: {_format_duration(aggregate_total)}")
            return

        session_seconds = self._current_session_seconds(selected_instance.instance_id)
        instance_total = int(selected_instance.total_played_seconds) + session_seconds
        self.playtime_primary.setText(
            f"{selected_instance.name}, last played {_format_last_played(selected_instance.last_played)}"
        )
        self.playtime_session.setText(
            f"Session: {_format_duration(session_seconds)} | Instance total: {_format_duration(instance_total)}"
        )
        self.playtime_total.setText(f"Total playtime: {_format_duration(aggregate_total)}")

    def _apply_initial_restore_request(self) -> None:
        self._sync_runtime_sessions(force_refresh=True)
        if self._restore_request:
            self.handle_ipc_message(self._restore_request)

    def _activate_window(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def _ensure_background_cache(self) -> None:
        if self._background_pixmap.isNull():
            self._background_cache = QPixmap()
            self._background_cache_size = QSize()
            return
        if self._background_cache_size == self.size() and not self._background_cache.isNull():
            return
        transform_mode = Qt.FastTransformation if self._background_is_video else Qt.SmoothTransformation
        scaled = self._background_pixmap.scaled(self.size(), Qt.KeepAspectRatioByExpanding, transform_mode)
        source_x = max(0, int((scaled.width() - self.width()) / 2))
        source_y = max(0, int((scaled.height() - self.height()) / 2))
        self._background_cache = scaled.copy(source_x, source_y, self.width(), self.height())
        self._background_cache_size = QSize(self.size())

    def _invalidate_background_cache(self) -> None:
        self._background_cache = QPixmap()
        self._background_cache_size = QSize()


def _format_duration(total_seconds: int) -> str:
    seconds = max(0, int(total_seconds))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def _format_last_played(value: str | None) -> str:
    if not value:
        return "never"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return parsed.astimezone().strftime("on %m/%d/%y %I:%M %p")


def _parse_runtime_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
