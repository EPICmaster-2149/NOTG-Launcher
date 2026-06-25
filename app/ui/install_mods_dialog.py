from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import requests
from PySide6.QtCore import QEasingCurve, QRectF, QSize, Qt, QThread, QTimer, Signal, QVariantAnimation
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

from core.launcher import InstanceRecord, LauncherService
from ui.responsive import fitted_window_size

# ---------------------------------------------------------------------------
# Modrinth colour palette (identical to modrinth_modpack_browser)
# ---------------------------------------------------------------------------

class Mr:
    BG = QColor("#0d1117")
    BG_PANEL = QColor("#141920")
    BG_CARD = QColor("#161b22")
    BG_CARD_HOVER = QColor("#1c2333")
    BG_CARD_ACTIVE = QColor("#21283a")
    BG_SURFACE = QColor("#1a1f2e")
    BG_ELEVATED = QColor("#21262d")
    BG_INPUT = QColor("#0d1117")

    GREEN = QColor("#1bd96a")
    GREEN_BRIGHT = QColor("#2eeb7a")
    GREEN_DIM = QColor("#17b559")
    GREEN_GLOW = QColor(27, 217, 106, 42)
    GREEN_SOFT = QColor(27, 217, 106, 22)

    TEXT = QColor("#f0f6fc")
    TEXT_MUTED = QColor("#8b949e")
    TEXT_SUBTLE = QColor("#6e7681")

    BORDER = QColor(48, 54, 61, 180)
    BORDER_LIGHT = QColor(48, 54, 61, 100)
    SEPARATOR = QColor(48, 54, 61, 80)

    DANGER = QColor("#f85149")
    WARNING = QColor("#d29922")
    SUCCESS = QColor("#3fb950")
    INSTALLED = QColor("#3fb950")

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
    return f"rgba({c.red()},{c.green()},{c.blue()},{c.alpha()})"


# ---------------------------------------------------------------------------
# Sizing constants (aligned with Modpack Browser)
# ---------------------------------------------------------------------------

_ICON_SIZE = 40
_LARGE_ICON_SIZE = 80
_CARD_HEIGHT = 84
_CARD_RADIUS = 10
_CAT_BADGE_H = 26
_CAT_BADGE_PAD_H = 14
_CAT_BADGE_RADIUS = 13
_BADGE_RADIUS = 14

_TITLE_PX = 28
_SECTION_PX = 18
_PRIMARY_PX = 14
_META_PX = 12
_SMALL_PX = 11

# ---------------------------------------------------------------------------
# Icon helpers (identical to modrinth_modpack_browser)
# ---------------------------------------------------------------------------

_ICON_CACHE: dict[str, bytes] = {}


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
                "User-Agent": "NOTG-Launcher/Modrinth-Content",
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


def _draw_chip(
    p: QPainter,
    text: str,
    rect: QRectF,
    border_color: QColor,
    bg_color: QColor,
    text_color: QColor,
    radius: float = _BADGE_RADIUS,
) -> None:
    p.setPen(QPen(border_color, 1.2))
    p.setBrush(bg_color)
    p.drawRoundedRect(rect, radius, radius)
    p.setPen(text_color)
    p.drawText(rect, Qt.AlignCenter, text)


def _loader_badge_colors(loader: str) -> tuple[QColor, QColor, QColor]:
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
    return base, Mr.with_alpha(base, 24), base


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------

