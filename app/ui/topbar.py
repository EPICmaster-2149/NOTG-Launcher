from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPoint, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QIcon, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ui.responsive import scaled_px
from ui.theme import theme_palette


def blend_colors(start: QColor, end: QColor, factor: float) -> QColor:
    factor = max(0.0, min(1.0, factor))
    return QColor(
        int(start.red() + (end.red() - start.red()) * factor),
        int(start.green() + (end.green() - start.green()) * factor),
        int(start.blue() + (end.blue() - start.blue()) * factor),
        int(start.alpha() + (end.alpha() - start.alpha()) * factor),
    )


class ModernButton(QPushButton):
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
        self._hover = 0.0
        self._press = 0.0
        self._active = 0.0
        self._invalid = 0.0
        self._icon_size = icon_size
        self._radius = radius if radius is not None else (10 if role == "toolbar" else 10)
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
        font = self._button_font()
        metrics = QFontMetrics(font)
        gap = 12 if not self.icon().isNull() else 0
        icon_width = self._icon_size if not self.icon().isNull() else 0
        horizontal_padding = self._horizontal_padding if self._horizontal_padding is not None else (
            44 if self._role == "toolbar" else 34
        )
        width = metrics.horizontalAdvance(self.text()) + icon_width + gap + horizontal_padding
        minimum_width = self._minimum_width_override if self._minimum_width_override is not None else (
            144 if self._role == "toolbar" else 112
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

    def refresh_theme(self) -> None:
        self.update()

    def _button_font(self, point_size: float | None = None) -> QFont:
        font = QFont(self.font())
        font.setPointSizeF(point_size if point_size is not None else float(self._font_point_size or (12 if self._role == "toolbar" else 11)))
        font.setWeight(self._font_weight)
        return font

    def _fit_text_lines(self, max_width: float, max_height: float) -> tuple[QFont, list[str]]:
        text = self.text().strip()
        if not text:
            return self._button_font(), [""]

        base_size = float(self._font_point_size or (12 if self._role == "toolbar" else 11))
        minimum_size = 8.0 if self._role == "toolbar" else 7.8
        has_breaks = " " in text.strip()
        candidate_size = base_size

        while candidate_size >= minimum_size:
            font = self._button_font(candidate_size)
            metrics = QFontMetrics(font)
            lines = self._wrap_lines(text, metrics, int(max_width), allow_wrap=has_breaks)
            line_height = metrics.lineSpacing()
            fits_width = all(metrics.horizontalAdvance(line) <= max_width + 1 for line in lines if line)
            fits_height = (line_height * len(lines)) <= max_height + 1
            if fits_width and fits_height:
                return font, lines
            candidate_size -= 0.4

        font = self._button_font(minimum_size)
        metrics = QFontMetrics(font)
        return font, self._wrap_lines(text, metrics, int(max_width), allow_wrap=has_breaks)

    def _wrap_lines(self, text: str, metrics: QFontMetrics, max_width: int, *, allow_wrap: bool) -> list[str]:
        if max_width <= 0:
            return [text]
        if not allow_wrap or metrics.horizontalAdvance(text) <= max_width:
            return [text]

        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            proposal = word if not current else f"{current} {word}"
            if metrics.horizontalAdvance(proposal) <= max_width:
                current = proposal
                continue
            if current:
                lines.append(current)
            current = word
        if current:
            lines.append(current)
        return lines or [text]

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
        colors = theme_palette(self)["buttons"][self._role]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        shadow_offset = 3 + self._press
        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -(shadow_offset + 1.5))
        rect.translate(0, 0.8 * self._press)

        bg = blend_colors(colors["bg"], colors["hover"], self._hover)
        bg = blend_colors(bg, colors["press"], self._press)
        bg = blend_colors(bg, colors["active"], self._active)
        bg = blend_colors(bg, QColor("#5c2740"), self._invalid * 0.9)

        border = blend_colors(colors["border"], colors["border_hover"], self._hover)
        border = blend_colors(border, colors["border_hover"], self._press * 0.45)
        border = blend_colors(border, colors["border_active"], self._active)
        border = blend_colors(border, QColor("#ff91bc"), self._invalid)

        text_color = blend_colors(colors["text"], QColor("#ffe2ee"), self._invalid * 0.8)

        if not self.isEnabled():
            bg.setAlpha(int(bg.alpha() * 0.4))
            border.setAlpha(int(border.alpha() * 0.45))
            text_color.setAlpha(int(text_color.alpha() * 0.58))

        painter.setPen(Qt.NoPen)
        shadow = QColor(colors["shadow"])
        shadow_strength = 0.7 + (self._hover * 0.3) + (self._invalid * 0.2)
        shadow.setAlpha(int(shadow.alpha() * shadow_strength))
        painter.setBrush(shadow)
        painter.drawRoundedRect(rect.adjusted(0, shadow_offset, 0, shadow_offset), self._radius, self._radius)

        painter.setPen(QPen(border, 1.2))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, self._radius, self._radius)

        content_rect = rect.adjusted(18, 0, -18, 0)
        gap = 12 if not self.icon().isNull() else 0
        available_width = max(0.0, content_rect.width())
        icon_width = self._icon_size if not self.icon().isNull() else 0
        reserved_width = icon_width + gap if not self.icon().isNull() else 0
        max_text_width = max(0.0, available_width - reserved_width)

        font, text_lines = self._fit_text_lines(max_text_width, content_rect.height())
        painter.setFont(font)
        metrics = QFontMetrics(font)
        rendered_text_width = max((metrics.horizontalAdvance(line) for line in text_lines), default=0)
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
        line_height = metrics.lineSpacing()
        total_text_height = line_height * len(text_lines)
        text_top = content_rect.center().y() - (total_text_height / 2)
        if self.icon().isNull():
            for index, line in enumerate(text_lines):
                line_rect = QRectF(content_rect.left(), text_top + (index * line_height), content_rect.width(), line_height)
                painter.drawText(line_rect, Qt.AlignHCenter | Qt.AlignVCenter, line)
        else:
            text_width = max(0.0, content_rect.right() - text_left + 1)
            for index, line in enumerate(text_lines):
                line_rect = QRectF(text_left, text_top + (index * line_height), text_width, line_height)
                painter.drawText(line_rect, Qt.AlignLeft | Qt.AlignVCenter, line)


