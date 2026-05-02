from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEasingCurve, QRectF, QSize, Qt, QTimer, QUrl, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImageReader, QPainter, QPen, QPixmap, QTextOption
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
except ImportError:  # pragma: no cover - depends on the local Qt build
    QAudioOutput = None
    QMediaPlayer = None
    QVideoSink = None

from core.launcher import BACKGROUND_SUFFIXES, BackgroundRecord, LauncherService
from ui.responsive import fitted_window_size, scaled_px, screen_scale
from ui.theme import theme_palette
from ui.topbar import ModernButton, blend_colors


class BackgroundTile(QWidget):
    clicked = Signal(str)

    def __init__(self, background_record: BackgroundRecord, parent: QWidget | None = None):
        super().__init__(parent)
        self.background_record = background_record
        self._tile_width = 188
        self._tile_height = 164
        self._thumbnail = QPixmap()
        self._hover = 0.0
        self._press = 0.0
        self._selected = 0.0

        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setMouseTracking(True)

        self._hover_animation = QVariantAnimation(
            self,
            duration=170,
            easingCurve=QEasingCurve.OutCubic,
            valueChanged=self._set_hover,
        )
        self._press_animation = QVariantAnimation(
            self,
            duration=120,
            easingCurve=QEasingCurve.OutCubic,
            valueChanged=self._set_press,
        )
        self._selected_animation = QVariantAnimation(
            self,
            duration=180,
            easingCurve=QEasingCurve.OutCubic,
            valueChanged=self._set_selected,
        )

    def sizeHint(self) -> QSize:
        return QSize(self._tile_width, self._tile_height)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def set_tile_size(self, width: int, height: int) -> None:
        self._tile_width = width
        self._tile_height = height
        self.setFixedSize(width, height)
        self.updateGeometry()
        self.update()

    def set_thumbnail(self, pixmap: QPixmap) -> None:
        self._thumbnail = pixmap
        self.update()

    def set_selected(self, selected: bool) -> None:
        self._selected_animation.stop()
        self._selected_animation.setStartValue(self._selected)
        self._selected_animation.setEndValue(1.0 if selected else 0.0)
        self._selected_animation.start()

    def _set_hover(self, value: float) -> None:
        self._hover = float(value)
        self.update()

    def _set_press(self, value: float) -> None:
        self._press = float(value)
        self.update()

    def _set_selected(self, value: float) -> None:
        self._selected = float(value)
        self.update()

    def enterEvent(self, event) -> None:
        self._hover_animation.stop()
        self._hover_animation.setStartValue(self._hover)
        self._hover_animation.setEndValue(1.0)
        self._hover_animation.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_animation.stop()
        self._hover_animation.setStartValue(self._hover)
        self._hover_animation.setEndValue(0.0)
        self._hover_animation.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press_animation.stop()
            self._press_animation.setStartValue(self._press)
            self._press_animation.setEndValue(1.0)
            self._press_animation.start()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._press_animation.stop()
        self._press_animation.setStartValue(self._press)
        self._press_animation.setEndValue(0.0)
        self._press_animation.start()
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.background_record.relative_path)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        del event
        palette = theme_palette(self)["icon_tile"]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        scale = screen_scale(self, minimum=0.9, maximum=1.05)

        inset = 7 * scale
        rect = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        rect.translate(0, -1.0 * self._hover + 0.8 * self._press)

        shadow_rect = rect.adjusted(0, 5 * scale + self._press, 0, 7 * scale + self._press)
        painter.setPen(Qt.NoPen)
        shadow = blend_colors(palette["shadow"], palette["shadow_hover"], self._hover)
        painter.setBrush(shadow)
        painter.drawRoundedRect(shadow_rect, 12 * scale, 12 * scale)

        fill_top = blend_colors(palette["outer_top"], palette["outer_top_hover"], self._hover)
        fill_top = blend_colors(fill_top, palette["outer_top_selected"], self._selected)
        border = blend_colors(palette["border"], palette["border_selected"], self._selected)
        border = blend_colors(border, palette["border_hover"], self._hover * 0.4)
        painter.setPen(QPen(border, max(1.0, 1.15 * scale)))
        painter.setBrush(fill_top)
        painter.drawRoundedRect(rect, 12 * scale, 12 * scale)

        preview = rect.adjusted(10 * scale, 10 * scale, -10 * scale, -58 * scale)
        painter.setPen(QPen(palette["inner_border"], max(1.0, scale)))
        painter.setBrush(palette["inner_fill"])
        painter.drawRoundedRect(preview, 9 * scale, 9 * scale)

        if self._thumbnail.isNull():
            painter.setPen(theme_palette(self)["background_preview"]["text"])
            painter.drawText(preview, Qt.AlignCenter, "No preview")
        else:
            scaled = self._thumbnail.scaled(
                int(preview.width()),
                int(preview.height()),
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            source_x = max(0, int((scaled.width() - preview.width()) / 2))
            source_y = max(0, int((scaled.height() - preview.height()) / 2))
            painter.drawPixmap(
                int(preview.left()),
                int(preview.top()),
                scaled,
                source_x,
                source_y,
                int(preview.width()),
                int(preview.height()),
            )

        if self.background_record.is_video:
            self._draw_video_tag(painter, preview, scale)

        label_rect = rect.adjusted(12 * scale, rect.height() - 49 * scale, -12 * scale, -6 * scale)
        font = QFont(self.font())
        font.setPointSizeF(max(7.5, 9.5 * scale))
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(theme_palette(self)["instance_card"]["text"])
        option = QTextOption(Qt.AlignCenter)
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        painter.drawText(label_rect, self.background_record.name, option)

        if self._selected > 0.02:
            glow = rect.adjusted(2 * scale, 2 * scale, -2 * scale, -2 * scale)
            accent = blend_colors(palette["glow_start"], palette["glow_end"], self._selected)
            painter.setPen(QPen(accent, max(1.2, 1.8 * scale)))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(glow, 10 * scale, 10 * scale)

    def _draw_video_tag(self, painter: QPainter, preview: QRectF, scale: float) -> None:
        tag_font = QFont(self.font())
        tag_font.setPointSizeF(max(7.0, 8.0 * scale))
        tag_font.setWeight(QFont.Weight.Bold)
        metrics = QFontMetrics(tag_font)
        text = "VIDEO"
        width = metrics.horizontalAdvance(text) + int(13 * scale)
        tag = QRectF(preview.left() + 8 * scale, preview.top() + 8 * scale, width, 21 * scale)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(16, 26, 43, 210))
        painter.drawRoundedRect(tag, 6 * scale, 6 * scale)
        painter.setPen(QColor("#dcecff"))
        painter.setFont(tag_font)
        painter.drawText(tag, Qt.AlignCenter, text)


