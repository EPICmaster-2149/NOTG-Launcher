from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEasingCurve, QMimeData, QPoint, QRectF, QSize, Qt, QTimer, QUrl, Signal, QVariantAnimation, QObject
from PySide6.QtGui import QColor, QDrag, QFont, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStyle,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
except ImportError:  # pragma: no cover - depends on the local Qt build
    QAudioOutput = None
    QMediaDevices = None
    QMediaPlayer = None

from core.launcher import MUSIC_SUFFIXES, LauncherService, MusicRecord
from ui.app_icon import application_icon
from ui.responsive import fitted_window_size, scaled_px
from ui.theme import theme_palette
from ui.topbar import ModernButton, blend_colors


MUSIC_MIME = "application/x-notg-music-track"


class MusicController(QObject):
    tracks_changed = Signal()
    current_track_changed = Signal(object)
    playback_changed = Signal(bool)
    volume_changed = Signal(int, bool)
    position_changed = Signal(int)
    duration_changed = Signal(int)
    loop_changed = Signal(bool)
    background_play_changed = Signal(bool)
    checkpoint_resume_changed = Signal(bool)

    def __init__(self, service: LauncherService, parent: QObject | None = None):
        super().__init__(parent)
        self.service = service
        self._tracks = self.service.list_music_tracks()
        self._current_music_id = self.service.get_active_music_id()
        self._volume = self.service.get_music_volume()
        self._muted = self.service.get_music_muted() or self._volume <= 0
        self._loop = self.service.get_music_loop()
        self._run_while_closed = self.service.get_music_run_while_closed()
        self._resume_checkpoint = self.service.get_music_resume_checkpoint_enabled()
        checkpoint_id, checkpoint_position = self.service.get_music_checkpoint()
        self._stored_checkpoint_id = checkpoint_id
        self._stored_checkpoint_position = checkpoint_position
        self._pending_checkpoint_position = 0
        self._pending_checkpoint_attempts = 0
        self._last_known_position = 0
        self._checkpoint_saved_for_stop = False
        self._started = False
        self._player = None
        self._audio_output = None
        self._media_devices = None

        if QMediaPlayer is not None and QAudioOutput is not None:
            self._player = QMediaPlayer(self)
            self._audio_output = QAudioOutput(self)
            if QMediaDevices is not None:
                self._media_devices = QMediaDevices(self)
                self._media_devices.audioOutputsChanged.connect(self._refresh_default_audio_device)
                self._refresh_default_audio_device()
            self._player.setAudioOutput(self._audio_output)
            self._player.positionChanged.connect(self._handle_position_changed)
            self._player.durationChanged.connect(self._handle_duration_changed)
            self._player.playbackStateChanged.connect(self._handle_playback_state)
            self._player.mediaStatusChanged.connect(self._handle_media_status)
            self._player.errorOccurred.connect(self._handle_player_error)
            self._apply_audio_output()

    @property
    def available(self) -> bool:
        return self._player is not None and self._audio_output is not None

    @property
    def volume(self) -> int:
        return self._volume

    @property
    def muted(self) -> bool:
        return self._muted

    @property
    def loop_enabled(self) -> bool:
        return self._loop

    @property
    def run_while_closed(self) -> bool:
        return self._run_while_closed

    @property
    def resume_checkpoint_enabled(self) -> bool:
        return self._resume_checkpoint

    @property
    def is_playing(self) -> bool:
        if self._player is None or QMediaPlayer is None:
            return False
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    @property
    def position(self) -> int:
        return int(self._player.position()) if self._player is not None else 0

    @property
    def duration(self) -> int:
        return int(self._player.duration()) if self._player is not None else 0

    def tracks(self) -> list[MusicRecord]:
        return list(self._tracks)

    def current_track(self) -> MusicRecord | None:
        return self._track_by_id(self._current_music_id)

    def playable_tracks(self) -> list[MusicRecord]:
        return [track for track in self._tracks if track.enabled]

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        if not self.available:
            return
        checkpoint_id, checkpoint_position = (
            (self._stored_checkpoint_id, self._stored_checkpoint_position)
            if self._resume_checkpoint
            else (None, 0)
        )
        track = self._track_by_id(checkpoint_id) if checkpoint_id else None
        if track is not None and track.enabled:
            self._pending_checkpoint_position = checkpoint_position
            self._pending_checkpoint_attempts = 0
        else:
            track = self._track_by_id(self._current_music_id)
        if track is None or not track.enabled:
            track = self._first_playable_track()
        if track is not None:
            self.play_track(track.music_id)

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()

    def play(self) -> None:
        if not self.available:
            return
        self._checkpoint_saved_for_stop = False
        track = self._track_by_id(self._current_music_id)
        if track is None or not track.enabled:
            track = self._first_playable_track()
            if track is None:
                return
            self.play_track(track.music_id)
            return
        self._player.play()

    def pause(self) -> None:
        if self._player is not None:
            self._player.pause()

    def toggle_playback(self) -> None:
        if self.is_playing:
            self.pause()
        else:
            self.play()

    def play_track(self, music_id: str) -> bool:
        if not self.available:
            return False
        self._checkpoint_saved_for_stop = False
        track = self._track_by_id(music_id)
        if track is None or not track.enabled:
            return False

        if self._current_music_id != track.music_id:
            self._current_music_id = track.music_id
            self.service.set_active_music_id(track.music_id)
            self.current_track_changed.emit(track)

        current_source = self._player.source().toLocalFile() if self._player.source().isLocalFile() else ""
        if Path(current_source) != Path(track.absolute_path):
            self._player.stop()
            self._player.setSource(QUrl.fromLocalFile(track.absolute_path))
            self.duration_changed.emit(self.duration)
            self.position_changed.emit(self.position)
        self._player.play()
        self._apply_pending_checkpoint()
        return True

    def next_track(self, *, wrap: bool = True) -> bool:
        return self._move_by(1, wrap=wrap)

    def previous_track(self, *, wrap: bool = True) -> bool:
        return self._move_by(-1, wrap=wrap)

    def seek(self, position_ms: int) -> None:
        if self._player is None:
            return
        position = max(0, int(position_ms))
        self._player.setPosition(position)
        self._last_known_position = position

    def set_volume(self, volume: int) -> None:
        self._volume = self.service.set_music_volume(volume)
        if self._volume <= 0:
            self._muted = self.service.set_music_muted(True)
        elif self._muted:
            self._muted = self.service.set_music_muted(False)
        self._apply_audio_output()
        self.volume_changed.emit(self._volume, self._muted)

    def toggle_mute(self) -> None:
        if self._muted or self._volume <= 0:
            if self._volume <= 0:
                self._volume = self.service.set_music_volume(self.service.get_music_last_nonzero_volume())
            self._muted = self.service.set_music_muted(False)
        else:
            self._muted = self.service.set_music_muted(True)
        self._apply_audio_output()
        self.volume_changed.emit(self._volume, self._muted)

    def set_loop(self, enabled: bool) -> None:
        self._loop = self.service.set_music_loop(enabled)
        self.loop_changed.emit(self._loop)

    def set_run_while_closed(self, enabled: bool) -> None:
        self._run_while_closed = self.service.set_music_run_while_closed(enabled)
        self.background_play_changed.emit(self._run_while_closed)

    def set_resume_checkpoint_enabled(self, enabled: bool) -> None:
        self._resume_checkpoint = self.service.set_music_resume_checkpoint_enabled(enabled)
        if self._resume_checkpoint:
            self.save_checkpoint()
        self.checkpoint_resume_changed.emit(self._resume_checkpoint)

    def save_checkpoint(self) -> None:
        if not self._resume_checkpoint:
            return
        track = self.current_track()
        position = max(self.position, self._last_known_position)
        music_id = track.music_id if track is not None else self._current_music_id
        if not music_id:
            return
        if (
            self._pending_checkpoint_position > 0
            and music_id == self._stored_checkpoint_id
            and position <= 0
        ):
            position = self._pending_checkpoint_position
        self._stored_checkpoint_id = music_id
        self._stored_checkpoint_position = max(0, position)
        self.service.set_music_checkpoint(music_id, self._stored_checkpoint_position)

    def stop_with_checkpoint(self) -> None:
        if not self._checkpoint_saved_for_stop:
            self.save_checkpoint()
            self._checkpoint_saved_for_stop = True
        self.stop()

    def add_music(self, source_path: str | Path) -> str:
        reference = self.service.store_user_music(source_path)
        self.reload_tracks()
        if self.current_track() is None:
            self.play_track(reference)
        return reference

    def delete_music(self, music_id: str) -> bool:
        track = self._track_by_id(music_id)
        if track is None or track.is_default:
            return False
        was_current = track.music_id == self._current_music_id
        removed = self.service.remove_user_music(track.relative_path)
        if not removed:
            return False
        self.reload_tracks()
        if was_current:
            replacement = self._first_playable_track()
            if replacement is None:
                self.stop()
                self._current_music_id = None
                self.service.set_active_music_id(None)
                self.current_track_changed.emit(None)
            else:
                self.play_track(replacement.music_id)
        return True

    def set_track_enabled(self, music_id: str, enabled: bool) -> None:
        was_current = music_id == self._current_music_id
        self._tracks = self.service.set_music_enabled(music_id, enabled)
        self.tracks_changed.emit()
        if was_current and not enabled:
            replacement = self._first_playable_track()
            if replacement is None:
                self.stop()
                self._current_music_id = None
                self.service.set_active_music_id(None)
                self.current_track_changed.emit(None)
            else:
                self.play_track(replacement.music_id)

    def reorder_tracks(self, ordered_ids: list[str], *, dropped_music_id: str | None = None) -> None:
        self._tracks = self.service.set_music_order(ordered_ids)
        self.tracks_changed.emit()
        if dropped_music_id and self._tracks and self._tracks[0].music_id == dropped_music_id and self._tracks[0].enabled:
            self.play_track(dropped_music_id)

    def reload_tracks(self) -> None:
        self._tracks = self.service.list_music_tracks()
        if self._track_by_id(self._current_music_id) is None:
            self._current_music_id = self.service.get_active_music_id()
        self.tracks_changed.emit()
        self.current_track_changed.emit(self.current_track())

    def _move_by(self, step: int, *, wrap: bool) -> bool:
        playable = self.playable_tracks()
        if not playable:
            return False
        current_id = self._current_music_id
        current_index = next((index for index, track in enumerate(playable) if track.music_id == current_id), -1)
        if current_index < 0:
            return self.play_track(playable[0].music_id)
        next_index = current_index + step
        if wrap:
            next_index %= len(playable)
        elif next_index < 0 or next_index >= len(playable):
            return False
        return self.play_track(playable[next_index].music_id)

    def _first_playable_track(self) -> MusicRecord | None:
        playable = self.playable_tracks()
        return playable[0] if playable else None

    def _track_by_id(self, music_id: str | None) -> MusicRecord | None:
        if not music_id:
            return None
        for track in self._tracks:
            if track.music_id == music_id:
                return track
        return None

    def _apply_audio_output(self) -> None:
        if self._audio_output is None:
            return
        self._audio_output.setVolume(max(0.0, min(1.0, self._volume / 100.0)))
        self._audio_output.setMuted(self._muted or self._volume <= 0)

    def _handle_position_changed(self, value: int) -> None:
        position = int(value)
        self._last_known_position = max(0, position)
        self.position_changed.emit(position)

    def _handle_duration_changed(self, value: int) -> None:
        self.duration_changed.emit(int(value))
        self._apply_pending_checkpoint()

    def _apply_pending_checkpoint(self) -> None:
        if self._player is None or self._pending_checkpoint_position <= 0:
            return
        duration = self.duration
        if duration <= 0:
            self._pending_checkpoint_attempts += 1
            QTimer.singleShot(200, self._apply_pending_checkpoint)
            return
        if (
            hasattr(self._player, "isSeekable")
            and not self._player.isSeekable()
            and self._pending_checkpoint_attempts < 50
        ):
            self._pending_checkpoint_attempts += 1
            QTimer.singleShot(200, self._apply_pending_checkpoint)
            return
        position = min(self._pending_checkpoint_position, max(0, duration - 800))
        self._pending_checkpoint_position = 0
        self._pending_checkpoint_attempts = 0
        self.seek(position)

    def _refresh_default_audio_device(self) -> None:
        if self._audio_output is None or QMediaDevices is None:
            return
        default_device = QMediaDevices.defaultAudioOutput()
        if hasattr(default_device, "isNull") and default_device.isNull():
            return
        self._audio_output.setDevice(default_device)

    def _handle_playback_state(self, state) -> None:
        if QMediaPlayer is None:
            self.playback_changed.emit(False)
            return
        self.playback_changed.emit(state == QMediaPlayer.PlaybackState.PlayingState)

    def _handle_media_status(self, status) -> None:
        if QMediaPlayer is None:
            return
        if status in {
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        }:
            self._apply_pending_checkpoint()
        if status != QMediaPlayer.MediaStatus.EndOfMedia:
            return
        if not self.next_track(wrap=self._loop):
            self.stop()

    def _handle_player_error(self, *_args) -> None:
        if len(self.playable_tracks()) > 1:
            QTimer.singleShot(0, lambda: self.next_track(wrap=True))
        else:
            self.stop()