class ClickableFrame(QFrame):
    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


@dataclass(slots=True)
class PopupAction:
    action_id: str
    label: str
    role: str = "sidebar"
    bold: bool = False
    active: bool = False


class ActionPopup(QWidget):
    action_triggered = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("actionPopup")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(4)
        self._buttons: list[ModernButton] = []
        self._minimum_popup_width = 184

    def set_actions(self, actions: list[PopupAction]) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._buttons.clear()
        for action in actions:
            button = ModernButton(
                action.label,
                role=action.role,
                height=36,
                icon_size=0,
                radius=8,
                minimum_width=self._minimum_popup_width,
                horizontal_padding=30,
                font_weight=QFont.Bold if action.bold else QFont.Medium,
                font_point_size=10,
            )
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.set_active(action.active)
            button.clicked.connect(lambda _=False, action_id=action.action_id: self._emit_action(action_id))
            self._layout.addWidget(button)
            self._buttons.append(button)

        self._sync_width()

    def show_below(self, widget: QWidget, *, align_right: bool = False) -> None:
        anchor = widget.mapToGlobal(QPoint(0, widget.height() + 4))
        if align_right:
            anchor.setX(anchor.x() + max(0, widget.width() - self.width()))
        self._show_at(anchor)

    def show_at_global(self, global_pos: QPoint) -> None:
        self._show_at(global_pos)

    def _sync_width(self) -> None:
        target_width = self._minimum_popup_width
        for button in self._buttons:
            target_width = max(target_width, button.sizeHint().width())
        self.setFixedWidth(target_width + 4)
        self.adjustSize()

    def _show_at(self, global_pos: QPoint) -> None:
        geometry = QGuiApplication.primaryScreen().availableGeometry() if QGuiApplication.primaryScreen() else None
        target_x = global_pos.x()
        target_y = global_pos.y()
        if geometry is not None:
            target_x = max(geometry.left() + 6, min(target_x, geometry.right() - self.width() - 6))
            target_y = max(geometry.top() + 6, min(target_y, geometry.bottom() - self.height() - 6))
        self.move(QPoint(target_x, target_y))
        self.show()
        self.raise_()

    def _emit_action(self, action_id: str) -> None:
        self.hide()
        self.action_triggered.emit(action_id)


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
        self.account_popup = ActionPopup(self)
        self.account_popup.action_triggered.connect(self._handle_popup_action)
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
        actions = [
            PopupAction(
                action_id=f"Account:{account_name}",
                label=account_name,
                role="sidebar",
                active=account_name == active_account,
            )
            for account_name in accounts
        ]
        actions.append(PopupAction("Manage Accounts", "Manage Accounts", bold=True))
        self.account_popup.set_actions(actions)

    def _handle_click(self, action):
        self.action_requested.emit(action)

    def _handle_popup_action(self, action: str) -> None:
        self.action_requested.emit(action)

    def _toggle_account_popup(self):
        if self.account_popup.isVisible():
            self.account_popup.hide()
            return
        self.account_popup.show_below(self.account_chip, align_right=True)
