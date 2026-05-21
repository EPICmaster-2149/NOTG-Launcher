from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QTimer, Signal, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import (
    QApplication,
    QAbstractButton,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.launcher import LauncherService, VIDEO_SUFFIXES
from ui.app_icon import application_icon
from ui.background_selector_dialog import BackgroundSelectorDialog
from ui.responsive import fitted_window_size, scaled_px
from ui.theme import apply_theme, current_theme_accent, set_theme_accent, theme_palette
from ui.topbar import ModernButton, blend_colors
from ui.update_settings import UpdateSettingsPanel


class BackgroundPreview(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._pixmap = QPixmap()
        self._video_selected = False
        self.setMinimumHeight(260)

    def set_image_path(self, image_path: str | None) -> None:
        self._video_selected = bool(image_path and Path(image_path).suffix.lower() in VIDEO_SUFFIXES)
        self._pixmap = QPixmap(image_path) if image_path and not self._video_selected else QPixmap()
        self.update()

    def paintEvent(self, event) -> None:
        del event
        palette = theme_palette(self)["background_preview"]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        outer = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(palette["outer_border"], 1.2))
        painter.setBrush(palette["outer_fill"])
        painter.drawRoundedRect(outer, 16, 16)

        inner = outer.adjusted(12, 12, -12, -12)
        painter.setPen(Qt.NoPen)
        painter.setBrush(palette["inner_fill"])
        painter.drawRoundedRect(inner, 12, 12)

        if self._pixmap.isNull():
            painter.setPen(palette["text"])
            painter.drawText(inner, Qt.AlignCenter, "Video background selected" if self._video_selected else "No background selected")
            return

        scaled = self._pixmap.scaled(
            int(inner.width()),
            int(inner.height()),
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        source_x = max(0, int((scaled.width() - inner.width()) / 2))
        source_y = max(0, int((scaled.height() - inner.height()) / 2))
        painter.drawPixmap(
            int(inner.left()),
            int(inner.top()),
            scaled,
            source_x,
            source_y,
            int(inner.width()),
            int(inner.height()),
        )


class ToggleSwitch(QAbstractButton):
    def __init__(self, checked: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self._progress = 1.0 if checked else 0.0
        self._animation = QVariantAnimation(
            self,
            duration=160,
            easingCurve=QEasingCurve.OutCubic,
            valueChanged=self._set_progress,
        )
        self.toggled.connect(self._animate_toggle)
        self.setChecked(checked)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def sizeHint(self) -> QSize:
        return QSize(56, 30)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _set_progress(self, value: float) -> None:
        self._progress = float(value)
        self.update()

    def _animate_toggle(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._progress)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def paintEvent(self, event) -> None:
        del event
        palette = theme_palette(self)
        accent = palette["buttons"]["accent"]
        sidebar = palette["buttons"]["sidebar"]
        track_fill = blend_colors(sidebar["bg"], accent["bg"], self._progress)
        track_border = blend_colors(sidebar["border"], accent["border"], self._progress)
        thumb_fill = QColor("#fdfefe") if self.isChecked() else QColor(palette["line_edit"]["background_focus"])

        if not self.isEnabled():
            track_fill.setAlpha(int(track_fill.alpha() * 0.4))
            track_border.setAlpha(int(track_border.alpha() * 0.45))

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        painter.setPen(QPen(track_border, 1.1))
        painter.setBrush(track_fill)
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)

        knob_margin = 3.0
        knob_size = rect.height() - (knob_margin * 2)
        knob_x = rect.left() + knob_margin + ((rect.width() - knob_size - (knob_margin * 2)) * self._progress)
        knob_rect = QRectF(knob_x, rect.top() + knob_margin, knob_size, knob_size)
        painter.setPen(Qt.NoPen)
        painter.setBrush(thumb_fill)
        painter.drawEllipse(knob_rect)


class SettingsNavButton(QAbstractButton):
    def __init__(self, text: str, icon_kind: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._icon_kind = icon_kind
        self._compact = False
        self._hover = 0.0
        self._active = 0.0

        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._hover_animation = QVariantAnimation(self, duration=150, easingCurve=QEasingCurve.OutCubic)
        self._hover_animation.valueChanged.connect(lambda value: self._set_value("_hover", value))
        self._active_animation = QVariantAnimation(self, duration=190, easingCurve=QEasingCurve.OutCubic)
        self._active_animation.valueChanged.connect(lambda value: self._set_value("_active", value))

    def sizeHint(self) -> QSize:
        return QSize(52 if self._compact else 196, 48)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def set_compact(self, compact: bool) -> None:
        self._compact = bool(compact)
        self.updateGeometry()
        self.update()

    def setChecked(self, checked: bool) -> None:  # noqa: N802
        super().setChecked(checked)
        self._active_animation.stop()
        self._active_animation.setStartValue(self._active)
        self._active_animation.setEndValue(1.0 if checked else 0.0)
        self._active_animation.start()

    def enterEvent(self, event) -> None:
        self._animate(self._hover_animation, self._hover, 1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate(self._hover_animation, self._hover, 0.0)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        del event
        colors = theme_palette(self)["buttons"]["sidebar"]
        accent = theme_palette(self)["buttons"]["accent"]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)

        bg = blend_colors(colors["bg"], colors["hover"], self._hover)
        bg = blend_colors(bg, accent["active"], self._active)
        border = blend_colors(colors["border"], colors["border_hover"], self._hover)
        border = blend_colors(border, accent["border_active"], self._active)
        text_color = blend_colors(colors["text"], accent["text"], self._active)

        painter.setPen(QPen(border, 1.0))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 10, 10)

        icon_rect = QRectF(rect.left() + (14 if not self._compact else (rect.width() - 22) / 2), rect.center().y() - 11, 22, 22)
        painter.setPen(QPen(text_color, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        if self._icon_kind == "appearance":
            painter.drawEllipse(icon_rect.adjusted(1.5, 1.5, -1.5, -1.5))
            painter.drawEllipse(QRectF(icon_rect.center().x() - 3, icon_rect.center().y() - 3, 6, 6))
            painter.drawLine(icon_rect.center(), QPointF(icon_rect.right() - 3, icon_rect.top() + 5))
        else:
            painter.drawArc(icon_rect.adjusted(2, 3, -2, -3), 35 * 16, 270 * 16)
            painter.drawLine(QPointF(icon_rect.right() - 4, icon_rect.top() + 6), QPointF(icon_rect.right() - 1, icon_rect.top() + 12))
            painter.drawLine(QPointF(icon_rect.right() - 4, icon_rect.top() + 6), QPointF(icon_rect.right() - 10, icon_rect.top() + 5))

        if not self._compact:
            font = QFont(self.font())
            font.setPointSize(10)
            font.setWeight(QFont.DemiBold)
            painter.setFont(font)
            painter.setPen(text_color)
            painter.drawText(rect.adjusted(46, 0, -10, 0), Qt.AlignVCenter | Qt.AlignLeft, self.text())

    def _animate(self, animation: QVariantAnimation, start: float, end: float) -> None:
        animation.stop()
        animation.setStartValue(float(start))
        animation.setEndValue(float(end))
        animation.start()

    def _set_value(self, attribute: str, value) -> None:
        setattr(self, attribute, float(value))
        self.update()


class ThemeColorWheel(QWidget):
    color_changed = Signal(str)

    def __init__(self, color: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._color = QColor(color)
        if not self._color.isValid():
            self._color = current_theme_accent(self)
        self._adaptive = True
        self._hover_pin = False
        self._pulse = 0.0
        self.setCursor(Qt.ForbiddenCursor)
        self.setMinimumSize(220, 220)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._pulse_animation = QVariantAnimation(self, duration=2400, easingCurve=QEasingCurve.InOutSine)
        self._pulse_animation.setStartValue(0.0)
        self._pulse_animation.setEndValue(1.0)
        self._pulse_animation.valueChanged.connect(self._set_pulse)
        self._pulse_animation.setLoopCount(-1)
        self._pulse_animation.start()

    def set_color(self, color: str | QColor) -> None:
        next_color = QColor(color)
        if next_color.isValid() and next_color.name() != self._color.name():
            self._color = next_color
            self.update()

    def set_adaptive(self, adaptive: bool) -> None:
        self._adaptive = bool(adaptive)
        self.setCursor(Qt.ForbiddenCursor if adaptive else Qt.CrossCursor)
        self.update()

    def color_hex(self) -> str:
        return self._color.name().upper()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        side = min(self.width(), self.height()) - 8
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        center = rect.center()
        ring_width = max(12.0, side * 0.075)

        # active color (consistent across wheel, preview, glow)
        active_color = current_theme_accent(self) if self._adaptive else self._color
        active = QColor(active_color)
        accent_light = blend_colors(active, QColor("#ffffff"), 0.32)

        # Ambient bloom behind the wheel (subtle, performance-friendly radial)
        painter.save()
        bloom = QColor(active)
        bloom.setAlpha(28 if self._adaptive else 18)
        rg_bloom = QRadialGradient(center.x(), center.y(), side * 0.9)
        rg_bloom.setColorAt(0.0, bloom)
        tb = QColor(bloom)
        tb.setAlpha(0)
        rg_bloom.setColorAt(0.6, tb)
        painter.setPen(Qt.NoPen)
        painter.setBrush(rg_bloom)
        painter.drawEllipse(QRectF(center.x() - side * 0.55, center.y() - side * 0.55, side * 1.1, side * 1.1))

        # soft shadow to lift the wheel
        shadow_grad = QRadialGradient(center.x(), center.y() + side * 0.06, side * 0.7)
        shadow_grad.setColorAt(0.0, QColor(0, 0, 0, 64))
        shadow_grad.setColorAt(0.6, QColor(0, 0, 0, 0))
        painter.setBrush(shadow_grad)
        painter.drawEllipse(QRectF(center.x() - side * 0.6, center.y() - side * 0.22, side * 1.2, side * 0.7))
        painter.restore()

        # Wheel ring: draw arc segments to ensure pin math matches rendering
        painter.setOpacity(0.88 if self._adaptive else 1.0)
        steps = 120
        adj = rect.adjusted(ring_width / 2, ring_width / 2, -ring_width / 2, -ring_width / 2)
        painter.setBrush(Qt.NoBrush)
        span = 360.0 / steps
        for i in range(steps):
            h = i / steps
            col = QColor.fromHsvF(h if h < 1.0 else 0.0, 0.88, 1.0)
            if self._adaptive:
                col = blend_colors(col, QColor("#d7e7ff"), 0.28)
            pen_seg = QPen(col, ring_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            painter.setPen(pen_seg)
            start_deg = (h * 360.0) - 90.0
            painter.drawArc(adj, int(start_deg * 16), int(span * 16))

        # Center preview (simplified, non-metallic)
        painter.setOpacity(1.0)
        active_color = current_theme_accent(self) if self._adaptive else self._color
        preview_radius = side * 0.255
        preview = QRectF(center.x() - preview_radius, center.y() - preview_radius, preview_radius * 2, preview_radius * 2)

        core_grad = QRadialGradient(center.x(), center.y(), preview_radius)
        inner = blend_colors(QColor("#ffffff"), QColor(active_color), 0.18)
        inner.setAlpha(230)
        mid = QColor(active_color)
        mid.setAlpha(210)
        outer = QColor(active_color)
        outer.setAlpha(36)
        core_grad.setColorAt(0.0, inner)
        core_grad.setColorAt(0.6, mid)
        core_grad.setColorAt(1.0, outer)

        painter.setPen(QPen(blend_colors(QColor("#000000"), QColor(active_color), 0.12), 1.0))
        painter.setBrush(core_grad)
        painter.drawEllipse(preview)

        # Show hex and friendly name inside the preview
        font = QFont(self.font())
        font.setPointSize(9)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(247, 251, 255, 230))
        painter.drawText(preview.adjusted(0, -8, 0, 0), Qt.AlignCenter, active_color.name().upper())
        font.setPointSize(8)
        font.setWeight(QFont.Normal)
        painter.setFont(font)
        painter.setPen(QColor(210, 225, 245, 160))
        painter.drawText(preview.adjusted(0, 14, 0, 0), Qt.AlignCenter, _color_name(active_color))

        if self._adaptive:
            return

        # Pin: simple filled circle with subtle glow (no metallic specular)
        pin = self._pin_position(rect, ring_width)
        pin_radius = 7.5 if self._hover_pin else 6.0

        # subtle outer halo
        halo = QColor(active_color)
        halo.setAlpha(80)
        painter.setPen(Qt.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(QRectF(pin.x() - pin_radius * 1.8, pin.y() - pin_radius * 1.8, pin_radius * 3.6, pin_radius * 3.6))

        # pin body
        painter.setPen(QPen(QColor("#ffffff"), 1.0))
        painter.setBrush(QColor(active_color))
        painter.drawEllipse(QRectF(pin.x() - pin_radius, pin.y() - pin_radius, pin_radius * 2, pin_radius * 2))

    def mousePressEvent(self, event) -> None:
        if self._adaptive or event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        self._set_color_from_point(event.position())
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._adaptive:
            return
        self._hover_pin = self._pin_hit(event.position())
        if event.buttons() & Qt.LeftButton:
            self._set_color_from_point(event.position())
        else:
            self.update()

    def leaveEvent(self, event) -> None:
        self._hover_pin = False
        self.update()
        super().leaveEvent(event)

    def _set_color_from_point(self, point: QPointF) -> None:
        center = QPointF(self.width() / 2, self.height() / 2)
        angle = math.degrees(math.atan2(center.y() - point.y(), point.x() - center.x()))
        hue = ((angle + 90.0) % 360.0) / 360.0
        self._color = QColor.fromHsvF(hue, 0.82, 1.0)
        self.color_changed.emit(self._color.name())
        self.update()

    def _pin_hit(self, point: QPointF) -> bool:
        side = min(self.width(), self.height()) - 8
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        pin = self._pin_position(rect, max(12.0, side * 0.075))
        return (point.x() - pin.x()) ** 2 + (point.y() - pin.y()) ** 2 <= 16 ** 2

    def _pin_position(self, rect: QRectF, ring_width: float) -> QPointF:
        hue = self._color.hsvHueF()
        if hue < 0:
            hue = 0.58
        angle = math.radians((hue * 360.0) - 90.0)
        radius = (rect.width() - ring_width) / 2
        center = rect.center()
        return QPointF(center.x() + math.cos(angle) * radius, center.y() - math.sin(angle) * radius)

    def _set_pulse(self, value: float) -> None:
        self._pulse = float(value)
        if self._adaptive:
            self.update()


class SettingsDialog(QDialog):
    background_changed = Signal(str)
    theme_changed = Signal()

    def __init__(self, service: LauncherService, parent: QWidget | None = None):
        super().__init__(parent)
        self.service = service
        self._pending_theme_color = self.service.get_theme_accent_color()
        self._manual_theme_timer = QTimer(self)
        self._manual_theme_timer.setSingleShot(True)
        self._manual_theme_timer.setInterval(90)
        self._manual_theme_timer.timeout.connect(self._commit_manual_theme_color)

        self.setObjectName("settingsDialog")
        self.setWindowTitle("Settings")
        self.setWindowIcon(application_icon(self.service.project_root))
        self.setModal(False)
        self.setMinimumSize(680, 540)
        self.resize(fitted_window_size(self.parentWidget() or self, 920, 660, minimum_width=680, minimum_height=540))

        self._build_ui()
        self._apply_responsive_layout()
        self._refresh_preview()
        self._select_page(0)

    def showEvent(self, event) -> None:
        self._apply_responsive_layout()
        super().showEvent(event)

    def resizeEvent(self, event) -> None:
        self._apply_responsive_layout()
        super().resizeEvent(event)

    def refresh_theme(self) -> None:
        self.theme_color_wheel.update()
        for button in self.nav_buttons:
            button.update()

    def _build_ui(self) -> None:
        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(14, 14, 14, 14)
        root_layout.setSpacing(14)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("settingsSidebar")
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(10, 12, 10, 12)
        sidebar_layout.setSpacing(8)
        self.sidebar_title = QLabel("Settings")
        self.sidebar_title.setObjectName("settingsSidebarTitle")
        sidebar_layout.addWidget(self.sidebar_title)

        self.appearance_nav = SettingsNavButton("Appearance", "appearance")
        self.updates_nav = SettingsNavButton("Updates", "updates")
        self.nav_buttons = [self.appearance_nav, self.updates_nav]
        self.appearance_nav.clicked.connect(lambda: self._select_page(0))
        self.updates_nav.clicked.connect(lambda: self._select_page(1))
        sidebar_layout.addWidget(self.appearance_nav)
        sidebar_layout.addWidget(self.updates_nav)
        sidebar_layout.addStretch()
        root_layout.addWidget(self.sidebar)

        self.content = QFrame()
        self.content.setObjectName("settingsContent")
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(16, 16, 16, 14)
        content_layout.setSpacing(12)

        self.stack = QStackedWidget()
        self.stack.setObjectName("settingsStack")
        self.stack.addWidget(self._build_appearance_page())
        self.stack.addWidget(self._build_updates_page())
        content_layout.addWidget(self.stack, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addStretch()
        self.ok_button = ModernButton("OK", role="accent", height=38, icon_size=0, minimum_width=88, horizontal_padding=24, font_point_size=10)
        self.ok_button.clicked.connect(self.accept)
        footer.addWidget(self.ok_button)
        content_layout.addLayout(footer)
        root_layout.addWidget(self.content, 1)

    def _build_appearance_page(self) -> QWidget:
        page, page_layout = self._page_shell("Appearance", "Visuals, background, and launcher theme.")

        background_card, background_layout = self._section_card("Background")
        background_actions = QHBoxLayout()
        background_actions.setContentsMargins(0, 0, 0, 0)
        background_actions.setSpacing(10)
        self.change_background_button = ModernButton(
            "Change Background",
            role="accent",
            height=36,
            icon_size=0,
            minimum_width=150,
            horizontal_padding=22,
            font_point_size=10,
        )
        self.change_background_button.clicked.connect(self._change_background)
        background_actions.addWidget(self.change_background_button)
        background_actions.addStretch()
        background_layout.addLayout(background_actions)

        self.preview = BackgroundPreview()
        background_layout.addWidget(self.preview, 1)
        self.caption = QLabel("")
        self.caption.setObjectName("settingsCaption")
        self.caption.setWordWrap(True)
        background_layout.addWidget(self.caption)
        page_layout.addWidget(background_card)

        theme_card, theme_layout = self._section_card("Theme")
        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(12)
        self.theme_switch = ToggleSwitch(checked=self.service.get_theme_mode() == "light")
        self.theme_switch.toggled.connect(self._set_light_theme)
        mode_row.addWidget(self.theme_switch, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        self.theme_label = QLabel("Light mode")
        self.theme_label.setObjectName("settingsFieldTitle")
        mode_row.addWidget(self.theme_label, 1, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        theme_layout.addLayout(mode_row)

        adaptive_row = QHBoxLayout()
        adaptive_row.setContentsMargins(0, 0, 0, 0)
        adaptive_row.setSpacing(12)
        # Adapt to Music is disabled by default and not editable
        self.adapt_theme_switch = ToggleSwitch(checked=False)
        self.adapt_theme_switch.setEnabled(False)
        self.adapt_theme_switch.toggled.connect(self._set_adapt_to_music)
        adaptive_row.addWidget(self.adapt_theme_switch, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        adaptive_label = QLabel("Adapt to Music")
        adaptive_label.setObjectName("settingsFieldTitle")
        adaptive_row.addWidget(adaptive_label, 1, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        theme_layout.addLayout(adaptive_row)

        wheel_row = QHBoxLayout()
        wheel_row.setContentsMargins(0, 6, 0, 0)
        wheel_row.setSpacing(16)
        self.theme_color_wheel = ThemeColorWheel(self.service.get_theme_accent_color())
        self.theme_color_wheel.set_adaptive(False)
        self.theme_color_wheel.color_changed.connect(self._schedule_manual_theme_color)
        wheel_row.addWidget(self.theme_color_wheel, 0, Qt.AlignCenter | Qt.AlignVCenter)
        theme_layout.addLayout(wheel_row)
        page_layout.addWidget(theme_card)

        general_card, general_layout = self._section_card("General")
        self.close_on_launch_checkbox = QCheckBox("Close the launcher after game launch")
        self.close_on_launch_checkbox.setObjectName("editorFilterCheck")
        self.close_on_launch_checkbox.setChecked(self.service.get_close_ui_on_launch())
        self.close_on_launch_checkbox.toggled.connect(self._set_close_on_launch)
        general_layout.addWidget(self.close_on_launch_checkbox)
        page_layout.addWidget(general_card)
        page_layout.addStretch()
        return page

    def _build_updates_page(self) -> QWidget:
        page, page_layout = self._page_shell("Updates", "Launcher update checks and install flow.")
        updates_card, updates_layout = self._section_card("Launcher Updates")
        self.update_settings = UpdateSettingsPanel(
            parent=self,
            github_owner="EPICmaster-2149",
            github_repo="NOTG-Launcher",
        )
        updates_layout.addWidget(self.update_settings, 1)
        page_layout.addWidget(updates_card, 1)
        return page

    def _page_shell(self, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        scroll_area = QScrollArea()
        scroll_area.setObjectName("settingsScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setAutoFillBackground(False)

        page = QWidget()
        page.setObjectName("settingsScrollContent")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 6, 0)
        page_layout.setSpacing(14)

        title_label = QLabel(title)
        title_label.setObjectName("settingsPageTitle")
        page_layout.addWidget(title_label)
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("settingsSubtitle")
        subtitle_label.setWordWrap(True)
        page_layout.addWidget(subtitle_label)
        scroll_area.setWidget(page)
        scroll_area.viewport().setAutoFillBackground(False)
        scroll_area.viewport().setAttribute(Qt.WA_StyledBackground, False)
        return scroll_area, page_layout

    def _section_card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("settingsSectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        label = QLabel(title)
        label.setObjectName("editorSectionTitle")
        layout.addWidget(label)
        return card, layout

    def _select_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for button_index, button in enumerate(self.nav_buttons):
            button.setChecked(button_index == index)

    def _apply_responsive_layout(self) -> None:
        compact_sidebar = self.width() < 760
        self.sidebar.setFixedWidth(scaled_px(self, 76 if compact_sidebar else 228, minimum=72 if compact_sidebar else 210, maximum=82 if compact_sidebar else 240))
        self.sidebar_title.setVisible(not compact_sidebar)
        for button in self.nav_buttons:
            button.set_compact(compact_sidebar)

        layout = self.layout()
        if isinstance(layout, QHBoxLayout):
            margin = scaled_px(self, 14, minimum=10, maximum=16)
            layout.setContentsMargins(margin, margin, margin, margin)
            layout.setSpacing(scaled_px(self, 14, minimum=10, maximum=16))

        content_layout = self.content.layout()
        if isinstance(content_layout, QVBoxLayout):
            margin = scaled_px(self, 16, minimum=12, maximum=18)
            content_layout.setContentsMargins(margin, margin, margin, scaled_px(self, 14, minimum=10, maximum=16))
            content_layout.setSpacing(scaled_px(self, 12, minimum=9, maximum=14))

        self.change_background_button.set_metrics(height=scaled_px(self, 36, minimum=32, maximum=38), icon_size=0)
        self.ok_button.set_metrics(height=scaled_px(self, 38, minimum=34, maximum=40), icon_size=0)
        self.preview.setMinimumHeight(scaled_px(self, 260, minimum=200, maximum=320))

    def _refresh_preview(self) -> None:
        background_path = self.service.get_active_background_path()
        self.preview.set_image_path(background_path)
        self.caption.setText(Path(background_path).name if background_path else "Default background")

    def _change_background(self) -> None:
        dialog = BackgroundSelectorDialog(self.service, self.service.get_active_background_reference(), self)
        dialog.active_background_changed.connect(self._handle_background_dialog_active_changed)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            resolved = self.service.set_active_background(dialog.selected_background_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Background", str(exc))
            return
        self._refresh_preview()
        self.background_changed.emit(resolved)

    def _handle_background_dialog_active_changed(self, resolved_path: str) -> None:
        self._refresh_preview()
        self.background_changed.emit(resolved_path)

    def _set_close_on_launch(self, checked: bool) -> None:
        try:
            self.service.set_close_ui_on_launch(checked)
        except Exception as exc:  # noqa: BLE001
            self.close_on_launch_checkbox.blockSignals(True)
            self.close_on_launch_checkbox.setChecked(not checked)
            self.close_on_launch_checkbox.blockSignals(False)
            QMessageBox.warning(self, "Gameplay behaviour", str(exc))

    def _set_light_theme(self, checked: bool) -> None:
        try:
            mode = self.service.set_theme_mode("light" if checked else "dark")
        except Exception as exc:  # noqa: BLE001
            self.theme_switch.blockSignals(True)
            self.theme_switch.setChecked(not checked)
            self.theme_switch.blockSignals(False)
            QMessageBox.warning(self, "Appearance", str(exc))
            return

        app = QApplication.instance()
        if app is not None:
            apply_theme(app, mode)
        self.theme_changed.emit()

    def _set_adapt_to_music(self, checked: bool) -> None:
        try:
            enabled = self.service.set_theme_adapt_to_music(checked)
        except Exception as exc:  # noqa: BLE001
            self.adapt_theme_switch.blockSignals(True)
            self.adapt_theme_switch.setChecked(not checked)
            self.adapt_theme_switch.blockSignals(False)
            QMessageBox.warning(self, "Appearance", str(exc))
            return
        self.theme_color_wheel.set_adaptive(enabled)
        if not enabled:
            self._commit_manual_theme_color()
        self.theme_changed.emit()

    def _schedule_manual_theme_color(self, color: str) -> None:
        self._pending_theme_color = color
        self._manual_theme_timer.start()

    def _commit_manual_theme_color(self) -> None:
        try:
            saved = self.service.set_theme_accent_color(self._pending_theme_color)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Appearance", str(exc))
            return
        self.theme_color_wheel.set_color(saved)
        if not self.service.get_theme_adapt_to_music():
            app = QApplication.instance()
            if app is not None:
                set_theme_accent(app, saved)
        self.theme_changed.emit()


def _color_name(color: QColor) -> str:
    hue = color.hsvHue()
    if hue < 0:
        return "Soft White"
    if hue < 18 or hue >= 344:
        return "Crimson"
    if hue < 42:
        return "Sunset Orange"
    if hue < 72:
        return "Gold"
    if hue < 155:
        return "Emerald"
    if hue < 190:
        return "Aqua"
    if hue < 235:
        return "Sky Blue"
    if hue < 275:
        return "Violet"
    if hue < 320:
        return "Magenta"
    return "Rose"
