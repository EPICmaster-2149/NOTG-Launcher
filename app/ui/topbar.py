from pathlib import Path

from PySide6.QtCore import QEasingCurve, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget


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
            "bg": QColor(0, 0, 0, 0),
            "hover": QColor(104, 154, 255, 30),
            "press": QColor(104, 154, 255, 46),
            "active": QColor(104, 154, 255, 54),
            "border": QColor(140, 178, 255, 0),
            "border_hover": QColor(140, 178, 255, 84),
            "border_active": QColor(140, 178, 255, 120),
            "text": QColor("#e6efff"),
            "shadow": QColor(0, 0, 0, 0),
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

    def __init__(self, text, icon=None, role="toolbar", height=44, icon_size=18, parent=None):
        super().__init__(text, parent)
        self._role = role
        self._colors = self.ROLE_COLORS[role]
        self._hover = 0.0
        self._press = 0.0
        self._active = 0.0
        self._invalid = 0.0
        self._icon_size = icon_size
        self._radius = 18 if role == "toolbar" else 16

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
        font.setPointSize(12 if self._role == "toolbar" else 11)
        font.setWeight(QFont.DemiBold)
        metrics = QFontMetrics(font)
        gap = 14 if not self.icon().isNull() else 0
        icon_width = self._icon_size if not self.icon().isNull() else 0
        width = metrics.horizontalAdvance(self.text()) + icon_width + gap + 48
        minimum_width = 156 if self._role == "toolbar" else 134
        return QSize(max(width, minimum_width), self.minimumHeight())

    def minimumSizeHint(self):
        return self.sizeHint()

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

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
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
        painter.drawRoundedRect(rect.adjusted(0, 3 + self._press, 0, 3 + self._press), self._radius, self._radius)

        painter.setPen(QPen(border, 1.2))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, self._radius, self._radius)

        content_rect = rect.adjusted(18, 0, -18, 0)
        icon_rect = QRectF()
        font = QFont(self.font())
        font.setPointSize(12 if self._role == "toolbar" else 11)
        font.setWeight(QFont.DemiBold)
        metrics = QFontMetrics(font)
        gap = 14 if not self.icon().isNull() else 0
        text_width = metrics.horizontalAdvance(self.text())
        total_width = text_width
        if not self.icon().isNull():
            total_width += self._icon_size + gap

        text_left = content_rect.center().x() - (total_width / 2)
        if not self.icon().isNull():
            pixmap = self.icon().pixmap(self._icon_size, self._icon_size)
            icon_y = content_rect.center().y() - self._icon_size / 2
            icon_rect = QRectF(text_left, icon_y, self._icon_size, self._icon_size)
            painter.drawPixmap(icon_rect.topLeft(), pixmap)
            text_left += self._icon_size + gap

        painter.setPen(text_color)
        painter.setFont(font)
        if self.icon().isNull():
            text_rect = QRectF(content_rect.left(), content_rect.top(), content_rect.width(), content_rect.height())
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignHCenter, self.text())
        else:
            text_rect = QRectF(text_left, content_rect.top(), content_rect.right() - text_left, content_rect.height())
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self.text())


class TopBar(QWidget):
    action_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("topBar")

        asset_root = Path(__file__).resolve().parents[2] / "assets"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(12)

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
                height=52,
                icon_size=30,
            )
            button.clicked.connect(lambda _, action=name: self._handle_click(action))
            layout.addWidget(button)
            self.buttons[name] = button

        layout.addStretch()

        self.account_chip = QFrame()
        self.account_chip.setObjectName("accountChip")
        account_layout = QHBoxLayout(self.account_chip)
        account_layout.setContentsMargins(12, 8, 12, 8)
        account_layout.setSpacing(10)

        self.account_avatar = QLabel("P")
        self.account_avatar.setObjectName("accountAvatar")
        self.account_avatar.setAlignment(Qt.AlignCenter)
        account_layout.addWidget(self.account_avatar)

        self.account_name = QLabel("player1")
        self.account_name.setObjectName("accountName")
        account_layout.addWidget(self.account_name)

        layout.addWidget(self.account_chip)

    def _handle_click(self, action):
        self.action_requested.emit(action)
