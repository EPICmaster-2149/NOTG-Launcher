from __future__ import annotations

import math
import re
import shutil
from pathlib import Path
from typing import Any, Callable
import threading
import http.server
import urllib.parse
import webbrowser
import time

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QRectF, QSize, Qt, QTimer, QUrl, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QCursor, QDesktopServices, QDragEnterEvent, QDropEvent, QFont, QImage, QMouseEvent, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QTransform
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.launcher import AccountAuthenticationError, AccountConfigurationError, AccountRecord, ElyTwoFactorRequired, LauncherService
from ui.responsive import fitted_window_size, scaled_px
from ui.theme import theme_palette
from ui.topbar import ModernButton


def _rgba(color: QColor, alpha: int | None = None) -> str:
    target = QColor(color)
    if alpha is not None:
        target.setAlpha(max(0, min(255, int(alpha))))
    return f"rgba({target.red()}, {target.green()}, {target.blue()}, {target.alpha()})"


def _hex(color: QColor) -> str:
    return QColor(color).name()


def _blend(start: QColor, end: QColor, factor: float) -> QColor:
    factor = max(0.0, min(1.0, factor))
    return QColor(
        int(start.red() + (end.red() - start.red()) * factor),
        int(start.green() + (end.green() - start.green()) * factor),
        int(start.blue() + (end.blue() - start.blue()) * factor),
        int(start.alpha() + (end.alpha() - start.alpha()) * factor),
    )


def _button_icon(symbol: str, palette: dict[str, Any], *, role: str = "accent") -> QPixmap:
    colors = palette["buttons"].get(role, palette["buttons"]["accent"])
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(colors["text"]), 2.2)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    if symbol == "plus":
        painter.drawLine(12, 5, 12, 19)
        painter.drawLine(5, 12, 19, 12)
    elif symbol == "check":
        painter.drawLine(5, 12, 10, 17)
        painter.drawLine(10, 17, 19, 7)
    elif symbol == "trash":
        painter.drawLine(8, 8, 8, 19)
        painter.drawLine(16, 8, 16, 19)
        painter.drawRoundedRect(7, 7, 10, 13, 2, 2)
        painter.drawLine(5, 7, 19, 7)
        painter.drawLine(9, 4, 15, 4)
    elif symbol == "upload":
        painter.drawLine(12, 5, 12, 17)
        painter.drawLine(7, 10, 12, 5)
        painter.drawLine(17, 10, 12, 5)
        painter.drawLine(6, 19, 18, 19)
    elif symbol == "refresh":
        painter.drawArc(5, 5, 14, 14, 40 * 16, 270 * 16)
        painter.drawLine(17, 5, 18, 10)
        painter.drawLine(17, 5, 12, 6)
    elif symbol == "download":
        painter.drawLine(12, 5, 12, 17)
        painter.drawLine(7, 12, 12, 17)
        painter.drawLine(17, 12, 12, 17)
        painter.drawLine(6, 20, 18, 20)
    painter.end()
    return pixmap