class BackgroundSelectorDialog(QDialog):
    active_background_changed = Signal(str)

    _GRID_COLUMNS = 4

    def __init__(
        self,
        service: LauncherService,
        selected_background_path: str | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.service = service
        self.selected_background_path = selected_background_path or self.service.get_active_background_reference()
        self._tiles: dict[str, BackgroundTile] = {}
        self._video_queue: list[BackgroundRecord] = []
        self._pending_video: BackgroundRecord | None = None
        self._thumbnail_player = None
        self._thumbnail_audio = None
        self._thumbnail_sink = None
        self._thumbnail_timeout = QTimer(self)
        self._thumbnail_timeout.setSingleShot(True)
        self._thumbnail_timeout.timeout.connect(self._skip_video_thumbnail)

        self.setObjectName("backgroundSelectorDialog")
        self.setWindowTitle("Pick Background")
        self.setModal(True)
        self.setMinimumSize(760, 700)
        self.resize(fitted_window_size(self.parentWidget() or self, 980, 820, minimum_width=760, minimum_height=700))

        self._build_ui()
        self._apply_responsive_layout()
        self._reload_backgrounds(self.selected_background_path)

    def showEvent(self, event) -> None:
        self._apply_responsive_layout()
        super().showEvent(event)

    def resizeEvent(self, event) -> None:
        self._apply_responsive_layout()
        super().resizeEvent(event)

    def closeEvent(self, event) -> None:
        self._stop_thumbnail_player()
        super().closeEvent(event)

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(20, 20, 20, 20)
        root_layout.setSpacing(14)

        presentation = QFrame()
        presentation.setObjectName("iconPresentationSurface")
        presentation_layout = QVBoxLayout(presentation)
        presentation_layout.setContentsMargins(14, 14, 14, 14)
        presentation_layout.setSpacing(0)
        root_layout.addWidget(presentation, 1)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setObjectName("iconPresentationScroll")
        self.scroll_area.setAutoFillBackground(False)
        self.scroll_area.viewport().setAutoFillBackground(False)
        self.scroll_area.viewport().setAttribute(Qt.WA_StyledBackground, False)
        presentation_layout.addWidget(self.scroll_area)

        self.grid_holder = QWidget()
        self.grid_holder.setObjectName("iconGridHolder")
        self.grid_holder.setAutoFillBackground(False)
        self.grid_layout = QGridLayout(self.grid_holder)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setHorizontalSpacing(12)
        self.grid_layout.setVerticalSpacing(12)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll_area.setWidget(self.grid_holder)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(10)
        root_layout.addLayout(footer)

        self.add_background_button = ModernButton("Add Background", role="sidebar", height=44, icon_size=0)
        self.add_background_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.add_background_button.clicked.connect(self._add_background)
        footer.addWidget(self.add_background_button)

        self.remove_background_button = ModernButton("Remove Background", role="danger", height=44, icon_size=0)
        self.remove_background_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.remove_background_button.clicked.connect(self._remove_selected_background)
        footer.addWidget(self.remove_background_button)

        self.open_folder_button = ModernButton("Open Folder", role="sidebar", height=44, icon_size=0)
        self.open_folder_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.open_folder_button.clicked.connect(self._open_folder)
        footer.addWidget(self.open_folder_button)

        footer.addStretch()

        self.ok_button = ModernButton("OK", role="accent", height=44, icon_size=0)
        self.ok_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.ok_button.clicked.connect(self._confirm_selection)
        footer.addWidget(self.ok_button)

        self.cancel_button = ModernButton("Cancel", role="sidebar", height=44, icon_size=0)
        self.cancel_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.cancel_button.clicked.connect(self.reject)
        footer.addWidget(self.cancel_button)

    def _reload_backgrounds(self, preferred_background: str | None = None) -> None:
        self._stop_thumbnail_player()
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._tiles.clear()
        backgrounds = self.service.list_backgrounds()
        selected_background = preferred_background or self.selected_background_path or self.service.get_active_background_reference()
        available_paths = {background.relative_path for background in backgrounds}
        if selected_background not in available_paths:
            selected_background = backgrounds[0].relative_path if backgrounds else None

        self._video_queue = []
        for index, background in enumerate(backgrounds):
            tile = BackgroundTile(background, self.grid_holder)
            tile.clicked.connect(self._select_background)
            if background.is_video:
                self._video_queue.append(background)
            else:
                tile.set_thumbnail(_load_image_thumbnail(background.absolute_path, 360, 204))
            row = index // self._GRID_COLUMNS
            column = index % self._GRID_COLUMNS
            self.grid_layout.addWidget(tile, row, column)
            self._tiles[background.relative_path] = tile

        for column in range(self._GRID_COLUMNS):
            self.grid_layout.setColumnStretch(column, 0)
        if selected_background:
            self._select_background(selected_background)
        self._apply_responsive_layout()
        self._start_next_video_thumbnail()

    def _apply_responsive_layout(self) -> None:
        layout = self.layout()
        if isinstance(layout, QVBoxLayout):
            margin = scaled_px(self, 20, minimum=16, maximum=24)
            layout.setContentsMargins(margin, margin, margin, margin)
            layout.setSpacing(scaled_px(self, 14, minimum=12, maximum=18))

        self.grid_layout.setHorizontalSpacing(scaled_px(self, 12, minimum=10, maximum=14))
        self.grid_layout.setVerticalSpacing(scaled_px(self, 12, minimum=10, maximum=14))
        tile_width = scaled_px(self, 204, minimum=176, maximum=214, scale_min=0.92, scale_max=1.0)
        tile_height = int(tile_width * 0.86)
        for tile in self._tiles.values():
            tile.set_tile_size(tile_width, tile_height)
        button_height = scaled_px(self, 46, minimum=42, maximum=48)
        self.add_background_button.set_metrics(height=button_height, icon_size=0)
        self.remove_background_button.set_metrics(height=button_height, icon_size=0)
        self.open_folder_button.set_metrics(height=button_height, icon_size=0)
        self.ok_button.set_metrics(height=button_height, icon_size=0)
        self.cancel_button.set_metrics(height=button_height, icon_size=0)

    def _select_background(self, relative_path: str) -> None:
        if relative_path not in self._tiles:
            return

        self.selected_background_path = relative_path
        for background_path, tile in self._tiles.items():
            tile.set_selected(background_path == relative_path)

    def _add_background(self) -> None:
        start_dir = str(self.service.project_root)
        suffixes = " ".join(f"*{suffix}" for suffix in sorted(BACKGROUND_SUFFIXES))
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Add Custom Background",
            start_dir,
            f"Background Files ({suffixes})",
        )
        if not file_path:
            return

        try:
            relative_path = self.service.store_user_background(file_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Background Error", str(exc))
            return

        self._reload_backgrounds(relative_path)

    def _remove_selected_background(self) -> None:
        selected_tile = self._tiles.get(self.selected_background_path)
        if selected_tile is None:
            self.remove_background_button.flash_invalid()
            return
        if selected_tile.background_record.is_default:
            self.remove_background_button.flash_invalid()
            return

        self._stop_thumbnail_player()
        selected_background = self.selected_background_path
        if self.service.get_active_background_reference() == selected_background:
            self.service.reset_background()
            active_background = self.service.get_active_background_path() or ""
            self.active_background_changed.emit(active_background)
            app = QApplication.instance()
            if app is not None:
                app.processEvents()

        try:
            removed = self.service.remove_user_background(selected_background)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Background Error", str(exc))
            return

        if not removed:
            self.remove_background_button.flash_invalid()
            return

        self._reload_backgrounds(self.service.get_active_background_reference())

    def _open_folder(self) -> None:
        self.service.backgrounds_folder().mkdir(parents=True, exist_ok=True)
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.service.backgrounds_folder())))

    def _confirm_selection(self) -> None:
        if self.selected_background_path not in self._tiles:
            self.ok_button.flash_invalid()
            return
        self.accept()

    def _start_next_video_thumbnail(self) -> None:
        if QMediaPlayer is None or QVideoSink is None:
            return
        if self._pending_video is not None or not self._video_queue:
            return
        self._pending_video = self._video_queue.pop(0)
        if self._thumbnail_player is None:
            self._thumbnail_player = QMediaPlayer(self)
            if QAudioOutput is not None:
                self._thumbnail_audio = QAudioOutput(self)
                self._thumbnail_audio.setMuted(True)
                self._thumbnail_audio.setVolume(0)
                self._thumbnail_player.setAudioOutput(self._thumbnail_audio)
            self._thumbnail_sink = QVideoSink(self)
            self._thumbnail_sink.videoFrameChanged.connect(self._handle_video_frame)
            self._thumbnail_player.setVideoSink(self._thumbnail_sink)

        self._thumbnail_player.stop()
        self._thumbnail_player.setSource(QUrl.fromLocalFile(self._pending_video.absolute_path))
        self._thumbnail_player.play()
        self._thumbnail_timeout.start(2600)

    def _handle_video_frame(self, frame) -> None:
        if self._pending_video is None:
            return
        try:
            image = frame.toImage()
        except Exception:  # noqa: BLE001
            image = None
        if image is None or image.isNull():
            return

        tile = self._tiles.get(self._pending_video.relative_path)
        if tile is not None:
            tile.set_thumbnail(QPixmap.fromImage(image))
        self._finish_pending_video_thumbnail()

    def _skip_video_thumbnail(self) -> None:
        self._finish_pending_video_thumbnail()

    def _finish_pending_video_thumbnail(self) -> None:
        self._thumbnail_timeout.stop()
        if self._thumbnail_player is not None:
            self._thumbnail_player.stop()
        self._pending_video = None
        QTimer.singleShot(0, self._start_next_video_thumbnail)

    def _stop_thumbnail_player(self) -> None:
        self._thumbnail_timeout.stop()
        self._pending_video = None
        self._video_queue = []
        if self._thumbnail_player is not None:
            self._thumbnail_player.stop()
            self._thumbnail_player.setSource(QUrl())


def _load_image_thumbnail(path: str, width: int, height: int) -> QPixmap:
    reader = QImageReader(str(Path(path).resolve()))
    reader.setAutoTransform(True)
    source_size = reader.size()
    if source_size.isValid():
        reader.setScaledSize(source_size.scaled(QSize(width, height), Qt.KeepAspectRatioByExpanding))
    image = reader.read()
    return QPixmap.fromImage(image) if not image.isNull() else QPixmap()