class RemoteContentWorker(QThread):
    loaded = Signal(str, object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(
        self,
        service: LauncherService,
        instance: InstanceRecord,
        job: str,
        *,
        content_type: str,
        query: str = "",
        project: dict[str, Any] | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._service = service
        self._instance = instance
        self._job = job
        self._content_type = content_type
        self._query = query
        self._project = dict(project or {})

    def run(self) -> None:
        try:
            if self._job == "search":
                projects = self._service.search_remote_content(
                    self._instance, provider="modrinth",
                    content_type=self._content_type, query=self._query, limit=24,
                )
                installed = self._service.remote_content_installed_index(self._instance, self._content_type)
                payload = {"projects": projects, "installed": list(installed)}
            elif self._job == "details":
                payload = self._service.get_remote_content_details(self._instance, self._project)
            elif self._job == "install":
                payload = self._service.install_remote_content(
                    self._instance, self._project, progress_callback=self.progress.emit,
                )
            else:
                raise ValueError(f"Unsupported remote content job: {self._job}")
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        if not self.isInterruptionRequested():
            self.loaded.emit(self._job, payload)


class RemoteIconWorker(QThread):
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
# ModCard – Compact list item (84px)
# ---------------------------------------------------------------------------

class ModCard(QWidget):
    clicked = Signal(object)
    install_clicked = Signal(object)

    def __init__(self, project: dict[str, Any], parent: QWidget | None = None):
        super().__init__(parent)
        self.project = project
        self._hover = 0.0
        self._selected = 0.0
        self._icon_pixmap: QPixmap | None = None
        self._install_state = "ready"
        self.setObjectName("modCard")
        self.setFixedHeight(_CARD_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)

        self._hover_anim = QVariantAnimation(self, duration=150, easingCurve=QEasingCurve.OutCubic, valueChanged=self._on_hover)
        self._select_anim = QVariantAnimation(self, duration=180, easingCurve=QEasingCurve.OutCubic, valueChanged=self._on_select)

    def _on_hover(self, v: float) -> None:
        self._hover = float(v)
        self.update()

    def _on_select(self, v: float) -> None:
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

    def set_state(self, state: str) -> None:
        self._install_state = state
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
            self.clicked.emit(self.project)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)

        bg = Mr.blend(Mr.BG_CARD, Mr.BG_CARD_HOVER, self._hover)
        bg = Mr.blend(bg, Mr.BG_CARD_ACTIVE, self._selected)
        border_col = Mr.blend(Mr.BORDER, Mr.GREEN, (self._hover + self._selected * 0.5) * 0.6)
        border_w = 1.0 + self._selected

        p.setPen(QPen(border_col, border_w))
        p.setBrush(bg)
        p.drawRoundedRect(rect, _CARD_RADIUS, _CARD_RADIUS)

        # Icon – 40×40, 8px radius
        icon_pad = 10
        icon_rect = QRectF(rect.left() + icon_pad, rect.top() + (rect.height() - _ICON_SIZE) / 2, _ICON_SIZE, _ICON_SIZE)
        if self._icon_pixmap is not None and not self._icon_pixmap.isNull():
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
            font.setPixelSize(18)
            font.setWeight(QFont.Bold)
            p.setFont(font)
            p.setPen(Mr.TEXT_MUTED)
            p.drawText(icon_rect, Qt.AlignCenter, (self.project.get("title") or "M")[0].upper())

        # Text area
        text_left = icon_rect.right() + 12
        install_btn_w = 72
        text_right = w - install_btn_w - 16
        text_width = text_right - text_left

        # Title (14px DemiBold)
        title = str(self.project.get("title") or "Untitled")
        title_font = QFont(self.font())
        title_font.setPixelSize(14)
        title_font.setWeight(QFont.DemiBold)
        p.setFont(title_font)
        p.setPen(Mr.TEXT)
        title_rect = QRectF(text_left, rect.top() + 10, text_width, 20)
        p.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, _truncate(title, 50))

        # Author + downloads (11px)
        author = str(self.project.get("author") or "Unknown")
        downloads = int(self.project.get("downloads") or 0)
        meta_font = QFont(self.font())
        meta_font.setPixelSize(11)
        p.setFont(meta_font)
        p.setPen(Mr.TEXT_SUBTLE)
        meta_text = f"{author}  ·  {_format_count(downloads)}"
        meta_rect = QRectF(text_left, rect.top() + 32, text_width, 16)
        p.drawText(meta_rect, Qt.AlignLeft | Qt.AlignVCenter, _truncate(meta_text, 45))

        # Category chips (bottom row)
        categories = self.project.get("categories") or self.project.get("display_categories") or []
        if isinstance(categories, list) and categories:
            badge_font = QFont(self.font())
            badge_font.setPixelSize(10)
            badge_font.setWeight(QFont.Medium)
            p.setFont(badge_font)
            bx = text_left
            by = rect.top() + 50
            gap = 4
            for cat in categories[:2]:
                cat_str = str(cat).strip()
                if not cat_str:
                    continue
                metrics = QFontMetrics(badge_font)
                bw = metrics.horizontalAdvance(cat_str) + 10
                bh = 16
                if bx + bw > text_right:
                    break
                badge_rect = QRectF(bx, by, bw, bh)
                _draw_chip(p, cat_str, badge_rect, Mr.with_alpha(Mr.GREEN, 60), Mr.with_alpha(Mr.GREEN, 15), Mr.GREEN, 8)
                bx += bw + gap

        # Install / Installed badge (right side, vertically centered)
        btn_h = 26
        btn_x = w - install_btn_w - 12
        btn_y = rect.top() + (rect.height() - btn_h) / 2
        btn_rect = QRectF(btn_x, btn_y, install_btn_w, btn_h)

        if self._install_state == "installed":
            p.setPen(QPen(Mr.INSTALLED, 1.0))
            p.setBrush(Mr.with_alpha(Mr.INSTALLED, 30))
            p.drawRoundedRect(btn_rect, 8, 8)
            btn_font = QFont(self.font())
            btn_font.setPixelSize(11)
            btn_font.setWeight(QFont.Medium)
            p.setFont(btn_font)
            p.setPen(Mr.INSTALLED)
            p.drawText(btn_rect, Qt.AlignCenter, "Installed")
        elif self._install_state == "installing":
            p.setPen(QPen(Mr.WARNING, 1.0))
            p.setBrush(Mr.with_alpha(Mr.WARNING, 22))
            p.drawRoundedRect(btn_rect, 8, 8)
            btn_font = QFont(self.font())
            btn_font.setPixelSize(11)
            btn_font.setWeight(QFont.Medium)
            p.setFont(btn_font)
            p.setPen(Mr.WARNING)
            p.drawText(btn_rect, Qt.AlignCenter, "...")
        else:
            hover_alpha = min(60, int(60 * self._hover * 1.5))
            btn_bg = Mr.blend(Mr.with_alpha(Mr.GREEN, 0), Mr.with_alpha(Mr.GREEN, 60), self._hover)
            p.setPen(QPen(Mr.with_alpha(Mr.GREEN, 180), 1.0))
            p.setBrush(btn_bg)
            p.drawRoundedRect(btn_rect, 8, 8)
            btn_font = QFont(self.font())
            btn_font.setPixelSize(11)
            btn_font.setWeight(QFont.Medium)
            p.setFont(btn_font)
            p.setPen(Mr.GREEN)
            p.drawText(btn_rect, Qt.AlignCenter, "Install")

    def sizeHint(self) -> QSize:
        return QSize(0, _CARD_HEIGHT)

    def is_install_hit(self, pos: QPoint) -> bool:
        w = self.width()
        btn_rect = QRectF(w - 72 - 12, (self.height() - 26) / 2, 72, 26)
        return btn_rect.contains(pos)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.is_install_hit(event.position()):
            self.install_clicked.emit(self.project)
            return
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# CategoryBadge – Pill badge for detail view categories
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


# ===================================================================
# Main Dialog – Modrinth-only Mod Installer (cleaned, balanced)
# ===================================================================