def _brand_icon(account_type: str, service: LauncherService, size: int = 36) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    if account_type == "microsoft":
        gap = max(2, size // 12)
        block = (size - gap) // 2
        colors = [QColor("#f25022"), QColor("#7fba00"), QColor("#00a4ef"), QColor("#ffb900")]
        rects = [
            QRectF(0, 0, block, block),
            QRectF(block + gap, 0, block, block),
            QRectF(0, block + gap, block, block),
            QRectF(block + gap, block + gap, block, block),
        ]
        for rect, color in zip(rects, colors):
            painter.fillRect(rect, color)
    elif account_type == "ely":
        painter.setBrush(QColor("#1f7f59"))
        painter.setPen(QPen(QColor("#14583e"), max(1, size // 14)))
        painter.drawRoundedRect(QRectF(1, 1, size - 2, size - 2), 4, 4)
        painter.setPen(QColor("#ffffff"))
        font = QFont("Segoe UI Semibold", max(9, int(size * 0.36)))
        painter.setFont(font)
        painter.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, "Ely")
    else:
        icon_path = Path(service.resolve_icon_path("assets/default-instance-icons/Grass Block.png"))
        if icon_path.is_file():
            painter.drawPixmap(0, 0, size, size, QPixmap(str(icon_path)))
        else:
            painter.setBrush(QColor("#4a9f38"))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(QRectF(0, 0, size, size), 4, 4)
    painter.end()
    return pixmap


def _set_label_font(label: QLabel, *, size: int, weight: int = QFont.Normal) -> None:
    font = QFont("Segoe UI")
    font.setPointSize(size)
    font.setWeight(weight)
    label.setFont(font)


def _valid_offline_username(value: str) -> bool:
    return re.fullmatch(r"[A-Za-z0-9_]{3,16}", value or "") is not None


def _optional_profile_link(profile: dict[str, Any]) -> str | None:
    for key in ("profileLink", "profile_link"):
        value = profile.get(key)
        if isinstance(value, str) and value.strip():
            link = value.strip()
            if link.startswith("http://"):
                return "https://" + link.removeprefix("http://")
            if link.startswith("https://"):
                return link
    nested = profile.get("user")
    if isinstance(nested, dict):
        return _optional_profile_link(nested)
    return None


def _optional_text(value: Any) -> str | None:
    if isinstance(value, (str, int)):
        text = str(value).strip()
        if text:
            return text
    return None


def _optional_ely_user_id(profile: dict[str, Any]) -> str | None:
    for key in ("ely_user_id", "elyUserId", "user_id", "userId"):
        text = _optional_text(profile.get(key))
        if text:
            return text
    for key in ("user", "account"):
        nested = profile.get(key)
        if isinstance(nested, dict):
            text = _optional_text(nested.get("id"))
            if text:
                return text
    authserver = profile.get("authserver")
    if isinstance(authserver, dict):
        user = authserver.get("user")
        if isinstance(user, dict):
            text = _optional_text(user.get("id"))
            if text:
                return text
    return None


def _optional_ely_skin_page_id(account: AccountRecord) -> str | None:
    skin = account.skin
    if skin is None:
        return None
    for value in (skin.texture_id, skin.alias):
        text = _optional_text(value)
        if text:
            return text
    url = _optional_text(skin.url)
    if url:
        path = urllib.parse.urlparse(url).path
        name = Path(path).stem
        return _optional_text(name)
    return None


class AccountAvatar(QLabel):
    def __init__(self, size: int, parent: QWidget | None = None):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.setScaledContents(False)

    def set_avatar(self, path: str | None, fallback: QPixmap | None = None) -> None:
        pixmap = QPixmap(path or "") if path else QPixmap()
        if pixmap.isNull() and fallback is not None:
            pixmap = fallback
        if pixmap.isNull():
            self.clear()
            return
        self.setPixmap(pixmap.scaled(self._size, self._size, Qt.KeepAspectRatio, Qt.SmoothTransformation))


class AccountCard(QFrame):
    selected = Signal(str)

    def __init__(self, account: AccountRecord, service: LauncherService, parent: QWidget | None = None):
        super().__init__(parent)
        self.account = account
        self.service = service
        self._active = False
        self._selected = False
        self._hover = 0.0
        self.setFixedHeight(80)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)

        self._hover_anim = QVariantAnimation(self, duration=150, easingCurve=QEasingCurve.OutCubic)
        self._hover_anim.valueChanged.connect(self._set_hover)
        self._select_anim = QVariantAnimation(self, duration=200, easingCurve=QEasingCurve.OutCubic)
        self._select_anim.valueChanged.connect(lambda _value: self.update())

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 14, 12, 14)
        layout.setSpacing(12)

        self.avatar = AccountAvatar(46)
        layout.addWidget(self.avatar)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        self.name_label = QLabel(account.username)
        self.name_label.setObjectName("accountsPrimaryText")
        self.name_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        _set_label_font(self.name_label, size=12, weight=QFont.DemiBold)
        self.type_label = QLabel(account.display_type)
        self.type_label.setObjectName("accountsSecondaryText")
        self.type_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        _set_label_font(self.type_label, size=10)
        text_col.addWidget(self.name_label)
        text_col.addWidget(self.type_label)
        layout.addLayout(text_col, 1)

        self.badge = QLabel("In Use")
        self.badge.setObjectName("accountsBadge")
        self.badge.setAlignment(Qt.AlignCenter)
        _set_label_font(self.badge, size=9, weight=QFont.DemiBold)
        self.badge.setFixedHeight(28)
        self.badge.setMinimumWidth(58)
        layout.addWidget(self.badge)

        self.refresh_theme()
        self.refresh_avatar()

    def set_active_account(self, active: bool) -> None:
        self._active = active
        self.badge.setVisible(active)
        self.update()

    def set_selected_account(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = selected
        self._select_anim.stop()
        self._select_anim.setStartValue(0.0)
        self._select_anim.setEndValue(1.0)
        self._select_anim.start()
        self.update()

    def refresh_avatar(self) -> None:
        try:
            path = self.service.account_avatar_path(self.account.account_id)
        except Exception:
            path = self.service.resolve_icon_path("assets/default-instance-icons/Grass Block.png")
        self.avatar.set_avatar(path, _brand_icon(self.account.account_type, self.service, 46))

    def refresh_theme(self) -> None:
        palette = theme_palette(self)
        roles = palette["roles"]
        self.name_label.setStyleSheet(f"color: {_hex(roles['text'])}; background: transparent;")
        self.type_label.setStyleSheet(f"color: {_hex(roles['text_muted'])}; background: transparent;")
        self.badge.setStyleSheet(
            "QLabel#accountsBadge {"
            f"background-color: {_rgba(roles['accent_soft'])};"
            f"border: 1px solid {_rgba(roles['accent_bright'], 150)};"
            f"color: {_hex(roles['text'])};"
            "border-radius: 6px;"
            "padding-left: 8px;"
            "padding-right: 8px;"
            "}"
        )

    def _set_hover(self, value: Any) -> None:
        self._hover = float(value)
        self.update()

    def enterEvent(self, event) -> None:
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.selected.emit(self.account.account_id)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        del event
        palette = theme_palette(self)
        roles = palette["roles"]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        bg = _blend(QColor(roles["card"]), QColor(roles["card_hover"]), self._hover)
        if self._selected:
            bg = _blend(bg, QColor(roles["selected"]), 0.72)
        painter.setBrush(bg)
        border = QColor(roles["outline_variant"])
        width = 1
        if self._hover > 0:
            border = _blend(border, QColor(roles["accent_bright"]), self._hover)
        if self._selected:
            border = QColor(roles["accent_bright"])
            width = 2
        painter.setPen(QPen(border, width))
        painter.drawRoundedRect(rect, 8, 8)
        painter.end()


class AccountTypeCard(QFrame):
    clicked = Signal()

    def __init__(self, title: str, subtitle: str, icon: QPixmap, parent: QWidget | None = None):
        super().__init__(parent)
        self._hover = 0.0
        self.setFixedHeight(94)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)

        self._hover_anim = QVariantAnimation(self, duration=150, easingCurve=QEasingCurve.OutCubic)
        self._hover_anim.valueChanged.connect(self._set_hover)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(22, 16, 22, 16)
        layout.setSpacing(16)
        icon_label = QLabel()
        icon_label.setFixedSize(46, 46)
        icon_label.setPixmap(icon.scaled(46, 46, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(icon_label)
        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("accountsPrimaryText")
        _set_label_font(self.title_label, size=13, weight=QFont.DemiBold)
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("accountsSecondaryText")
        _set_label_font(self.subtitle_label, size=10)
        text_col.addWidget(self.title_label)
        text_col.addWidget(self.subtitle_label)
        layout.addLayout(text_col, 1)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        roles = theme_palette(self)["roles"]
        self.title_label.setStyleSheet(f"color: {_hex(roles['text'])}; background: transparent;")
        self.subtitle_label.setStyleSheet(f"color: {_hex(roles['text_muted'])}; background: transparent;")

    def _set_hover(self, value: Any) -> None:
        self._hover = float(value)
        self.update()

    def enterEvent(self, event) -> None:
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        del event
        roles = theme_palette(self)["roles"]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setBrush(_blend(QColor(roles["card"]), QColor(roles["card_hover"]), self._hover))
        painter.setPen(QPen(_blend(QColor(roles["outline_variant"]), QColor(roles["accent_bright"]), self._hover), 1 + self._hover))
        painter.drawRoundedRect(rect, 8, 8)
        painter.end()


class ModelChoiceLabel(QLabel):
    clicked = Signal(str)

    def __init__(self, model: str, text: str, parent: QWidget | None = None):
        super().__init__(text, parent)
        self.model = model
        self.setObjectName("modelChoice")
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(86, 42)
        _set_label_font(self, size=10, weight=QFont.DemiBold)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.model)
        super().mousePressEvent(event)


class SkinPreviewWidget(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._skin = QImage()
        self._cape = QImage()
        self._model = "classic"
        self._yaw = -22.0
        self._drag_start: QPoint | None = None
        self._drag_yaw = 0.0
        self._auto_rotate = False
        self.setMinimumSize(240, 260)
        self.setCursor(Qt.OpenHandCursor)
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    def set_skin(self, path: str | None, model: str | None = None, cape_path: str | None = None) -> None:
        self._skin = QImage(path or "")
        self._cape = QImage(cape_path or "")
        self._model = model or "classic"
        self.update()

    def set_auto_rotate(self, enabled: bool) -> None:
        self._auto_rotate = enabled
        if enabled:
            self._timer.start()
        else:
            self._timer.stop()

    def is_hd_skin(self) -> bool:
        return not self._skin.isNull() and (self._skin.width() > 64 or self._skin.height() > 64)

    def skin_resolution(self) -> str:
        if self._skin.isNull():
            return "Unavailable"
        return f"{self._skin.width()}x{self._skin.height()}"

    def _tick(self) -> None:
        self._yaw = (self._yaw + 0.9) % 360
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_start = event.position().toPoint()
            self._drag_yaw = self._yaw
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_start is not None:
            delta = event.position().toPoint().x() - self._drag_start.x()
            self._yaw = (self._drag_yaw + delta * 0.8) % 360
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_start = None
        self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        del event
        palette = theme_palette(self)
        roles = palette["roles"]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setBrush(QColor(roles["surface_1"]))
        painter.setPen(QPen(QColor(roles["outline_variant"]), 1))
        painter.drawRoundedRect(rect, 8, 8)

        if self._skin.isNull():
            painter.setPen(QColor(roles["text_muted"]))
            painter.setFont(QFont("Segoe UI", 11))
            painter.drawText(rect, Qt.AlignCenter, "No skin")
            painter.end()
            return

        self._draw_player(painter, rect)
        if self.is_hd_skin():
            badge = QRectF(rect.right() - 54, rect.top() + 12, 38, 24)
            painter.setBrush(QColor(roles["accent_soft"]))
            painter.setPen(QPen(QColor(roles["accent_bright"]), 1))
            painter.drawRoundedRect(badge, 6, 6)
            painter.setPen(QColor(roles["text"]))
            painter.setFont(QFont("Segoe UI Semibold", 9))
            painter.drawText(badge, Qt.AlignCenter, "HD")
        painter.end()

    def _texture(self, x: int, y: int, width: int, height: int, *, source: QImage | None = None) -> QImage:
        skin = source if source is not None else self._skin
        if skin.isNull():
            return QImage()
        scale = max(1.0, skin.width() / 64.0)
        source = QRectF(x * scale, y * scale, width * scale, height * scale).toRect()
        return skin.copy(source)

    def _draw_player(self, painter: QPainter, rect: QRectF) -> None:
        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
        yaw = math.radians(self._yaw)
        pitch = math.radians(-8)
        scale = min(rect.width() / 28.0, rect.height() / 38.0)
        camera = 58.0
        center = QPointF(rect.center().x(), rect.top() + rect.height() * 0.53)

        def rotate(point: tuple[float, float, float]) -> tuple[float, float, float]:
            x, y, z = point
            y -= 16.0
            cos_y, sin_y = math.cos(yaw), math.sin(yaw)
            x, z = (x * cos_y + z * sin_y, -x * sin_y + z * cos_y)
            cos_p, sin_p = math.cos(pitch), math.sin(pitch)
            y, z = (y * cos_p - z * sin_p, y * sin_p + z * cos_p)
            return x, y, z

        def project(point: tuple[float, float, float]) -> QPointF:
            x, y, z = rotate(point)
            factor = camera / max(8.0, camera - z)
            return QPointF(center.x() + x * scale * factor, center.y() + y * scale * factor)

        def face_depth(points: list[tuple[float, float, float]]) -> float:
            return sum(rotate(point)[2] for point in points) / len(points)

        def draw_textured(points: list[tuple[float, float, float]], texture: QImage, shade: float = 1.0) -> None:
            if texture.isNull():
                return
            poly = QPolygonF([project(point) for point in points])
            if poly.boundingRect().width() < 1 or poly.boundingRect().height() < 1:
                return
            source = QPolygonF([
                QPointF(0, 0),
                QPointF(texture.width(), 0),
                QPointF(texture.width(), texture.height()),
                QPointF(0, texture.height()),
            ])
            transform = QTransform()
            if not QTransform.quadToQuad(source, poly, transform):
                return
            painter.save()
            clip = QPainterPath()
            clip.addPolygon(poly)
            painter.setClipPath(clip)
            painter.setTransform(transform, True)
            painter.drawImage(QRectF(0, 0, texture.width(), texture.height()), texture)
            painter.restore()
            if shade < 0.98:
                painter.save()
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(0, 0, 0, int((1.0 - shade) * 90)))
                painter.drawPolygon(poly)
                painter.restore()

        faces: list[tuple[float, list[tuple[float, float, float]], QImage, float]] = []

        def add_box(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float, uv: dict[str, tuple[int, int, int, int]], inflate: float = 0.0) -> None:
            x0i, x1i, y0i, y1i, z0i, z1i = x0 - inflate, x1 + inflate, y0 - inflate, y1 + inflate, z0 - inflate, z1 + inflate
            face_points = {
                "front": [(x0i, y0i, z1i), (x1i, y0i, z1i), (x1i, y1i, z1i), (x0i, y1i, z1i)],
                "back": [(x1i, y0i, z0i), (x0i, y0i, z0i), (x0i, y1i, z0i), (x1i, y1i, z0i)],
                "left": [(x0i, y0i, z0i), (x0i, y0i, z1i), (x0i, y1i, z1i), (x0i, y1i, z0i)],
                "right": [(x1i, y0i, z1i), (x1i, y0i, z0i), (x1i, y1i, z0i), (x1i, y1i, z1i)],
                "top": [(x0i, y0i, z0i), (x1i, y0i, z0i), (x1i, y0i, z1i), (x0i, y0i, z1i)],
                "bottom": [(x0i, y1i, z1i), (x1i, y1i, z1i), (x1i, y1i, z0i), (x0i, y1i, z0i)],
            }
            shades = {"front": 1.0, "right": 0.82, "left": 0.74, "back": 0.62, "top": 1.08, "bottom": 0.58}
            for name, points in face_points.items():
                if name not in uv:
                    continue
                rotated = [rotate(point) for point in points]
                p0, p1, p2 = rotated[0], rotated[1], rotated[2]
                ax, ay, az = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
                bx, by, bz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
                normal_z = ax * by - ay * bx
                if normal_z <= -0.01:
                    continue
                x, y, w, h = uv[name]
                faces.append((face_depth(points), points, self._texture(x, y, w, h), shades[name]))

        arm_w = 3.0 if self._model == "slim" else 4.0
        add_box(-4, 4, 0, 8, -4, 4, {"front": (8, 8, 8, 8), "back": (24, 8, 8, 8), "left": (0, 8, 8, 8), "right": (16, 8, 8, 8), "top": (8, 0, 8, 8), "bottom": (16, 0, 8, 8)})
        add_box(-4, 4, 8, 20, -2, 2, {"front": (20, 20, 8, 12), "back": (32, 20, 8, 12), "left": (16, 20, 4, 12), "right": (28, 20, 4, 12), "top": (20, 16, 8, 4), "bottom": (28, 16, 8, 4)})
        add_box(-4 - arm_w, -4, 8, 20, -2, 2, {"front": (36, 52, 4, 12), "back": (44, 52, 4, 12), "left": (32, 52, 4, 12), "right": (40, 52, 4, 12), "top": (36, 48, 4, 4), "bottom": (40, 48, 4, 4)})
        add_box(4, 4 + arm_w, 8, 20, -2, 2, {"front": (44, 20, 4, 12), "back": (52, 20, 4, 12), "left": (40, 20, 4, 12), "right": (48, 20, 4, 12), "top": (44, 16, 4, 4), "bottom": (48, 16, 4, 4)})
        add_box(-4, 0, 20, 32, -2, 2, {"front": (4, 20, 4, 12), "back": (12, 20, 4, 12), "left": (0, 20, 4, 12), "right": (8, 20, 4, 12), "top": (4, 16, 4, 4), "bottom": (8, 16, 4, 4)})
        add_box(0, 4, 20, 32, -2, 2, {"front": (20, 52, 4, 12), "back": (28, 52, 4, 12), "left": (16, 52, 4, 12), "right": (24, 52, 4, 12), "top": (20, 48, 4, 4), "bottom": (24, 48, 4, 4)})

        if self._skin.height() >= 64:
            add_box(-4, 4, 0, 8, -4, 4, {"front": (40, 8, 8, 8), "back": (56, 8, 8, 8), "left": (32, 8, 8, 8), "right": (48, 8, 8, 8), "top": (40, 0, 8, 8), "bottom": (48, 0, 8, 8)}, 0.35)
            add_box(-4, 4, 8, 20, -2, 2, {"front": (20, 36, 8, 12), "back": (32, 36, 8, 12), "left": (16, 36, 4, 12), "right": (28, 36, 4, 12), "top": (20, 32, 8, 4), "bottom": (28, 32, 8, 4)}, 0.25)

        if not self._cape.isNull():
            cape = self._texture(0, 0, min(10, self._cape.width()), min(16, self._cape.height()), source=self._cape)
            faces.append((face_depth([(-5, 9, -2.7), (5, 9, -2.7), (5, 25, -3.8), (-5, 25, -3.8)]), [(-5, 9, -2.7), (5, 9, -2.7), (5, 25, -3.8), (-5, 25, -3.8)], cape, 0.92))

        for _depth, points, texture, shade in sorted(faces, key=lambda item: item[0]):
            draw_textured(points, texture, shade)


class OAuthLoginDialog(QDialog):
    account_added = Signal()
    _device_poll_finished = Signal(object, object)
    _oauth_finished = Signal(object, object)

    def __init__(self, service: LauncherService, account_type: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.service = service
        self.account_type = account_type
        self._login_data: dict[str, str] = {}
        self._finished = False
        self._local_server: http.server.HTTPServer | None = None
        self._local_server_timer = QTimer(self)
        self._local_server_timer.setInterval(300)
        self._local_server_timer.timeout.connect(lambda: self._check_local_callback())
        self._device_poll_timer = QTimer(self)
        self._device_poll_timer.timeout.connect(self._poll_microsoft_device_login)
        self._device_poll_inflight = False
        self._device_poll_finished.connect(self._handle_microsoft_device_poll_result)
        self._oauth_finished.connect(self._handle_oauth_finished)

        title = "Microsoft Login"
        self.setObjectName("accountsDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(fitted_window_size(parent or self, 860, 680, minimum_width=720, minimum_height=560))

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        root.setSpacing(14)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("accountsTitle")
        _set_label_font(self.title_label, size=18, weight=QFont.DemiBold)
        root.addWidget(self.title_label)

        self.status = QLabel("Preparing secure sign-in...")
        self.status.setObjectName("accountsSubtitle")
        self.status.setWordWrap(True)
        _set_label_font(self.status, size=10)
        root.addWidget(self.status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        root.addWidget(self.progress)

        self.web_container = QFrame()
        self.web_container.setObjectName("accountPanel")
        self.web_layout = QVBoxLayout(self.web_container)
        self.web_layout.setContentsMargins(1, 1, 1, 1)
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings

            class AuthWebPage(QWebEnginePage):
                def javaScriptAlert(page_self, security_origin: QUrl, msg: str) -> None:  # noqa: N805
                    del page_self, security_origin
                    self._handle_provider_alert(msg)

            self.web_view = QWebEngineView()
            self.web_view.setPage(AuthWebPage(self.web_view))
            self._tune_embedded_browser(self.web_view, QWebEngineSettings)
            self.web_view.urlChanged.connect(self._handle_url_changed)
            self.web_view.loadStarted.connect(lambda: self._set_status("Loading sign-in page..."))
            self.web_view.loadFinished.connect(self._handle_load_finished)
            self.web_layout.addWidget(self.web_view)
        except Exception as exc:  # noqa: BLE001
            self.web_view = None
            fallback = QLabel(f"Embedded browser is unavailable: {exc}")
            fallback.setAlignment(Qt.AlignCenter)
            fallback.setWordWrap(True)
            self.web_layout.addWidget(fallback)
        root.addWidget(self.web_container, 1)

        footer = QHBoxLayout()
        footer.addStretch()
        self.cancel_button = ModernButton("Cancel", role="sidebar", height=40, icon_size=0)
        self.cancel_button.clicked.connect(self.reject)
        footer.addWidget(self.cancel_button)
        root.addLayout(footer)

        self._apply_theme()
        QTimer.singleShot(0, self._begin)

    def _apply_theme(self) -> None:
        roles = theme_palette(self)["roles"]
        self.setStyleSheet(
            f"""
            QDialog#accountsDialog {{
                background-color: {_hex(roles['background'])};
            }}
            QLabel#accountsTitle {{ color: {_hex(roles['text'])}; background: transparent; }}
            QLabel#accountsSubtitle {{ color: {_hex(roles['text_muted'])}; background: transparent; }}
            QFrame#accountPanel {{
                background-color: transparent;
                border: 1px solid {_rgba(roles['outline_variant'])};
                border-radius: 8px;
            }}
            QProgressBar {{
                background-color: {_rgba(roles['surface_1'], 220)};
                border: 1px solid {_rgba(roles['outline_variant'])};
                border-radius: 5px;
                min-height: 8px;
                max-height: 8px;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background-color: {_rgba(roles['accent_bright'])};
                border-radius: 5px;
            }}
            """
        )

    def _set_status(self, message: str) -> None:
        self.status.setText(message)

    def _tune_embedded_browser(self, web_view: QWidget, settings_cls: object) -> None:
        try:
            settings = web_view.settings()  # type: ignore[attr-defined]
        except Exception:
            return
        for name in ("PluginsEnabled", "PdfViewerEnabled", "WebGLEnabled", "Accelerated2dCanvasEnabled"):
            attr = getattr(getattr(settings_cls, "WebAttribute", settings_cls), name, None)
            if attr is None:
                attr = getattr(settings_cls, name, None)
            if attr is None:
                continue
            try:
                settings.setAttribute(attr, False)
            except Exception:
                pass
        try:
            web_view.setZoomFactor(0.96)  # type: ignore[attr-defined]
        except Exception:
            pass

    def reject(self) -> None:
        self._stop_local_http_server()
        self._device_poll_timer.stop()
        super().reject()

    def _begin(self) -> None:
        self._begin_browser_login("microsoft")

    def _begin_browser_login(self, account_type: str) -> None:
        try:
            self._login_data = self._build_login_data(account_type)
        except (AccountConfigurationError, AccountAuthenticationError, ValueError) as exc:
            self._fail(str(exc))
            return
        self._set_status("Complete the sign-in. NOTG will store the session so you do not need to log in repeatedly.")
        url = self._login_data.get("url", "")

        if self.web_view is not None:
            self.web_view.load(QUrl(url))
            return

        if self._local_server is not None:
            try:
                webbrowser.open(url)
            except Exception:
                pass
            self._set_status("Waiting for browser sign-in to complete...")
            return

        self._fail(
            "Embedded browser is unavailable and the configured redirect URI cannot be captured automatically. "
            "Configure a loopback redirect URI such as http://localhost for this provider."
        )

    def _begin_microsoft_device_login(self) -> None:
        try:
            self._login_data = self.service.begin_microsoft_device_login()
        except (AccountConfigurationError, AccountAuthenticationError, ValueError) as exc:
            self._fail(str(exc))
            return
        user_code = self._login_data.get("user_code", "")
        self._set_status(
            "Open microsoft.com/link in your browser, enter the code, and NOTG will finish automatically."
        )
        interval_ms = max(3, int(self._login_data.get("interval", "5") or 5)) * 1000
        self._device_poll_timer.setInterval(interval_ms)
        self._device_poll_timer.start()
        self._render_microsoft_device_panel()

    def _render_microsoft_device_panel(self) -> None:
        if self.web_view is not None:
            self.web_view.hide()
        panel = QFrame()
        panel.setObjectName("accountPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(18)

        prompt = QLabel("Sign in with Microsoft")
        prompt.setObjectName("accountsPrimaryText")
        prompt.setAlignment(Qt.AlignCenter)
        _set_label_font(prompt, size=14, weight=QFont.DemiBold)
        layout.addWidget(prompt)

        url_label = QLabel("Open https://www.microsoft.com/link")
        url_label.setObjectName("accountsSubtitle")
        url_label.setAlignment(Qt.AlignCenter)
        _set_label_font(url_label, size=10)
        layout.addWidget(url_label)

        code_label = QLabel(self._login_data.get("user_code", ""))
        code_label.setObjectName("accountsTitle")
        code_label.setAlignment(Qt.AlignCenter)
        code_font = QFont("Consolas")
        code_font.setPointSize(30)
        code_font.setWeight(QFont.DemiBold)
        code_font.setLetterSpacing(QFont.AbsoluteSpacing, 4)
        code_label.setFont(code_font)
        code_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(code_label)

        button_row = QHBoxLayout()
        button_row.addStretch()
        copy_button = ModernButton("Copy Code", role="sidebar", height=40, icon_size=0, minimum_width=118)
        copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self._login_data.get("user_code", "")))
        button_row.addWidget(copy_button)
        open_button = ModernButton("Open Link", role="accent", height=40, icon_size=0, minimum_width=118)
        open_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self._login_data.get("verification_uri", "https://www.microsoft.com/link"))))
        button_row.addWidget(open_button)
        button_row.addStretch()
        layout.addLayout(button_row)

        detail = QLabel("After approval, keep this window open while NOTG retrieves your Minecraft profile.")
        detail.setObjectName("accountsSubtitle")
        detail.setAlignment(Qt.AlignCenter)
        detail.setWordWrap(True)
        _set_label_font(detail, size=10)
        layout.addWidget(detail)
        layout.addStretch()

        self.web_layout.addWidget(panel)

    def _poll_microsoft_device_login(self) -> None:
        if self._finished or self._device_poll_inflight:
            return
        device_code = self._login_data.get("device_code", "")
        if not device_code:
            self._fail("Microsoft device sign-in could not start because no device code was returned.")
            return
        self._device_poll_inflight = True

        def worker() -> None:
            try:
                account = self.service.complete_microsoft_device_login(device_code)
            except Exception as exc:  # noqa: BLE001
                self._device_poll_finished.emit(None, exc)
                return
            self._device_poll_finished.emit(account, None)

        threading.Thread(target=worker, daemon=True).start()

    def _handle_microsoft_device_poll_result(self, account: object, error: object) -> None:
        self._device_poll_inflight = False
        if self._finished:
            return
        if error is not None:
            message = str(error)
            if message == "authorization_pending":
                return
            if message == "slow_down":
                self._device_poll_timer.setInterval(self._device_poll_timer.interval() + 5000)
                return
            self._device_poll_timer.stop()
            self._fail(message)
            return
        if account is None:
            return
        self._finished = True
        self._device_poll_timer.stop()
        try:
            self.service.generate_account_avatar(account.account_id, refresh=True)
        except Exception:
            pass
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self._set_status("Signed in successfully.")
        self.account_added.emit()
        QTimer.singleShot(500, self.accept)

    def _inject_microsoft_device_code(self) -> None:
        if self.web_view is None or self._login_data.get("flow") != "device":
            return
        code = self._login_data.get("user_code", "")
        if not code:
            return
        script = """
        (() => {
          const code = %r;
          const candidates = Array.from(document.querySelectorAll('input'));
          const input = candidates.find(el => {
            const name = (el.name || '').toLowerCase();
            const id = (el.id || '').toLowerCase();
            const type = (el.type || '').toLowerCase();
            return type !== 'hidden' && (name.includes('otc') || name.includes('code') || id.includes('otc') || id.includes('code') || candidates.length === 1);
          });
          if (!input) return false;
          input.focus();
          input.value = code;
          input.dispatchEvent(new Event('input', { bubbles: true }));
          input.dispatchEvent(new Event('change', { bubbles: true }));
          const buttons = Array.from(document.querySelectorAll('button,input[type=submit]'));
          const next = buttons.find(el => !el.disabled && /next|submit|continue|verify/i.test(el.innerText || el.value || '')) || buttons.find(el => !el.disabled);
          if (next) next.click();
          return true;
        })();
        """ % code
        try:
            self.web_view.page().runJavaScript(script)
        except Exception:
            pass

    def _build_login_data(self, account_type: str, redirect_uri: str | None = None) -> dict[str, str]:
        redirect_uri = redirect_uri or self.service.oauth_redirect_uri(account_type)
        if self._is_loopback_redirect(redirect_uri):
            server = self._start_local_http_server(redirect_uri)
            if server is None:
                raise AccountAuthenticationError(
                    f"Could not start a local callback listener for {redirect_uri}. "
                    "Check whether another app is using the configured port."
                )
            self._local_server = server
            self._local_server_timer.start()
            redirect_uri = str(getattr(server, "redirect_uri", redirect_uri))
        if account_type == "microsoft":
            return self.service.begin_microsoft_login(redirect_uri=redirect_uri)
        raise ValueError(f"Unsupported browser login type: {account_type}")

    def _is_loopback_redirect(self, redirect_uri: str) -> bool:
        parsed = urllib.parse.urlparse(redirect_uri)
        host = (parsed.hostname or "").lower()
        return parsed.scheme == "http" and host in {"localhost", "127.0.0.1"}

    def _handle_load_finished(self, ok: bool) -> None:
        if self._finished:
            return
        if self._login_data.get("flow") == "device":
            if ok:
                self._set_status(
                    "Complete Microsoft sign-in. NOTG will approve the device code automatically when the page allows it."
                )
                QTimer.singleShot(450, self._inject_microsoft_device_code)
            else:
                self._set_status("The Microsoft sign-in page could not finish loading. Check your network and try again.")
            return
        if ok:
            self._set_status("Waiting for authentication approval...")
            # Inspect the loaded page HTML for common provider-block messages
            try:
                if self.web_view is not None and getattr(self.web_view, "page", None):
                    self.web_view.page().toHtml(self._inspect_html_for_errors)
            except Exception:
                pass
        else:
            self._set_status("The sign-in page could not finish loading. Check your network and try again.")

    def _handle_url_changed(self, url: QUrl) -> None:
        if self._finished:
            return
        if self._login_data.get("flow") == "device":
            return
        text = url.toString()
        if "code=" not in text and "error=" not in text:
            return
        self._finished = True
        self.progress.setRange(0, 0)
        self._set_status("Completing authentication and retrieving profile...")
        QApplication.processEvents()
        self._complete_oauth_in_background(text)

    def _handle_external_callback(self, text: str) -> None:
        if self._finished:
            return
        if "code=" not in text and "error=" not in text:
            self._fail("No authorization code or provider error was found in the callback URL.")
            return
        self._finished = True
        self.progress.setRange(0, 0)
        self._set_status("Completing authentication and retrieving profile...")
        QApplication.processEvents()
        self._complete_oauth_in_background(text)

    def _complete_oauth_in_background(self, text: str) -> None:
        def worker() -> None:
            try:
                account = self.service.complete_microsoft_login(
                    text,
                    self._login_data.get("state", ""),
                    self._login_data.get("code_verifier", ""),
                    self._login_data.get("redirect_uri", ""),
                )
                try:
                    self.service.generate_account_avatar(account.account_id, refresh=True)
                except Exception:
                    pass
            except Exception as exc:  # noqa: BLE001
                self._oauth_finished.emit(None, exc)
                return
            self._oauth_finished.emit(account, None)

        threading.Thread(target=worker, daemon=True).start()

    def _handle_oauth_finished(self, account: object, error: object) -> None:
        if error is not None:
            self._fail(str(error))
            return
        if account is None:
            self._fail("Authentication completed but no account was returned.")
            return
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self._set_status("Signed in successfully.")
        self.account_added.emit()
        QTimer.singleShot(500, self.accept)

    def _inspect_html_for_errors(self, html: str) -> None:
        if self._finished:
            return
        if not html:
            return
        lowered = html.lower()
        # Known fragments that indicate the provider blocked embedded webviews or app registration issues
        error_signals = [
            "you have reached a page that is not normally shown",
            "invalid app registration",
            "this app is not allowed to sign in",
            "not normally shown",
        ]
        for sig in error_signals:
            if sig in lowered:
                self._trigger_fallback()
                return

    def _handle_provider_alert(self, message: str) -> None:
        text = (message or "").strip()
        if not text:
            return
        self._fail(text)

    def _trigger_fallback(self) -> None:
        if self._finished:
            return
        self._set_status("Embedded browser blocked; opening browser and capturing the callback automatically...")
        if self._local_server is None:
            try:
                fallback_redirect = self.service.oauth_redirect_uri(self.account_type)
                if not self._is_loopback_redirect(fallback_redirect):
                    fallback_redirect = "http://localhost"
                self._login_data = self._build_login_data(self.account_type, fallback_redirect)
            except Exception as exc:  # noqa: BLE001
                self._fail(f"Could not prepare automatic browser callback: {exc}")
                return
        try:
            webbrowser.open(self._login_data.get("url", ""))
        except Exception:
            pass
        self._set_status("Waiting for browser sign-in to complete...")

    def _start_local_http_callback(self, redirect_uri: str, timeout: int = 60) -> str | None:
        # Deprecated blocking helper. Use _start_local_http_server instead.
        server = self._start_local_http_server(redirect_uri)
        if not server:
            return None
        # Wait briefly for the callback (short blocking wait) to support callers
        # that expect an immediate response (rare). Prefer the non-blocking
        # polling via QTimer implemented elsewhere.
        start = time.time()
        try:
            while time.time() - start < timeout:
                if getattr(server, "callback_url", None):
                    callback = server.callback_url
                    try:
                        server.shutdown()
                        server.server_close()
                    except Exception:
                        pass
                    return callback
                time.sleep(0.1)
        finally:
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass
        return None

    def _start_local_http_server(self, redirect_uri: str) -> http.server.HTTPServer | None:
        parsed = urllib.parse.urlparse(redirect_uri)
        host = parsed.hostname or "localhost"
        port = parsed.port or 0
        scheme = parsed.scheme
        base_path = parsed.path or ""

        class _CallbackHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self_inner) -> None:
                try:
                    self_inner.send_response(200)
                    self_inner.send_header("Content-Type", "text/html; charset=utf-8")
                    self_inner.end_headers()
                    self_inner.wfile.write(
                        b"<html><body><h2>Sign-in complete</h2><p>You may close this window and return to the launcher.</p></body></html>"
                    )
                    actual_redirect = getattr(self_inner.server, "redirect_uri", f"{scheme}://{host}")
                    parsed_actual = urllib.parse.urlparse(actual_redirect)
                    self_inner.server.callback_url = f"{parsed_actual.scheme}://{parsed_actual.netloc}{self_inner.path}"
                finally:
                    # Do not shutdown here; let the owner stop the server after handling
                    pass

            def log_message(self_inner, *_: Any) -> None:  # silence logging
                return

        try:
            server = http.server.HTTPServer((host, port), _CallbackHandler)
        except Exception:
            return None

        server.callback_url = None
        actual_netloc = f"{host}:{server.server_port}" if server.server_port else host
        server.redirect_uri = urllib.parse.urlunparse((scheme, actual_netloc, base_path, "", "", ""))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server

    def _stop_local_http_server(self) -> None:
        try:
            if self._local_server is not None:
                try:
                    self._local_server.shutdown()
                except Exception:
                    pass
                try:
                    self._local_server.server_close()
                except Exception:
                    pass
                self._local_server = None
        except Exception:
            pass

    def _check_local_callback(self) -> None:
        if self._local_server is None:
            return
        callback = getattr(self._local_server, "callback_url", None)
        if callback:
            self._local_server_timer.stop()
            try:
                self._handle_external_callback(callback)
            finally:
                self._stop_local_http_server()

    def _fail(self, message: str) -> None:
        self._finished = False
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self._set_status(message)
        QMessageBox.warning(self, self.windowTitle(), message)


