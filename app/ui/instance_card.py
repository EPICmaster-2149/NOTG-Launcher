from PySide6.QtCore import QEasingCurve, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ui.icon_utils import load_scaled_icon
from ui.responsive import scaled_px, screen_scale


def blend_colors(start: QColor, end: QColor, factor: float) -> QColor:
    factor = max(0.0, min(1.0, factor))
    return QColor(
        int(start.red() + (end.red() - start.red()) * factor),
        int(start.green() + (end.green() - start.green()) * factor),
        int(start.blue() + (end.blue() - start.blue()) * factor),
        int(start.alpha() + (end.alpha() - start.alpha()) * factor),
    )


class InstanceCard(QWidget):
    clicked = Signal()

    def __init__(self, name, version, icon_path):
        super().__init__()
        self.name = name
        self.version = version.replace("Minecraft ", "")
        self.icon_path = icon_path
        self._hover_progress = 0.0
        self._selected_progress = 0.0
        self._selected = False

        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_Hover, True)

        self._hover_animation = QVariantAnimation(
            self,
            duration=160,
            easingCurve=QEasingCurve.OutCubic,
            valueChanged=self._set_hover_progress,
        )
        self._selection_animation = QVariantAnimation(
            self,
            duration=180,
            easingCurve=QEasingCurve.OutCubic,
            valueChanged=self._set_selected_progress,
        )

    def sizeHint(self):
        return QSize(
            scaled_px(self, 198, minimum=176, maximum=206),
            scaled_px(self, 212, minimum=188, maximum=220),
        )

    def minimumSizeHint(self):
        return self.sizeHint()

    def _set_hover_progress(self, value):
        self._hover_progress = float(value)
        self.update()

    def _set_selected_progress(self, value):
        self._selected_progress = float(value)
        self.update()

    def _animate(self, animation, start, end):
        animation.stop()
        animation.setStartValue(float(start))
        animation.setEndValue(float(end))
        animation.start()

    def set_selected(self, selected):
        self._selected = selected
        self._animate(self._selection_animation, self._selected_progress, 1.0 if selected else 0.0)

    def enterEvent(self, event):
        self._animate(self._hover_animation, self._hover_progress, 1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate(self._hover_animation, self._hover_progress, 0.0)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        scale = screen_scale(self, minimum=0.78, maximum=1.05)

        outer_padding = 10 * scale
        icon_size = int(round(72 * scale))
        icon_top = 12 * scale
        info_height = 74 * scale
        info_gap = 10 * scale
        available_width = max(0.0, self.width() - (outer_padding * 2))
        info_width = min(max(134 * scale, available_width * 0.88), available_width)

        rect = QRectF(self.rect()).adjusted(outer_padding, outer_padding, -outer_padding, -outer_padding)
        rect.translate(0, -1.2 * self._hover_progress)
        shadow_rect = rect.adjusted(0, 5 * scale, 0, 7 * scale)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(3, 8, 18, 42))
        painter.drawRoundedRect(shadow_rect, 20 * scale, 20 * scale)

        shell_top = blend_colors(QColor("#0d1524"), QColor("#13233b"), self._hover_progress * 0.55)
        shell_top = blend_colors(shell_top, QColor("#183257"), self._selected_progress)
        shell_bottom = blend_colors(QColor("#09111d"), QColor("#102036"), self._hover_progress * 0.45)
        shell_bottom = blend_colors(shell_bottom, QColor("#132b49"), self._selected_progress)
        fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        fill.setColorAt(0.0, shell_top)
        fill.setColorAt(1.0, shell_bottom)

        border = blend_colors(QColor("#1b2a42"), QColor("#40679f"), self._hover_progress * 0.55)
        border = blend_colors(border, QColor("#79b0ff"), self._selected_progress * 0.9)
        painter.setPen(QPen(border, 1.15))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 20 * scale, 20 * scale)

        icon_rect = QRectF(
            rect.center().x() - (icon_size / 2),
            rect.top() + icon_top,
            icon_size,
            icon_size,
        )

        pixmap = load_scaled_icon(self.icon_path, icon_size, icon_size)
        if not pixmap.isNull():
            pix_x = icon_rect.center().x() - pixmap.width() / 2
            pix_y = icon_rect.center().y() - pixmap.height() / 2
            painter.drawPixmap(int(pix_x), int(pix_y), pixmap)

        info_rect = QRectF(
            rect.center().x() - (info_width / 2),
            icon_rect.bottom() + info_gap,
            info_width,
            min(info_height, rect.bottom() - (icon_rect.bottom() + info_gap)),
        )
        info_top = blend_colors(QColor("#16253a"), QColor("#1d3050"), self._hover_progress * 0.45)
        info_top = blend_colors(info_top, QColor("#203a61"), self._selected_progress * 0.7)
        info_bottom = blend_colors(QColor("#0f1a2b"), QColor("#15253d"), self._hover_progress * 0.35)
        info_bottom = blend_colors(info_bottom, QColor("#173251"), self._selected_progress * 0.6)
        info_fill = QLinearGradient(info_rect.topLeft(), info_rect.bottomLeft())
        info_fill.setColorAt(0.0, info_top)
        info_fill.setColorAt(1.0, info_bottom)
        info_border = blend_colors(QColor("#2a3d5e"), QColor("#557eb7"), self._hover_progress * 0.5)
        info_border = blend_colors(info_border, QColor("#8cbcff"), self._selected_progress * 0.65)
        painter.setPen(QPen(info_border, 1.0))
        painter.setBrush(info_fill)
        painter.drawRoundedRect(info_rect, 16 * scale, 16 * scale)

        name_font = QFont(self.font())
        name_font.setPointSizeF(11.2 * scale)
        name_font.setWeight(QFont.DemiBold)
        painter.setFont(name_font)
        painter.setPen(QColor("#eef5ff"))
        name_metrics = QFontMetrics(name_font)
        version_font = QFont(self.font())
        version_font.setPointSizeF(8.8 * scale)
        version_metrics = QFontMetrics(version_font)

        text_padding_x = 14 * scale
        name_height = max(24.0 * scale, float(name_metrics.height()) + (4 * scale))
        version_height = max(16.0 * scale, float(version_metrics.height()) + (2 * scale))
        text_block_height = name_height + (4 * scale) + version_height
        text_top = info_rect.center().y() - (text_block_height / 2)
        name_rect = QRectF(
            info_rect.left() + text_padding_x,
            text_top,
            info_rect.width() - (text_padding_x * 2),
            name_height,
        )
        painter.drawText(
            name_rect,
            Qt.AlignHCenter | Qt.AlignVCenter,
            name_metrics.elidedText(self.name, Qt.ElideRight, int(name_rect.width())),
        )

        painter.setFont(version_font)
        painter.setPen(QColor("#95abd1"))
        version_rect = QRectF(
            info_rect.left() + text_padding_x,
            name_rect.bottom() + (4 * scale),
            info_rect.width() - (text_padding_x * 2),
            version_height,
        )
        painter.drawText(
            version_rect,
            Qt.AlignHCenter | Qt.AlignVCenter,
            version_metrics.elidedText(self.version, Qt.ElideRight, int(version_rect.width())),
        )

        if self._selected_progress > 0.01 or self._hover_progress > 0.04:
            glow_rect = rect.adjusted(2 * scale, 2 * scale, -2 * scale, -2 * scale)
            accent = blend_colors(
                QColor(92, 148, 222, 0),
                QColor(132, 192, 255, 58),
                max(self._selected_progress, self._hover_progress * 0.65),
            )
            painter.setPen(QPen(accent, max(1.1, 1.8 * scale)))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(glow_rect, 18 * scale, 18 * scale)
