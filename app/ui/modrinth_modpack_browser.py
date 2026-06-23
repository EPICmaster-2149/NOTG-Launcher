from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Any

import requests
from PySide6.QtCore import (
    QEasingCurve,
    QRectF,
    QSize,
    QThread,
    QPoint,
    QTimer,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.launcher import LauncherService
from ui.responsive import fitted_window_size

# ---------------------------------------------------------------------------
# Modrinth-inspired colour palette (fully self-contained)
# ---------------------------------------------------------------------------

class Mr:
    """Modrinth colour tokens – no dependency on launcher theme."""

    # Backgrounds
    BG = QColor("#0d1117")
    BG_PANEL = QColor("#141920")
    BG_CARD = QColor("#161b22")
    BG_CARD_HOVER = QColor("#1c2333")
    BG_CARD_ACTIVE = QColor("#21283a")
    BG_SURFACE = QColor("#1a1f2e")
    BG_ELEVATED = QColor("#21262d")
    BG_INPUT = QColor("#0d1117")
    BG_MODAL = QColor("#0d1117")

    # Accent – Modrinth green
    GREEN = QColor("#1bd96a")
    GREEN_BRIGHT = QColor("#2eeb7a")
    GREEN_DIM = QColor("#17b559")
    GREEN_GLOW = QColor(27, 217, 106, 42)
    GREEN_SOFT = QColor(27, 217, 106, 22)

    # Text
    TEXT = QColor("#f0f6fc")
    TEXT_MUTED = QColor("#8b949e")
    TEXT_SUBTLE = QColor("#6e7681")

    # Borders
    BORDER = QColor(48, 54, 61, 180)
    BORDER_LIGHT = QColor(48, 54, 61, 100)
    SEPARATOR = QColor(48, 54, 61, 80)

    # Status
    DANGER = QColor("#f85149")
    WARNING = QColor("#d29922")
    SUCCESS = QColor("#3fb950")

    # Badge colours per loader
    FABRIC = QColor("#dbd0b4")
    FORGE = QColor("#d4a574")
    NEOFORGE = QColor("#c084fc")
    QUILT = QColor("#c77dff")

    @classmethod
    def with_alpha(cls, color: QColor, alpha: int) -> QColor:
        c = QColor(color)
        c.setAlpha(max(0, min(255, alpha)))
        return c

    @classmethod
    def blend(cls, a: QColor, b: QColor, t: float) -> QColor:
        t = max(0.0, min(1.0, t))
        return QColor(
            int(a.red() + (b.red() - a.red()) * t),
            int(a.green() + (b.green() - a.green()) * t),
            int(a.blue() + (b.blue() - a.blue()) * t),
            int(a.alpha() + (b.alpha() - a.alpha()) * t),
        )


def _mr_css(c: QColor) -> str:
    """Convert QColor to CSS rgba string."""
    return f"rgba({c.red()},{c.green()},{c.blue()},{c.alpha()})"


# Spinner animation (braille dots)
_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧")

# ---------------------------------------------------------------------------
# Typography & Sizing Constants
# ---------------------------------------------------------------------------

_ICON_SIZE = 44
_LARGE_ICON_SIZE = 80
_CARD_HEIGHT = 96
_PAGE_SIZE = 30

# Font sizes (px)
_TITLE_PX = 22       # modpack name in detail
_HERO_PX = 16        # card title
_SECTION_PX = 15     # section headings
_PRIMARY_PX = 13     # primary info
_META_PX = 12        # metadata / badge text
_SMALL_PX = 11       # small text
_CHIP_PX = 12        # filter chip text

# Badge sizing (tall, generous)
_BADGE_H = 28
_BADGE_PAD_H = 16
_BADGE_RADIUS = 14

# Category chip sizing
_CAT_BADGE_H = 26
_CAT_BADGE_PAD_H = 14
_CAT_BADGE_RADIUS = 13

# Filter chip
_CHIP_H = 32
_CHIP_PAD_H = 16
_CHIP_RADIUS = 8

# Version row height
_VERSION_ROW_H = 82

# Card corner radius
_CARD_RADIUS = 10

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ICON_CACHE: dict[str, bytes] = {}


def _project_key(project: dict[str, Any]) -> str:
    value = str(project.get("project_id") or project.get("slug") or project.get("title") or "modpack")
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _load_icon_bytes(url: str, cache_dir: Path) -> bytes | None:
    cached = _ICON_CACHE.get(url)
    if cached:
        return cached
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    path = cache_dir / f"{digest}.img"
    if path.is_file():
        try:
            data = path.read_bytes()
        except OSError:
            data = b""
        if data:
            _ICON_CACHE[url] = data
            return data
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": "NOTG-Launcher/Modrinth-Modpacks",
                "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*,*/*;q=0.8",
            },
            timeout=12,
        )
    except requests.RequestException:
        return None
    if not resp.ok or not resp.content:
        return None
    data = resp.content[:1_500_000]
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError:
        pass
    _ICON_CACHE[url] = data
    return data