class ElyLoginDialog(QDialog):
    account_added = Signal()
    _login_finished = Signal(object, object)

    def __init__(self, service: LauncherService, parent: QWidget | None = None):
        super().__init__(parent)
        self.service = service
        self._login_finished.connect(self._handle_login_finished)
        self.setObjectName("accountsDialog")
        self.setWindowTitle("Ely.by Login")
        self.setModal(True)
        self.resize(fitted_window_size(parent or self, 420, 400, minimum_width=380, minimum_height=350))

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 26, 28, 24)
        root.setSpacing(14)

        title = QLabel("Ely.by Login")
        title.setObjectName("accountsTitle")
        _set_label_font(title, size=19, weight=QFont.DemiBold)
        root.addWidget(title)

        self.username_input = QLineEdit()
        self.username_input.setObjectName("accountsInput")
        self.username_input.setPlaceholderText("Email or username")
        self.username_input.setMinimumHeight(44)
        root.addWidget(self.username_input)

        self.password_input = QLineEdit()
        self.password_input.setObjectName("accountsInput")
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setMinimumHeight(44)
        root.addWidget(self.password_input)

        self.totp_input = QLineEdit()
        self.totp_input.setObjectName("accountsInput")
        self.totp_input.setPlaceholderText("Two-factor code")
        self.totp_input.setInputMethodHints(Qt.ImhDigitsOnly)
        self.totp_input.setMinimumHeight(44)
        self.totp_input.setVisible(False)
        root.addWidget(self.totp_input)

        self.login_button = ModernButton("Log In", role="accent", height=46, icon_size=0)
        self.login_button.clicked.connect(self._submit)
        root.addWidget(self.login_button)
        root.addStretch()

        footer = QHBoxLayout()
        self.signup_button = ModernButton("Sign Up", role="sidebar", height=40, icon_size=0)
        self.signup_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://account.ely.by/register")))
        footer.addWidget(self.signup_button)
        footer.addStretch()
        cancel_button = ModernButton("Cancel", role="sidebar", height=40, icon_size=0)
        cancel_button.clicked.connect(self.reject)
        footer.addWidget(cancel_button)
        root.addLayout(footer)

        self.username_input.returnPressed.connect(self._submit)
        self.password_input.returnPressed.connect(self._submit)
        self.totp_input.returnPressed.connect(self._submit)
        self._apply_theme()
        self.username_input.setFocus()

    def _apply_theme(self) -> None:
        roles = theme_palette(self)["roles"]
        line_edit = theme_palette(self)["line_edit"]
        self.setStyleSheet(
            f"""
            QDialog#accountsDialog {{
                background-color: {_hex(roles['background'])};
            }}
            QLabel#accountsTitle {{
                color: {_hex(roles['text'])};
                background: transparent;
            }}
            QLineEdit#accountsInput {{
                background-color: {_rgba(line_edit['background'])};
                border: 1px solid {_rgba(line_edit['border'])};
                border-radius: 8px;
                padding-left: 12px;
                padding-right: 12px;
                color: {_hex(roles['text'])};
            }}
            QLineEdit#accountsInput:focus {{
                border-color: {_rgba(line_edit['border_focus'])};
            }}
            """
        )

    def _submit(self) -> None:
        username = self.username_input.text().strip()
        password = self.password_input.text()
        if not username or not password:
            self.login_button.flash_invalid()
            return
        self.login_button.setEnabled(False)
        self.login_button.setText("Logging In...")
        totp = self.totp_input.text().strip() if self.totp_input.isVisible() else None

        def worker() -> None:
            try:
                account = self.service.authenticate_ely_account(username, password, totp)
                try:
                    self.service.generate_account_avatar(account.account_id, refresh=True)
                except Exception:
                    pass
            except Exception as exc:  # noqa: BLE001
                self._login_finished.emit(None, exc)
                return
            self._login_finished.emit(account, None)

        threading.Thread(target=worker, daemon=True).start()

    def _handle_login_finished(self, account: object, error: object) -> None:
        self.login_button.setEnabled(True)
        self.login_button.setText("Log In")
        if isinstance(error, ElyTwoFactorRequired):
            self.totp_input.setVisible(True)
            self.totp_input.setFocus()
            return
        if error is not None:
            QMessageBox.warning(self, self.windowTitle(), str(error))
            return
        if account is None:
            QMessageBox.warning(self, self.windowTitle(), "Ely.by did not return an account.")
            return
        self.account_added.emit()
        self.accept()


