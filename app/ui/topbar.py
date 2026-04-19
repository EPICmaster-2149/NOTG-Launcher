from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPoint, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ui.responsive import scaled_px


def blend_colors(start: QColor, end: QColor, factor: float) -> QColor:
    factor = max(0.0, min(1.0, factor))
    return QColor(
        int(start.red() + (end.red() - start.red()) * factor),
        int(start.green() + (end.green() - start.green()) * factor),
        int(start.blue() + (end.blue() - start.blue()) * factor),
        int(start.alpha() + (end.alpha() - start.alpha()) * factor),
    )


class ModernButton(QPushButton):
    ROLE_COLORS = {
        "toolbar": {
            "bg": QColor(22, 35, 56, 214),
            "hover": QColor(40, 62, 94, 230),
            "press": QColor(28, 46, 74, 238),
            "active": QColor(54, 84, 126, 232),
            "border": QColor("#39557e"),
            "border_hover": QColor("#7aa6e3"),
            "border_active": QColor("#aac9f4"),
            "text": QColor("#e6efff"),
            "shadow": QColor(8, 17, 31, 74),
        },
        "sidebar": {
            "bg": QColor(34, 50, 80, 208),
            "hover": QColor(44, 66, 103, 224),
            "press": QColor(28, 43, 70, 232),
            "active": QColor(54, 81, 126, 228),
            "border": QColor("#3d567f"),
            "border_hover": QColor("#6b8fc6"),
            "border_active": QColor("#93b7eb"),
            "text": QColor("#edf4ff"),
            "shadow": QColor(8, 16, 29, 76),
        },
        "accent": {
            "bg": QColor(42, 72, 98, 222),
            "hover": QColor(55, 89, 120, 230),
            "press": QColor(33, 61, 84, 236),
            "active": QColor(67, 104, 138, 232),
            "border": QColor("#567da4"),
            "border_hover": QColor("#7ea4cb"),
            "border_active": QColor("#a2c2e5"),
            "text": QColor("#f7fbff"),
            "shadow": QColor(18, 45, 72, 74),
        },
        "danger": {
            "bg": QColor("#391926"),
            "hover": QColor("#482031"),
            "press": QColor("#331724"),
            "active": QColor("#5c2740"),
            "border": QColor("#75405a"),
            "border_hover": QColor("#b4688b"),
            "border_active": QColor("#d78aa7"),
            "text": QColor("#ffcedd"),
            "shadow": QColor(50, 12, 25, 72),
        },
    }

    def __init__(
        self,
        text,
        icon=None,
        role="toolbar",
        height=44,
        icon_size=18,
        parent=None,
        *,
        radius: int | None = None,
        font_point_size: int | None = None,
        font_weight: int | None = None,
        minimum_width: int | None = None,
        horizontal_padding: int | None = None,
    ):
        super().__init__(text, parent)
        self._role = role
        self._colors = self.ROLE_COLORS[role]
        self._hover = 0.0
        self._press = 0.0
        self._active = 0.0
        self._invalid = 0.0
        self._icon_size = icon_size
        self._radius = radius if radius is not None else (12 if role == "toolbar" else 14)
        self._font_point_size = font_point_size
        self._font_weight = font_weight if font_weight is not None else QFont.DemiBold
        self._minimum_width_override = minimum_width
        self._horizontal_padding = horizontal_padding

        if icon is not None:
            self.setIcon(icon)

        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self._hover_animation = QVariantAnimation(
            self,
            duration=180,
            easingCurve=QEasingCurve.OutCubic,
            valueChanged=self._set_hover_progress,
        )
        self._press_animation = QVariantAnimation(
            self,
            duration=120,
            easingCurve=QEasingCurve.OutCubic,
            valueChanged=self._set_press_progress,
        )
        self._active_animation = QVariantAnimation(
            self,
            duration=220,
            easingCurve=QEasingCurve.OutCubic,
            valueChanged=self._set_active_progress,
        )
        self._invalid_animation = QVariantAnimation(
            self,
            duration=440,
            easingCurve=QEasingCurve.InOutCubic,
            valueChanged=self._set_invalid_progress,
        )
        self._invalid_animation.setStartValue(0.0)
        self._invalid_animation.setKeyValueAt(0.42, 1.0)
        self._invalid_animation.setEndValue(0.0)

    def sizeHint(self):
        font = QFont(self.font())
        font.setPointSize(self._font_point_size or (12 if self._role == "toolbar" else 11))
        font.setWeight(self._font_weight)
        metrics = QFontMetrics(font)
        gap = 12 if not self.icon().isNull() else 0
        icon_width = self._icon_size if not self.icon().isNull() else 0
        horizontal_padding = self._horizontal_padding if self._horizontal_padding is not None else (
            58 if self._role == "toolbar" else 54
        )
        width = metrics.horizontalAdvance(self.text()) + icon_width + gap + horizontal_padding
        minimum_width = self._minimum_width_override if self._minimum_width_override is not None else (
            176 if self._role == "toolbar" else 152
        )
        return QSize(max(width, minimum_width), self.minimumHeight() + 5)

    def minimumSizeHint(self):
        return self.sizeHint()

    def set_metrics(self, *, height: int | None = None, icon_size: int | None = None) -> None:
        if icon_size is not None:
            self._icon_size = icon_size
        if height is not None:
            self.setMinimumHeight(height)
            self.setMaximumHeight(height + 5)
        self.setMinimumWidth(self.sizeHint().width())
        self.updateGeometry()
        self.update()

    def _set_hover_progress(self, value):
        self._hover = float(value)
        self.update()

    def _set_press_progress(self, value):
        self._press = float(value)
        self.update()

    def _set_active_progress(self, value):
        self._active = float(value)
        self.update()

    def _set_invalid_progress(self, value):
        self._invalid = float(value)
        self.update()

    def _animate(self, animation, start, end):
        animation.stop()
        animation.setStartValue(float(start))
        animation.setEndValue(float(end))
        animation.start()

    def set_active(self, active):
        target = 1.0 if active else 0.0
        self._animate(self._active_animation, self._active, target)

    def flash_invalid(self):
        self._invalid_animation.stop()
        self._invalid_animation.start()

    def enterEvent(self, event):
        self._animate(self._hover_animation, self._hover, 1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate(self._hover_animation, self._hover, 0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._animate(self._press_animation, self._press, 1.0)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._animate(self._press_animation, self._press, 0.0)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        shadow_offset = 3 + self._press
        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -(shadow_offset + 1.5))
        rect.translate(0, 0.8 * self._press)

        bg = blend_colors(self._colors["bg"], self._colors["hover"], self._hover)
        bg = blend_colors(bg, self._colors["press"], self._press)
        bg = blend_colors(bg, self._colors["active"], self._active)
        bg = blend_colors(bg, QColor("#5c2740"), self._invalid * 0.9)

        border = blend_colors(self._colors["border"], self._colors["border_hover"], self._hover)
        border = blend_colors(border, self._colors["border_hover"], self._press * 0.45)
        border = blend_colors(border, self._colors["border_active"], self._active)
        border = blend_colors(border, QColor("#ff91bc"), self._invalid)

        text_color = blend_colors(self._colors["text"], QColor("#ffe2ee"), self._invalid * 0.8)

        if not self.isEnabled():
            bg.setAlpha(int(bg.alpha() * 0.4))
            border.setAlpha(int(border.alpha() * 0.45))
            text_color.setAlpha(int(text_color.alpha() * 0.58))

        painter.setPen(Qt.NoPen)
        shadow = QColor(self._colors["shadow"])
        shadow_strength = 0.7 + (self._hover * 0.3) + (self._invalid * 0.2)
        shadow.setAlpha(int(shadow.alpha() * shadow_strength))
        painter.setBrush(shadow)
        painter.drawRoundedRect(rect.adjusted(0, shadow_offset, 0, shadow_offset), self._radius, self._radius)

        painter.setPen(QPen(border, 1.2))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, self._radius, self._radius)

        content_rect = rect.adjusted(18, 0, -18, 0)
        font = QFont(self.font())
        font.setPointSize(self._font_point_size or (12 if self._role == "toolbar" else 11))
        font.setWeight(self._font_weight)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        gap = 12 if not self.icon().isNull() else 0
        available_width = max(0.0, content_rect.width())
        icon_width = self._icon_size if not self.icon().isNull() else 0
        text_width = metrics.horizontalAdvance(self.text())
        reserved_width = icon_width + gap if not self.icon().isNull() else 0
        max_text_width = max(0, int(available_width - reserved_width))
        text_value = metrics.elidedText(self.text(), Qt.ElideRight, max_text_width)
        rendered_text_width = metrics.horizontalAdvance(text_value)
        rendered_total_width = rendered_text_width
        if not self.icon().isNull():
            rendered_total_width += icon_width + gap

        text_left = content_rect.center().x() - (rendered_total_width / 2)
        if not self.icon().isNull():
            pixmap = self.icon().pixmap(self._icon_size, self._icon_size)
            icon_y = content_rect.center().y() - self._icon_size / 2
            painter.drawPixmap(int(text_left), int(icon_y), pixmap)
            text_left += self._icon_size + gap

        painter.setPen(text_color)
        if self.icon().isNull():
            text_rect = QRectF(content_rect.left(), content_rect.top(), content_rect.width(), content_rect.height())
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignHCenter, text_value)
        else:
            text_rect = QRectF(text_left, content_rect.top(), content_rect.right() - text_left + 1, content_rect.height())
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, text_value)