def _format_count(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _date_relative(date_str: str) -> str:
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return date_str
    now = datetime.now(timezone.utc)
    diff = now - dt
    if diff.days > 365:
        years = diff.days // 365
        return f"{years}y ago"
    if diff.days > 30:
        months = diff.days // 30
        return f"{months}mo ago"
    if diff.days > 0:
        return f"{diff.days}d ago"
    if diff.seconds >= 3600:
        return f"{diff.seconds // 3600}h ago"
    if diff.seconds >= 60:
        return f"{diff.seconds // 60}m ago"
    return "Just now"


def _draw_chip(
    p: QPainter,
    text: str,
    rect: QRectF,
    border_color: QColor,
    bg_color: QColor,
    text_color: QColor,
    radius: float = _BADGE_RADIUS,
) -> None:
    """Draw a capsule-style chip/badge with fully rounded ends."""
    p.setPen(QPen(border_color, 1.2))
    p.setBrush(bg_color)
    p.drawRoundedRect(rect, radius, radius)
    p.setPen(text_color)
    p.drawText(rect, Qt.AlignCenter, text)


def _loader_badge(loader: str) -> tuple[QColor, QColor, QColor]:
    lc = loader.lower()
    if "fabric" in lc:
        base = Mr.FABRIC
    elif "forge" in lc:
        base = Mr.FORGE
    elif "neoforge" in lc or "neo" in lc:
        base = Mr.NEOFORGE
    elif "quilt" in lc:
        base = Mr.QUILT
    else:
        base = Mr.TEXT_MUTED
    bg = Mr.with_alpha(base, 24)
    return base, bg, base


def _channel_badge(version_type: str) -> tuple[QColor, QColor, QColor]:
    vt = version_type.lower()
    if vt == "release":
        c = Mr.GREEN
    elif vt == "beta":
        c = Mr.WARNING
    elif vt == "alpha":
        c = Mr.DANGER
    else:
        c = Mr.TEXT_MUTED
    bg = Mr.with_alpha(c, 22)
    return c, bg, c


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------

class ModrinthSearchWorker(QThread):
    loaded = Signal(list)
    failed = Signal(str)

    def __init__(self, service: LauncherService, query: str, limit: int = _PAGE_SIZE, offset: int = 0, parent: QWidget | None = None):
        super().__init__(parent)
        self._service = service
        self._query = query
        self._limit = limit
        self._offset = offset

    def run(self) -> None:
        try:
            payload = self._service.search_modrinth_modpacks(self._query, self._limit, self._offset)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        if not self.isInterruptionRequested():
            self.loaded.emit(list(payload) if isinstance(payload, list) else [])


class ModrinthDetailsWorker(QThread):
    loaded = Signal(dict)
    failed = Signal(str)

    def __init__(self, service: LauncherService, project_id: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._service = service
        self._project_id = project_id

    def run(self) -> None:
        try:
            payload = self._service.get_modrinth_modpack_details(self._project_id)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        if not self.isInterruptionRequested():
            self.loaded.emit(payload if isinstance(payload, dict) else {})


class ModrinthVersionsWorker(QThread):
    loaded = Signal(list)
    failed = Signal(str)

    def __init__(self, service: LauncherService, project_id: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._service = service
        self._project_id = project_id

    def run(self) -> None:
        try:
            payload = self._service.get_modrinth_modpack_versions(self._project_id)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        if not self.isInterruptionRequested():
            self.loaded.emit(list(payload) if isinstance(payload, list) else [])


class ModrinthDownloadWorker(QThread):
    loaded = Signal(str)
    failed = Signal(str)

    def __init__(self, service: LauncherService, version: dict[str, Any], parent: QWidget | None = None):
        super().__init__(parent)
        self._service = service
        self._version = version

    def run(self) -> None:
        try:
            path = self._service.download_modrinth_modpack_version(self._version)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        if not self.isInterruptionRequested():
            self.loaded.emit(str(path))


class IconLoadWorker(QThread):
    icon_loaded = Signal(str, object)

    def __init__(self, targets: list[tuple[str, str]], cache_dir: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self._targets = list(targets)
        self._cache_dir = cache_dir

    def run(self) -> None:
        for key, url in self._targets:
            if self.isInterruptionRequested():
                return
            data = _load_icon_bytes(url, self._cache_dir)
            if data:
                self.icon_loaded.emit(key, data)


# ---------------------------------------------------------------------------
# ModpackCard – Left panel listing (Modrinth-style)
# ---------------------------------------------------------------------------

class ModpackCard(QWidget):
    clicked = Signal(str)

    def __init__(self, project: dict[str, Any], parent: QWidget | None = None):
        super().__init__(parent)
        self._project = dict(project)
        self._project_id = str(project.get("project_id") or project.get("slug") or "")
        self._hover = 0.0
        self._selected = 0.0
        self._icon_pixmap: QPixmap | None = None
        self.setObjectName("modpackCard")
        self.setFixedHeight(_CARD_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)

        self._hover_anim = QVariantAnimation(self, duration=150, easingCurve=QEasingCurve.OutCubic, valueChanged=self._set_hover)
        self._select_anim = QVariantAnimation(self, duration=180, easingCurve=QEasingCurve.OutCubic, valueChanged=self._set_select)

    def _set_hover(self, v: float) -> None:
        self._hover = float(v)
        self.update()

    def _set_select(self, v: float) -> None:
        self._selected = float(v)
        self.update()

    def set_selected(self, selected: bool) -> None:
        self._select_anim.stop()
        self._select_anim.setStartValue(self._selected)
        self._select_anim.setEndValue(1.0 if selected else 0.0)
        self._select_anim.start()

    def set_icon_data(self, data: bytes) -> None:
        pix = QPixmap()
        if pix.loadFromData(data):
            self._icon_pixmap = pix
            self.update()

    def project_id(self) -> str:
        return self._project_id

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

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._project_id)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)

        # Background with hover/select blending
        bg = Mr.blend(Mr.BG_CARD, Mr.BG_CARD_HOVER, self._hover)
        bg = Mr.blend(bg, Mr.BG_CARD_ACTIVE, self._selected)
        border_col = Mr.blend(Mr.BORDER, Mr.GREEN, (self._hover + self._selected * 0.5) * 0.6)
        border_w = 1.0 + self._selected

        p.setPen(QPen(border_col, border_w))
        p.setBrush(bg)
        p.drawRoundedRect(rect, _CARD_RADIUS, _CARD_RADIUS)

        # Icon (44×44, rounded 8px)
        icon_rect = QRectF(rect.left() + 12, rect.top() + 12, _ICON_SIZE, _ICON_SIZE)
        if self._icon_pixmap is not None:
            scaled = self._icon_pixmap.scaled(_ICON_SIZE, _ICON_SIZE, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(icon_rect), 8, 8)
            p.setClipPath(clip)
            p.drawPixmap(icon_rect.topLeft(), scaled)
            p.setClipping(False)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(Mr.BG_ELEVATED)
            p.drawRoundedRect(icon_rect, 8, 8)
            font = QFont(self.font())
            font.setPixelSize(20)
            font.setWeight(QFont.Bold)
            p.setFont(font)
            p.setPen(Mr.TEXT_MUTED)
            letter = (self._project.get("title") or "M")[0].upper()
            p.drawText(icon_rect, Qt.AlignCenter, letter)

        # Title – prominent, bold
        title = str(self._project.get("title") or "Untitled")
        text_left = icon_rect.right() + 14
        text_top = rect.top() + 14
        text_width = rect.width() - text_left + rect.left() - 14

        title_font = QFont(self.font())
        title_font.setPixelSize(15)
        title_font.setWeight(QFont.DemiBold)
        p.setFont(title_font)
        p.setPen(Mr.TEXT)
        title_rect = QRectF(text_left, text_top, text_width, 20)
        p.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, _truncate(title, 42))

        # Description – smaller, muted
        desc = str(self._project.get("description") or "")
        desc_font = QFont(self.font())
        desc_font.setPixelSize(11)
        p.setFont(desc_font)
        p.setPen(Mr.TEXT_MUTED)
        desc_rect = QRectF(text_left, text_top + 22, text_width, 16)
        p.drawText(desc_rect, Qt.AlignLeft | Qt.AlignVCenter, _truncate(desc, 70))

        # Author + downloads
        author = str(self._project.get("author") or "Unknown")
        downloads = int(self._project.get("downloads") or 0)
        meta_font = QFont(self.font())
        meta_font.setPixelSize(11)
        p.setFont(meta_font)
        p.setPen(Mr.TEXT_SUBTLE)
        meta_text = f"{author}  ·  {_format_count(downloads)}"
        meta_rect = QRectF(text_left, text_top + 40, text_width, 16)
        p.drawText(meta_rect, Qt.AlignLeft | Qt.AlignVCenter, meta_text)

        # Category chips – right-aligned, compact
        categories = self._project.get("categories") or self._project.get("display_categories") or []
        if isinstance(categories, list) and categories:
            badge_font = QFont(self.font())
            badge_font.setPixelSize(_META_PX)
            badge_font.setWeight(QFont.Medium)
            p.setFont(badge_font)
            bx = rect.right() - 10
            by = rect.top() + 8
            gap = 5
            for cat in reversed(categories[:3]):
                cat_str = str(cat).strip()
                if not cat_str:
                    continue
                metrics = QFontMetrics(badge_font)
                bw = metrics.horizontalAdvance(cat_str) + _CAT_BADGE_PAD_H
                bh = 22
                bx -= bw + gap
                badge_rect = QRectF(bx, by, bw, bh)
                c = Mr.GREEN
                bg_cat = Mr.with_alpha(c, 20)
                _draw_chip(p, cat_str, badge_rect, Mr.with_alpha(Mr.GREEN, 80), bg_cat, Mr.GREEN, _CAT_BADGE_RADIUS)

    def sizeHint(self) -> QSize:
        return QSize(0, _CARD_HEIGHT)


# ---------------------------------------------------------------------------
# VersionRow – Proper Modrinth-style hierarchy
#   Layout: Version Name (top, prominent)
#           Loader • MC • Channel badges (middle row)
#           Published X ago (bottom-left)
#           [Install] button (right side, vertically centered)
# ---------------------------------------------------------------------------

class VersionRow(QWidget):
    clicked = Signal(dict)
    install_clicked = Signal(dict)

    def __init__(self, version: dict[str, Any], parent: QWidget | None = None):
        super().__init__(parent)
        self._version = dict(version)
        self._hover = 0.0
        self._selected = 0.0
        self.setObjectName("versionRow")
        self.setFixedHeight(_VERSION_ROW_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)

        self._hover_anim = QVariantAnimation(self, duration=150, easingCurve=QEasingCurve.OutCubic, valueChanged=self._set_hover)
        self._select_anim = QVariantAnimation(self, duration=180, easingCurve=QEasingCurve.OutCubic, valueChanged=self._set_select)

    def version_data(self) -> dict[str, Any]:
        return self._version

    def set_selected(self, selected: bool) -> None:
        self._select_anim.stop()
        self._select_anim.setStartValue(self._selected)
        self._select_anim.setEndValue(1.0 if selected else 0.0)
        self._select_anim.start()

    def _set_hover(self, v: float) -> None:
        self._hover = float(v)
        self.update()

    def _set_select(self, v: float) -> None:
        self._selected = float(v)
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

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._version)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        rect = QRectF(3, 1, w - 6, h - 2)

        # Background
        bg = Mr.blend(QColor(0, 0, 0, 0), Mr.BG_CARD_HOVER, self._hover)
        bg = Mr.blend(bg, Mr.with_alpha(Mr.GREEN_SOFT, 40), self._selected)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(rect, 8, 8)

        left = 16
        install_btn_w = 88
        install_btn_h = 32
        install_btn_x = w - 16 - install_btn_w
        content_max_x = install_btn_x - 12

        # -- Version Name (top, prominent) --
        name = str(self._version.get("name") or self._version.get("version_number") or "Unknown")
        name_font = QFont(self.font())
        name_font.setPixelSize(14)
        name_font.setWeight(QFont.Bold)
        p.setFont(name_font)
        p.setPen(Mr.TEXT)
        name_rect = QRectF(left, 8, content_max_x - left, 18)
        p.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter, _truncate(name, 60))

        # -- Badge row (middle) --
        loaders: list[str] = self._version.get("loaders") or []
        game_versions: list[str] = self._version.get("game_versions") or []
        version_type = str(self._version.get("version_type") or "release")

        badge_data: list[tuple[str, QColor, QColor, QColor]] = []
        for loader in loaders[:2]:
            bc, bgc, tc = _loader_badge(loader)
            badge_data.append((loader.capitalize(), bc, bgc, tc))
        for mc_v in game_versions[:2]:
            c = Mr.GREEN
            bgc = Mr.with_alpha(c, 20)
            badge_data.append((f"{mc_v}", Mr.with_alpha(Mr.GREEN, 100), bgc, c))
        c, bgc, tc = _channel_badge(version_type)
        badge_data.append((version_type.capitalize(), c, bgc, tc))

        badge_font = QFont(self.font())
        badge_font.setPixelSize(_META_PX)
        badge_font.setWeight(QFont.Medium)
        p.setFont(badge_font)

        bx = left
        by = 30
        badge_h = _BADGE_H
        badge_gap = 6
        max_badge_x = content_max_x

        for text, bc, bgc, tc in badge_data:
            metrics = QFontMetrics(badge_font)
            bw = metrics.horizontalAdvance(text) + _BADGE_PAD_H
            if bx + bw > max_badge_x:
                remaining = len(badge_data) - badge_data.index((text, bc, bgc, tc))
                more_text = f"+{remaining}"
                bw_more = metrics.horizontalAdvance(more_text) + _BADGE_PAD_H
                if bx + bw_more <= max_badge_x:
                    badge_rect = QRectF(bx, by, bw_more, badge_h)
                    _draw_chip(p, more_text, badge_rect, Mr.TEXT_SUBTLE, Mr.BG_ELEVATED, Mr.TEXT_MUTED)
                break
            badge_rect = QRectF(bx, by, bw, badge_h)
            _draw_chip(p, text, badge_rect, bc, bgc, tc)
            bx += bw + badge_gap

        # -- Published date (bottom-left) --
        date_str = str(self._version.get("date_published") or "")
        if date_str:
            date_font = QFont(self.font())
            date_font.setPixelSize(_SMALL_PX)
            p.setFont(date_font)
            p.setPen(Mr.TEXT_SUBTLE)
            relative = _date_relative(date_str)
            published = f"Published {relative}"
            date_rect = QRectF(left, 62, content_max_x - left, 14)
            p.drawText(date_rect, Qt.AlignLeft | Qt.AlignVCenter, published)

        # -- Install button (right side, vertically centered) --
        btn_rect = QRectF(install_btn_x, (h - install_btn_h) / 2, install_btn_w, install_btn_h)

        btn_hover_factor = min(1.0, self._hover * 1.8)
        btn_bg = Mr.blend(Mr.GREEN, Mr.GREEN_BRIGHT, btn_hover_factor)
        btn_border = Mr.blend(Mr.GREEN_DIM, Mr.GREEN, btn_hover_factor)

        p.setPen(QPen(btn_border, 1.2))
        p.setBrush(btn_bg)
        path = QPainterPath()
        path.addRoundedRect(btn_rect, 8, 8)
        p.drawPath(path)

        btn_font = QFont(self.font())
        btn_font.setPixelSize(13)
        btn_font.setWeight(QFont.DemiBold)
        p.setFont(btn_font)
        p.setPen(QColor("#0d1117"))
        p.drawText(btn_rect, Qt.AlignCenter, "Install")

        # Bottom separator
        sep = QPen(Mr.with_alpha(Mr.BORDER, 60), 1)
        p.setPen(sep)
        p.drawLine(rect.left() + 4, h - 0.5, rect.right() - 4, h - 0.5)

    def sizeHint(self) -> QSize:
        return QSize(0, _VERSION_ROW_H)

    def is_install_button_at(self, pos: QPoint) -> bool:
        w = self.width()
        btn_rect = QRectF(w - 16 - 88, (self.height() - 32) / 2, 88, 32)
        return btn_rect.contains(pos)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.is_install_button_at(event.position()):
            self.install_clicked.emit(self._version)
            return
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# CategoryBadge – Modern pill badge for categories in detail view
# ---------------------------------------------------------------------------

