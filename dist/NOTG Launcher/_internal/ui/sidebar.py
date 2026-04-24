from pathlib import Path
import sys

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.topbar import ModernButton
from ui.icon_utils import load_scaled_icon
from ui.responsive import scaled_px
from ui.theme import theme_palette
from ui.version_display import format_launcher_version_label


class SideBar(QWidget):
    action_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("sideBar")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.side_panel = QFrame()
        self.side_panel.setObjectName("sidePanel")
        layout.addWidget(self.side_panel)

        panel_layout = QVBoxLayout(self.side_panel)
        panel_layout.setContentsMargins(14, 14, 14, 14)
        panel_layout.setSpacing(8)

        self.preview_panel = QFrame()
        self.preview_panel.setObjectName("sidePreview")
        preview_layout = QVBoxLayout(self.preview_panel)
        preview_layout.setContentsMargins(18, 18, 18, 20)
        preview_layout.setSpacing(8)
        preview_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

        self.icon_label = QLabel()
        self.icon_label.setObjectName("selectedInstanceIcon")
        self.icon_label.setFixedSize(104, 104)
        self.icon_label.setAlignment(Qt.AlignCenter)
        preview_layout.addWidget(self.icon_label, alignment=Qt.AlignHCenter)

        self.name_label = QLabel("No instance")
        self.name_label.setObjectName("instanceInfoName")
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        preview_layout.addWidget(self.name_label)

        self.version_label = QLabel("Select an instance")
        self.version_label.setObjectName("instanceInfoVersion")
        self.version_label.setAlignment(Qt.AlignCenter)
        self.version_label.setWordWrap(True)
        self.version_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        preview_layout.addWidget(self.version_label)

        self.status_badge = StatusBadge()
        preview_layout.addWidget(self.status_badge, alignment=Qt.AlignHCenter)

        panel_layout.addWidget(self.preview_panel)

        self.divider = QFrame()
        self.divider.setObjectName("sideDivider")
        panel_layout.addWidget(self.divider)

        self.buttons = {}
        actions = [
            ("Launch", "accent"),
            ("Kill", "danger"),
            ("Edit", "sidebar"),
            ("Folder", "sidebar"),
            ("Copy", "sidebar"),
        ]

        for name, role in actions:
            button = ModernButton(name, icon=None, role=role, height=44, icon_size=0)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.clicked.connect(lambda _, action=name: self._handle_click(action))
            panel_layout.addWidget(button)
            self.buttons[name] = button

        panel_layout.addStretch()

        delete_button = ModernButton(
            "Delete",
            icon=None,
            role="danger",
            height=44,
            icon_size=0,
        )
        delete_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        delete_button.clicked.connect(lambda _=False: self._handle_click("Delete"))
        panel_layout.addWidget(delete_button)
        self.buttons["Delete"] = delete_button

        self._current_instance = None
        self._active_action = "Launch"
        self._sync_button_state()
        self.clear_instance()
        self._apply_responsive_metrics()

    def showEvent(self, event) -> None:
        self._apply_responsive_metrics()
        super().showEvent(event)

    def resizeEvent(self, event) -> None:
        self._apply_responsive_metrics()
        super().resizeEvent(event)

    def _handle_click(self, action):
        if action in self.buttons and action != "Delete":
            self._active_action = action
            self._sync_button_state()
        self.action_requested.emit(action)

    def set_instance(self, instance):
        self._current_instance = instance
        self.name_label.setText(instance.name)
        self.version_label.setText(format_launcher_version_label(instance.vanilla_version, instance.loader_name))

        pixmap = load_scaled_icon(instance.icon_path, 78, 78)
        self.icon_label.setPixmap(pixmap)
        self.update_status(instance.status)

    def clear_instance(self):
        self._current_instance = None
        self.name_label.setText("No instance")
        self.version_label.setText("Select an instance")
        if hasattr(sys, '_MEIPASS'):
            asset_root = Path(sys._MEIPASS) / "assets" / "default-instance-icons"
        else:
            asset_root = Path(__file__).resolve().parents[2] / "assets" / "default-instance-icons"
        pixmap = load_scaled_icon(asset_root / "Grass Block.png", 78, 78)
        self.icon_label.setPixmap(pixmap)
        self.update_status("Quit")

    def update_status(self, status):
        self.status_badge.set_status(status)

    def _sync_button_state(self):
        for name, button in self.buttons.items():
            button.set_active(name == self._active_action)

    def _apply_responsive_metrics(self) -> None:
        self.setFixedWidth(scaled_px(self, 284, minimum=220, maximum=300))
        icon_size = scaled_px(self, 104, minimum=76, maximum=104)
        self.icon_label.setFixedSize(icon_size, icon_size)
        self.name_label.setMaximumWidth(scaled_px(self, 216, minimum=170, maximum=222))
        self.version_label.setMaximumWidth(scaled_px(self, 216, minimum=170, maximum=222))

        for button in self.buttons.values():
            button.set_metrics(height=scaled_px(self, 44, minimum=38, maximum=46), icon_size=0)

        self.status_badge.setMinimumHeight(scaled_px(self, 40, minimum=34, maximum=42))
        self.status_badge.updateGeometry()
class StatusBadge(QWidget):
    LABELS = {
        "launched": "Running",
        "launching": "Launching",
        "quit": "Stopped",
        "crashed": "Crashed",
    }

    def __init__(self):
        super().__init__()
        self._status_key = "quit"
        self._label = self.LABELS[self._status_key]
        self.setMinimumHeight(40)
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)

    def sizeHint(self):
        font = QFont(self.font())
        font.setPointSize(11)
        font.setWeight(QFont.DemiBold)
        metrics = QFontMetrics(font)
        text_width = metrics.horizontalAdvance(self._label)
        return QSize(max(132, text_width + 56), 40)

    def set_status(self, status):
        status_key = status.lower().replace(" ", "-")
        colors = theme_palette(self)["status_badge"]
        self._status_key = status_key if status_key in colors else "quit"
        self._label = self.LABELS.get(self._status_key, status.title())
        self.updateGeometry()
        self.update()

    def paintEvent(self, event):
        del event
        colors = theme_palette(self)["status_badge"][self._status_key]

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(colors["border"], 1.2))
        painter.setBrush(colors["bg"])
        painter.drawRoundedRect(rect, 14, 14)

        font = QFont(self.font())
        font.setPointSize(11)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)

        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(self._label)
        dot_size = 10
        gap = 10
        total_width = dot_size + gap + text_width
        start_x = rect.center().x() - (total_width / 2)
        dot_y = rect.center().y() - (dot_size / 2)

        painter.setPen(Qt.NoPen)
        painter.setBrush(colors["dot"])
        painter.drawEllipse(QRectF(start_x, dot_y, dot_size, dot_size))

        painter.setPen(colors["text"])
        text_rect = QRectF(
            start_x + dot_size + gap,
            rect.top(),
            text_width + 4,
            rect.height(),
        )
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self._label)
