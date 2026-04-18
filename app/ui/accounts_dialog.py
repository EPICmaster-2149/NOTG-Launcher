from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.launcher import LauncherService
from ui.responsive import fitted_window_size, scaled_px
from ui.topbar import ModernButton


class AccountsDialog(QDialog):
    def __init__(self, service: LauncherService, parent: QWidget | None = None):
        super().__init__(parent)
        self.service = service

        self.setObjectName("accountsDialog")
        self.setWindowTitle("Manage Accounts")
        self.setModal(True)
        self.setMinimumSize(640, 460)
        self.resize(fitted_window_size(self.parentWidget() or self, 760, 560, minimum_width=640, minimum_height=460))

        self._build_ui()
        self._apply_responsive_layout()
        self.refresh()

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
        header.setObjectName("accountsHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(18, 16, 18, 16)
        header_layout.setSpacing(6)

        title = QLabel("Manage Accounts")
        title.setObjectName("accountsTitle")
        header_layout.addWidget(title)

        subtitle = QLabel("Offline launcher profiles used when starting Minecraft instances.")
        subtitle.setObjectName("accountsSubtitle")
        header_layout.addWidget(subtitle)
        root_layout.addWidget(header)

        self.table = QTableWidget(0, 2)
        self.table.setObjectName("catalogTable")
        self.table.setHorizontalHeaderLabels(["Account", "In Use"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._sync_action_state)
        root_layout.addWidget(self.table, 1)

        add_row = QHBoxLayout()
        add_row.setContentsMargins(0, 0, 0, 0)
        add_row.setSpacing(12)

        self.account_input = QLineEdit()
        self.account_input.setObjectName("accountsInput")
        self.account_input.setPlaceholderText("Enter account name")
        self.account_input.returnPressed.connect(self._add_account)
        add_row.addWidget(self.account_input, 1)

        self.add_button = ModernButton("Add", role="accent", height=42, icon_size=0)
        self.add_button.clicked.connect(self._add_account)
        add_row.addWidget(self.add_button)
        root_layout.addLayout(add_row)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(12)

        self.use_button = ModernButton("Use Selected", role="sidebar", height=42, icon_size=0)
        self.use_button.clicked.connect(self._activate_selected)
        footer.addWidget(self.use_button)

        self.delete_button = ModernButton("Delete Selected", role="danger", height=42, icon_size=0)
        self.delete_button.clicked.connect(self._delete_selected)
        footer.addWidget(self.delete_button)

        footer.addStretch()

        self.close_button = ModernButton("Close", role="sidebar", height=42, icon_size=0)
        self.close_button.clicked.connect(self.accept)
        footer.addWidget(self.close_button)
        root_layout.addLayout(footer)

    def _apply_responsive_layout(self) -> None:
        layout = self.layout()
        if isinstance(layout, QVBoxLayout):
            margin = scaled_px(self, 22, minimum=16, maximum=24)
            layout.setContentsMargins(margin, margin, margin, scaled_px(self, 20, minimum=14, maximum=22))
            layout.setSpacing(scaled_px(self, 14, minimum=10, maximum=16))

        self.table.verticalHeader().setDefaultSectionSize(scaled_px(self, 38, minimum=34, maximum=40))
        self.add_button.set_metrics(height=scaled_px(self, 42, minimum=38, maximum=44), icon_size=0)
        self.use_button.set_metrics(height=scaled_px(self, 42, minimum=38, maximum=44), icon_size=0)
        self.delete_button.set_metrics(height=scaled_px(self, 42, minimum=38, maximum=44), icon_size=0)
        self.close_button.set_metrics(height=scaled_px(self, 42, minimum=38, maximum=44), icon_size=0)

    def refresh(self) -> None:
        accounts = self.service.list_accounts()
        active = self.service.get_player_name()

        self.table.setRowCount(len(accounts))
        for row, account_name in enumerate(accounts):
            account_item = QTableWidgetItem(account_name)
            account_item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            active_item = QTableWidgetItem("Yes" if account_name == active else "")
            active_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 0, account_item)
            self.table.setItem(row, 1, active_item)

        if accounts:
            self.table.selectRow(0)
        self._sync_action_state()

    def _selected_account(self) -> str | None:
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return None
        row = selected_rows[0].row()
        item = self.table.item(row, 0)
        return item.text() if item is not None else None

    def _sync_action_state(self) -> None:
        selected = self._selected_account()
        has_selected = bool(selected)
        self.use_button.setEnabled(has_selected)
        self.delete_button.setEnabled(has_selected)

    def _call_service(self, callback: Callable[[], str | None]) -> bool:
        try:
            callback()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Accounts", str(exc))
            return False
        self.refresh()
        return True

    def _add_account(self) -> None:
        name = self.account_input.text().strip()
        if not name:
            self.add_button.flash_invalid()
            self.account_input.setFocus()
            return
        if self._call_service(lambda: self.service.add_account(name)):
            self.account_input.clear()

    def _activate_selected(self) -> None:
        account_name = self._selected_account()
        if not account_name:
            self.use_button.flash_invalid()
            return
        self._call_service(lambda: self.service.set_active_account(account_name))

    def _delete_selected(self) -> None:
        account_name = self._selected_account()
        if not account_name:
            self.delete_button.flash_invalid()
            return

        answer = QMessageBox.question(
            self,
            "Delete Account",
            f"Delete account '{account_name}' from the launcher?",
        )
        if answer != QMessageBox.Yes:
            return
        self._call_service(lambda: self.service.delete_account(account_name))