class ClickableFrame(QFrame):
    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class AccountPopup(QWidget):
    account_selected = Signal(str)
    manage_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("accountPopup")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 10, 10, 10)
        self._layout.setSpacing(6)
        self._account_buttons: list[ModernButton] = []
        self._manage_button = ModernButton(
            "Manage Accounts",
            role="sidebar",
            height=36,
            icon_size=0,
            radius=10,
            minimum_width=148,
            horizontal_padding=36,
            font_weight=QFont.Bold,
        )
        self._manage_button.clicked.connect(self._handle_manage)

    def set_accounts(self, accounts: list[str], active_account: str) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                if widget is self._manage_button:
                    widget.setParent(None)
                    continue
                widget.deleteLater()
        self._account_buttons.clear()

        for account_name in accounts:
            button = ModernButton(
                account_name,
                role="sidebar",
                height=36,
                icon_size=0,
                radius=10,
                minimum_width=148,
                horizontal_padding=36,
                font_weight=QFont.Medium,
            )
            button.set_active(account_name == active_account)
            button.clicked.connect(lambda _=False, name=account_name: self._handle_account(name))
            self._layout.addWidget(button)
            self._account_buttons.append(button)

        self._layout.addWidget(self._manage_button)
        self.adjustSize()

    def show_below(self, widget: QWidget) -> None:
        global_pos = widget.mapToGlobal(QPoint(0, widget.height() + 4))
        self.move(global_pos)
        self.show()
        self.raise_()

    def _handle_account(self, account_name: str) -> None:
        self.hide()
        self.account_selected.emit(account_name)

    def _handle_manage(self) -> None:
        self.hide()
        self.manage_requested.emit()