class AddAccountDialog(QDialog):
    account_added = Signal()

    def __init__(self, service: LauncherService, parent: QWidget | None = None):
        super().__init__(parent)
        self.service = service
        self.setObjectName("accountsDialog")
        self.setWindowTitle("Add Account")
        self.setModal(True)
        self.setMinimumSize(680, 540)
        self.resize(fitted_window_size(parent or self, 760, 600, minimum_width=680, minimum_height=540))
        self.setWindowOpacity(0.0)

        self._open_anim = QVariantAnimation(self, duration=200, easingCurve=QEasingCurve.OutCubic)
        self._open_anim.valueChanged.connect(lambda value: self.setWindowOpacity(float(value)))

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 30, 32, 28)
        root.setSpacing(16)

        title = QLabel("Add Account")
        title.setObjectName("accountsTitle")
        _set_label_font(title, size=26, weight=QFont.DemiBold)
        root.addWidget(title)

        subtitle = QLabel("Choose an account type to add to NOTG Launcher")
        subtitle.setObjectName("accountsSubtitle")
        _set_label_font(subtitle, size=10)
        root.addWidget(subtitle)

        offline = QFrame()
        offline.setObjectName("accountPanel")
        offline.setMinimumHeight(132)
        offline_layout = QVBoxLayout(offline)
        offline_layout.setContentsMargins(20, 18, 20, 16)
        offline_layout.setSpacing(12)
        label = QLabel("Offline Account")
        label.setObjectName("accountsPrimaryText")
        _set_label_font(label, size=13, weight=QFont.DemiBold)
        offline_layout.addWidget(label)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.username_input = QLineEdit()
        self.username_input.setObjectName("accountsInput")
        self.username_input.setPlaceholderText("Enter username")
        self.username_input.setMinimumHeight(46)
        self.username_input.textChanged.connect(self._validate_username)
        self.username_input.returnPressed.connect(self._add_offline)
        row.addWidget(self.username_input, 1)
        self.add_button = ModernButton("Add", role="accent", height=44, icon_size=0, minimum_width=96)
        self.add_button.clicked.connect(self._add_offline)
        self.add_button.setEnabled(False)
        row.addWidget(self.add_button)
        offline_layout.addLayout(row)
        self.validation_label = QLabel("3-16 characters: A-Z, 0-9, underscore")
        self.validation_label.setObjectName("accountsSubtitle")
        _set_label_font(self.validation_label, size=9)
        offline_layout.addWidget(self.validation_label)
        root.addWidget(offline)

        divider = QHBoxLayout()
        left = QFrame()
        left.setObjectName("accountDivider")
        right = QFrame()
        right.setObjectName("accountDivider")
        or_label = QLabel("OR")
        or_label.setObjectName("accountsSubtitle")
        or_label.setAlignment(Qt.AlignCenter)
        _set_label_font(or_label, size=9, weight=QFont.DemiBold)
        divider.addWidget(left, 1)
        divider.addWidget(or_label)
        divider.addWidget(right, 1)
        root.addLayout(divider)

        self.microsoft_card = AccountTypeCard(
            "Microsoft Account",
            "Sign in with Microsoft",
            _brand_icon("microsoft", service, 46),
        )
        self.microsoft_card.clicked.connect(lambda: self._open_oauth("microsoft"))
        root.addWidget(self.microsoft_card)

        self.ely_card = AccountTypeCard(
            "Ely.by Account",
            "Sign in with Ely.by",
            _brand_icon("ely", service, 46),
        )
        self.ely_card.clicked.connect(self._open_ely_login)
        root.addWidget(self.ely_card)
        root.addStretch()

        self._apply_theme()

    def showEvent(self, event) -> None:
        self._open_anim.stop()
        self._open_anim.setStartValue(0.0)
        self._open_anim.setEndValue(1.0)
        self._open_anim.start()
        super().showEvent(event)

    def _apply_theme(self) -> None:
        roles = theme_palette(self)["roles"]
        self.setStyleSheet(
            f"""
            QDialog#accountsDialog {{
                background-color: {_hex(roles['background'])};
            }}
            QLabel#accountsTitle, QLabel#accountsPrimaryText {{ color: {_hex(roles['text'])}; background: transparent; }}
            QLabel#accountsSubtitle {{ color: {_hex(roles['text_muted'])}; background: transparent; }}
            QFrame#accountPanel {{
                background-color: transparent;
                border: 1px solid {_rgba(roles['outline_variant'])};
                border-radius: 8px;
            }}
            QFrame#accountDivider {{
                background-color: {_rgba(roles['separator'])};
                border: none;
                min-height: 1px;
                max-height: 1px;
            }}
            QLineEdit#accountsInput {{
                background-color: {_rgba(theme_palette(self)['line_edit']['background'])};
                border: 1px solid {_rgba(theme_palette(self)['line_edit']['border'])};
                border-radius: 8px;
                min-height: 38px;
                padding-left: 12px;
                padding-right: 12px;
                color: {_hex(roles['text'])};
            }}
            QLineEdit#accountsInput:focus {{
                border: 1px solid {_rgba(theme_palette(self)['line_edit']['border_focus'])};
            }}
            """
        )
        self.microsoft_card.refresh_theme()
        self.ely_card.refresh_theme()

    def _validate_username(self, value: str) -> None:
        valid = _valid_offline_username(value.strip())
        self.add_button.setEnabled(valid)
        roles = theme_palette(self)["roles"]
        if not value:
            self.validation_label.setText("3-16 characters: A-Z, 0-9, underscore")
            color = roles["text_muted"]
        elif valid:
            self.validation_label.setText("Username is valid")
            color = roles["success"]
        else:
            self.validation_label.setText("Use 3-16 characters: A-Z, 0-9, underscore")
            color = roles["danger"]
        self.validation_label.setStyleSheet(f"color: {_hex(color)}; background: transparent;")

    def _add_offline(self) -> None:
        username = self.username_input.text().strip()
        if not _valid_offline_username(username):
            self.add_button.flash_invalid()
            return
        try:
            account = self.service.add_offline_account(username)
            self.service.generate_account_avatar(account.account_id, refresh=True)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Add Account", str(exc))
            return
        self.account_added.emit()
        self.accept()

    def _open_oauth(self, account_type: str) -> None:
        dialog = OAuthLoginDialog(self.service, account_type, self)
        dialog.account_added.connect(self.account_added)
        if dialog.exec() == QDialog.Accepted:
            self.accept()

    def _open_ely_login(self) -> None:
        dialog = ElyLoginDialog(self.service, self)
        dialog.account_added.connect(self.account_added)
        if dialog.exec() == QDialog.Accepted:
            self.accept()

