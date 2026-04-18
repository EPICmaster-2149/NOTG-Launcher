from PySide6.QtCore import QEasingCurve, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ui.icon_utils import load_scaled_icon


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
        return QSize(188, 212)

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

        rect = QRectF(self.rect()).adjusted(7, 7, -7, -7)
        rect.translate(0, -1.1 * self._hover_progress)
        shadow_rect = rect.adjusted(0, 6, 0, 8)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(3, 8, 18, 42))
        painter.drawRoundedRect(shadow_rect, 22, 22)

        top_color = blend_colors(QColor("#121b2d"), QColor("#182844"), self._hover_progress)
        top_color = blend_colors(top_color, QColor("#1d345d"), self._selected_progress)
        bottom_color = blend_colors(QColor("#0d1524"), QColor("#132137"), self._hover_progress)
        bottom_color = blend_colors(bottom_color, QColor("#16294c"), self._selected_progress)
        fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        fill.setColorAt(0.0, top_color)
        fill.setColorAt(1.0, bottom_color)

        border = blend_colors(QColor("#23324f"), QColor("#4d7cdd"), self._selected_progress)
        border = blend_colors(border, QColor("#36598d"), self._hover_progress * 0.55)

        painter.setPen(QPen(border, 1.3))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 22, 22)

        icon_box = QRectF(rect.left() + 20, rect.top() + 18, rect.width() - 40, 88)
        icon_bg = blend_colors(QColor("#18263d"), QColor("#203558"), self._selected_progress)
        icon_bg = blend_colors(icon_bg, QColor("#22395d"), self._hover_progress * 0.4)
        painter.setPen(QPen(QColor("#2c4164"), 1.0))
        painter.setBrush(icon_bg)
        painter.drawRoundedRect(icon_box, 18, 18)

        pixmap = load_scaled_icon(self.icon_path, 70, 70)
        pix_x = icon_box.center().x() - pixmap.width() / 2
        pix_y = icon_box.center().y() - pixmap.height() / 2
        painter.drawPixmap(int(pix_x), int(pix_y), pixmap)

        name_rect = QRectF(rect.left() + 16, rect.top() + 122, rect.width() - 32, 28)
        version_rect = QRectF(rect.left() + 16, rect.top() + 150, rect.width() - 32, 20)

        name_font = QFont(self.font())
        name_font.setPointSize(12)
        name_font.setWeight(QFont.DemiBold)
        painter.setFont(name_font)
        painter.setPen(QColor("#eef5ff"))
        painter.drawText(name_rect, Qt.AlignHCenter | Qt.AlignVCenter, self.name)

        version_font = QFont(self.font())
        version_font.setPointSize(9)
        painter.setFont(version_font)
        painter.setPen(QColor("#95abd1"))
        painter.drawText(version_rect, Qt.AlignHCenter | Qt.AlignVCenter, self.version)

        if self._selected_progress > 0.02:
            glow_rect = rect.adjusted(2, 2, -2, -2)
            accent = blend_colors(QColor(61, 103, 192, 0), QColor(109, 166, 255, 56), self._selected_progress)
            painter.setPen(QPen(accent, 2.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(glow_rect, 20, 20)