class CategoryBadge(QWidget):
    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._text = text
        font = QFont(self.font())
        font.setPixelSize(_META_PX)
        font.setWeight(QFont.Medium)
        metrics = QFontMetrics(font)
        self._badge_w = metrics.horizontalAdvance(text) + _CAT_BADGE_PAD_H
        self.setFixedSize(self._badge_w, _CAT_BADGE_H)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, event) -> None:
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())
        c = Mr.GREEN
        bg = Mr.with_alpha(c, 20)
        _draw_chip(p, self._text, rect, Mr.with_alpha(Mr.GREEN, 80), bg, Mr.GREEN, _CAT_BADGE_RADIUS)


# ---------------------------------------------------------------------------
# ChannelChip – Compact filter toggle (Modrinth-style)
# ---------------------------------------------------------------------------

class ChannelChip(QWidget):
    toggled = Signal(str, bool)

    def __init__(self, label: str, channel: str, default_checked: bool = True, parent: QWidget | None = None):
        super().__init__(parent)
        self._label = label
        self._channel = channel
        self._checked = default_checked
        self._hover = 0.0
        self.setFixedHeight(_CHIP_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self._hover_anim = QVariantAnimation(self, duration=120, easingCurve=QEasingCurve.OutCubic, valueChanged=self._set_hover)

    def _set_hover(self, v: float) -> None:
        self._hover = float(v)
        self.update()

    def is_checked(self) -> bool:
        return self._checked

    def set_checked(self, checked: bool) -> None:
        self._checked = checked
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

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._checked = not self._checked
            self.toggled.emit(self._channel, self._checked)
            self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(self.rect()).adjusted(0, 0, 0, 0)

        if self._checked:
            c = Mr.GREEN
            bg = Mr.blend(Mr.with_alpha(c, 24), Mr.with_alpha(c, 60), self._hover)
            border = Mr.with_alpha(Mr.GREEN, 160)
            text_col = Mr.GREEN
        else:
            bg = Mr.blend(Mr.BG_ELEVATED, Mr.BG_CARD_HOVER, self._hover)
            border = Mr.with_alpha(Mr.BORDER, 100)
            text_col = Mr.TEXT_MUTED

        p.setPen(QPen(border, 1.2))
        p.setBrush(bg)
        p.drawRoundedRect(rect, _CHIP_RADIUS, _CHIP_RADIUS)

        font = QFont(self.font())
        font.setPixelSize(_CHIP_PX)
        font.setWeight(QFont.Medium)
        p.setFont(font)
        p.setPen(text_col)
        p.drawText(rect, Qt.AlignCenter, self._label)

    def sizeHint(self) -> QSize:
        font = QFont(self.font())
        font.setPixelSize(_CHIP_PX)
        metrics = QFontMetrics(font)
        w = metrics.horizontalAdvance(self._label) + _CHIP_PAD_H
        return QSize(w, _CHIP_H)


# ===================================================================
# Main Dialog – Modrinth-styled modpack browser (fully self-contained)
# ===================================================================

class ModrinthModpackBrowser(QDialog):
    install_ready = Signal(str, str)

    def __init__(self, service: LauncherService, parent: QWidget | None = None):
        super().__init__(parent)
        self.service = service
        self._projects: list[dict[str, Any]] = []
        self._project_by_id: dict[str, dict[str, Any]] = {}
        self._project_rows: dict[str, ModpackCard] = {}
        self._query = ""
        self._offset = 0
        self._has_more = True
        self._loading = False
        self._versions: list[dict[str, Any]] = []
        self._filtered_versions: list[dict[str, Any]] = []
        self._selected_version: dict[str, Any] | None = None
        self._selected_project_id: str | None = None
        self._details_loaded = False

        self._search_worker: ModrinthSearchWorker | None = None
        self._details_worker: ModrinthDetailsWorker | None = None
        self._versions_worker: ModrinthVersionsWorker | None = None
        self._download_worker: ModrinthDownloadWorker | None = None
        self._icon_workers: list[IconLoadWorker] = []

        self._release_filter: set[str] = {"release", "beta", "alpha"}
        self._icon_cache_dir = self.service.cache_root / "modrinth-modpack-icons"

        # Download spinner animation
        self._spinner_index = 0
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(80)
        self._spinner_timer.timeout.connect(self._tick_spinner)

        self.setObjectName("modrinthBrowser")
        self.setWindowTitle("Modrinth Modpacks")
        self.setModal(True)
        self.setMinimumSize(1100, 760)
        self.resize(fitted_window_size(self.parentWidget() or self, 1280, 860, minimum_width=1100, minimum_height=760))
        self._build_ui()
        QTimer.singleShot(0, self._load_initial)

    # ================================================================
    # Spinner tick
    # ================================================================

    def _tick_spinner(self) -> None:
        self._spinner_index = (self._spinner_index + 1) % len(_SPINNER_FRAMES)
        spinner = _SPINNER_FRAMES[self._spinner_index]
        self.footer_status.setText(f"{spinner}  Downloading modpack…")

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        content = QWidget()
        content.setObjectName("browserContent")
        cl = QHBoxLayout(content)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.setSpacing(12)

        cl.addWidget(self._build_left_panel(), 1)

        divider = QFrame()
        divider.setObjectName("browserDivider")
        divider.setFixedWidth(1)
        cl.addWidget(divider)

        cl.addWidget(self._build_right_panel(), 2)
        root.addWidget(content, 1)
        root.addWidget(self._build_footer())

        self._apply_styles()

    def _build_header(self) -> QWidget:
        h = QWidget()
        h.setObjectName("browserHeader")
        h.setFixedHeight(54)
        layout = QHBoxLayout(h)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(12)

        logo = QLabel("Modrinth Modpacks")
        logo.setObjectName("browserTitle")
        layout.addWidget(logo)
        layout.addStretch()
        return h

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("browserLeftPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Search row
        search_row_layout = QHBoxLayout()
        search_row_layout.setContentsMargins(0, 0, 0, 0)
        search_row_layout.setSpacing(6)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search modpacks…")
        self.search_edit.setObjectName("modpackSearchField")
        self.search_edit.returnPressed.connect(self._on_search_submit)
        search_row_layout.addWidget(self.search_edit, 1)

        search_btn = QPushButton("Search")
        search_btn.setObjectName("searchButton")
        search_btn.clicked.connect(self._on_search_submit)
        search_row_layout.addWidget(search_btn)

        layout.addLayout(search_row_layout)

        # Card scroll area
        self.card_scroll = QScrollArea()
        self.card_scroll.setObjectName("browserCardScroll")
        self.card_scroll.setWidgetResizable(True)
        self.card_scroll.setFrameShape(QFrame.NoFrame)
        self.card_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.card_scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)

        self.card_container = QWidget()
        self.card_container.setObjectName("cardContainer")
        self.card_list = QVBoxLayout(self.card_container)
        self.card_list.setContentsMargins(0, 0, 0, 0)
        self.card_list.setSpacing(4)
        self.card_list.addStretch()
        self.card_scroll.setWidget(self.card_container)
        layout.addWidget(self.card_scroll, 1)

        self.list_status = QLabel("")
        self.list_status.setObjectName("browserStatus")
        self.list_status.setAlignment(Qt.AlignLeft)
        self.list_status.setFixedHeight(18)
        layout.addWidget(self.list_status)

        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("browserRightPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Scroll area for detail content
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setObjectName("browserDetailScroll")
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFrameShape(QFrame.NoFrame)
        self.detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.detail_widget = QWidget()
        self.detail_widget.setObjectName("detailWidget")
        self.detail_layout = QVBoxLayout(self.detail_widget)
        self.detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_layout.setSpacing(0)

        # --- Detail inner (visible when project selected) ---
        self.detail_inner = QWidget()
        self.detail_inner.setObjectName("detailInner")
        inner_layout = QVBoxLayout(self.detail_inner)
        inner_layout.setContentsMargins(20, 20, 20, 16)
        inner_layout.setSpacing(0)

        # Header row: icon + title/author/stats
        self.detail_header = QWidget()
        self.detail_header.setObjectName("detailHeaderSection")
        dh_layout = QHBoxLayout(self.detail_header)
        dh_layout.setContentsMargins(0, 0, 0, 0)
        dh_layout.setSpacing(16)

        self.detail_icon = QLabel()
        self.detail_icon.setObjectName("detailIcon")
        self.detail_icon.setFixedSize(_LARGE_ICON_SIZE, _LARGE_ICON_SIZE)
        dh_layout.addWidget(self.detail_icon)

        ht = QVBoxLayout()
        ht.setContentsMargins(0, 0, 0, 0)
        ht.setSpacing(2)

        self.detail_title = QLabel()
        self.detail_title.setObjectName("detailTitle")
        self.detail_title.setWordWrap(True)
        ht.addWidget(self.detail_title)

        self.detail_author = QLabel()
        self.detail_author.setObjectName("detailAuthor")
        ht.addWidget(self.detail_author)

        self.detail_stats = QLabel()
        self.detail_stats.setObjectName("detailStats")
        ht.addWidget(self.detail_stats)

        ht.addStretch()
        dh_layout.addLayout(ht, 1)
        inner_layout.addWidget(self.detail_header)

        # Spacing
        inner_layout.addSpacing(12)

        # Categories (pill-style)
        self.detail_categories = QWidget()
        self.detail_categories.setObjectName("detailCategories")
        cat_layout = QHBoxLayout(self.detail_categories)
        cat_layout.setContentsMargins(0, 0, 0, 0)
        cat_layout.setSpacing(6)
        cat_layout.addStretch()
        inner_layout.addWidget(self.detail_categories)

        inner_layout.addSpacing(12)

        # Description section with heading
        self.detail_desc_section = QWidget()
        self.detail_desc_section.setObjectName("detailSection")
        ds_layout = QVBoxLayout(self.detail_desc_section)
        ds_layout.setContentsMargins(0, 0, 0, 0)
        ds_layout.setSpacing(4)

        desc_label = QLabel("Description")
        desc_label.setObjectName("detailSectionTitle")
        ds_layout.addWidget(desc_label)

        self.detail_desc = QLabel()
        self.detail_desc.setObjectName("detailDescription")
        self.detail_desc.setWordWrap(True)
        self.detail_desc.setOpenExternalLinks(True)
        self.detail_desc.setTextFormat(Qt.RichText)
        self.detail_desc.setMaximumHeight(80)
        ds_layout.addWidget(self.detail_desc)
        inner_layout.addWidget(self.detail_desc_section)

        inner_layout.addSpacing(12)

        # Gallery (compact horizontal strip)
        self.detail_gallery_section = QWidget()
        self.detail_gallery_section.setObjectName("detailSection")
        gs_layout = QVBoxLayout(self.detail_gallery_section)
        gs_layout.setContentsMargins(0, 0, 0, 0)
        gs_layout.setSpacing(5)

        gallery_label = QLabel("Gallery")
        gallery_label.setObjectName("detailSectionTitle")
        gs_layout.addWidget(gallery_label)

        gs_scroll = QScrollArea()
        gs_scroll.setObjectName("galleryScroll")
        gs_scroll.setWidgetResizable(True)
        gs_scroll.setFrameShape(QFrame.NoFrame)
        gs_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        gs_scroll.setMaximumHeight(90)
        self.detail_gallery = QWidget()
        self.detail_gallery.setObjectName("galleryContainer")
        self.gallery_layout = QHBoxLayout(self.detail_gallery)
        self.gallery_layout.setContentsMargins(0, 0, 0, 0)
        self.gallery_layout.setSpacing(6)
        self.gallery_layout.addStretch()
        gs_scroll.setWidget(self.detail_gallery)
        gs_layout.addWidget(gs_scroll)
        inner_layout.addWidget(self.detail_gallery_section)

        inner_layout.addSpacing(12)

        # Version browser (stretch to fill remaining)
        self.version_section = QWidget()
        self.version_section.setObjectName("versionSection")
        vs_layout = QVBoxLayout(self.version_section)
        vs_layout.setContentsMargins(0, 0, 0, 0)
        vs_layout.setSpacing(8)

        # Title row with count
        v_title_row = QHBoxLayout()
        v_title_row.setContentsMargins(0, 0, 0, 0)
        v_title_row.setSpacing(8)
        v_title = QLabel("Versions")
        v_title.setObjectName("detailSectionTitle")
        v_title_row.addWidget(v_title)
        self.version_count_label = QLabel("")
        self.version_count_label.setObjectName("versionCountLabel")
        v_title_row.addWidget(self.version_count_label)
        v_title_row.addStretch()
        vs_layout.addLayout(v_title_row)

        # Filters bar – improved spacing, no clipping
        fw = QWidget()
        fw.setObjectName("versionFilters")
        fw_layout = QVBoxLayout(fw)
        fw_layout.setContentsMargins(0, 0, 0, 0)
        fw_layout.setSpacing(8)

        # Row 1: MC, Loader, Sort, Search
        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(8)

        self.mc_filter_combo = QComboBox()
        self.mc_filter_combo.setObjectName("versionFilterCombo")
        self.mc_filter_combo.addItem("All MC", "")
        self.mc_filter_combo.setMinimumWidth(100)
        self.mc_filter_combo.currentIndexChanged.connect(self._apply_version_filters)
        row1.addWidget(self.mc_filter_combo)

        self.loader_filter_combo = QComboBox()
        self.loader_filter_combo.setObjectName("versionFilterCombo")
        self.loader_filter_combo.addItem("All Loaders", "")
        for ldr in ["Fabric", "Forge", "NeoForge", "Quilt"]:
            self.loader_filter_combo.addItem(ldr, ldr.lower())
        self.loader_filter_combo.setMinimumWidth(110)
        self.loader_filter_combo.currentIndexChanged.connect(self._apply_version_filters)
        row1.addWidget(self.loader_filter_combo)

        self.sort_combo = QComboBox()
        self.sort_combo.setObjectName("versionFilterCombo")
        self.sort_combo.addItem("Newest", "newest")
        self.sort_combo.addItem("Oldest", "oldest")
        self.sort_combo.setMinimumWidth(90)
        self.sort_combo.currentIndexChanged.connect(self._apply_version_filters)
        row1.addWidget(self.sort_combo)

        self.version_search_field = QLineEdit()
        self.version_search_field.setObjectName("versionSearchField")
        self.version_search_field.setPlaceholderText("Search versions…")
        self.version_search_field.setMinimumWidth(140)
        self.version_search_field.textChanged.connect(self._apply_version_filters)
        row1.addWidget(self.version_search_field, 1)

        row1.addStretch()
        fw_layout.addLayout(row1)

        # Row 2: Release channel chips
        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(8)

        self._release_chip = ChannelChip("Release", "release", True)
        self._release_chip.toggled.connect(self._on_chip_toggled)
        row2.addWidget(self._release_chip)
        self._beta_chip = ChannelChip("Beta", "beta", True)
        self._beta_chip.toggled.connect(self._on_chip_toggled)
        row2.addWidget(self._beta_chip)
        self._alpha_chip = ChannelChip("Alpha", "alpha", True)
        self._alpha_chip.toggled.connect(self._on_chip_toggled)
        row2.addWidget(self._alpha_chip)

        row2.addStretch()
        fw_layout.addLayout(row2)

        vs_layout.addWidget(fw)

        # Version list – takes remaining space
        self.version_scroll = QScrollArea()
        self.version_scroll.setObjectName("versionScroll")
        self.version_scroll.setWidgetResizable(True)
        self.version_scroll.setFrameShape(QFrame.NoFrame)
        self.version_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.version_container = QWidget()
        self.version_container.setObjectName("versionContainer")
        self.version_list_layout = QVBoxLayout(self.version_container)
        self.version_list_layout.setContentsMargins(0, 0, 0, 0)
        self.version_list_layout.setSpacing(2)
        self.version_scroll.setWidget(self.version_container)
        vs_layout.addWidget(self.version_scroll, 1)

        self.version_status = QLabel("")
        self.version_status.setObjectName("versionStatus")
        self.version_status.setAlignment(Qt.AlignLeft)
        self.version_status.setFixedHeight(18)
        vs_layout.addWidget(self.version_status)

        inner_layout.addWidget(self.version_section, 1)
        self.detail_layout.addWidget(self.detail_inner)

        # Placeholder / loading
        self.detail_placeholder = QLabel("Select a modpack to view details")
        self.detail_placeholder.setObjectName("detailPlaceholder")
        self.detail_placeholder.setAlignment(Qt.AlignCenter)
        self.detail_layout.addWidget(self.detail_placeholder, 1)

        self.detail_loading = QLabel("Loading modpack details…")
        self.detail_loading.setObjectName("detailLoading")
        self.detail_loading.setAlignment(Qt.AlignCenter)
        self.detail_loading.setVisible(False)
        self.detail_layout.addWidget(self.detail_loading)

        self.detail_scroll.setWidget(self.detail_widget)
        layout.addWidget(self.detail_scroll, 1)
        return panel

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        footer.setObjectName("browserFooter")
        footer.setFixedHeight(44)
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(8)
        self.footer_status = QLabel("")
        self.footer_status.setObjectName("footerStatus")
        layout.addWidget(self.footer_status, 1)
        self.cancel_button = QPushButton("Close")
        self.cancel_button.setObjectName("footerCloseButton")
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(self.cancel_button)
        return footer

    # ================================================================
    # Styles – fully self-contained using Mr colour tokens
    # ================================================================

    def _apply_styles(self) -> None:
        self.setStyleSheet(f"""
        QDialog#modrinthBrowser {{
            background-color: {_mr_css(Mr.BG)};
        }}
        QWidget#browserHeader {{
            background-color: {_mr_css(Mr.BG_PANEL)};
            border-bottom: 1px solid {_mr_css(Mr.BORDER)};
        }}
        QLabel#browserTitle {{
            color: {_mr_css(Mr.TEXT)};
            font-size: 18px;
            font-weight: 700;
            background: transparent;
        }}
        QWidget#browserFooter {{
            background-color: {_mr_css(Mr.BG_PANEL)};
            border-top: 1px solid {_mr_css(Mr.BORDER)};
        }}
        QLabel#footerStatus {{
            color: {_mr_css(Mr.TEXT_MUTED)};
            font-size: 11px;
            background: transparent;
        }}
        QPushButton#footerCloseButton {{
            background-color: {_mr_css(Mr.BG_ELEVATED)};
            border: 1px solid {_mr_css(Mr.BORDER)};
            border-radius: 6px;
            color: {_mr_css(Mr.TEXT)};
            font-size: 12px;
            font-weight: 600;
            padding: 6px 18px;
            min-height: 28px;
        }}
        QPushButton#footerCloseButton:hover {{
            background-color: {_mr_css(Mr.BG_CARD_HOVER)};
            border-color: {_mr_css(Mr.GREEN)};
        }}
        QWidget#browserLeftPanel {{
            background-color: {_mr_css(Mr.BG_CARD)};
            border: 1px solid {_mr_css(Mr.BORDER)};
            border-radius: 10px;
        }}
        QWidget#browserRightPanel {{
            background-color: {_mr_css(Mr.BG_SURFACE)};
            border: 1px solid {_mr_css(Mr.BORDER)};
            border-radius: 10px;
        }}
        QFrame#browserDivider {{
            background-color: {_mr_css(Mr.SEPARATOR)};
            max-width: 1px;
            border: none;
        }}
        QScrollArea#browserCardScroll, QScrollArea#browserDetailScroll, QScrollArea#versionScroll {{
            background: transparent;
            border: none;
        }}
        QScrollArea#galleryScroll {{
            background: transparent;
            border: none;
        }}
        QWidget#cardContainer, QWidget#detailWidget, QWidget#detailInner, QWidget#versionContainer {{
            background: transparent;
        }}
        QLineEdit#modpackSearchField {{
            background-color: {_mr_css(Mr.BG_INPUT)};
            border: 1px solid {_mr_css(Mr.BORDER)};
            border-radius: 7px;
            color: {_mr_css(Mr.TEXT)};
            font-size: 12px;
            padding: 5px 10px;
            min-height: 28px;
        }}
        QLineEdit#modpackSearchField:focus {{
            border: 1px solid {_mr_css(Mr.GREEN_BRIGHT)};
        }}
        QLineEdit#modpackSearchField::placeholder {{
            color: {_mr_css(Mr.TEXT_MUTED)};
        }}
        QPushButton#searchButton {{
            background-color: {_mr_css(Mr.GREEN_DIM)};
            border: 1px solid {_mr_css(Mr.GREEN)};
            border-radius: 6px;
            color: {_mr_css(Mr.BG)};
            font-size: 12px;
            font-weight: 700;
            padding: 5px 14px;
            min-height: 28px;
        }}
        QPushButton#searchButton:hover {{
            background-color: {_mr_css(Mr.GREEN)};
        }}
        QLineEdit#versionSearchField {{
            background-color: {_mr_css(Mr.BG_INPUT)};
            border: 1px solid {_mr_css(Mr.BORDER)};
            border-radius: 6px;
            color: {_mr_css(Mr.TEXT)};
            font-size: 11px;
            padding: 4px 10px;
            min-height: 24px;
        }}
        QLineEdit#versionSearchField:focus {{
            border: 1px solid {_mr_css(Mr.GREEN_BRIGHT)};
        }}
        QLineEdit#versionSearchField::placeholder {{
            color: {_mr_css(Mr.TEXT_MUTED)};
        }}
        QLabel#browserStatus {{
            color: {_mr_css(Mr.TEXT_MUTED)};
            font-size: 11px;
            background: transparent;
        }}
        QLabel#versionStatus {{
            color: {_mr_css(Mr.TEXT_SUBTLE)};
            font-size: 10px;
            background: transparent;
        }}
        QLabel#versionCountLabel {{
            color: {_mr_css(Mr.TEXT_SUBTLE)};
            font-size: 11px;
            font-weight: 400;
            background: transparent;
        }}
        QLabel#detailPlaceholder {{
            color: {_mr_css(Mr.TEXT_MUTED)};
            font-size: 13px;
            background: transparent;
        }}
        QLabel#detailLoading {{
            color: {_mr_css(Mr.TEXT_MUTED)};
            font-size: 12px;
            background: transparent;
        }}
        QLabel#detailTitle {{
            color: {_mr_css(Mr.TEXT)};
            font-size: {_TITLE_PX}px;
            font-weight: 700;
            background: transparent;
        }}
        QLabel#detailAuthor {{
            color: {_mr_css(Mr.TEXT_MUTED)};
            font-size: {_PRIMARY_PX}px;
            background: transparent;
        }}
        QLabel#detailStats {{
            color: {_mr_css(Mr.TEXT_SUBTLE)};
            font-size: {_META_PX}px;
            font-weight: 400;
            background: transparent;
        }}
        QWidget#detailHeaderSection, QWidget#detailCategories, QWidget#detailSection {{
            background: transparent;
        }}
        QLabel#detailSectionTitle {{
            color: {_mr_css(Mr.TEXT)};
            font-size: {_SECTION_PX}px;
            font-weight: 600;
            background: transparent;
        }}
        QLabel#detailDescription {{
            color: {_mr_css(Mr.TEXT_MUTED)};
            font-size: {_META_PX}px;
            line-height: 1.5;
            background: transparent;
        }}
        QWidget#versionSection, QWidget#versionFilters {{
            background: transparent;
        }}
        QComboBox#versionFilterCombo {{
            background-color: {_mr_css(Mr.BG_INPUT)};
            border: 1px solid {_mr_css(Mr.BORDER)};
            border-radius: 6px;
            color: {_mr_css(Mr.TEXT)};
            font-size: 11px;
            padding: 4px 10px;
            min-height: 26px;
            min-width: 90px;
        }}
        QComboBox#versionFilterCombo:focus {{
            border-color: {_mr_css(Mr.GREEN_BRIGHT)};
        }}
        QComboBox#versionFilterCombo::drop-down {{
            border: none;
            width: 16px;
        }}
        QComboBox#versionFilterCombo QAbstractItemView {{
            background-color: {_mr_css(Mr.BG_SURFACE)};
            border: 1px solid {_mr_css(Mr.BORDER)};
            border-radius: 6px;
            selection-background-color: {_mr_css(Mr.GREEN_SOFT)};
            selection-color: {_mr_css(Mr.GREEN)};
            color: {_mr_css(Mr.TEXT)};
            font-size: 11px;
            padding: 4px 0px;
            outline: none;
        }}
        QComboBox#versionFilterCombo QAbstractItemView::item {{
            padding: 4px 10px;
            min-height: 22px;
        }}
        QComboBox#versionFilterCombo QAbstractItemView::item:hover {{
            background-color: {_mr_css(Mr.BG_CARD_HOVER)};
        }}
        QLabel#detailIcon {{
            background-color: {_mr_css(Mr.BG_ELEVATED)};
            border: 1px solid {_mr_css(Mr.BORDER)};
            border-radius: 10px;
        }}
        QScrollBar:vertical {{
            background: transparent;
            width: 6px;
            margin: 0;
        }}
        QScrollBar::handle:vertical {{
            background: {_mr_css(Mr.with_alpha(Mr.BORDER, 100))};
            border-radius: 3px;
            min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {_mr_css(Mr.TEXT_SUBTLE)};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: transparent;
        }}
        """)

    # ================================================================
    # Search & Loading
    # ================================================================

    def _on_search_submit(self) -> None:
        self._query = self.search_edit.text().strip()
        self._offset = 0
        self._has_more = True
        self._projects.clear()
        self._project_by_id.clear()
        self._project_rows.clear()
        self._clear_cards()
        self.list_status.setText("Searching…" if self._query else "Loading popular modpacks…")
        self._search(self._query)

    def _load_initial(self) -> None:
        self._query = ""
        self._offset = 0
        self._has_more = True
        self._projects.clear()
        self._project_by_id.clear()
        self._project_rows.clear()
        self._clear_cards()
        self.list_status.setText("Loading popular modpacks…")
        self._search("")

    def _search(self, query: str) -> None:
        if self._loading:
            return
        self._loading = True
        if self._search_worker and self._search_worker.isRunning():
            self._search_worker.requestInterruption()
            self._search_worker.wait(800)
        worker = ModrinthSearchWorker(self.service, query, limit=_PAGE_SIZE, offset=self._offset, parent=self)
        worker.loaded.connect(self._on_search_loaded)
        worker.failed.connect(self._on_search_failed)
        worker.finished.connect(lambda: setattr(self, "_search_worker", None))
        self._search_worker = worker
        worker.start()

    def _on_search_loaded(self, projects: list[dict[str, Any]]) -> None:
        self._loading = False
        if self._offset == 0:
            self._projects.clear()
            self._project_by_id.clear()
            self._project_rows.clear()
            self._clear_cards()
        if not projects and not self._projects:
            self._has_more = False
            self.list_status.setText("No modpacks found. Try a different search.")
            return
        self._append_projects(projects)
        self._offset += len(projects)
        self._has_more = len(projects) >= _PAGE_SIZE
        self.list_status.setText(f"{len(self._projects)} modpacks found")
        self._load_card_icons(projects)
        if not self._selected_project_id and self._projects:
            first = self._projects[0]
            pid = str(first.get("project_id") or first.get("slug") or "")
            self._select_project(pid)

    def _on_search_failed(self, message: str) -> None:
        self._loading = False
        self.list_status.setText(f"Error: {message}")
        QMessageBox.warning(self, "Search Failed", f"Could not search modpacks:\n{message}")

    def _append_projects(self, projects: list[dict[str, Any]]) -> None:
        for project in projects:
            key = _project_key(project)
            if key in self._project_rows:
                continue
            self._projects.append(project)
            pid = str(project.get("project_id") or project.get("slug") or "")
            self._project_by_id[pid] = project
            self._project_by_id[key] = project
            card = ModpackCard(project)
            card.clicked.connect(self._on_card_clicked)
            self.card_list.insertWidget(self.card_list.count() - 1, card)
            self._project_rows[key] = card

    def _clear_cards(self) -> None:
        for i in reversed(range(self.card_list.count())):
            item = self.card_list.itemAt(i)
            if item and item.widget():
                w = item.widget()
                self.card_list.removeWidget(w)
                w.deleteLater()

    def _load_card_icons(self, projects: list[dict[str, Any]]) -> None:
        targets: list[tuple[str, str]] = []
        for project in projects:
            url = str(project.get("icon_url") or "")
            if url.startswith(("http://", "https://")):
                targets.append((_project_key(project), url))
        if not targets:
            return
        worker = IconLoadWorker(targets, self._icon_cache_dir, self)
        worker.icon_loaded.connect(self._on_card_icon_loaded)
        worker.finished.connect(lambda w=worker: self._icon_workers.remove(w) if w in self._icon_workers else None)
        self._icon_workers.append(worker)
        worker.start()

    def _on_card_icon_loaded(self, key: str, data: object) -> None:
        if not isinstance(data, (bytes, bytearray)):
            return
        row = self._project_rows.get(key)
        if row:
            row.set_icon_data(bytes(data))

    def _on_scroll(self, value: int) -> None:
        scroll = self.sender()
        if scroll and hasattr(scroll, "maximum") and value >= scroll.maximum() - 200:
            if not self._loading and self._has_more:
                self._search(self._query)

    def _on_card_clicked(self, project_id: str) -> None:
        self._select_project(project_id)

    def _select_project(self, project_id: str) -> None:
        self._selected_project_id = project_id
        for key, card in self._project_rows.items():
            card.set_selected(key == _project_key(self._project_by_id.get(project_id, {})) or key == project_id)
        self.detail_placeholder.setVisible(False)
        self.detail_inner.setVisible(False)
        self.detail_loading.setVisible(True)
        self._load_details(project_id)

    def _load_details(self, project_id: str) -> None:
        if self._details_worker and self._details_worker.isRunning():
            self._details_worker.requestInterruption()
            self._details_worker.wait(800)
        w = ModrinthDetailsWorker(self.service, project_id, parent=self)
        w.loaded.connect(self._on_details_loaded)
        w.failed.connect(self._on_details_failed)
        self._details_worker = w
        w.start()

        if self._versions_worker and self._versions_worker.isRunning():
            self._versions_worker.requestInterruption()
            self._versions_worker.wait(800)
        vw = ModrinthVersionsWorker(self.service, project_id, parent=self)
        vw.loaded.connect(self._on_versions_loaded)
        vw.failed.connect(self._on_versions_failed)
        self._versions_worker = vw
        vw.start()

    def _on_details_loaded(self, details: dict[str, Any]) -> None:
        self.detail_loading.setVisible(False)
        self._details_loaded = True
        self._populate_details(details)
        project_id = self._selected_project_id or ""
        icon_url = str(details.get("icon_url") or "")
        if icon_url.startswith(("http://", "https://")):
            w = IconLoadWorker([(project_id, icon_url)], self._icon_cache_dir, self)
            w.icon_loaded.connect(self._on_detail_icon_loaded)
            w.finished.connect(lambda w=w: setattr(self, "_detail_icon_worker", None) if hasattr(self, "_detail_icon_worker") else None)
            self._detail_icon_worker = w
            w.start()

    def _on_details_failed(self, message: str) -> None:
        self.detail_loading.setVisible(False)
        self.detail_placeholder.setVisible(True)
        self.detail_placeholder.setText(f"Failed to load details:\n{message}")

    def _on_detail_icon_loaded(self, key: str, data: object) -> None:
        if not isinstance(data, (bytes, bytearray)):
            return
        pix = QPixmap()
        if pix.loadFromData(bytes(data)):
            scaled = pix.scaled(_LARGE_ICON_SIZE, _LARGE_ICON_SIZE, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            self.detail_icon.setPixmap(scaled)

    def _populate_details(self, details: dict[str, Any]) -> None:
        self.detail_inner.setVisible(True)

        title = str(details.get("title") or "Untitled Modpack")
        self.detail_title.setText(title)

        author = str(details.get("author") or "Unknown")
        self.detail_author.setText(f"by {author}")

        downloads = int(details.get("downloads") or 0)
        follows = int(details.get("follows") or 0)
        self.detail_stats.setText(f"{_format_count(downloads)} downloads  •  {_format_count(follows)} follows")

        cat_layout = self.detail_categories.layout()
        while cat_layout.count() > 1:
            item = cat_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        categories = details.get("categories") or details.get("display_categories") or []
        if isinstance(categories, list):
            for cat in categories:
                cs = str(cat).strip()
                if cs:
                    cat_layout.insertWidget(cat_layout.count() - 1, CategoryBadge(cs))

        desc = str(details.get("description") or "No description available.")
        self.detail_desc.setText(desc)

        self.detail_gallery_section.setVisible(False)
        gallery = details.get("gallery") or []
        if isinstance(gallery, list) and gallery:
            self.detail_gallery_section.setVisible(True)
            self._clear_gallery()
            for img in gallery[:8]:
                if isinstance(img, dict):
                    img_url = str(img.get("url") or "")
                    if img_url.startswith(("http://", "https://")):
                        self._load_gallery_image(img_url)

        self.footer_status.setText(f"Viewing: {title}")

    def _clear_gallery(self) -> None:
        while self.gallery_layout.count() > 1:
            item = self.gallery_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

    def _load_gallery_image(self, url: str) -> None:
        w = IconLoadWorker([(url, url)], self._icon_cache_dir, self)
        w.icon_loaded.connect(self._on_gallery_image_loaded)
        w.finished.connect(lambda w=w: None)
        w.start()

    def _on_gallery_image_loaded(self, key: str, data: object) -> None:
        if not isinstance(data, (bytes, bytearray)):
            return
        pix = QPixmap()
        if pix.loadFromData(bytes(data)):
            scaled = pix.scaled(130, 74, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            label = QLabel()
            label.setFixedSize(130, 74)
            label.setPixmap(scaled)
            label.setStyleSheet(f"border:1px solid {_mr_css(Mr.with_alpha(Mr.TEXT, 16))}; border-radius:4px;")
            self.gallery_layout.insertWidget(self.gallery_layout.count() - 1, label)

    def _on_versions_loaded(self, versions: list[dict[str, Any]]) -> None:
        self._versions = list(versions)
        self._build_version_filters()
        self._apply_version_filters()

    def _on_versions_failed(self, message: str) -> None:
        self.version_status.setText(f"Failed to load versions: {message}")

    # ================================================================
    # Filtering
    # ================================================================

    def _on_chip_toggled(self, channel: str, checked: bool) -> None:
        if checked:
            self._release_filter.add(channel)
        else:
            self._release_filter.discard(channel)
        self._apply_version_filters()

    def _build_version_filters(self) -> None:
        cur = self.mc_filter_combo.currentData()
        self.mc_filter_combo.blockSignals(True)
        self.mc_filter_combo.clear()
        self.mc_filter_combo.addItem("All MC", "")
        mc_set: set[str] = set()
        for v in self._versions:
            for gv in v.get("game_versions") or []:
                mc_set.add(str(gv))
        for mc_v in sorted(mc_set, reverse=True):
            self.mc_filter_combo.addItem(mc_v, mc_v)
        if cur:
            idx = self.mc_filter_combo.findData(cur)
            if idx >= 0:
                self.mc_filter_combo.setCurrentIndex(idx)
        self.mc_filter_combo.blockSignals(False)

    def _apply_version_filters(self) -> None:
        mc = self.mc_filter_combo.currentData()
        loader = self.loader_filter_combo.currentData()
        sort = self.sort_combo.currentData()
        search_text = self.version_search_field.text().strip().lower()

        filtered = []
        for v in self._versions:
            vt = str(v.get("version_type") or "release")
            if vt not in self._release_filter:
                continue
            if mc:
                gv = [str(x) for x in (v.get("game_versions") or [])]
                if mc not in gv:
                    continue
            if loader:
                ld = [str(x).lower() for x in (v.get("loaders") or [])]
                if loader.lower() not in ld:
                    continue
            if search_text:
                vn = str(v.get("name") or v.get("version_number") or "").lower()
                if search_text not in vn:
                    continue
            filtered.append(v)

        if sort == "newest":
            filtered.sort(key=lambda x: x.get("date_published", ""), reverse=True)
        elif sort == "oldest":
            filtered.sort(key=lambda x: x.get("date_published", ""))

        self._filtered_versions = filtered
        self._rebuild_version_list()

    def _rebuild_version_list(self) -> None:
        while self.version_list_layout.count() > 0:
            item = self.version_list_layout.takeAt(0)
            if item and item.widget():
                w = item.widget()
                w.deleteLater()

        if not self._filtered_versions:
            self.version_status.setText("No versions match the current filters")
            self.version_count_label.setText("")
            self.version_list_layout.addStretch()
            return

        n = len(self._filtered_versions)
        self.version_count_label.setText(f"({n})")
        self.version_status.setText(f"{n} version{'s' if n != 1 else ''} • {len(self._versions)} total")
        self._selected_version = None

        for version in self._filtered_versions:
            row = VersionRow(version)
            row.clicked.connect(self._on_version_clicked)
            row.install_clicked.connect(self._install_version)
            self.version_list_layout.addWidget(row)

        if self._filtered_versions:
            first_row = self.version_list_layout.itemAt(0)
            if first_row and first_row.widget():
                first_row.widget().set_selected(True)
                self._selected_version = self._filtered_versions[0]

    def _on_version_clicked(self, version: dict[str, Any]) -> None:
        for i in range(self.version_list_layout.count()):
            item = self.version_list_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), VersionRow):
                item.widget().set_selected(item.widget().version_data() is version)
        self._selected_version = version

    # ================================================================
    # Installation with footer spinner
    # ================================================================

    def _install_version(self, version: dict[str, Any]) -> None:
        self._selected_version = version
        self._start_download()

    def _start_download(self) -> None:
        if self._selected_version is None:
            QMessageBox.information(self, "Select Version", "Please select a version first.")
            return
        if self._download_worker and self._download_worker.isRunning():
            QMessageBox.information(self, "Downloading", "A download is already in progress.")
            return
        self._spinner_index = 0
        self._spinner_timer.start()
        self.footer_status.setText(f"{_SPINNER_FRAMES[0]}  Downloading modpack…")
        w = ModrinthDownloadWorker(self.service, self._selected_version, parent=self)
        w.loaded.connect(self._on_download_loaded)
        w.failed.connect(self._on_download_failed)
        w.finished.connect(lambda: setattr(self, "_download_worker", None))
        self._download_worker = w
        w.start()

    def _on_download_loaded(self, path: str) -> None:
        self._spinner_timer.stop()
        project = self._project_by_id.get(self._selected_project_id or "", {})
        suggested = str(project.get("title") or "Modrinth Modpack")
        if self._selected_version:
            vn = str(self._selected_version.get("name") or self._selected_version.get("version_number") or "")
            if vn:
                suggested = f"{suggested} {vn}"
        self.footer_status.setText("Download complete")
        self.install_ready.emit(suggested, path)
        self.accept()

    def _on_download_failed(self, message: str) -> None:
        self._spinner_timer.stop()
        self.footer_status.setText("Download failed")
        QMessageBox.warning(self, "Download Failed", f"Could not download modpack:\n{message}")

    def closeEvent(self, event) -> None:
        self._spinner_timer.stop()
        for w in [self._search_worker, self._details_worker, self._versions_worker, self._download_worker]:
            if w and w.isRunning():
                w.requestInterruption()
                w.wait(1200)
        for w in list(self._icon_workers):
            if w.isRunning():
                w.requestInterruption()
                w.wait(1200)
        super().closeEvent(event)