class InstallModsDialog(QDialog):
    def __init__(self, service: LauncherService, instance: InstanceRecord, parent: QWidget | None = None):
        super().__init__(parent)
        self.service = service
        self.instance = instance
        self._content_type = "mods"
        self._projects: list[dict[str, Any]] = []
        self._cards: dict[str, ModCard] = {}
        self._installed: set[str] = set()
        self._worker: RemoteContentWorker | None = None
        self._icon_worker: RemoteIconWorker | None = None
        self._active_job: str | None = None
        self._selected_project: dict[str, Any] | None = None
        self._installing_project_key: str | None = None
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._run_search)
        self._search_query = ""
        self._icon_cache_dir = self.service.cache_root / "remote-content-icons"

        mc_ver = self.instance.vanilla_version or "?"
        loader = self.instance.loader_name or "?"
        self.setObjectName("installModsDialog")
        self.setWindowTitle(f"Browse Mods — {instance.name}  ({loader} {mc_ver})")
        self.setModal(False)
        self.setMinimumSize(1100, 720)
        self.resize(fitted_window_size(self.parentWidget() or self, 1280, 840, minimum_width=1100, minimum_height=720))
        self._build_ui()
        self._apply_styles()
        QTimer.singleShot(0, self._run_search)

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.requestInterruption()
            self._worker.wait()
        if self._icon_worker is not None and self._icon_worker.isRunning():
            self._icon_worker.requestInterruption()
            self._icon_worker.wait()
        super().closeEvent(event)

    # ================================================================
    # UI Construction (balanced panels: 40% left, 60% right)
    # ================================================================

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
        # Balanced: left panel gets fixed stretch factor 3, right gets 5 (40/60)
        cl.addWidget(self._build_left_panel(), 3)
        divider = QFrame()
        divider.setObjectName("panelDivider")
        divider.setFixedWidth(1)
        cl.addWidget(divider)
        cl.addWidget(self._build_right_panel(), 5)
        root.addWidget(content, 1)
        root.addWidget(self._build_footer())

    def _build_header(self) -> QWidget:
        h = QWidget()
        h.setObjectName("browserHeader")
        h.setFixedHeight(50)
        layout = QHBoxLayout(h)
        layout.setContentsMargins(18, 0, 18, 0)
        layout.setSpacing(10)

        title = QLabel("Mod Browser")
        title.setObjectName("browserTitle")
        layout.addWidget(title)

        self.content_type_combo = QComboBox()
        self.content_type_combo.setObjectName("contentTypeCombo")
        self.content_type_combo.addItem("Mods", "mods")
        self.content_type_combo.addItem("Resource Packs", "resourcepacks")
        self.content_type_combo.currentIndexChanged.connect(self._on_content_type_changed)
        self.content_type_combo.setFixedWidth(140)
        layout.addWidget(self.content_type_combo)

        layout.addStretch()

        # Compact info badges
        loader = self.instance.loader_name or "?"
        mc_ver = self.instance.vanilla_version or "?"
        loader_badge = QLabel(loader.capitalize())
        loader_badge.setObjectName("infoBadge")
        layout.addWidget(loader_badge)
        mc_badge = QLabel(f"MC {mc_ver}")
        mc_badge.setObjectName("infoBadge")
        layout.addWidget(mc_badge)

        return h

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("leftPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Search row
        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(6)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search mods…")
        self.search_input.setObjectName("modSearchField")
        self.search_input.textChanged.connect(self._schedule_search)
        self.search_input.returnPressed.connect(self._run_search)
        search_row.addWidget(self.search_input, 1)
        search_btn = QPushButton("Search")
        search_btn.setObjectName("searchBtn")
        search_btn.clicked.connect(self._run_search)
        search_row.addWidget(search_btn)
        layout.addLayout(search_row)

        # Filter bar: category dropdown + sort
        filter_bar = QHBoxLayout()
        filter_bar.setContentsMargins(0, 0, 0, 0)
        filter_bar.setSpacing(6)

        self.category_combo = QComboBox()
        self.category_combo.setObjectName("filterCombo")
        self.category_combo.addItem("All Categories", "")
        self.category_combo.addItem("Performance", "performance")
        self.category_combo.addItem("Utility", "utility")
        self.category_combo.addItem("Storage", "storage")
        self.category_combo.addItem("World Gen", "worldgen")
        self.category_combo.addItem("Magic", "magic")
        self.category_combo.addItem("Tech", "technology")
        self.category_combo.addItem("Adventure", "adventure")
        self.category_combo.addItem("Decoration", "decoration")
        self.category_combo.addItem("Food", "food")
        self.category_combo.addItem("Mobs", "mobs")
        self.category_combo.setMinimumWidth(130)
        self.category_combo.currentIndexChanged.connect(self._run_search)
        filter_bar.addWidget(self.category_combo)

        self.sort_combo = QComboBox()
        self.sort_combo.setObjectName("filterCombo")
        self.sort_combo.addItem("Relevance", "relevance")
        self.sort_combo.addItem("Downloads", "downloads")
        self.sort_combo.addItem("Updated", "updated")
        self.sort_combo.setMinimumWidth(100)
        self.sort_combo.currentIndexChanged.connect(self._run_search)
        filter_bar.addWidget(self.sort_combo)

        filter_bar.addStretch()
        layout.addLayout(filter_bar)

        # Status
        self.list_status = QLabel("")
        self.list_status.setObjectName("listStatus")
        self.list_status.setFixedHeight(16)
        layout.addWidget(self.list_status)

        # Card scroll area
        self.card_scroll = QScrollArea()
        self.card_scroll.setObjectName("cardScroll")
        self.card_scroll.setWidgetResizable(True)
        self.card_scroll.setFrameShape(QFrame.NoFrame)
        self.card_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.card_container = QWidget()
        self.card_container.setObjectName("cardContainer")
        self.card_layout = QVBoxLayout(self.card_container)
        self.card_layout.setContentsMargins(0, 0, 0, 0)
        self.card_layout.setSpacing(4)
        self.card_layout.addStretch()
        self.card_scroll.setWidget(self.card_container)
        layout.addWidget(self.card_scroll, 1)

        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("rightPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.detail_scroll = QScrollArea()
        self.detail_scroll.setObjectName("detailScroll")
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFrameShape(QFrame.NoFrame)
        self.detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.detail_widget = QWidget()
        self.detail_widget.setObjectName("detailWidget")
        self.detail_layout = QVBoxLayout(self.detail_widget)
        self.detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_layout.setSpacing(0)

        # --- Detail inner ---
        self.detail_inner = QWidget()
        self.detail_inner.setObjectName("detailInner")
        inner = QVBoxLayout(self.detail_inner)
        inner.setContentsMargins(24, 24, 24, 20)
        inner.setSpacing(0)

        # === Hero: 80px icon + title/metadata/install button ===
        hero = QWidget()
        hero.setObjectName("detailHero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(0, 0, 0, 0)
        hero_layout.setSpacing(18)
        hero_layout.setAlignment(Qt.AlignTop)

        self.detail_icon = QLabel()
        self.detail_icon.setObjectName("detailIcon")
        self.detail_icon.setFixedSize(_LARGE_ICON_SIZE, _LARGE_ICON_SIZE)
        hero_layout.addWidget(self.detail_icon)

        # Title metadata column
        meta_col = QVBoxLayout()
        meta_col.setContentsMargins(0, 0, 0, 0)
        meta_col.setSpacing(4)

        # Title row with compact Install button
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)

        self.detail_title = QLabel()
        self.detail_title.setObjectName("detailTitle")
        self.detail_title.setWordWrap(True)
        title_row.addWidget(self.detail_title, 1)

        self.detail_install_btn = QPushButton("Install")
        self.detail_install_btn.setObjectName("detailInstallBtn")
        self.detail_install_btn.clicked.connect(self._on_detail_install)
        title_row.addWidget(self.detail_install_btn)
        meta_col.addLayout(title_row)

        self.detail_author = QLabel()
        self.detail_author.setObjectName("detailAuthor")
        meta_col.addWidget(self.detail_author)

        self.detail_stats = QLabel()
        self.detail_stats.setObjectName("detailStats")
        meta_col.addWidget(self.detail_stats)

        hero_layout.addLayout(meta_col, 1)
        inner.addWidget(hero)
        inner.addSpacing(16)

        # === Metadata grid (clean, complete) ===
        meta_grid = QWidget()
        meta_grid.setObjectName("detailMetaGrid")
        grid = QVBoxLayout(meta_grid)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)

        # Row: Categories
        cat_row = QWidget()
        cat_row.setObjectName("metaRow")
        cr = QHBoxLayout(cat_row)
        cr.setContentsMargins(0, 0, 0, 0)
        cr.setSpacing(8)
        cl = QLabel("Categories")
        cl.setObjectName("metaLabel")
        cr.addWidget(cl)
        self.detail_categories = QWidget()
        self.detail_categories.setObjectName("detailCategories")
        dc = QHBoxLayout(self.detail_categories)
        dc.setContentsMargins(0, 0, 0, 0)
        dc.setSpacing(6)
        dc.addStretch()
        cr.addWidget(self.detail_categories, 1)
        grid.addWidget(cat_row)

        # Row: MC Versions
        ver_row = QWidget()
        ver_row.setObjectName("metaRow")
        vr = QHBoxLayout(ver_row)
        vr.setContentsMargins(0, 0, 0, 0)
        vr.setSpacing(8)
        vl = QLabel("MC Versions")
        vl.setObjectName("metaLabel")
        vr.addWidget(vl)
        self.detail_version_badges = QWidget()
        self.detail_version_badges.setObjectName("detailTagRow")
        vb = QHBoxLayout(self.detail_version_badges)
        vb.setContentsMargins(0, 0, 0, 0)
        vb.setSpacing(4)
        vb.addStretch()
        vr.addWidget(self.detail_version_badges, 1)
        grid.addWidget(ver_row)

        # Row: Loaders
        loader_row = QWidget()
        loader_row.setObjectName("metaRow")
        lr = QHBoxLayout(loader_row)
        lr.setContentsMargins(0, 0, 0, 0)
        lr.setSpacing(8)
        ll = QLabel("Loaders")
        ll.setObjectName("metaLabel")
        lr.addWidget(ll)
        self.detail_loader_badges = QWidget()
        self.detail_loader_badges.setObjectName("detailTagRow")
        lb = QHBoxLayout(self.detail_loader_badges)
        lb.setContentsMargins(0, 0, 0, 0)
        lb.setSpacing(4)
        lb.addStretch()
        lr.addWidget(self.detail_loader_badges, 1)
        grid.addWidget(loader_row)

        # Row: Dependencies
        dep_row = QWidget()
        dep_row.setObjectName("metaRow")
        dr = QHBoxLayout(dep_row)
        dr.setContentsMargins(0, 0, 0, 0)
        dr.setSpacing(8)
        dl = QLabel("Dependencies")
        dl.setObjectName("metaLabel")
        dr.addWidget(dl)
        self.detail_deps = QLabel("None")
        self.detail_deps.setObjectName("metaValue")
        dr.addWidget(self.detail_deps, 1)
        grid.addWidget(dep_row)

        # Row: Links
        link_row = QWidget()
        link_row.setObjectName("metaRow")
        lkr = QHBoxLayout(link_row)
        lkr.setContentsMargins(0, 0, 0, 0)
        lkr.setSpacing(8)
        lkl = QLabel("Links")
        lkl.setObjectName("metaLabel")
        lkr.addWidget(lkl)
        self.detail_links = QLabel("Modrinth")
        self.detail_links.setObjectName("metaValue")
        lkr.addWidget(self.detail_links, 1)
        grid.addWidget(link_row)

        # Row: License (if available)
        self.detail_license_row = QWidget()
        self.detail_license_row.setObjectName("metaRow")
        licr = QHBoxLayout(self.detail_license_row)
        licr.setContentsMargins(0, 0, 0, 0)
        licr.setSpacing(8)
        lcl = QLabel("License")
        lcl.setObjectName("metaLabel")
        licr.addWidget(lcl)
        self.detail_license = QLabel("")
        self.detail_license.setObjectName("metaValue")
        licr.addWidget(self.detail_license, 1)
        grid.addWidget(self.detail_license_row)
        self.detail_license_row.setVisible(False)

        # Row: Published / Updated
        self.detail_dates_row = QWidget()
        self.detail_dates_row.setObjectName("metaRow")
        dtr = QHBoxLayout(self.detail_dates_row)
        dtr.setContentsMargins(0, 0, 0, 0)
        dtr.setSpacing(8)
        dtl = QLabel("Published")
        dtl.setObjectName("metaLabel")
        dtr.addWidget(dtl)
        self.detail_dates = QLabel("")
        self.detail_dates.setObjectName("metaValue")
        dtr.addWidget(self.detail_dates, 1)
        grid.addWidget(self.detail_dates_row)
        self.detail_dates_row.setVisible(False)

        inner.addWidget(meta_grid)
        inner.addSpacing(16)

        # === Description ===
        desc_section = QWidget()
        desc_section.setObjectName("detailSection")
        ds = QVBoxLayout(desc_section)
        ds.setContentsMargins(0, 0, 0, 0)
        ds.setSpacing(8)

        desc_heading = QLabel("Description")
        desc_heading.setObjectName("sectionTitle")
        ds.addWidget(desc_heading)

        self.detail_description = QLabel()
        self.detail_description.setObjectName("detailDescription")
        self.detail_description.setWordWrap(True)
        self.detail_description.setOpenExternalLinks(True)
        self.detail_description.setTextFormat(Qt.RichText)
        ds.addWidget(self.detail_description)
        inner.addWidget(desc_section)

        inner.addSpacing(16)

        # === Screenshots ===
        self.detail_screenshots_section = QWidget()
        self.detail_screenshots_section.setObjectName("detailSection")
        ss = QVBoxLayout(self.detail_screenshots_section)
        ss.setContentsMargins(0, 0, 0, 0)
        ss.setSpacing(8)

        ss_heading = QLabel("Screenshots")
        ss_heading.setObjectName("sectionTitle")
        ss.addWidget(ss_heading)

        ss_scroll = QScrollArea()
        ss_scroll.setObjectName("screenshotScroll")
        ss_scroll.setWidgetResizable(True)
        ss_scroll.setFrameShape(QFrame.NoFrame)
        ss_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ss_scroll.setMaximumHeight(110)
        self.detail_screenshots = QWidget()
        self.detail_screenshots.setObjectName("screenshotContainer")
        self.screenshots_layout = QHBoxLayout(self.detail_screenshots)
        self.screenshots_layout.setContentsMargins(0, 0, 0, 0)
        self.screenshots_layout.setSpacing(8)
        self.screenshots_layout.addStretch()
        ss_scroll.setWidget(self.detail_screenshots)
        ss.addWidget(ss_scroll)
        self.detail_screenshots_section.setVisible(False)
        inner.addWidget(self.detail_screenshots_section)

        inner.addStretch()
        self.detail_layout.addWidget(self.detail_inner)

        # Placeholder
        self.detail_placeholder = QLabel("Select a mod to view details")
        self.detail_placeholder.setObjectName("detailPlaceholder")
        self.detail_placeholder.setAlignment(Qt.AlignCenter)
        self.detail_layout.addWidget(self.detail_placeholder, 1)

        self.detail_loading = QLabel("Loading mod details…")
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
        footer.setFixedHeight(40)
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(8)
        self.footer_info = QLabel("")
        self.footer_info.setObjectName("footerInfo")
        layout.addWidget(self.footer_info, 1)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("footerCloseBtn")
        close_btn.clicked.connect(self.reject)
        layout.addWidget(close_btn)
        return footer

    # ================================================================
    # Styles
    # ================================================================

    def _apply_styles(self) -> None:
        self.setStyleSheet(f"""
        QDialog#installModsDialog {{
            background-color: {_mr_css(Mr.BG)};
        }}
        QWidget#browserHeader {{
            background-color: {_mr_css(Mr.BG_PANEL)};
            border-bottom: 1px solid {_mr_css(Mr.BORDER)};
        }}
        QLabel#browserTitle {{
            color: {_mr_css(Mr.TEXT)};
            font-size: 16px;
            font-weight: 700;
            background: transparent;
        }}
        QLabel#infoBadge {{
            background-color: {_mr_css(Mr.BG_ELEVATED)};
            border: 1px solid {_mr_css(Mr.BORDER)};
            border-radius: 5px;
            color: {_mr_css(Mr.TEXT_MUTED)};
            font-size: 11px;
            font-weight: 600;
            padding: 2px 10px;
        }}
        QWidget#browserFooter {{
            background-color: {_mr_css(Mr.BG_PANEL)};
            border-top: 1px solid {_mr_css(Mr.BORDER)};
        }}
        QLabel#footerInfo {{
            color: {_mr_css(Mr.TEXT_MUTED)};
            font-size: 11px;
            background: transparent;
        }}
        QPushButton#footerCloseBtn {{
            background-color: {_mr_css(Mr.BG_ELEVATED)};
            border: 1px solid {_mr_css(Mr.BORDER)};
            border-radius: 6px;
            color: {_mr_css(Mr.TEXT)};
            font-size: 12px;
            font-weight: 600;
            padding: 4px 16px;
            min-height: 26px;
        }}
        QPushButton#footerCloseBtn:hover {{
            background-color: {_mr_css(Mr.BG_CARD_HOVER)};
            border-color: {_mr_css(Mr.GREEN)};
        }}
        QWidget#leftPanel {{
            background-color: {_mr_css(Mr.BG_CARD)};
            border: 1px solid {_mr_css(Mr.BORDER)};
            border-radius: 10px;
        }}
        QWidget#rightPanel {{
            background-color: {_mr_css(Mr.BG_SURFACE)};
            border: 1px solid {_mr_css(Mr.BORDER)};
            border-radius: 10px;
        }}
        QFrame#panelDivider {{
            background-color: {_mr_css(Mr.SEPARATOR)};
            max-width: 1px;
            border: none;
        }}
        QScrollArea#cardScroll, QScrollArea#detailScroll, QScrollArea#screenshotScroll {{
            background: transparent;
            border: none;
        }}
        QWidget#cardContainer, QWidget#detailWidget, QWidget#detailInner {{
            background: transparent;
        }}
        QLineEdit#modSearchField {{
            background-color: {_mr_css(Mr.BG_INPUT)};
            border: 1px solid {_mr_css(Mr.BORDER)};
            border-radius: 7px;
            color: {_mr_css(Mr.TEXT)};
            font-size: 12px;
            padding: 5px 10px;
            min-height: 28px;
        }}
        QLineEdit#modSearchField:focus {{
            border: 1px solid {_mr_css(Mr.GREEN_BRIGHT)};
        }}
        QLineEdit#modSearchField::placeholder {{
            color: {_mr_css(Mr.TEXT_MUTED)};
        }}
        QPushButton#searchBtn {{
            background-color: {_mr_css(Mr.GREEN_DIM)};
            border: 1px solid {_mr_css(Mr.GREEN)};
            border-radius: 6px;
            color: {_mr_css(Mr.BG)};
            font-size: 12px;
            font-weight: 700;
            padding: 4px 14px;
            min-height: 28px;
        }}
        QPushButton#searchBtn:hover {{
            background-color: {_mr_css(Mr.GREEN)};
        }}
        QPushButton#detailInstallBtn {{
            background-color: {_mr_css(Mr.GREEN_DIM)};
            border: 1px solid {_mr_css(Mr.GREEN)};
            border-radius: 6px;
            color: {_mr_css(Mr.BG)};
            font-size: 13px;
            font-weight: 700;
            padding: 6px 20px;
            min-height: 32px;
            min-width: 90px;
        }}
        QPushButton#detailInstallBtn:hover {{
            background-color: {_mr_css(Mr.GREEN)};
        }}
        QPushButton#detailInstallBtn:disabled {{
            background-color: {_mr_css(Mr.BG_ELEVATED)};
            border-color: {_mr_css(Mr.BORDER)};
            color: {_mr_css(Mr.TEXT_SUBTLE)};
        }}
        QLabel#listStatus {{
            color: {_mr_css(Mr.TEXT_SUBTLE)};
            font-size: 10px;
            background: transparent;
        }}
        QLabel#detailPlaceholder {{
            color: {_mr_css(Mr.TEXT_MUTED)};
            font-size: 14px;
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
            font-size: 15px;
            background: transparent;
        }}
        QLabel#detailStats {{
            color: {_mr_css(Mr.TEXT_SUBTLE)};
            font-size: {_META_PX}px;
            font-weight: 400;
            background: transparent;
        }}
        QLabel#sectionTitle {{
            color: {_mr_css(Mr.TEXT)};
            font-size: {_SECTION_PX}px;
            font-weight: 600;
            background: transparent;
        }}
        QLabel#detailDescription {{
            color: {_mr_css(Mr.TEXT_MUTED)};
            font-size: 13px;
            line-height: 1.6;
            background: transparent;
        }}
        QLabel#metaLabel {{
            color: {_mr_css(Mr.TEXT_SUBTLE)};
            font-size: 12px;
            font-weight: 500;
            background: transparent;
            min-width: 90px;
        }}
        QLabel#metaValue {{
            color: {_mr_css(Mr.TEXT_MUTED)};
            font-size: 12px;
            background: transparent;
        }}
        QWidget#detailHero, QWidget#detailMetaGrid, QWidget#detailSection, QWidget#detailCategories,
        QWidget#metaRow, QWidget#detailTagRow {{
            background: transparent;
        }}
        QLabel#detailIcon {{
            background-color: {_mr_css(Mr.BG_ELEVATED)};
            border: 1px solid {_mr_css(Mr.BORDER)};
            border-radius: 10px;
        }}
        QComboBox#contentTypeCombo, QComboBox#filterCombo {{
            background-color: {_mr_css(Mr.BG_INPUT)};
            border: 1px solid {_mr_css(Mr.BORDER)};
            border-radius: 6px;
            color: {_mr_css(Mr.TEXT)};
            font-size: 11px;
            padding: 3px 8px;
            min-height: 24px;
        }}
        QComboBox#contentTypeCombo::drop-down, QComboBox#filterCombo::drop-down {{
            border: none;
            width: 16px;
        }}
        QComboBox#contentTypeCombo QAbstractItemView, QComboBox#filterCombo QAbstractItemView {{
            background-color: {_mr_css(Mr.BG_SURFACE)};
            border: 1px solid {_mr_css(Mr.BORDER)};
            selection-background-color: {_mr_css(Mr.GREEN_SOFT)};
            selection-color: {_mr_css(Mr.GREEN)};
            color: {_mr_css(Mr.TEXT)};
            font-size: 11px;
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
    # Search & Content Loading
    # ================================================================

    def _schedule_search(self) -> None:
        if self._active_job == "install":
            return
        self._search_timer.start()

    def _on_content_type_changed(self) -> None:
        self._content_type = str(self.content_type_combo.currentData() or "mods")
        self._run_search()

    def _run_search(self) -> None:
        if self._active_job == "install":
            return
        self._search_timer.stop()
        self._search_query = self.search_input.text().strip()
        self.list_status.setText("Searching…")
        self._clear_cards()
        self._hide_details()
        self.detail_placeholder.setText("Searching for mods…")
        self.detail_placeholder.setVisible(True)
        self._start_worker("search", query=self._search_query)

    def _start_worker(self, job: str, *, query: str = "", project: dict[str, Any] | None = None) -> None:
        if self._worker is not None and self._worker.isRunning():
            if self._active_job == "install":
                return
            self._worker.requestInterruption()
            self._worker.wait()
        self._active_job = job
        self._worker = RemoteContentWorker(
            self.service, self.instance, job,
            content_type=self._content_type, query=query, project=project, parent=self,
        )
        self._worker.loaded.connect(self._on_worker_loaded)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.progress.connect(self._on_install_progress)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_worker_loaded(self, job: str, payload: object) -> None:
        if job == "search":
            if isinstance(payload, dict):
                self._projects = list(payload.get("projects")) if isinstance(payload.get("projects"), list) else []
                self._installed = {str(item) for item in payload.get("installed", []) if item}
            else:
                self._projects = list(payload) if isinstance(payload, list) else []
            self._populate_results()
            return
        if job == "details":
            if isinstance(payload, dict):
                self._show_details(payload)
            return
        if job == "install":
            key = self._installing_project_key
            if key:
                self._installed.add(key)
                if self._selected_project is not None:
                    self._installed.update(self._project_key_candidates(self._selected_project))
                self._set_card_state(key, "installed")
                if self._selected_project is not None and self._project_key(self._selected_project) == key:
                    self._set_detail_install_state("installed")

    def _on_worker_failed(self, message: str) -> None:
        self.list_status.setText("Search failed")
        QMessageBox.warning(self, "Error", message)
        failed_key = self._installing_project_key
        if failed_key:
            self._set_card_state(failed_key, "ready")
        if self._selected_project is not None and self._project_key(self._selected_project) == failed_key:
            self._set_detail_install_state("ready")

    def _on_worker_finished(self) -> None:
        finished_job = self._active_job
        self._active_job = None
        if finished_job == "install":
            self._installing_project_key = None
            self._set_controls_enabled(True)

    def _on_install_progress(self, message: str) -> None:
        if message and self._selected_project:
            self.detail_title.setText(message)

    # ================================================================
    # Results
    # ================================================================

    def _populate_results(self) -> None:
        self._clear_cards()
        if not self._projects:
            self.list_status.setText("No mods found")
            self.detail_placeholder.setText("No mods found for this instance")
            self.detail_placeholder.setVisible(True)
            return

        n = len(self._projects)
        self.list_status.setText(f"{n} mod{'s' if n != 1 else ''} found")

        for project in self._projects:
            card = ModCard(project)
            card.clicked.connect(self._on_card_clicked)
            card.install_clicked.connect(self._install_project)
            state = "installed" if self._is_project_installed(project) else "ready"
            card.set_state(state)
            self.card_layout.insertWidget(self.card_layout.count() - 1, card)
            self._cards[self._project_key(project)] = card

        if self._projects:
            first = self._projects[0]
            card = self._cards.get(self._project_key(first))
            if card:
                card.set_selected(True)
                self._selected_project = first
                self._start_worker("details", project=first)

        self._start_icon_worker()

    def _clear_cards(self) -> None:
        for i in reversed(range(self.card_layout.count())):
            item = self.card_layout.itemAt(i)
            if item and item.widget():
                w = item.widget()
                self.card_layout.removeWidget(w)
                w.deleteLater()
        self._cards.clear()
        self.card_layout.addStretch()

    def _start_icon_worker(self) -> None:
        targets: list[tuple[str, str]] = []
        for project in self._projects:
            url = str(project.get("icon_url") or "")
            if url.startswith(("http://", "https://")):
                targets.append((self._project_key(project), url))
        if not targets:
            return
        worker = RemoteIconWorker(targets, self._icon_cache_dir, self)
        worker.icon_loaded.connect(self._on_icon_loaded)
        worker.finished.connect(lambda w=worker: setattr(self, "_icon_worker", None) if self._icon_worker is w else None)
        self._icon_worker = worker
        worker.start()

    def _on_icon_loaded(self, key: str, data: object) -> None:
        if not isinstance(data, (bytes, bytearray)):
            return
        card = self._cards.get(key)
        if card:
            card.set_icon_data(bytes(data))
        if self._selected_project and self._project_key(self._selected_project) == key:
            pix = QPixmap()
            if pix.loadFromData(bytes(data)):
                scaled = pix.scaled(_LARGE_ICON_SIZE, _LARGE_ICON_SIZE, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                self.detail_icon.setPixmap(scaled)

    def _on_card_clicked(self, project: dict[str, Any]) -> None:
        for card in self._cards.values():
            card.set_selected(False)
        key = self._project_key(project)
        card = self._cards.get(key)
        if card:
            card.set_selected(True)
        self._selected_project = project
        self._hide_details()
        self.detail_loading.setVisible(True)
        if self._active_job == "install":
            return
        self._start_worker("details", project=project)

    def _hide_details(self) -> None:
        self.detail_inner.setVisible(False)
        self.detail_placeholder.setVisible(False)
        self.detail_loading.setVisible(False)

    # ================================================================
    # Details Display – full, complete project page
    # ================================================================

    def _show_details(self, project: dict[str, Any]) -> None:
        self.detail_loading.setVisible(False)
        self.detail_inner.setVisible(True)
        self.detail_placeholder.setVisible(False)

        # Title – 28px bold
        self.detail_title.setText(str(project.get("title") or "Untitled"))
        self.detail_author.setText(f"by {project.get('author') or 'Unknown'}")

        downloads = int(project.get("downloads") or 0)
        follows = int(project.get("follows") or 0)
        self.detail_stats.setText(f"{_format_count(downloads)} downloads  •  {_format_count(follows)} follows")

        # Categories
        cat_layout = self.detail_categories.layout()
        while cat_layout.count() > 1:
            item = cat_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        categories = project.get("categories") or project.get("display_categories") or []
        if isinstance(categories, list):
            for cat in categories[:8]:
                cs = str(cat).strip()
                if cs:
                    cat_layout.insertWidget(cat_layout.count() - 1, CategoryBadge(cs))

        # MC Versions – pill badges
        vb_layout = self.detail_version_badges.layout()
        while vb_layout.count() > 1:
            item = vb_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        game_versions = project.get("game_versions") or []
        if isinstance(game_versions, list):
            for ver in game_versions[:6]:
                vs = str(ver)
                lbl = QLabel(vs)
                lbl.setStyleSheet(f"""
                    background-color: {_mr_css(Mr.with_alpha(Mr.TEXT_MUTED, 20))};
                    border: 1px solid {_mr_css(Mr.with_alpha(Mr.TEXT_MUTED, 60))};
                    border-radius: 10px;
                    color: {_mr_css(Mr.TEXT_MUTED)};
                    font-size: 11px;
                    font-weight: 500;
                    padding: 2px 10px;
                """)
                vb_layout.insertWidget(vb_layout.count() - 1, lbl)

        # Loaders – colored pill badges
        lb_layout = self.detail_loader_badges.layout()
        while lb_layout.count() > 1:
            item = lb_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        loaders = project.get("loaders") or []
        if isinstance(loaders, list):
            for loader in loaders[:4]:
                lc = loader.capitalize()
                lbl = QLabel(lc)
                base, _, _ = _loader_badge_colors(loader)
                lbl.setStyleSheet(f"""
                    background-color: {_mr_css(Mr.with_alpha(base, 22))};
                    border: 1px solid {_mr_css(Mr.with_alpha(base, 80))};
                    border-radius: 10px;
                    color: {_mr_css(base)};
                    font-size: 11px;
                    font-weight: 500;
                    padding: 2px 10px;
                """)
                lb_layout.insertWidget(lb_layout.count() - 1, lbl)

        # Dependencies - resolved to actual names
        deps = project.get("dependencies") or []
        if isinstance(deps, list) and deps:
            dep_count = len(deps)
            # Use resolved dependency names if available (set by worker), otherwise show IDs
            dep_names_raw = []
            for d in deps[:5]:
                pid = str(d.get("project_id") or d.get("version_id") or "?")
                dep_names_raw.append(pid)
            resolved_names = project.get("_resolved_dependency_names") or []
            if resolved_names:
                dep_names = resolved_names[:5]
            else:
                dep_names = dep_names_raw
            dep_text = ", ".join(dep_names)
            if dep_count > 5:
                dep_text += f" + {dep_count - 5} more"
            self.detail_deps.setText(f"{dep_count} required — {dep_text}")
        else:
            deps_count = project.get("dependencies_count") or 0
            if deps_count:
                self.detail_deps.setText(f"{deps_count} required")
            else:
                self.detail_deps.setText("None")

        # Links
        links: list[str] = []
        project_url = str(project.get("project_url") or project.get("url") or "")
        source_url = str(project.get("source_url") or "")
        issues_url = str(project.get("issues_url") or "")
        wiki_url = str(project.get("wiki_url") or "")
        if project_url:
            links.append("Project Page")
        if source_url:
            links.append("Source")
        if issues_url:
            links.append("Issues")
        if wiki_url:
            links.append("Wiki")
        self.detail_links.setText(" | ".join(links) if links else "Modrinth")

        # License (optional metadata)
        license_name = project.get("license") or ""
        if isinstance(license_name, dict):
            license_name = str(license_name.get("name") or license_name.get("id") or "")
        if license_name:
            self.detail_license.setText(str(license_name))
            self.detail_license_row.setVisible(True)
        else:
            self.detail_license_row.setVisible(False)

        # Dates
        date_parts: list[str] = []
        date_created = project.get("date_created") or ""
        date_modified = project.get("date_modified") or project.get("updated") or ""
        if date_created:
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(str(date_created).replace("Z", "+00:00"))
                date_parts.append(f"Created {dt.strftime('%b %Y')}")
            except (ValueError, TypeError):
                pass
        if date_modified:
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(str(date_modified).replace("Z", "+00:00"))
                date_parts.append(f"Updated {dt.strftime('%b %Y')}")
            except (ValueError, TypeError):
                pass
        if date_parts:
            self.detail_dates.setText("  •  ".join(date_parts))
            self.detail_dates_row.setVisible(True)
        else:
            self.detail_dates_row.setVisible(False)

        # Description
        desc = str(project.get("description") or "No description available.")
        self.detail_description.setText(desc)

        # Screenshots
        self.detail_screenshots_section.setVisible(False)
        gallery = project.get("gallery") or []
        if isinstance(gallery, list) and gallery:
            self.detail_screenshots_section.setVisible(True)
            self._clear_screenshots()
            for img in gallery[:8]:
                if isinstance(img, dict):
                    img_url = str(img.get("url") or "")
                    if img_url.startswith(("http://", "https://")):
                        data = _load_icon_bytes(img_url, self._icon_cache_dir)
                        if data:
                            self._on_screenshot_loaded(img_url, data)

        # Install state
        state = "installed" if self._is_project_installed(project) else "ready"
        self._set_detail_install_state(state)

        # Large icon
        icon_url = str(project.get("icon_url") or "")
        if icon_url.startswith(("http://", "https://")):
            data = _load_icon_bytes(icon_url, self._icon_cache_dir)
            if data:
                pix = QPixmap()
                if pix.loadFromData(data):
                    scaled = pix.scaled(_LARGE_ICON_SIZE, _LARGE_ICON_SIZE, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                    self.detail_icon.setPixmap(scaled)

        self.footer_info.setText(f"Viewing: {project.get('title') or 'Untitled'}")

    def _clear_screenshots(self) -> None:
        while self.screenshots_layout.count() > 1:
            item = self.screenshots_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

    def _on_screenshot_loaded(self, key: str, data: object) -> None:
        if not isinstance(data, (bytes, bytearray)):
            return
        pix = QPixmap()
        if pix.loadFromData(bytes(data)):
            scaled = pix.scaled(140, 80, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            label = QLabel()
            label.setFixedSize(140, 80)
            label.setPixmap(scaled)
            label.setStyleSheet(f"border:1px solid {_mr_css(Mr.with_alpha(Mr.TEXT, 16))}; border-radius:6px;")
            self.screenshots_layout.insertWidget(self.screenshots_layout.count() - 1, label)

    # ================================================================
    # Installation
    # ================================================================

    def _install_project(self, project: dict[str, Any] | None) -> None:
        if self._active_job == "install":
            return
        if not project:
            return
        self._selected_project = project
        key = self._project_key(project)
        if self._is_project_installed(project):
            return
        self._installing_project_key = key
        self._set_card_state(key, "installing")
        self._set_detail_install_state("installing")
        self._set_controls_enabled(False)
        self._start_worker("install", project=project)

    def _on_detail_install(self) -> None:
        self._install_project(self._selected_project)

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.search_input.setEnabled(enabled)
        self.content_type_combo.setEnabled(enabled)
        self.sort_combo.setEnabled(enabled)
        self.category_combo.setEnabled(enabled)

    def _set_card_state(self, key: str, state: str) -> None:
        card = self._cards.get(key)
        if card:
            card.set_state(state)

    def _set_detail_install_state(self, state: str) -> None:
        if state == "installing":
            self.detail_install_btn.setText("Installing…")
            self.detail_install_btn.setEnabled(False)
        elif state == "installed":
            self.detail_install_btn.setText("Installed ✓")
            self.detail_install_btn.setEnabled(False)
        else:
            self.detail_install_btn.setText("Install")
            self.detail_install_btn.setEnabled(True)

    def _is_project_installed(self, project: dict[str, Any]) -> bool:
        return bool(self._project_key_candidates(project) & self._installed)

    def _project_key(self, project: dict[str, Any]) -> str:
        candidates = sorted(self._project_key_candidates(project))
        return candidates[0] if candidates else f"modrinth:{project.get('project_id') or project.get('slug')}"

    def _project_key_candidates(self, project: dict[str, Any]) -> set[str]:
        candidates: set[str] = set()
        for key_name in ("project_id", "slug"):
            value = str(project.get(key_name) or "").strip()
            if value:
                candidates.add(f"modrinth:{value.lower()}")
                normalized = _slug(value)
                if normalized:
                    candidates.add(f"modrinth:{normalized}")
        title = str(project.get("title") or "").strip()
        if title:
            normalized = _slug(title)
            if normalized:
                candidates.add(f"modrinth:{normalized}")
        return candidates


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return text