class TopBar(QWidget):
    action_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("topBar")

        asset_root = Path(__file__).resolve().parents[2] / "assets"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        self.buttons = {}
        for name, icon_name in [
            ("Add Instance", "Add-Instance.png"),
            ("Folders", "Folder.png"),
            ("Settings", "Settings.png"),
        ]:
            button = ModernButton(
                name,
                icon=QIcon(str(asset_root / icon_name)),
                role="toolbar",
                height=46,
                icon_size=24,
                radius=10,
                minimum_width=136,
                horizontal_padding=42,
                font_point_size=11,
            )
            button.clicked.connect(lambda _, action=name: self._handle_click(action))
            layout.addWidget(button)
            self.buttons[name] = button

        layout.addStretch()

        self.account_chip = ClickableFrame()
        self.account_chip.setObjectName("accountChip")
        self.account_chip.setCursor(Qt.PointingHandCursor)
        self.account_chip.clicked.connect(self._toggle_account_popup)
        account_layout = QHBoxLayout(self.account_chip)
        account_layout.setContentsMargins(10, 6, 10, 6)
        account_layout.setSpacing(8)

        self.account_avatar = QLabel("P")
        self.account_avatar.setObjectName("accountAvatar")
        self.account_avatar.setAlignment(Qt.AlignCenter)
        account_layout.addWidget(self.account_avatar)

        self.account_name = QLabel("player1")
        self.account_name.setObjectName("accountName")
        account_layout.addWidget(self.account_name)

        layout.addWidget(self.account_chip)
        self.account_popup = AccountPopup(self)
        self.account_popup.account_selected.connect(lambda account: self.action_requested.emit(f"Account:{account}"))
        self.account_popup.manage_requested.connect(lambda: self.action_requested.emit("Manage Accounts"))
        self._layout = layout
        self._account_layout = account_layout
        self._apply_responsive_metrics()

    def showEvent(self, event) -> None:
        self._apply_responsive_metrics()
        super().showEvent(event)

    def resizeEvent(self, event) -> None:
        self._apply_responsive_metrics()
        super().resizeEvent(event)

    def _apply_responsive_metrics(self) -> None:
        margins = scaled_px(self, 12, minimum=10, maximum=16)
        vertical_margin = scaled_px(self, 10, minimum=8, maximum=12)
        spacing = scaled_px(self, 8, minimum=6, maximum=10)
        self._layout.setContentsMargins(margins, vertical_margin, margins, vertical_margin)
        self._layout.setSpacing(spacing)
        self._account_layout.setContentsMargins(
            scaled_px(self, 10, minimum=8, maximum=12),
            scaled_px(self, 6, minimum=5, maximum=8),
            scaled_px(self, 10, minimum=8, maximum=12),
            scaled_px(self, 6, minimum=5, maximum=8),
        )
        self._account_layout.setSpacing(scaled_px(self, 8, minimum=6, maximum=10))
        avatar_size = scaled_px(self, 26, minimum=22, maximum=28)
        self.account_avatar.setFixedSize(avatar_size, avatar_size)

        for button in self.buttons.values():
            button.set_metrics(
                height=scaled_px(self, 46, minimum=40, maximum=48),
                icon_size=scaled_px(self, 24, minimum=18, maximum=24),
            )

    def set_accounts(self, accounts: list[str], active_account: str) -> None:
        self.account_name.setText(active_account)
        self.account_avatar.setText(active_account[:1].upper())
        self.account_popup.set_accounts(accounts, active_account)

    def _handle_click(self, action):
        self.action_requested.emit(action)

    def _toggle_account_popup(self):
        if self.account_popup.isVisible():
            self.account_popup.hide()
            return
        self.account_popup.show_below(self.account_chip)