class SkinManagerDialog(QDialog):
    skin_changed = Signal()

    def __init__(self, service: LauncherService, account: AccountRecord, parent: QWidget | None = None):
        super().__init__(parent)
        self.service = service
        self.account = account
        self.setObjectName("accountsDialog")
        self.setWindowTitle("Manage Skin")
        self.setModal(True)
        self.resize(fitted_window_size(parent or self, 760, 580, minimum_width=680, minimum_height=520))
        self.setAcceptDrops(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 22)
        root.setSpacing(16)

        title = QLabel("Manage Skin")
        title.setObjectName("accountsTitle")
        _set_label_font(title, size=20, weight=QFont.DemiBold)
        root.addWidget(title)

        self.preview = SkinPreviewWidget()
        root.addWidget(self.preview, 1)

        self.status = QLabel("")
        self.status.setObjectName("accountsSubtitle")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        palette = theme_palette(self)
        self.upload_button = ModernButton("Upload", icon=_button_icon("upload", palette), role="accent", height=42)
        self.refresh_button = ModernButton("Refresh", icon=_button_icon("refresh", palette), role="sidebar", height=42)
        self.download_button = ModernButton("Download", icon=_button_icon("download", palette), role="sidebar", height=42)
        self.remove_button = ModernButton("Remove", icon=_button_icon("trash", palette, role="danger"), role="danger", height=42)
        self.close_button = ModernButton("Close", role="sidebar", height=42, icon_size=0)
        self.upload_button.clicked.connect(self._upload)
        self.refresh_button.clicked.connect(self._refresh)
        self.download_button.clicked.connect(self._download)
        self.remove_button.clicked.connect(self._remove)
        self.close_button.clicked.connect(self.accept)
        actions.addWidget(self.upload_button)
        actions.addWidget(self.refresh_button)
        actions.addWidget(self.download_button)
        actions.addWidget(self.remove_button)
        actions.addStretch()
        actions.addWidget(self.close_button)
        root.addLayout(actions)

        self._apply_theme()
        self._reload()

    def _apply_theme(self) -> None:
        roles = theme_palette(self)["roles"]
        self.setStyleSheet(
            f"""
            QDialog#accountsDialog {{
                background-color: {_hex(roles['background'])};
            }}
            QLabel#accountsTitle {{ color: {_hex(roles['text'])}; background: transparent; }}
            QLabel#accountsSubtitle {{ color: {_hex(roles['text_muted'])}; background: transparent; }}
            """
        )

    def _reload(self) -> None:
        self.account = self.service.get_account_by_id(self.account.account_id) or self.account
        skin_path = self._skin_path()
        self.preview.set_skin(skin_path, self.account.skin.model if self.account.skin else None)
        has_skin = bool(skin_path)
        offline = self.account.account_type == "offline"
        microsoft = self.account.account_type == "microsoft"
        self.upload_button.setEnabled(offline or microsoft)
        self.remove_button.setEnabled((offline or microsoft) and has_skin)
        self.download_button.setEnabled(has_skin)
        if offline:
            self.status.setText("Drop a PNG skin here or use Upload.")
        elif microsoft:
            self.status.setText("Upload sends the PNG skin to Minecraft services. Refresh syncs the official profile.")
        elif self.account.account_type == "ely":
            self.status.setText("Refresh downloads your current Ely.by website skin. Ely.by does not document launcher-side skin or cape upload APIs.")
        else:
            self.status.setText("Online account skins can be refreshed and downloaded from the account provider.")

    def _skin_path(self) -> str | None:
        try:
            return self.service.cache_account_skin_texture(self.account.account_id)
        except Exception as exc:  # noqa: BLE001
            self.status.setText(str(exc))
            return None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self.account.account_type == "offline" and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if self.account.account_type != "offline":
            return
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_file():
                self._set_offline_skin(path)
                break

    def _set_offline_skin(self, path: Path) -> None:
        try:
            self.account = self.service.set_offline_account_skin(self.account.account_id, path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Manage Skin", str(exc))
            return
        self.status.setText("Skin updated.")
        self.skin_changed.emit()
        self._reload()

    def _upload(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Upload Skin", "", "PNG Images (*.png)")
        if not path:
            return
        if self.account.account_type == "offline":
            self._set_offline_skin(Path(path))
            return
        if self.account.account_type == "microsoft":
            try:
                model = self.account.skin.model if self.account.skin else None
                self.account = self.service.upload_microsoft_account_skin(self.account.account_id, Path(path), model)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, "Upload Skin", str(exc))
                return
            self.status.setText("Skin uploaded.")
            self.skin_changed.emit()
            self._reload()
            return
        self.upload_button.flash_invalid()

    def _refresh(self) -> None:
        try:
            if self.account.account_type != "offline":
                self.account = self.service.refresh_account_profile(self.account.account_id)
                self.service.cache_account_skin_texture(self.account.account_id, refresh=True)
            self.service.generate_account_avatar(self.account.account_id, refresh=True)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Refresh Skin", str(exc))
            return
        self.status.setText("Skin refreshed.")
        self.skin_changed.emit()
        self._reload()

    def _download(self) -> None:
        skin_path = self._skin_path()
        if not skin_path:
            self.download_button.flash_invalid()
            return
        target, _ = QFileDialog.getSaveFileName(self, "Download Skin", f"{self.account.username}.png", "PNG Images (*.png)")
        if not target:
            return
        try:
            shutil.copy2(skin_path, target)
        except OSError as exc:
            QMessageBox.warning(self, "Download Skin", str(exc))
            return
        self.status.setText("Skin downloaded.")

    def _remove(self) -> None:
        if self.account.account_type not in {"offline", "microsoft"}:
            self.remove_button.flash_invalid()
            return
        target = "local skin" if self.account.account_type == "offline" else "official skin"
        answer = QMessageBox.question(self, "Remove Skin", f"Remove the {target} for {self.account.username}?")
        if answer != QMessageBox.Yes:
            return
        try:
            if self.account.account_type == "offline":
                self.account = self.service.remove_offline_account_skin(self.account.account_id)
            else:
                self.account = self.service.remove_microsoft_account_skin(self.account.account_id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Remove Skin", str(exc))
            return
        self.status.setText("Skin removed.")
        self.skin_changed.emit()
        self._reload()


class AccountsDialog(QDialog):
    accounts_changed = Signal()
    _ely_appearance_synced = Signal()

    def __init__(self, service: LauncherService, parent: QWidget | None = None):
        super().__init__(parent)
        self.service = service
        self._selected_account_id: str | None = None
        self._cards: dict[str, AccountCard] = {}
        self._ely_appearance_syncing_accounts: set[str] = set()
        self._ely_appearance_synced_accounts: set[str] = set()
        self._ely_appearance_synced.connect(self._handle_accounts_changed)
        self._fade_anim = QVariantAnimation(self, duration=200, easingCurve=QEasingCurve.OutCubic)
        self._fade_anim.valueChanged.connect(lambda value: self.right_panel.setWindowOpacity(float(value)))

        self.setObjectName("accountsDialog")
        self.setWindowTitle("Manage Accounts")
        self.setModal(True)
        self.setMinimumSize(900, 620)
        self.resize(fitted_window_size(parent or self, 1180, 760, minimum_width=900, minimum_height=620))

        self._build_ui()
        self._apply_theme()
        self.refresh()

    def showEvent(self, event) -> None:
        self._apply_theme()
        super().showEvent(event)

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(0)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setObjectName("accountSplitter")
        self.splitter.setChildrenCollapsible(False)
        root.addWidget(self.splitter)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("accountSidebar")
        self.sidebar.setMinimumWidth(350)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(18, 18, 18, 18)
        sidebar_layout.setSpacing(16)

        title_row = QHBoxLayout()
        title = QLabel("Accounts")
        title.setObjectName("accountsTitle")
        _set_label_font(title, size=15, weight=QFont.DemiBold)
        title_row.addWidget(title)
        title_row.addStretch()
        self.add_button = ModernButton(
            "Add Account",
            icon=_button_icon("plus", theme_palette(self)),
            role="accent",
            height=40,
            icon_size=20,
            minimum_width=142,
        )
        self.add_button.clicked.connect(self._open_add_account)
        title_row.addWidget(self.add_button)
        sidebar_layout.addLayout(title_row)

        self.account_scroll = QScrollArea()
        self.account_scroll.setObjectName("accountScroll")
        self.account_scroll.viewport().setObjectName("accountScrollViewport")
        self.account_scroll.setWidgetResizable(True)
        self.account_scroll.setFrameShape(QFrame.NoFrame)
        self.account_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.account_container = QWidget()
        self.account_container.setObjectName("accountListBody")
        self.account_list = QVBoxLayout(self.account_container)
        self.account_list.setContentsMargins(0, 0, 0, 0)
        self.account_list.setSpacing(12)
        self.account_list.addStretch()
        self.account_scroll.setWidget(self.account_container)
        sidebar_layout.addWidget(self.account_scroll, 1)

        self.right_panel = QFrame()
        self.right_panel.setObjectName("accountContent")
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self.header = QFrame()
        self.header.setObjectName("accountHeader")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(26, 24, 26, 24)
        header_layout.setSpacing(18)
        self.header_avatar = AccountAvatar(70)
        header_layout.addWidget(self.header_avatar)
        header_text = QVBoxLayout()
        header_text.setSpacing(6)
        self.header_name = QLabel("")
        self.header_name.setObjectName("accountHeaderName")
        _set_label_font(self.header_name, size=19, weight=QFont.DemiBold)
        self.header_type = QLabel("")
        self.header_type.setObjectName("accountsSubtitle")
        _set_label_font(self.header_type, size=11)
        header_text.addWidget(self.header_name)
        header_text.addWidget(self.header_type)
        header_layout.addLayout(header_text, 1)
        self.use_button = ModernButton(
            "Use Account",
            icon=_button_icon("check", theme_palette(self)),
            role="accent",
            height=44,
            icon_size=20,
            minimum_width=150,
        )
        self.use_button.clicked.connect(self._use_selected)
        header_layout.addWidget(self.use_button)
        self.remove_button = ModernButton(
            "Remove Account",
            icon=_button_icon("trash", theme_palette(self), role="danger"),
            role="danger",
            height=44,
            icon_size=20,
            minimum_width=170,
        )
        self.remove_button.clicked.connect(self._remove_selected)
        header_layout.addWidget(self.remove_button)
        right_layout.addWidget(self.header)

        self.detail_tabs = QTabWidget()
        self.detail_tabs.setObjectName("accountTabs")

        self.overview_scroll = QScrollArea()
        self.overview_scroll.setObjectName("accountScroll")
        self.overview_scroll.viewport().setObjectName("accountScrollViewport")
        self.overview_scroll.setWidgetResizable(True)
        self.overview_scroll.setFrameShape(QFrame.NoFrame)
        self.overview_body = QWidget()
        self.overview_body.setObjectName("accountBody")
        overview_layout = QVBoxLayout(self.overview_body)
        overview_layout.setContentsMargins(18, 18, 18, 18)
        overview_layout.setSpacing(12)

        self.profile_panel = self._panel("Profile Information")
        self.profile_grid = QGridLayout()
        self.profile_grid.setContentsMargins(0, 2, 0, 0)
        self.profile_grid.setHorizontalSpacing(22)
        self.profile_grid.setVerticalSpacing(10)
        self.profile_panel.layout().addLayout(self.profile_grid)
        overview_layout.addWidget(self.profile_panel)
        overview_layout.addStretch()
        self.overview_scroll.setWidget(self.overview_body)
        self.detail_tabs.addTab(self.overview_scroll, "Profile")

        self.cosmetics_scroll = QScrollArea()
        self.cosmetics_scroll.setObjectName("accountScroll")
        self.cosmetics_scroll.viewport().setObjectName("accountScrollViewport")
        self.cosmetics_scroll.setWidgetResizable(True)
        self.cosmetics_scroll.setFrameShape(QFrame.NoFrame)
        self.cosmetics_body = QWidget()
        self.cosmetics_body.setObjectName("accountBody")
        cosmetics_layout = QVBoxLayout(self.cosmetics_body)
        cosmetics_layout.setContentsMargins(18, 18, 18, 18)
        cosmetics_layout.setSpacing(12)

        self.skin_panel = self._panel("Skin")
        skin_panel_layout = self.skin_panel.layout()
        skin_header_row = QHBoxLayout()
        skin_header_row.addStretch()
        self.manage_skin_button = ModernButton("Manage Skin", role="accent", height=42, icon_size=0, minimum_width=134)
        self.manage_skin_button.clicked.connect(self._open_skin_manager)
        skin_header_row.addWidget(self.manage_skin_button)
        self.open_ely_button = ModernButton("Open Ely.by", role="sidebar", height=42, icon_size=0, minimum_width=134)
        self.open_ely_button.clicked.connect(self._open_ely_browser)
        skin_header_row.addWidget(self.open_ely_button)
        skin_panel_layout.addLayout(skin_header_row)

        skin_row = QHBoxLayout()
        skin_row.setSpacing(22)
        self.skin_preview = SkinPreviewWidget()
        self.skin_preview.setMinimumSize(260, 220)
        skin_row.addWidget(self.skin_preview, 2)
        info_col = QVBoxLayout()
        info_col.setSpacing(12)
        self.skin_name = QLabel("Current Skin")
        self.skin_name.setObjectName("accountsPrimaryText")
        _set_label_font(self.skin_name, size=12, weight=QFont.DemiBold)
        self.skin_resolution = QLabel("")
        self.skin_resolution.setObjectName("accountsSubtitle")
        self.skin_model = QLabel("")
        self.skin_model.setObjectName("accountsSubtitle")
        self.auto_rotate = QCheckBox("Auto rotate")
        self.auto_rotate.stateChanged.connect(lambda state: self.skin_preview.set_auto_rotate(state == Qt.Checked.value))
        model_label = QLabel("Model Type")
        model_label.setObjectName("accountsSubtitle")
        self.model_classic = ModelChoiceLabel("classic", "Classic")
        self.model_slim = ModelChoiceLabel("slim", "Slim")
        self.model_classic.clicked.connect(self._set_skin_model)
        self.model_slim.clicked.connect(self._set_skin_model)
        model_row = QHBoxLayout()
        model_row.setSpacing(10)
        model_row.addWidget(self.model_classic)
        model_row.addWidget(self.model_slim)
        info_col.addWidget(self.skin_name)
        info_col.addWidget(self.skin_resolution)
        info_col.addWidget(self.skin_model)
        info_col.addSpacing(4)
        info_col.addWidget(model_label)
        info_col.addLayout(model_row)
        info_col.addSpacing(8)
        info_col.addWidget(self.auto_rotate)
        info_col.addStretch()
        skin_row.addLayout(info_col, 1)
        skin_panel_layout.addLayout(skin_row)
        cosmetics_layout.addWidget(self.skin_panel)

        self.cape_panel = self._panel("Cape")
        cape_layout = self.cape_panel.layout()
        cape_header_row = QHBoxLayout()
        cape_header_row.addStretch()
        self.upload_cape_button = ModernButton("Upload Cape", role="accent", height=40, icon_size=0, minimum_width=128)
        self.remove_cape_button = ModernButton("Remove Cape", role="danger", height=40, icon_size=0, minimum_width=128)
        self.refresh_cape_button = ModernButton("Refresh Cape", role="sidebar", height=40, icon_size=0, minimum_width=128)
        self.upload_cape_button.clicked.connect(self._upload_cape)
        self.remove_cape_button.clicked.connect(self._remove_cape)
        self.refresh_cape_button.clicked.connect(self._refresh_cape)
        cape_header_row.addWidget(self.upload_cape_button)
        cape_header_row.addWidget(self.remove_cape_button)
        cape_header_row.addWidget(self.refresh_cape_button)
        cape_layout.addLayout(cape_header_row)
        cape_row = QHBoxLayout()
        cape_row.setSpacing(24)
        self.cape_preview = QLabel("No cape")
        self.cape_preview.setObjectName("capePreview")
        self.cape_preview.setAlignment(Qt.AlignCenter)
        self.cape_preview.setMinimumSize(160, 110)
        cape_row.addWidget(self.cape_preview)
        cape_info = QVBoxLayout()
        cape_info.setSpacing(10)
        self.cape_status = QLabel("")
        self.cape_status.setObjectName("accountsSubtitle")
        self.cape_type = QLabel("")
        self.cape_type.setObjectName("accountsSubtitle")
        cape_info.addWidget(self.cape_status)
        cape_info.addWidget(self.cape_type)
        cape_info.addStretch()
        cape_row.addLayout(cape_info, 1)
        cape_layout.addLayout(cape_row)
        cosmetics_layout.addWidget(self.cape_panel)
        cosmetics_layout.addStretch()
        self.cosmetics_scroll.setWidget(self.cosmetics_body)

        self.detail_tabs.addTab(self.cosmetics_scroll, "Skin & Cape")

        right_layout.addWidget(self.detail_tabs, 1)

        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.right_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setSizes([360, 860])

    def _panel(self, title: str) -> QFrame:
        panel = QFrame()
        panel.setObjectName("accountPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(14)
        label = QLabel(title)
        label.setObjectName("accountsSectionTitle")
        _set_label_font(label, size=13, weight=QFont.DemiBold)
        layout.addWidget(label)
        return panel

    def _apply_theme(self) -> None:
        palette = theme_palette(self)
        roles = palette["roles"]
        line_edit = palette["line_edit"]
        self.setStyleSheet(
            f"""
            QDialog#accountsDialog {{
                background-color: {_rgba(roles['surface_1'], 238)};
            }}
            QWidget#accountBody, QWidget#accountListBody {{
                background-color: {_rgba(roles['surface_1'], 214)};
            }}
            QSplitter#accountSplitter {{
                background-color: {_rgba(roles['surface_1'], 188)};
            }}
            QSplitter#accountSplitter::handle {{
                background-color: {_rgba(roles['outline_variant'], 118)};
            }}
            QFrame#accountSidebar, QFrame#accountContent {{
                background-color: {_rgba(roles['surface_1'], 224)};
                border: 1px solid {_rgba(roles['outline_variant'])};
                border-radius: 8px;
            }}
            QFrame#accountHeader {{
                background-color: transparent;
                border-bottom: 1px solid {_rgba(roles['separator'])};
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }}
            QFrame#accountPanel {{
                background-color: transparent;
                border: 1px solid {_rgba(roles['outline_variant'])};
                border-radius: 8px;
            }}
            QTabWidget#accountTabs::pane {{
                border: none;
                background: transparent;
            }}
            QTabBar::tab {{
                color: {_hex(roles['text_muted'])};
                background-color: {_rgba(roles['surface_1'], 190)};
                border: 1px solid {_rgba(roles['outline_variant'])};
                border-bottom: none;
                padding: 9px 18px;
                margin-right: 6px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }}
            QTabBar::tab:selected {{
                color: {_hex(roles['text'])};
                background-color: {_rgba(roles['accent_soft'])};
                border-color: {_rgba(roles['accent_bright'], 170)};
            }}
            QScrollArea#accountScroll {{
                background-color: {_rgba(roles['surface_1'], 214)};
                border: none;
            }}
            QWidget#accountScrollViewport {{
                background-color: {_rgba(roles['surface_1'], 214)};
            }}
            QLabel#accountsTitle, QLabel#accountHeaderName, QLabel#accountsSectionTitle, QLabel#accountsPrimaryText {{
                color: {_hex(roles['text'])};
                background: transparent;
            }}
            QLabel#accountsSubtitle {{
                color: {_hex(roles['text_muted'])};
                background: transparent;
            }}
            QLabel#profileKey {{
                color: {_hex(roles['text_muted'])};
                background: transparent;
            }}
            QLabel#profileValue {{
                color: {_hex(roles['text'])};
                background: transparent;
            }}
            QLabel#modelChoice {{
                color: {_hex(roles['text'])};
                background-color: {_rgba(roles['surface_1'], 214)};
                border: 1px solid {_rgba(roles['outline_variant'])};
                border-radius: 8px;
            }}
            QLabel#modelChoice[selected="true"] {{
                background-color: {_rgba(roles['accent_soft'])};
                border: 2px solid {_rgba(roles['accent_bright'])};
            }}
            QLabel#capePreview {{
                color: {_hex(roles['text_muted'])};
                background-color: {_rgba(roles['surface_1'], 214)};
                border: 1px solid {_rgba(roles['outline_variant'])};
                border-radius: 8px;
            }}
            QLineEdit#accountsInput {{
                background-color: {_rgba(line_edit['background'])};
                border: 1px solid {_rgba(line_edit['border'])};
                border-radius: 8px;
                min-height: 38px;
                padding-left: 12px;
                padding-right: 12px;
                color: {_hex(roles['text'])};
            }}
            QLineEdit#accountsInput:focus {{
                border: 1px solid {_rgba(line_edit['border_focus'])};
            }}
            QCheckBox {{
                color: {_hex(roles['text_muted'])};
                spacing: 8px;
            }}
            QSplitter::handle {{
                background-color: {_rgba(roles['separator'])};
                width: 4px;
            }}
            """
        )
        for card in self._cards.values():
            card.refresh_theme()

    def refresh(self) -> None:
        accounts = self.service.list_account_records()
        active = self.service.get_active_account().account_id
        if self._selected_account_id not in {account.account_id for account in accounts}:
            self._selected_account_id = active if active else (accounts[0].account_id if accounts else None)
        self._rebuild_cards(accounts, active)
        self._render_selected()

    def _rebuild_cards(self, accounts: list[AccountRecord], active_id: str) -> None:
        while self.account_list.count() > 1:
            item = self.account_list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._cards.clear()
        for account in accounts:
            card = AccountCard(account, self.service)
            card.selected.connect(self._select_account)
            card.set_active_account(account.account_id == active_id)
            card.set_selected_account(account.account_id == self._selected_account_id)
            self.account_list.insertWidget(self.account_list.count() - 1, card)
            self._cards[account.account_id] = card

    def _select_account(self, account_id: str) -> None:
        self._selected_account_id = account_id
        for card_id, card in self._cards.items():
            card.set_selected_account(card_id == account_id)
        self._render_selected()

    def _selected_account(self) -> AccountRecord | None:
        if not self._selected_account_id:
            return None
        return self.service.get_account_by_id(self._selected_account_id)

    def _render_selected(self) -> None:
        account = self._selected_account()
        if account is None:
            return
        active_id = self.service.get_active_account().account_id
        self.header_name.setText(account.username)
        self.header_type.setText(account.display_type)
        try:
            avatar = self.service.account_avatar_path(account.account_id)
        except Exception:
            avatar = self.service.resolve_icon_path("assets/default-instance-icons/Grass Block.png")
        self.header_avatar.set_avatar(avatar, _brand_icon(account.account_type, self.service, 70))
        self.use_button.setEnabled(account.account_id != active_id)
        self.remove_button.setEnabled(True)
        self._render_profile(account)
    def _render_profile(self, account: AccountRecord) -> None:
        while self.profile_grid.count():
            item = self.profile_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        rows: list[tuple[str, str]] = [
            ("Username", account.username),
            ("Account Type", account.display_type),
            ("Authentication Status", "Offline" if account.account_type == "offline" else "Session stored"),
        ]
        skin_model = (account.skin.model if account.skin else None) or "classic"
        rows.extend(
            [
                ("Skin Type", skin_model.title()),
                ("Cape Status", "Available" if account.cape and (account.cape.url or account.cape.local_path) else "None"),
            ]
        )
        if account.uuid:
            rows.append(("UUID", account.uuid))
        if account.email and account.account_type != "offline":
            rows.append(("Email", account.email))
        for row, (key, value) in enumerate(rows):
            key_label = QLabel(key)
            key_label.setObjectName("profileKey")
            value_label = QLabel(value)
            value_label.setObjectName("profileValue")
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            _set_label_font(key_label, size=10)
            _set_label_font(value_label, size=10)
            self.profile_grid.addWidget(key_label, row, 0)
            self.profile_grid.addWidget(value_label, row, 1)
        self._apply_theme()

    def _render_skin(self, account: AccountRecord) -> None:
        skin_path = None
        skin_error = ""
        try:
            skin_path = self.service.cache_account_skin_texture(account.account_id)
        except Exception as exc:  # noqa: BLE001
            skin_error = str(exc)
        cape_path = None
        try:
            cape_path = self.service.cache_account_cape_texture(account.account_id)
        except Exception:
            cape_path = None
        has_skin = bool(skin_path)
        self.skin_preview.set_skin(skin_path, account.skin.model if account.skin else None, cape_path)
        model = (account.skin.model if account.skin else None) or "classic"
        self.model_classic.setProperty("selected", model == "classic")
        self.model_slim.setProperty("selected", model == "slim")
        self.model_classic.style().unpolish(self.model_classic)
        self.model_classic.style().polish(self.model_classic)
        self.model_slim.style().unpolish(self.model_slim)
        self.model_slim.style().polish(self.model_slim)
        if has_skin:
            self.skin_name.setText("Current Skin")
            self.skin_resolution.setText(f"Resolution: {self.skin_preview.skin_resolution()}")
            self.skin_model.setText(f"Model Type: {model.title()}")
        else:
            self.skin_name.setText("Current Skin")
            self.skin_resolution.setText(skin_error or "No skin available")
            self.skin_model.setText("")
        self.manage_skin_button.setEnabled(True)
        self.open_ely_button.setVisible(account.account_type == "ely")

    def _render_cape(self, account: AccountRecord) -> None:
        cape_path = None
        cape_error = ""
        try:
            cape_path = self.service.cache_account_cape_texture(account.account_id)
        except Exception as exc:  # noqa: BLE001
            cape_error = str(exc)
        offline = account.account_type == "offline"
        self.upload_cape_button.setEnabled(offline)
        self.remove_cape_button.setEnabled(offline and bool(cape_path))
        self.refresh_cape_button.setEnabled(account.account_type != "offline")
        if cape_path:
            pixmap = QPixmap(cape_path)
            if not pixmap.isNull():
                self.cape_preview.setPixmap(pixmap.scaled(120, 96, Qt.KeepAspectRatio, Qt.FastTransformation))
            self.cape_status.setText("Cape Status: Available")
            cape_type = (account.cape.source if account.cape else account.account_type) or account.account_type
            self.cape_type.setText(f"Cape Type: {cape_type.title()}")
        else:
            self.cape_preview.setPixmap(QPixmap())
            self.cape_preview.setText("No cape")
            self.cape_status.setText(f"Cape Status: {cape_error or 'None'}")
            self.cape_type.setText(f"Cape Type: {account.display_type}")

    def _set_skin_model(self, model: str) -> None:
        account = self._selected_account()
        if account is None:
            return
        try:
            self.service.set_account_skin_model(account.account_id, model)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Skin Model", str(exc))
            return
        self._render_selected()

    def _upload_cape(self) -> None:
        account = self._selected_account()
        if account is None or account.account_type != "offline":
            self.upload_cape_button.flash_invalid()
            return
        path, _ = QFileDialog.getOpenFileName(self, "Upload Cape", "", "PNG Images (*.png)")
        if not path:
            return
        try:
            self.service.set_offline_account_cape(account.account_id, Path(path))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Upload Cape", str(exc))
            return
        self._handle_accounts_changed()

    def _remove_cape(self) -> None:
        account = self._selected_account()
        if account is None or account.account_type != "offline":
            self.remove_cape_button.flash_invalid()
            return
        answer = QMessageBox.question(self, "Remove Cape", f"Remove the local cape for {account.username}?")
        if answer != QMessageBox.Yes:
            return
        try:
            self.service.remove_offline_account_cape(account.account_id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Remove Cape", str(exc))
            return
        self._handle_accounts_changed()

    def _refresh_cape(self) -> None:
        account = self._selected_account()
        if account is None:
            return
        try:
            if account.account_type != "offline":
                self.service.refresh_account_profile(account.account_id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Refresh Cape", str(exc))
            return
        self._handle_accounts_changed()

    def _open_add_account(self) -> None:
        dialog = AddAccountDialog(self.service, self)
        dialog.account_added.connect(self._handle_accounts_changed)
        dialog.exec()

    def _open_skin_manager(self) -> None:
        account = self._selected_account()
        if account is None:
            return
        dialog = SkinManagerDialog(self.service, account, self)
        dialog.skin_changed.connect(self._handle_accounts_changed)
        dialog.exec()

    def _open_ely_browser(self) -> None:
        QDesktopServices.openUrl(QUrl("https://ely.by/"))

    def _handle_accounts_changed(self) -> None:
        self.accounts_changed.emit()
        self.refresh()

    def _use_selected(self) -> None:
        account = self._selected_account()
        if account is None:
            self.use_button.flash_invalid()
            return
        try:
            self.service.set_active_account(account.account_id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Use Account", str(exc))
            return
        self.accounts_changed.emit()
        self.refresh()

    def _remove_selected(self) -> None:
        account = self._selected_account()
        if account is None:
            self.remove_button.flash_invalid()
            return
        answer = QMessageBox.question(self, "Remove Account", f"Remove {account.username} from NOTG Launcher?")
        if answer != QMessageBox.Yes:
            return
        try:
            self.service.delete_account(account.account_id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Remove Account", str(exc))
            return
        self._selected_account_id = self.service.get_active_account().account_id
        self.accounts_changed.emit()
        self.refresh()