class ClickSlider(QSlider):
    def __init__(self, orientation: Qt.Orientation, parent: QWidget | None = None):
        super().__init__(orientation, parent)
        self.setTracking(True)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        self.setSliderDown(True)
        self.sliderPressed.emit()
        self._set_value_from_event(event)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self.isSliderDown():
            self._set_value_from_event(event)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.isSliderDown():
            self._set_value_from_event(event)
            self.setSliderDown(False)
            self.sliderReleased.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _set_value_from_event(self, event) -> None:
        span = max(1, self.width() - 1)
        position = max(0, min(span, int(event.position().x())))
        value = QStyle.sliderValueFromPosition(
            self.minimum(),
            self.maximum(),
            position,
            span,
            self.invertedAppearance(),
        )
        self.setSliderPosition(value)
        self.setValue(value)
        self.sliderMoved.emit(value)


class IconButton(QPushButton):
    def __init__(self, icon_kind: str, *, role: str = "toolbar", button_size: int = 34, parent: QWidget | None = None):
        super().__init__("", parent)
        self._icon_kind = icon_kind
        self._role = role
        self._button_size = button_size
        self._hover = 0.0
        self._press = 0.0
        self._active = 0.0
        self._volume_level = 3
        self._muted = False

        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFixedSize(button_size, button_size)

        self._hover_animation = QVariantAnimation(self, duration=160, easingCurve=QEasingCurve.OutCubic)
        self._hover_animation.valueChanged.connect(lambda value: self._set_progress("_hover", value))
        self._press_animation = QVariantAnimation(self, duration=110, easingCurve=QEasingCurve.OutCubic)
        self._press_animation.valueChanged.connect(lambda value: self._set_progress("_press", value))
        self._active_animation = QVariantAnimation(self, duration=180, easingCurve=QEasingCurve.OutCubic)
        self._active_animation.valueChanged.connect(lambda value: self._set_progress("_active", value))

    def sizeHint(self) -> QSize:
        return QSize(self._button_size, self._button_size)

    def set_button_size(self, size: int) -> None:
        self._button_size = size
        self.setFixedSize(size, size)
        self.updateGeometry()
        self.update()

    def set_volume_state(self, volume: int, muted: bool) -> None:
        self._muted = bool(muted) or volume <= 0
        if self._muted:
            self._volume_level = 0
        elif volume < 34:
            self._volume_level = 1
        elif volume < 68:
            self._volume_level = 2
        else:
            self._volume_level = 3
        self.update()

    def set_icon_kind(self, icon_kind: str) -> None:
        self._icon_kind = icon_kind
        self.update()

    def set_active(self, active: bool) -> None:
        target = 1.0 if active else 0.0
        self._animate(self._active_animation, self._active, target)

    def enterEvent(self, event) -> None:
        self._animate(self._hover_animation, self._hover, 1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate(self._hover_animation, self._hover, 0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._animate(self._press_animation, self._press, 1.0)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._animate(self._press_animation, self._press, 0.0)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        del event
        colors = theme_palette(self)["buttons"][self._role]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(self.rect()).adjusted(1.2, 1.2, -1.2, -2.2)
        rect.translate(0, self._press * 0.8)
        bg = blend_colors(colors["bg"], colors["hover"], self._hover)
        bg = blend_colors(bg, colors["press"], self._press)
        bg = blend_colors(bg, colors["active"], self._active)
        border = blend_colors(colors["border"], colors["border_hover"], self._hover)
        border = blend_colors(border, colors["border_active"], self._active)
        icon_color = colors["text"]

        if not self.isEnabled():
            bg.setAlpha(int(bg.alpha() * 0.42))
            border.setAlpha(int(border.alpha() * 0.44))
            icon_color = QColor(icon_color)
            icon_color.setAlpha(130)

        painter.setPen(QPen(border, 1.1))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 9, 9)

        painter.setPen(QPen(icon_color, max(1.5, self._button_size / 18), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(icon_color)
        padding = 8 if self._icon_kind in {"volume", "dots"} else 11
        icon_rect = rect.adjusted(padding, padding, -padding, -padding)
        self._paint_icon(painter, icon_rect, icon_color)

    def _paint_standard_icon(self, painter: QPainter, rect: QRectF) -> None:
        icon_size = QSize(max(10, int(rect.width())), max(10, int(rect.height())))
        icon = self.style().standardIcon(self._standard_pixmap())
        pixmap = icon.pixmap(icon_size)
        if not self.isEnabled():
            painter.setOpacity(0.58)
        x = int(rect.center().x() - pixmap.width() / 2)
        y = int(rect.center().y() - pixmap.height() / 2)
        painter.drawPixmap(x, y, pixmap)

    def _standard_pixmap(self):
        if self._icon_kind == "volume":
            return QStyle.StandardPixmap.SP_MediaVolumeMuted if self._muted else QStyle.StandardPixmap.SP_MediaVolume
        if self._icon_kind == "previous":
            return QStyle.StandardPixmap.SP_MediaSkipBackward
        if self._icon_kind == "next":
            return QStyle.StandardPixmap.SP_MediaSkipForward
        if self._icon_kind == "pause":
            return QStyle.StandardPixmap.SP_MediaPause
        if self._icon_kind == "loop":
            return QStyle.StandardPixmap.SP_BrowserReload
        if self._icon_kind == "dots":
            return QStyle.StandardPixmap.SP_FileDialogDetailedView
        return QStyle.StandardPixmap.SP_MediaPlay

    def _paint_icon(self, painter: QPainter, rect: QRectF, color: QColor) -> None:
        if self._icon_kind == "volume":
            self._paint_volume(painter, rect, color)
        elif self._icon_kind == "dots":
            self._paint_dots(painter, rect, color)
        elif self._icon_kind == "previous":
            self._paint_previous_next(painter, rect, color, previous=True)
        elif self._icon_kind == "next":
            self._paint_previous_next(painter, rect, color, previous=False)
        elif self._icon_kind == "pause":
            self._paint_pause(painter, rect, color)
        elif self._icon_kind == "loop":
            self._paint_loop(painter, rect, color)
        else:
            self._paint_play(painter, rect, color)

    def _paint_volume(self, painter: QPainter, rect: QRectF, color: QColor) -> None:
        painter.save()
        painter.setClipRect(rect.adjusted(-1, -1, 1, 1))
        body = QPolygonF(
            [
                QPoint(int(rect.left()), int(rect.center().y() - rect.height() * 0.18)),
                QPoint(int(rect.left() + rect.width() * 0.26), int(rect.center().y() - rect.height() * 0.18)),
                QPoint(int(rect.left() + rect.width() * 0.44), int(rect.top())),
                QPoint(int(rect.left() + rect.width() * 0.44), int(rect.bottom())),
                QPoint(int(rect.left() + rect.width() * 0.26), int(rect.center().y() + rect.height() * 0.18)),
                QPoint(int(rect.left()), int(rect.center().y() + rect.height() * 0.18)),
            ]
        )
        painter.drawPolygon(body)
        painter.setBrush(Qt.NoBrush)
        if self._muted:
            painter.drawLine(QPoint(int(rect.left() + rect.width() * 0.62), int(rect.top() + 2)), QPoint(int(rect.right() - 1), int(rect.bottom() - 2)))
            painter.drawLine(QPoint(int(rect.right() - 1), int(rect.top() + 2)), QPoint(int(rect.left() + rect.width() * 0.62), int(rect.bottom() - 2)))
            painter.restore()
            return

        for index in range(self._volume_level):
            growth = (index + 1) / 3.0
            left_factor = 0.45 - (growth * 0.04)
            width_factor = 0.22 + (growth * 0.30)
            vertical_inset = max(1.0, 4.2 - (growth * 3.2))
            wave_rect = QRectF(
                rect.left() + rect.width() * left_factor,
                rect.top() + vertical_inset,
                rect.width() * width_factor,
                rect.height() - (vertical_inset * 2),
            )
            painter.drawArc(wave_rect, -42 * 16, 84 * 16)
        painter.restore()

    def _paint_dots(self, painter: QPainter, rect: QRectF, color: QColor) -> None:
        del color
        radius = max(1.25, rect.width() * 0.075)
        for offset in (-0.42, 0, 0.42):
            center = QPoint(int(rect.center().x()), int(rect.center().y() + rect.height() * offset))
            painter.drawEllipse(center, radius, radius)

    def _paint_previous_next(self, painter: QPainter, rect: QRectF, color: QColor, *, previous: bool) -> None:
        del color
        painter.setBrush(painter.pen().color())
        if previous:
            painter.drawRect(QRectF(rect.left(), rect.top() + 1, rect.width() * 0.12, rect.height() - 2))
            points = [
                QPoint(int(rect.right()), int(rect.top())),
                QPoint(int(rect.left() + rect.width() * 0.18), int(rect.center().y())),
                QPoint(int(rect.right()), int(rect.bottom())),
            ]
        else:
            painter.drawRect(QRectF(rect.right() - rect.width() * 0.12, rect.top() + 1, rect.width() * 0.12, rect.height() - 2))
            points = [
                QPoint(int(rect.left()), int(rect.top())),
                QPoint(int(rect.right() - rect.width() * 0.18), int(rect.center().y())),
                QPoint(int(rect.left()), int(rect.bottom())),
            ]
        painter.drawPolygon(QPolygonF(points))

    def _paint_play(self, painter: QPainter, rect: QRectF, color: QColor) -> None:
        del color
        points = [
            QPoint(int(rect.left() + 2), int(rect.top())),
            QPoint(int(rect.right()), int(rect.center().y())),
            QPoint(int(rect.left() + 2), int(rect.bottom())),
        ]
        painter.drawPolygon(QPolygonF(points))

    def _paint_pause(self, painter: QPainter, rect: QRectF, color: QColor) -> None:
        del color
        bar_width = rect.width() * 0.26
        gap = rect.width() * 0.18
        total_width = (bar_width * 2) + gap
        start_x = rect.center().x() - (total_width / 2)
        painter.drawRoundedRect(QRectF(start_x, rect.top(), bar_width, rect.height()), 2, 2)
        painter.drawRoundedRect(QRectF(start_x + bar_width + gap, rect.top(), bar_width, rect.height()), 2, 2)

    def _paint_loop(self, painter: QPainter, rect: QRectF, color: QColor) -> None:
        del color
        painter.save()
        painter.setBrush(Qt.NoBrush)
        pen = painter.pen()
        pen.setWidthF(max(1.8, rect.width() * 0.12))
        painter.setPen(pen)

        top_y = rect.top() + rect.height() * 0.34
        bottom_y = rect.top() + rect.height() * 0.66
        left_x = rect.left() + rect.width() * 0.20
        right_x = rect.right() - rect.width() * 0.20
        mid_x = rect.center().x()
        curve = rect.height() * 0.22

        top_path = QPainterPath()
        top_path.moveTo(left_x, top_y)
        top_path.cubicTo(left_x + curve, rect.top(), right_x - curve, rect.top(), right_x, top_y)
        painter.drawPath(top_path)
        top_arrow = QPolygonF(
            [
                QPoint(int(right_x), int(top_y)),
                QPoint(int(right_x - rect.width() * 0.18), int(top_y - rect.height() * 0.16)),
                QPoint(int(right_x - rect.width() * 0.05), int(top_y + rect.height() * 0.19)),
            ]
        )

        bottom_path = QPainterPath()
        bottom_path.moveTo(right_x, bottom_y)
        bottom_path.cubicTo(right_x - curve, rect.bottom(), left_x + curve, rect.bottom(), left_x, bottom_y)
        painter.drawPath(bottom_path)
        bottom_arrow = QPolygonF(
            [
                QPoint(int(left_x), int(bottom_y)),
                QPoint(int(left_x + rect.width() * 0.18), int(bottom_y + rect.height() * 0.16)),
                QPoint(int(left_x + rect.width() * 0.05), int(bottom_y - rect.height() * 0.19)),
            ]
        )

        painter.setBrush(painter.pen().color())
        painter.drawPolygon(top_arrow)
        painter.drawPolygon(bottom_arrow)
        painter.restore()

    def _animate(self, animation: QVariantAnimation, start: float, end: float) -> None:
        animation.stop()
        animation.setStartValue(float(start))
        animation.setEndValue(float(end))
        animation.start()

    def _set_progress(self, attribute: str, value) -> None:
        setattr(self, attribute, float(value))
        self.update()


class TopBarMusicWidget(QFrame):
    manager_requested = Signal()

    def __init__(self, controller: MusicController, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller
        self._syncing = False
        self.setObjectName("musicControl")
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(6)

        self.volume_button = IconButton("volume", button_size=30)
        self.volume_button.setToolTip("Mute or unmute music")
        self.volume_button.clicked.connect(self.controller.toggle_mute)
        layout.addWidget(self.volume_button)

        self.volume_slider = ClickSlider(Qt.Horizontal)
        self.volume_slider.setObjectName("musicVolumeSlider")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setFixedWidth(96)
        self.volume_slider.setMinimumHeight(30)
        self.volume_slider.setCursor(Qt.PointingHandCursor)
        self.volume_slider.setTracking(True)
        self.volume_slider.setValue(self.controller.volume)
        self.volume_slider.valueChanged.connect(self._handle_slider_changed)
        layout.addWidget(self.volume_slider)

        self.divider = QFrame()
        self.divider.setObjectName("musicControlDivider")
        self.divider.setFixedWidth(1)
        layout.addWidget(self.divider)

        self.manager_button = IconButton("dots", button_size=30)
        self.manager_button.setToolTip("Open music manager")
        self.manager_button.clicked.connect(self.manager_requested)
        layout.addWidget(self.manager_button)

        self.controller.volume_changed.connect(self._sync_volume)
        self._sync_volume(self.controller.volume, self.controller.muted)

    def set_metrics(self, *, height: int, slider_width: int, icon_size: int) -> None:
        self.setFixedHeight(height)
        self.volume_slider.setFixedWidth(slider_width)
        self.volume_slider.setMinimumHeight(max(28, icon_size))
        self.volume_button.set_button_size(icon_size)
        self.manager_button.set_button_size(icon_size)

    def _handle_slider_changed(self, value: int) -> None:
        if self._syncing:
            return
        self.controller.set_volume(value)

    def _sync_volume(self, volume: int, muted: bool) -> None:
        self._syncing = True
        self.volume_slider.setValue(volume)
        self._syncing = False
        self.volume_button.set_volume_state(volume, muted)


class TrackRowWidget(QFrame):
    enabled_changed = Signal(str, bool)

    def __init__(self, number: int, record: MusicRecord, parent: QWidget | None = None):
        super().__init__(parent)
        self.record = record
        self._active = False
        self._hover = 0.0
        self._flash = 0.0
        self.setObjectName("musicTrackRow")
        self.setMinimumHeight(40)
        self.setMouseTracking(True)

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity_effect)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 10, 5)
        layout.setSpacing(10)

        self.drag_handle = DragHandle()
        self.drag_handle.setToolTip("Drag to reorder")
        layout.addWidget(self.drag_handle)

        self.number_label = QLabel(str(number))
        self.number_label.setObjectName("musicTrackNumber")
        self.number_label.setAlignment(Qt.AlignCenter)
        self.number_label.setFixedWidth(44)
        layout.addWidget(self.number_label)

        self.name_label = QLabel(record.name)
        self.name_label.setObjectName("musicTrackName")
        self.name_label.setTextInteractionFlags(Qt.NoTextInteraction)
        self.name_label.setToolTip(record.name)
        layout.addWidget(self.name_label, 1)

        self.source_label = QLabel("Default" if record.is_default else "Custom")
        self.source_label.setObjectName("musicTrackSource")
        layout.addWidget(self.source_label)

        self.checkbox = QCheckBox()
        self.checkbox.setObjectName("musicTrackCheck")
        self.checkbox.setToolTip("Enable music")
        self.checkbox.setText("Enabled" if record.enabled else "Disabled")
        self.checkbox.setChecked(record.enabled)
        self.checkbox.toggled.connect(self._handle_enabled_toggled)
        layout.addWidget(self.checkbox)

        self._hover_animation = QVariantAnimation(self, duration=140, easingCurve=QEasingCurve.OutCubic)
        self._hover_animation.valueChanged.connect(lambda value: self._set_value("_hover", value))
        self._flash_animation = QVariantAnimation(self, duration=520, easingCurve=QEasingCurve.OutCubic)
        self._flash_animation.setStartValue(1.0)
        self._flash_animation.setEndValue(0.0)
        self._flash_animation.valueChanged.connect(lambda value: self._set_value("_flash", value))

    def set_number(self, number: int) -> None:
        self.number_label.setText(str(number))

    def drag_handle_contains(self, point: QPoint) -> bool:
        return self.drag_handle.geometry().contains(point)

    def set_active(self, active: bool) -> None:
        self._active = active
        font = QFont(self.name_label.font())
        font.setWeight(QFont.Bold if active else QFont.DemiBold)
        self.name_label.setFont(font)
        self.update()

    def set_dragging(self, dragging: bool) -> None:
        self._opacity_effect.setOpacity(0.46 if dragging else 1.0)

    def flash_moved(self) -> None:
        self._flash_animation.stop()
        self._flash_animation.start()

    def enterEvent(self, event) -> None:
        self._animate(self._hover_animation, self._hover, 1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate(self._hover_animation, self._hover, 0.0)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        del event
        palette = theme_palette(self)
        button_colors = palette["buttons"]["sidebar"]
        accent = palette["buttons"]["accent"]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        bg = QColor(button_colors["bg"])
        bg = blend_colors(bg, button_colors["hover"], self._hover)
        bg = blend_colors(bg, accent["active"], 0.52 if self._active else 0.0)
        bg = blend_colors(bg, accent["hover"], self._flash * 0.52)
        border = blend_colors(button_colors["border"], button_colors["border_hover"], max(self._hover, self._flash))
        border = blend_colors(border, accent["border_active"], 0.8 if self._active else 0.0)
        if not self.record.enabled:
            bg.setAlpha(int(bg.alpha() * 0.55))
            border.setAlpha(int(border.alpha() * 0.62))

        painter.setPen(QPen(border, 1.0))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 9, 9)

    def _animate(self, animation: QVariantAnimation, start: float, end: float) -> None:
        animation.stop()
        animation.setStartValue(float(start))
        animation.setEndValue(float(end))
        animation.start()

    def _set_value(self, attribute: str, value) -> None:
        setattr(self, attribute, float(value))
        self.update()

    def _handle_enabled_toggled(self, checked: bool) -> None:
        self.checkbox.setText("Enabled" if checked else "Disabled")
        self.enabled_changed.emit(self.record.music_id, checked)


class DragHandle(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("musicDragHandle")
        self.setCursor(Qt.OpenHandCursor)
        self.setFixedSize(24, 28)

    def paintEvent(self, event) -> None:
        del event
        colors = theme_palette(self)["buttons"]["sidebar"]
        color = QColor(colors["text"])
        color.setAlpha(170 if self.isEnabled() else 90)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        radius = 2.0
        start_x = self.width() / 2 - 4
        for column in range(2):
            for row in range(3):
                painter.drawEllipse(QRectF(start_x + (column * 8), 6 + (row * 8), radius * 2, radius * 2))


class AnimatedTrackList(QListWidget):
    records_reordered = Signal(list, str)
    track_enabled_changed = Signal(str, bool)
    track_activated = Signal(str)
    selected_track_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._drag_allowed = False
        self._drag_candidate_id: str | None = None
        self.setObjectName("musicTrackList")
        self.setFrameShape(QFrame.NoFrame)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDragDropOverwriteMode(False)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setSpacing(5)
        self.setMouseTracking(True)
        self.itemSelectionChanged.connect(self._emit_selected_track)

    def set_tracks(self, records: list[MusicRecord], current_music_id: str | None = None) -> None:
        selected_id = self.selected_music_id()
        scroll_value = self.verticalScrollBar().value()
        self.clear()
        for index, record in enumerate(records, start=1):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, record.music_id)
            item.setData(Qt.UserRole + 1, record)
            item.setSizeHint(QSize(100, 44))
            self.addItem(item)
            row = TrackRowWidget(index, record)
            row.enabled_changed.connect(self.track_enabled_changed)
            row.set_active(record.music_id == current_music_id)
            self.setItemWidget(item, row)

        restore_id = selected_id if self._item_for_id(selected_id) is not None else current_music_id
        item = self._item_for_id(restore_id)
        if item is not None:
            self.setCurrentItem(item)
        QTimer.singleShot(0, lambda value=scroll_value: self._restore_scroll_value(value))

    def selected_music_id(self) -> str | None:
        item = self.currentItem()
        return str(item.data(Qt.UserRole)) if item is not None else None

    def selected_record(self) -> MusicRecord | None:
        item = self.currentItem()
        if item is None:
            return None
        record = item.data(Qt.UserRole + 1)
        return record if isinstance(record, MusicRecord) else None

    def set_current_track_id(self, music_id: str | None) -> None:
        for index in range(self.count()):
            item = self.item(index)
            row = self.itemWidget(item)
            if isinstance(row, TrackRowWidget):
                row.set_active(item.data(Qt.UserRole) == music_id)

    def mousePressEvent(self, event) -> None:
        self._drag_allowed = False
        self._drag_candidate_id = None
        item = self.itemAt(event.position().toPoint())
        if item is not None:
            row_widget = self.itemWidget(item)
            item_rect = self.visualItemRect(item)
            row_point = QPoint(int(event.position().x() - item_rect.left()), int(event.position().y() - item_rect.top()))
            if isinstance(row_widget, TrackRowWidget) and row_widget.drag_handle_contains(row_point):
                self._drag_allowed = True
                self._drag_candidate_id = str(item.data(Qt.UserRole))
                self.setCurrentItem(item)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_allowed = False
        self._drag_candidate_id = None
        super().mouseReleaseEvent(event)

    def startDrag(self, supported_actions) -> None:
        item = self.currentItem()
        if item is None or not self._drag_allowed:
            return
        music_id = str(item.data(Qt.UserRole))
        if self._drag_candidate_id != music_id:
            return
        row = self.itemWidget(item)
        if isinstance(row, TrackRowWidget):
            row.set_dragging(True)
            pixmap = row.grab()
        else:
            pixmap = QPixmap(self.visualItemRect(item).size())
            pixmap.fill(Qt.transparent)

        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MUSIC_MIME, music_id.encode("utf-8"))
        drag.setMimeData(mime)
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(18, max(1, pixmap.height() // 2)))
        drag.exec(Qt.MoveAction if supported_actions & Qt.MoveAction else supported_actions)

        item = self._item_for_id(music_id)
        row = self.itemWidget(item) if item is not None else None
        if isinstance(row, TrackRowWidget):
            row.set_dragging(False)
        self._drag_allowed = False
        self._drag_candidate_id = None

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(MUSIC_MIME):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(MUSIC_MIME):
            event.setDropAction(Qt.MoveAction)
            event.accept()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasFormat(MUSIC_MIME):
            super().dropEvent(event)
            return
        dragged_id = bytes(event.mimeData().data(MUSIC_MIME)).decode("utf-8")
        source_item = self._item_for_id(dragged_id)
        if source_item is None:
            event.ignore()
            return

        source_row = self.row(source_item)
        target_row = self._target_row(event.position().toPoint())
        if target_row > source_row:
            target_row -= 1
        target_row = max(0, min(target_row, self.count() - 1))
        if target_row == source_row:
            event.accept()
            return

        widget = self.itemWidget(source_item)
        self.removeItemWidget(source_item)
        moved_item = self.takeItem(source_row)
        self.insertItem(target_row, moved_item)
        if widget is not None:
            self.setItemWidget(moved_item, widget)

        for index in range(self.count()):
            row_widget = self.itemWidget(self.item(index))
            if isinstance(row_widget, TrackRowWidget):
                row_widget.set_number(index + 1)
                row_widget.flash_moved()

        event.setDropAction(Qt.MoveAction)
        event.accept()
        self.setCurrentItem(moved_item)
        self.records_reordered.emit(self._ordered_ids(), dragged_id)

    def mouseDoubleClickEvent(self, event) -> None:
        item = self.itemAt(event.position().toPoint())
        if item is not None:
            self.track_activated.emit(str(item.data(Qt.UserRole)))
        super().mouseDoubleClickEvent(event)

    def _target_row(self, point: QPoint) -> int:
        target = self.itemAt(point)
        if target is None:
            return self.count()
        row = self.row(target)
        rect = self.visualItemRect(target)
        if point.y() > rect.center().y():
            row += 1
        return row

    def _ordered_ids(self) -> list[str]:
        return [str(self.item(index).data(Qt.UserRole)) for index in range(self.count())]

    def _item_for_id(self, music_id: str | None) -> QListWidgetItem | None:
        if not music_id:
            return None
        for index in range(self.count()):
            item = self.item(index)
            if item.data(Qt.UserRole) == music_id:
                return item
        return None

    def _restore_scroll_value(self, value: int) -> None:
        scroll_bar = self.verticalScrollBar()
        scroll_bar.setValue(max(scroll_bar.minimum(), min(int(value), scroll_bar.maximum())))

    def _emit_selected_track(self) -> None:
        self.selected_track_changed.emit(self.selected_record())


class MusicManagerDialog(QDialog):
    def __init__(self, controller: MusicController, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller
        self._seek_dragging = False
        self._bubble_hide_timer = QTimer(self)
        self._bubble_hide_timer.setSingleShot(True)
        self._bubble_hide_timer.timeout.connect(self._hide_time_bubble)

        self.setObjectName("musicManagerDialog")
        self.setWindowTitle("Music Manager")
        self.setWindowIcon(application_icon(self.controller.service.project_root))
        self.setModal(False)
        self.setMinimumSize(700, 560)
        self.resize(fitted_window_size(self.parentWidget() or self, 820, 640, minimum_width=700, minimum_height=560))

        self._build_ui()
        self._connect_controller()
        self._sync_all()

    def resizeEvent(self, event) -> None:
        self._position_time_bubble(self.seek_slider.value())
        super().resizeEvent(event)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(12)

        self.current_label = QLabel("Currently Playing Music: None")
        self.current_label.setObjectName("musicCurrentLabel")
        self.current_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.current_label)

        self.seek_holder = QFrame()
        self.seek_holder.setObjectName("musicSeekHolder")
        self.seek_holder.setMinimumHeight(54)
        seek_layout = QVBoxLayout(self.seek_holder)
        seek_layout.setContentsMargins(4, 22, 4, 2)
        seek_layout.setSpacing(0)

        self.time_bubble = QLabel("00:00", self.seek_holder)
        self.time_bubble.setObjectName("musicTimeBubble")
        self.time_bubble.setAlignment(Qt.AlignCenter)
        self.time_bubble.hide()

        self.seek_slider = ClickSlider(Qt.Horizontal)
        self.seek_slider.setObjectName("musicSeekSlider")
        self.seek_slider.setRange(0, 0)
        self.seek_slider.sliderPressed.connect(self._begin_seek_drag)
        self.seek_slider.sliderMoved.connect(self._preview_seek)
        self.seek_slider.sliderReleased.connect(self._finish_seek_drag)
        seek_layout.addWidget(self.seek_slider)
        root.addWidget(self.seek_holder)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(10)
        controls.addStretch()

        self.previous_button = IconButton("previous", role="accent", button_size=40)
        self.previous_button.setToolTip("Previous music")
        self.previous_button.clicked.connect(self.controller.previous_track)
        controls.addWidget(self.previous_button)

        self.play_button = IconButton("play", role="accent", button_size=44)
        self.play_button.setToolTip("Play or pause music")
        self.play_button.clicked.connect(self.controller.toggle_playback)
        controls.addWidget(self.play_button)

        self.next_button = IconButton("next", role="accent", button_size=40)
        self.next_button.setToolTip("Next music")
        self.next_button.clicked.connect(self.controller.next_track)
        controls.addWidget(self.next_button)

        controls.addStretch()
        root.addLayout(controls)

        self.track_list = AnimatedTrackList()
        self.track_list.track_enabled_changed.connect(self.controller.set_track_enabled)
        self.track_list.records_reordered.connect(self._handle_records_reordered)
        self.track_list.track_activated.connect(self.controller.play_track)
        self.track_list.selected_track_changed.connect(self._sync_delete_button)
        root.addWidget(self.track_list, 1)

        loop_row = QHBoxLayout()
        loop_row.setContentsMargins(0, 0, 0, 0)
        loop_row.setSpacing(12)
        self.run_closed_checkbox = QCheckBox("Run music while launcher closed")
        self.run_closed_checkbox.setObjectName("musicCompactCheck")
        self.run_closed_checkbox.setChecked(self.controller.run_while_closed)
        self.run_closed_checkbox.toggled.connect(self.controller.set_run_while_closed)
        loop_row.addWidget(self.run_closed_checkbox)

        self.resume_checkpoint_checkbox = QCheckBox("Resume stop point")
        self.resume_checkpoint_checkbox.setObjectName("musicCompactCheck")
        self.resume_checkpoint_checkbox.setChecked(self.controller.resume_checkpoint_enabled)
        self.resume_checkpoint_checkbox.toggled.connect(self.controller.set_resume_checkpoint_enabled)
        loop_row.addWidget(self.resume_checkpoint_checkbox)

        loop_row.addStretch()
        self.loop_label = QLabel("In Loop")
        self.loop_label.setObjectName("musicLoopLabel")
        loop_row.addWidget(self.loop_label)
        self.loop_button = IconButton("loop", role="accent", button_size=38)
        self.loop_button.setToolTip("Toggle playlist loop")
        self.loop_button.clicked.connect(lambda: self.controller.set_loop(not self.controller.loop_enabled))
        loop_row.addWidget(self.loop_button)
        root.addLayout(loop_row)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(10)

        self.add_button = ModernButton("Add Music", role="accent", height=38, icon_size=0, minimum_width=116, horizontal_padding=26, font_point_size=10)
        self.add_button.clicked.connect(self._add_music)
        footer.addWidget(self.add_button)

        self.delete_button = ModernButton("Delete Music", role="danger", height=38, icon_size=0, minimum_width=126, horizontal_padding=26, font_point_size=10)
        self.delete_button.clicked.connect(self._delete_music)
        footer.addWidget(self.delete_button)

        footer.addStretch()

        self.ok_button = ModernButton("OK", role="accent", height=38, icon_size=0, minimum_width=86, horizontal_padding=24, font_point_size=10)
        self.ok_button.clicked.connect(self.accept)
        footer.addWidget(self.ok_button)

        root.addLayout(footer)

    def _connect_controller(self) -> None:
        self.controller.tracks_changed.connect(self._sync_tracks)
        self.controller.current_track_changed.connect(self._sync_current_track)
        self.controller.playback_changed.connect(self._sync_playback)
        self.controller.position_changed.connect(self._sync_position)
        self.controller.duration_changed.connect(self._sync_duration)
        self.controller.loop_changed.connect(self._sync_loop)
        self.controller.background_play_changed.connect(self._sync_run_closed)
        self.controller.checkpoint_resume_changed.connect(self._sync_resume_checkpoint)

    def _sync_all(self) -> None:
        self._sync_tracks()
        self._sync_current_track(self.controller.current_track())
        self._sync_player_timeline()
        self._sync_playback(self.controller.is_playing)
        self._sync_loop(self.controller.loop_enabled)
        self._sync_delete_button(self.track_list.selected_record())
        if not self.controller.available:
            self.current_label.setText("Currently Playing Music: Audio unavailable")
            self.seek_slider.setEnabled(False)
            self.previous_button.setEnabled(False)
            self.play_button.setEnabled(False)
            self.next_button.setEnabled(False)

    def _sync_tracks(self) -> None:
        current = self.controller.current_track()
        self.track_list.set_tracks(self.controller.tracks(), current.music_id if current is not None else None)
        self._sync_delete_button(self.track_list.selected_record())

    def _sync_current_track(self, track: MusicRecord | None) -> None:
        name = track.name if track is not None else "None"
        self.current_label.setText(f"Currently Playing Music: {name}")
        self.track_list.set_current_track_id(track.music_id if track is not None else None)
        QTimer.singleShot(0, self._sync_player_timeline)

    def _sync_player_timeline(self) -> None:
        self._sync_duration(self.controller.duration)
        self._sync_position(self.controller.position)

    def _sync_playback(self, playing: bool) -> None:
        self.play_button.set_icon_kind("pause" if playing else "play")

    def _sync_position(self, position: int) -> None:
        if not self._seek_dragging:
            self.seek_slider.setValue(max(0, int(position)))

    def _sync_duration(self, duration: int) -> None:
        self.seek_slider.setRange(0, max(0, int(duration)))
        if self._seek_dragging:
            self._preview_seek(self.seek_slider.value())

    def _sync_loop(self, enabled: bool) -> None:
        self.loop_button.set_active(enabled)
        self.loop_label.setText("In Loop" if enabled else "Not In Loop")
        self.loop_button.setToolTip("Playlist loop on" if enabled else "Playlist loop off")

    def _sync_run_closed(self, enabled: bool) -> None:
        self.run_closed_checkbox.setChecked(enabled)

    def _sync_resume_checkpoint(self, enabled: bool) -> None:
        self.resume_checkpoint_checkbox.setChecked(enabled)

    def _sync_delete_button(self, record: MusicRecord | None) -> None:
        self.delete_button.setEnabled(record is not None and not record.is_default)

    def _begin_seek_drag(self) -> None:
        self._seek_dragging = True
        self._preview_seek(self.seek_slider.value())

    def _preview_seek(self, value: int) -> None:
        self.time_bubble.setText(_format_time(value))
        self.time_bubble.adjustSize()
        self._position_time_bubble(value)
        self.time_bubble.show()
        self._bubble_hide_timer.stop()

    def _finish_seek_drag(self) -> None:
        self._seek_dragging = False
        self.controller.seek(self.seek_slider.value())
        self._preview_seek(self.seek_slider.value())
        self._bubble_hide_timer.start(650)

    def _position_time_bubble(self, value: int) -> None:
        if self.seek_slider.maximum() <= self.seek_slider.minimum():
            ratio = 0.0
        else:
            ratio = (value - self.seek_slider.minimum()) / (self.seek_slider.maximum() - self.seek_slider.minimum())
        slider_x = self.seek_slider.x()
        usable_width = max(1, self.seek_slider.width() - 22)
        x = int(slider_x + 11 + usable_width * ratio - self.time_bubble.width() / 2)
        x = max(0, min(x, self.seek_holder.width() - self.time_bubble.width()))
        self.time_bubble.move(x, 0)

    def _hide_time_bubble(self) -> None:
        if not self._seek_dragging:
            self.time_bubble.hide()

    def _handle_records_reordered(self, ordered_ids: list[str], dropped_music_id: str) -> None:
        self.controller.reorder_tracks(ordered_ids, dropped_music_id=dropped_music_id)

    def _add_music(self) -> None:
        suffixes = " ".join(f"*{suffix}" for suffix in sorted(MUSIC_SUFFIXES))
        path, _ = QFileDialog.getOpenFileName(self, "Add Music", str(Path.home()), f"Audio Files ({suffixes})")
        if not path:
            return
        try:
            self.controller.add_music(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Add Music", str(exc))

    def _delete_music(self) -> None:
        record = self.track_list.selected_record()
        if record is None:
            return
        if record.is_default:
            QMessageBox.information(self, "Delete Music", "Default music cannot be deleted.")
            return
        answer = QMessageBox.question(self, "Delete Music", f"Delete '{record.name}' from custom music?")
        if answer != QMessageBox.Yes:
            return
        if not self.controller.delete_music(record.music_id):
            QMessageBox.warning(self, "Delete Music", "Only custom music can be deleted.")


def _format_time(position_ms: int) -> str:
    total_seconds = max(0, int(position_ms / 1000))
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"
