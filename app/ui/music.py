from __future__ import annotations

import hashlib
import os
import random
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from urllib.parse import urlparse

import requests
from PySide6.QtCore import (
    QEasingCurve,
    QMimeData,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
    QVariantAnimation,
    QObject,
)
from PySide6.QtGui import QColor, QDesktopServices, QDrag, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
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

from core.launcher import MUSIC_SUFFIXES, LauncherService, MusicPlaylistRecord, MusicRecord
from ui.app_icon import application_icon
from ui.responsive import fitted_window_size, scaled_px
from ui.theme import theme_palette
from ui.topbar import ModernButton, blend_colors


MUSIC_MIME = "application/x-notg-music-track"
DEFAULT_ACCENT = QColor("#5da8ff")
UNSET_ICON = object()
PLAYLIST_ICON_PREFIX = "assets/Playlist-Default-Icons"
MUSIC_ICON_PREFIX = "assets/Music-Icons"
_PIXMAP_CACHE: dict[tuple[str, int], QPixmap] = {}


class MediaResolveWorker(QThread):
    resolved = Signal(object)
    failed = Signal(object)
    progress = Signal(object)

    def __init__(
        self,
        *,
        mode: str,
        playlist_id: str,
        url: str,
        music_id: str | None = None,
        autoplay: bool = False,
        artwork_cache_dir: Path | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._mode = mode
        self._playlist_id = playlist_id
        self._url = url
        self._music_id = music_id
        self._autoplay = autoplay
        self._artwork_cache_dir = artwork_cache_dir

    def run(self) -> None:
        try:
            tracks = self._resolve_url(self._url)
            if self.isInterruptionRequested():
                return
            self.resolved.emit(
                {
                    "mode": self._mode,
                    "playlist_id": self._playlist_id,
                    "music_id": self._music_id,
                    "tracks": tracks,
                    "autoplay": self._autoplay,
                }
            )
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(
                {
                    "mode": self._mode,
                    "playlist_id": self._playlist_id,
                    "music_id": self._music_id,
                    "url": self._url,
                    "error": str(exc),
                    "autoplay": self._autoplay,
                }
            )

    def _resolve_url(self, url: str) -> list[dict[str, object]]:
        clean_url = url.strip()
        if not clean_url:
            raise ValueError("Enter a music URL.")
        if _is_spotify_url(clean_url):
            entity_type, _entity_id = _spotify_entity(clean_url)
            if entity_type in {"playlist", "album"}:
                raise RuntimeError(_playlist_import_error(clean_url))
            return self._resolve_spotify(clean_url)
        if _looks_like_playlist_url(clean_url) and not _is_youtube_url(clean_url):
            raise RuntimeError(_playlist_import_error(clean_url))
        return self._resolve_with_ytdlp(clean_url, source_url=clean_url, platform=_platform_from_url(clean_url))

    def _resolve_with_ytdlp(
        self,
        url: str,
        *,
        source_url: str,
        platform: str,
        display_name: str | None = None,
        artist: str | None = None,
        album: str | None = None,
        artwork_url: str | None = None,
        duration_ms: int = 0,
    ) -> list[dict[str, object]]:
        try:
            import yt_dlp
        except ImportError as exc:
            raise RuntimeError("yt-dlp is required for URL streaming. Install the updated requirements.") from exc

        self.progress.emit({"type": "status", "text": "Reading music link..."})
        if _is_youtube_playlist_url(url):
            return self._resolve_youtube_playlist(url, source_url=source_url)

        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "format": "bestaudio/best",
            "noplaylist": True,
            "playlistend": 50,
            "extract_flat": False,
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
            if not isinstance(info, dict):
                raise RuntimeError("Could not read media metadata.")
            payload = self._payload_from_info(info, source_url=source_url, platform=platform)
            if display_name:
                payload["name"] = display_name
            if artist:
                payload["artist"] = artist
            if album:
                payload["album"] = album
            if artwork_url:
                payload["artwork_url"] = artwork_url
                payload["artwork_path"] = self._cache_artwork(artwork_url)
            if duration_ms:
                payload["duration_ms"] = duration_ms
            self.progress.emit({"type": "progress", "value": 1, "maximum": 1, "text": f"Added {payload['name']}"})
            return [payload]

    def _resolve_youtube_playlist(self, url: str, *, source_url: str) -> list[dict[str, object]]:
        import yt_dlp

        flat_options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
            "ignoreerrors": True,
            "playlistend": 150,
        }
        self.progress.emit({"type": "status", "text": "Reading YouTube playlist..."})
        with yt_dlp.YoutubeDL(flat_options) as ydl:
            info = ydl.extract_info(url, download=False)
        if not isinstance(info, dict):
            raise RuntimeError("Could not read YouTube playlist.")
        entries = [entry for entry in (info.get("entries") or []) if isinstance(entry, dict)]
        if not entries:
            raise RuntimeError("No playable videos were found in this playlist.")

        total = len(entries)
        payloads: list[dict[str, object]] = []
        resolve_options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "format": "bestaudio/best",
            "noplaylist": True,
        }
        with yt_dlp.YoutubeDL(resolve_options) as ydl:
            for index, entry in enumerate(entries, start=1):
                if self.isInterruptionRequested():
                    break
                title = _optional_text(entry.get("title")) or f"Track {index}"
                self.progress.emit({"type": "progress", "value": index - 1, "maximum": total, "text": f"Resolving {title}"})
                entry_url = entry.get("webpage_url") or entry.get("url") or entry.get("id")
                if not entry_url:
                    continue
                if not str(entry_url).startswith(("http://", "https://")):
                    entry_url = f"https://www.youtube.com/watch?v={entry_url}"
                try:
                    nested = ydl.extract_info(str(entry_url), download=False)
                except Exception as exc:  # noqa: BLE001
                    self.progress.emit({"type": "log", "text": f"Skipped {title}: {exc}"})
                    continue
                if isinstance(nested, dict):
                    payloads.append(
                        self._payload_from_info(
                            nested,
                            source_url=str(nested.get("webpage_url") or entry_url or source_url),
                            platform="youtube",
                        )
                    )
                self.progress.emit({"type": "progress", "value": index, "maximum": total, "text": f"Added {title}"})
        if not payloads:
            raise RuntimeError("No playable YouTube playlist entries could be resolved.")
        return payloads

    def _resolve_spotify(self, spotify_url: str) -> list[dict[str, object]]:
        entity_type, entity_id = _spotify_entity(spotify_url)
        if entity_type == "track" and entity_id:
            metadata = self._spotify_track_metadata(entity_id, spotify_url)
            query = " ".join(
                item
                for item in (
                    metadata.get("artist"),
                    metadata.get("name"),
                    "official audio",
                )
                if item
            )
            resolved = self._resolve_with_ytdlp(
                f"ytsearch1:{query}",
                source_url=spotify_url,
                platform="spotify",
                display_name=str(metadata.get("name") or "Spotify Track"),
                artist=_optional_text(metadata.get("artist")),
                album=_optional_text(metadata.get("album")),
                artwork_url=_optional_text(metadata.get("artwork_url")),
                duration_ms=int(metadata.get("duration_ms") or 0),
            )
            for payload in resolved:
                payload["source_url"] = spotify_url
                payload["platform"] = "spotify"
            return resolved

        if entity_type in {"playlist", "album"} and entity_id:
            token = self._spotify_token()
            if not token:
                raise RuntimeError("Spotify playlist and album imports require SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET.")
            if entity_type == "playlist":
                tracks = self._spotify_playlist_tracks(entity_id, token)
            else:
                tracks = self._spotify_album_tracks(entity_id, token)
            payloads: list[dict[str, object]] = []
            for metadata in tracks[:50]:
                query = " ".join(
                    item
                    for item in (
                        metadata.get("artist"),
                        metadata.get("name"),
                        "official audio",
                    )
                    if item
                )
                try:
                    payload = self._resolve_with_ytdlp(
                        f"ytsearch1:{query}",
                        source_url=spotify_url,
                        platform="spotify",
                        display_name=str(metadata.get("name") or "Spotify Track"),
                        artist=_optional_text(metadata.get("artist")),
                        album=_optional_text(metadata.get("album")),
                        artwork_url=_optional_text(metadata.get("artwork_url")),
                        duration_ms=int(metadata.get("duration_ms") or 0),
                    )[0]
                except Exception:  # noqa: BLE001
                    continue
                payload["source_url"] = spotify_url
                payload["platform"] = "spotify"
                payloads.append(payload)
            if payloads:
                return payloads
            raise RuntimeError("No playable Spotify tracks could be resolved.")

        metadata = self._spotify_oembed(spotify_url)
        title = str(metadata.get("title") or "Spotify Track")
        resolved = self._resolve_with_ytdlp(
            f"ytsearch1:{title} official audio",
            source_url=spotify_url,
            platform="spotify",
            display_name=title,
            artwork_url=_optional_text(metadata.get("thumbnail_url")),
        )
        for payload in resolved:
            payload["source_url"] = spotify_url
            payload["platform"] = "spotify"
        return resolved

    def _spotify_track_metadata(self, track_id: str, spotify_url: str) -> dict[str, object]:
        token = self._spotify_token()
        if token:
            response = requests.get(
                f"https://api.spotify.com/v1/tracks/{track_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            if response.ok:
                data = response.json()
                artists = ", ".join(artist.get("name", "") for artist in data.get("artists", []) if artist.get("name"))
                images = data.get("album", {}).get("images", [])
                return {
                    "name": data.get("name"),
                    "artist": artists,
                    "album": data.get("album", {}).get("name"),
                    "artwork_url": images[0].get("url") if images else None,
                    "duration_ms": data.get("duration_ms") or 0,
                }

        oembed = self._spotify_oembed(spotify_url)
        return {
            "name": oembed.get("title") or "Spotify Track",
            "artist": None,
            "album": None,
            "artwork_url": oembed.get("thumbnail_url"),
            "duration_ms": 0,
        }

    def _spotify_playlist_tracks(self, playlist_id: str, token: str) -> list[dict[str, object]]:
        url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks?limit=50"
        response = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=20)
        if not response.ok:
            raise RuntimeError("Spotify playlist metadata could not be read.")
        tracks: list[dict[str, object]] = []
        for item in response.json().get("items", []):
            track = item.get("track") if isinstance(item, dict) else None
            if isinstance(track, dict):
                tracks.append(self._spotify_track_payload(track))
        return tracks

    def _spotify_album_tracks(self, album_id: str, token: str) -> list[dict[str, object]]:
        album_response = requests.get(
            f"https://api.spotify.com/v1/albums/{album_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
        if not album_response.ok:
            raise RuntimeError("Spotify album metadata could not be read.")
        album = album_response.json()
        images = album.get("images", [])
        album_name = album.get("name")
        tracks: list[dict[str, object]] = []
        for track in album.get("tracks", {}).get("items", []):
            if isinstance(track, dict):
                payload = self._spotify_track_payload(track)
                payload["album"] = album_name
                payload["artwork_url"] = images[0].get("url") if images else None
                tracks.append(payload)
        return tracks

    def _spotify_track_payload(self, track: dict[str, object]) -> dict[str, object]:
        artists = ", ".join(
            str(artist.get("name"))
            for artist in track.get("artists", [])
            if isinstance(artist, dict) and artist.get("name")
        )
        album = track.get("album") if isinstance(track.get("album"), dict) else {}
        images = album.get("images", []) if isinstance(album, dict) else []
        return {
            "name": track.get("name"),
            "artist": artists,
            "album": album.get("name") if isinstance(album, dict) else None,
            "artwork_url": images[0].get("url") if images else None,
            "duration_ms": track.get("duration_ms") or 0,
        }

    def _spotify_token(self) -> str | None:
        client_id = os.environ.get("SPOTIFY_CLIENT_ID")
        client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
        if not client_id or not client_secret:
            return None
        response = requests.post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
            timeout=15,
        )
        if not response.ok:
            return None
        return _optional_text(response.json().get("access_token"))

    def _spotify_oembed(self, spotify_url: str) -> dict[str, object]:
        response = requests.get("https://open.spotify.com/oembed", params={"url": spotify_url}, timeout=15)
        if not response.ok:
            raise RuntimeError("Spotify metadata could not be read.")
        data = response.json()
        return data if isinstance(data, dict) else {}

    def _payload_from_info(self, info: dict[str, object], *, source_url: str, platform: str) -> dict[str, object]:
        stream_url = _best_stream_url(info)
        if not stream_url:
            raise RuntimeError("No playable audio stream was found.")
        artwork_url = _optional_text(info.get("thumbnail"))
        return {
            "name": _optional_text(info.get("title")) or "Untitled Track",
            "source_url": source_url,
            "stream_url": stream_url,
            "artwork_url": artwork_url,
            "artwork_path": self._cache_artwork(artwork_url),
            "date_added": datetime.now(timezone.utc).isoformat(),
            "duration_ms": int(float(info.get("duration") or 0) * 1000),
            "platform": platform,
            "artist": _optional_text(info.get("artist")) or _optional_text(info.get("uploader")),
            "album": _optional_text(info.get("album")),
        }

    def _cache_artwork(self, url: str | None) -> str | None:
        if not url or self._artwork_cache_dir is None:
            return None
        try:
            response = requests.get(url, timeout=15)
        except requests.RequestException:
            return None
        if not response.ok or not response.content:
            return None
        suffix = Path(urlparse(url).path).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            suffix = ".jpg"
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
        self._artwork_cache_dir.mkdir(parents=True, exist_ok=True)
        target = self._artwork_cache_dir / f"{digest}{suffix}"
        try:
            if not target.exists():
                target.write_bytes(response.content)
        except OSError:
            return None
        return str(target.resolve())


class MusicController(QObject):
    tracks_changed = Signal()
    playlists_changed = Signal()
    current_playlist_changed = Signal(object)
    current_track_changed = Signal(object)
    playback_changed = Signal(bool)
    volume_changed = Signal(int, bool)
    position_changed = Signal(int)
    duration_changed = Signal(int)
    loop_changed = Signal(bool)
    shuffle_changed = Signal(bool)
    background_play_changed = Signal(bool)
    checkpoint_resume_changed = Signal(bool)
    resolving_changed = Signal(bool, str)
    resolve_progress = Signal(object)
    resolve_failed = Signal(str)

    def __init__(self, service: LauncherService, parent: QObject | None = None):
        super().__init__(parent)
        self.service = service
        self._playlists = self.service.list_music_playlists()
        self._current_playlist_id = self.service.get_active_music_playlist_id()
        self._current_music_id = self.service.get_active_music_id()
        self._volume = self.service.get_music_volume()
        self._muted = self.service.get_music_muted() or self._volume <= 0
        self._loop = self.service.get_music_loop()
        self._shuffle = self.service.get_music_shuffle()
        self._paused = self.service.get_music_paused()
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
        self._workers: set[MediaResolveWorker] = set()
        self._shuffle_queue: list[str] = []
        self._stream_retry_counts: dict[str, int] = {}
        self._last_network_error_at = 0.0
        self._last_resolve_warning_at = 0.0
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
    def shuffle_enabled(self) -> bool:
        return self._shuffle

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

    def playlists(self) -> list[MusicPlaylistRecord]:
        return list(self._playlists)

    def current_playlist(self) -> MusicPlaylistRecord:
        playlist = self._playlist_by_id(self._current_playlist_id)
        if playlist is not None:
            return playlist
        return self._playlists[0]

    def tracks(self) -> list[MusicRecord]:
        return list(self.current_playlist().tracks)

    def current_track(self) -> MusicRecord | None:
        return self._track_by_id(self._current_music_id)

    def playable_tracks(self) -> list[MusicRecord]:
        return [track for track in self.tracks() if track.enabled]

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        if not self.available:
            return
        if self._paused:
            track = self._track_by_id(self._current_music_id)
            self.current_track_changed.emit(track)
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
        self._paused = self.service.set_music_paused(False)
        self._checkpoint_saved_for_stop = False
        track = self._track_by_id(self._current_music_id)
        if track is None or not track.enabled:
            self.play_playlist()
            return
        self._player.play()

    def pause(self) -> None:
        if self._player is not None:
            self._player.pause()
        self._paused = self.service.set_music_paused(True)

    def toggle_playback(self) -> None:
        if self.is_playing:
            self.pause()
        else:
            self.play()

    def play_playlist(self, playlist_id: str | None = None) -> bool:
        if playlist_id:
            self.select_playlist(playlist_id)
        tracks = self.playable_tracks()
        if not tracks:
            return False
        if self._shuffle:
            self._shuffle_queue = [track.music_id for track in tracks]
            random.shuffle(self._shuffle_queue)
            return self.play_track(self._shuffle_queue[0])
        return self.play_track(tracks[0].music_id)

    def select_playlist(self, playlist_id: str) -> None:
        if playlist_id == self._current_playlist_id:
            return
        self._current_playlist_id = self.service.set_active_music_playlist_id(playlist_id)
        self.reload_playlists()
        self.current_playlist_changed.emit(self.current_playlist())
        self.tracks_changed.emit()

    def create_playlist(self, name: str = "New Playlist", icon_path: str | None = None) -> MusicPlaylistRecord:
        playlist = self.service.create_music_playlist(name, icon_path)
        self.reload_playlists(select_playlist_id=playlist.playlist_id)
        return playlist

    def update_playlist(
        self,
        playlist_id: str,
        *,
        name: str | None = None,
        icon_path: str | None | object = UNSET_ICON,
        order: list[str] | None = None,
    ) -> MusicPlaylistRecord:
        if icon_path is UNSET_ICON:
            playlist = self.service.update_music_playlist(playlist_id, name=name, order=order)
        else:
            playlist = self.service.update_music_playlist(playlist_id, name=name, icon_path=icon_path, order=order)
        self.reload_playlists(select_playlist_id=playlist.playlist_id)
        return playlist

    def play_track(self, music_id: str) -> bool:
        if not self.available:
            return False
        self._checkpoint_saved_for_stop = False
        track = self._track_by_id(music_id)
        if track is None or not track.enabled:
            return False

        if track.is_stream and not track.stream_url:
            self.resolve_track_stream(track, autoplay=True)
            return True

        if self._current_music_id != track.music_id:
            self._current_music_id = track.music_id
            self.service.set_active_music_id(track.music_id)
            self.current_track_changed.emit(track)

        self._paused = self.service.set_music_paused(False)
        source = QUrl(track.stream_url) if track.is_stream else QUrl.fromLocalFile(track.absolute_path)
        current_source = self._player.source() if self._player is not None else QUrl()
        if current_source != source:
            self._player.stop()
            self._player.setSource(source)
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

    def set_shuffle(self, enabled: bool) -> None:
        self._shuffle = self.service.set_music_shuffle(enabled)
        self._shuffle_queue = []
        self.shuffle_changed.emit(self._shuffle)

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
        if self._pending_checkpoint_position > 0 and music_id == self._stored_checkpoint_id and position <= 0:
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
        return self.add_music_file(self._current_playlist_id, source_path)

    def add_music_file(self, playlist_id: str, source_path: str | Path) -> str:
        reference = self.service.add_local_music_to_playlist(playlist_id, source_path)
        self.reload_playlists(select_playlist_id=playlist_id)
        if self.current_track() is None:
            self.play_track(reference)
        return reference

    def add_music_url(self, playlist_id: str, url: str) -> None:
        self._start_resolver(mode="add", playlist_id=playlist_id, url=url)

    def toggle_track_preview(self, music_id: str) -> None:
        if self._current_music_id == music_id and self.is_playing:
            self.pause()
            return
        if self._current_music_id == music_id:
            self.play()
            return
        self.play_track(music_id)

    def delete_playlist(self, playlist_id: str) -> bool:
        deleted = self.service.delete_music_playlist(playlist_id)
        if not deleted:
            return False
        self.reload_playlists(select_playlist_id=self.service.get_active_music_playlist_id())
        return True

    def resolve_track_stream(self, track: MusicRecord, *, autoplay: bool = False) -> None:
        source = track.source_url or track.relative_path
        if not source:
            return
        self._start_resolver(mode="refresh", playlist_id=self._current_playlist_id, url=source, music_id=track.music_id, autoplay=autoplay)

    def delete_music(self, music_id: str) -> bool:
        return self.remove_track_from_playlist(self._current_playlist_id, music_id)

    def remove_track_from_playlist(self, playlist_id: str, music_id: str) -> bool:
        removed = self.service.remove_music_from_playlist(playlist_id, music_id)
        if not removed:
            return False
        was_current = music_id == self._current_music_id
        self.reload_playlists(select_playlist_id=playlist_id)
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
        self.service.set_music_enabled(music_id, enabled)
        self.reload_playlists()
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
        self.service.set_music_playlist_order(self._current_playlist_id, ordered_ids)
        self.reload_playlists()
        if dropped_music_id and self.tracks() and self.tracks()[0].music_id == dropped_music_id and self.tracks()[0].enabled:
            self.play_track(dropped_music_id)

    def reorder_playlist_tracks(self, playlist_id: str, ordered_ids: list[str], *, dropped_music_id: str | None = None) -> None:
        self.service.set_music_playlist_order(playlist_id, ordered_ids)
        self.reload_playlists(select_playlist_id=playlist_id)
        if dropped_music_id:
            self.tracks_changed.emit()

    def reload_tracks(self) -> None:
        self.reload_playlists()

    def reload_playlists(self, *, select_playlist_id: str | None = None) -> None:
        if select_playlist_id:
            self._current_playlist_id = self.service.set_active_music_playlist_id(select_playlist_id)
        self._playlists = self.service.list_music_playlists()
        if self._playlist_by_id(self._current_playlist_id) is None:
            self._current_playlist_id = self.service.get_active_music_playlist_id()
        if self._track_by_id(self._current_music_id) is None:
            self._current_music_id = self.service.get_active_music_id()
        self.playlists_changed.emit()
        self.current_playlist_changed.emit(self.current_playlist())
        self.tracks_changed.emit()
        self.current_track_changed.emit(self.current_track())

    def _move_by(self, step: int, *, wrap: bool) -> bool:
        playable = self.playable_tracks()
        if not playable:
            return False
        if self._shuffle:
            ids = [track.music_id for track in playable]
            if not self._shuffle_queue or any(music_id not in ids for music_id in self._shuffle_queue):
                self._shuffle_queue = ids[:]
                random.shuffle(self._shuffle_queue)
            current_id = self._current_music_id
            current_index = self._shuffle_queue.index(current_id) if current_id in self._shuffle_queue else -1
            next_index = current_index + step
            if wrap:
                next_index %= len(self._shuffle_queue)
            elif next_index < 0 or next_index >= len(self._shuffle_queue):
                return False
            return self.play_track(self._shuffle_queue[next_index])

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
        for playlist in self._playlists:
            for track in playlist.tracks:
                if track.music_id == music_id:
                    return track
        return None

    def _playlist_by_id(self, playlist_id: str | None) -> MusicPlaylistRecord | None:
        if not playlist_id:
            return None
        for playlist in self._playlists:
            if playlist.playlist_id == playlist_id:
                return playlist
        return None

    def _start_resolver(
        self,
        *,
        mode: str,
        playlist_id: str,
        url: str,
        music_id: str | None = None,
        autoplay: bool = False,
    ) -> None:
        worker = MediaResolveWorker(
            mode=mode,
            playlist_id=playlist_id,
            url=url,
            music_id=music_id,
            autoplay=autoplay,
            artwork_cache_dir=self.service.cache_root / "music-artwork",
            parent=self,
        )
        worker.resolved.connect(self._handle_resolved_media)
        worker.failed.connect(self._handle_resolve_failed)
        worker.progress.connect(self.resolve_progress)
        worker.finished.connect(lambda worker=worker: self._workers.discard(worker))
        self._workers.add(worker)
        self.resolving_changed.emit(True, url)
        worker.start()

    def _handle_resolved_media(self, payload: dict[str, object]) -> None:
        playlist_id = str(payload.get("playlist_id") or self._current_playlist_id)
        mode = str(payload.get("mode") or "add")
        tracks = payload.get("tracks") if isinstance(payload.get("tracks"), list) else []
        first_id: str | None = None
        if mode == "refresh":
            music_id = _optional_text(payload.get("music_id"))
            if music_id and tracks:
                self.service.update_music_track_metadata(music_id, dict(tracks[0]))
                first_id = music_id
        else:
            for track_payload in tracks:
                if isinstance(track_payload, dict):
                    added_id = self.service.add_remote_music_to_playlist(playlist_id, track_payload)
                    first_id = first_id or added_id
        self.reload_playlists(select_playlist_id=playlist_id)
        self.resolving_changed.emit(False, "")
        if payload.get("autoplay") and first_id:
            self._stream_retry_counts.pop(first_id, None)
            self.play_track(first_id)

    def _handle_resolve_failed(self, payload: dict[str, object]) -> None:
        self.resolving_changed.emit(False, "")
        message = _optional_text(payload.get("error")) or "Music could not be resolved."
        music_id = _optional_text(payload.get("music_id"))
        if music_id:
            self.service.update_music_track_metadata(music_id, {"error": message})
            self.reload_playlists()
        now = monotonic()
        if now - self._last_resolve_warning_at > 8.0:
            self._last_resolve_warning_at = now
            self.resolve_failed.emit(message if message.startswith("Error:") else f"Error: {message}")

    def _apply_audio_output(self) -> None:
        if self._audio_output is None:
            return
        normalized = max(0.0, min(1.0, self._volume / 100.0))
        self._audio_output.setVolume(normalized**0.5)
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
        if hasattr(self._player, "isSeekable") and not self._player.isSeekable() and self._pending_checkpoint_attempts < 50:
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
        if status in {QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia}:
            self._apply_pending_checkpoint()
        if status != QMediaPlayer.MediaStatus.EndOfMedia:
            return
        if not self.next_track(wrap=self._loop):
            self.stop()

    def _handle_player_error(self, *_args) -> None:
        track = self.current_track()
        if track is not None and track.is_stream and track.source_url:
            now = monotonic()
            retry_count = self._stream_retry_counts.get(track.music_id, 0)
            if retry_count >= 1 or now - self._last_network_error_at < 8.0:
                self._last_network_error_at = now
                self.pause()
                return
            self._last_network_error_at = now
            self._stream_retry_counts[track.music_id] = retry_count + 1
            self.resolve_track_stream(track, autoplay=True)
            return
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
        value = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), position, span, self.invertedAppearance())
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
        self._hover_animation = QVariantAnimation(self, duration=150, easingCurve=QEasingCurve.OutCubic)
        self._hover_animation.valueChanged.connect(lambda value: self._set_progress("_hover", value))
        self._press_animation = QVariantAnimation(self, duration=100, easingCurve=QEasingCurve.OutCubic)
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
        self._animate(self._active_animation, self._active, 1.0 if active else 0.0)

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
        colors = theme_palette(self)["buttons"].get(self._role, theme_palette(self)["buttons"]["toolbar"])
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.2, 1.2, -1.2, -1.2)
        rect.translate(0, self._press * 0.7)
        bg = blend_colors(colors["bg"], colors["hover"], self._hover)
        bg = blend_colors(bg, colors["press"], self._press)
        bg = blend_colors(bg, colors["active"], self._active)
        border = blend_colors(colors["border"], colors["border_hover"], self._hover)
        border = blend_colors(border, colors["border_active"], self._active)
        icon_color = QColor(colors["text"])
        if self._active > 0.01:
            accent = self.property("accentColor")
            if isinstance(accent, QColor):
                icon_color = accent.lighter(135)
        if not self.isEnabled():
            bg.setAlpha(int(bg.alpha() * 0.42))
            border.setAlpha(int(border.alpha() * 0.44))
            icon_color.setAlpha(130)
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 8, 8)
        painter.setPen(QPen(icon_color, max(1.5, self._button_size / 18), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(icon_color)
        padding = 7 if self._icon_kind == "burger" else 8 if self._icon_kind in {"volume", "dots", "shuffle", "loop", "trash", "play", "pause", "plus", "edit", "window_play"} else 10
        self._paint_icon(painter, rect.adjusted(padding, padding, -padding, -padding), icon_color)

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
        if self._icon_kind == "trash":
            return QStyle.StandardPixmap.SP_TrashIcon
        return QStyle.StandardPixmap.SP_MediaPlay

    def _paint_icon(self, painter: QPainter, rect: QRectF, color: QColor) -> None:
        if self._icon_kind == "volume":
            self._paint_volume(painter, rect, color)
        elif self._icon_kind == "dots":
            self._paint_dots(painter, rect)
        elif self._icon_kind == "previous":
            self._paint_previous_next(painter, rect, previous=True)
        elif self._icon_kind == "next":
            self._paint_previous_next(painter, rect, previous=False)
        elif self._icon_kind == "pause":
            self._paint_pause(painter, rect)
        elif self._icon_kind == "loop":
            self._paint_loop(painter, rect)
        elif self._icon_kind == "shuffle":
            self._paint_shuffle(painter, rect)
        elif self._icon_kind == "burger":
            self._paint_burger(painter, rect)
        elif self._icon_kind == "trash":
            self._paint_trash(painter, rect)
        elif self._icon_kind == "window_play":
            self._paint_window_play(painter, rect)
        elif self._icon_kind == "plus":
            self._paint_plus(painter, rect)
        elif self._icon_kind == "edit":
            self._paint_edit(painter, rect)
        else:
            self._paint_play(painter, rect)

    def _paint_standard_icon(self, painter: QPainter, rect: QRectF) -> None:
        icon = self.style().standardIcon(self._standard_pixmap())
        pixmap = icon.pixmap(QSize(max(10, int(rect.width())), max(10, int(rect.height()))))
        painter.drawPixmap(int(rect.center().x() - pixmap.width() / 2), int(rect.center().y() - pixmap.height() / 2), pixmap)

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
            wave_rect = QRectF(
                rect.left() + rect.width() * (0.45 - (growth * 0.04)),
                rect.top() + max(1.0, 4.2 - (growth * 3.2)),
                rect.width() * (0.22 + (growth * 0.30)),
                rect.height() - (max(1.0, 4.2 - (growth * 3.2)) * 2),
            )
            painter.drawArc(wave_rect, -42 * 16, 84 * 16)
        painter.restore()

    def _paint_dots(self, painter: QPainter, rect: QRectF) -> None:
        radius = max(1.25, rect.width() * 0.075)
        for offset in (-0.42, 0, 0.42):
            painter.drawEllipse(QPoint(int(rect.center().x()), int(rect.center().y() + rect.height() * offset)), radius, radius)

    def _paint_previous_next(self, painter: QPainter, rect: QRectF, *, previous: bool) -> None:
        if previous:
            painter.drawRect(QRectF(rect.left(), rect.top() + 1, rect.width() * 0.12, rect.height() - 2))
            points = [QPoint(int(rect.right()), int(rect.top())), QPoint(int(rect.left() + rect.width() * 0.18), int(rect.center().y())), QPoint(int(rect.right()), int(rect.bottom()))]
        else:
            painter.drawRect(QRectF(rect.right() - rect.width() * 0.12, rect.top() + 1, rect.width() * 0.12, rect.height() - 2))
            points = [QPoint(int(rect.left()), int(rect.top())), QPoint(int(rect.right() - rect.width() * 0.18), int(rect.center().y())), QPoint(int(rect.left()), int(rect.bottom()))]
        painter.drawPolygon(QPolygonF(points))

    def _paint_play(self, painter: QPainter, rect: QRectF) -> None:
        painter.drawPolygon(
            QPolygonF(
                [
                    QPoint(int(rect.left() + 2), int(rect.top())),
                    QPoint(int(rect.right()), int(rect.center().y())),
                    QPoint(int(rect.left() + 2), int(rect.bottom())),
                ]
            )
        )

    def _paint_pause(self, painter: QPainter, rect: QRectF) -> None:
        bar_width = max(3.0, rect.width() * 0.22)
        gap = max(3.8, rect.width() * 0.28)
        bar_height = rect.height() * 0.86
        start_x = rect.center().x() - (((bar_width * 2) + gap) / 2)
        top = rect.center().y() - (bar_height / 2)
        radius = max(1.3, bar_width * 0.45)
        painter.drawRoundedRect(QRectF(start_x, top, bar_width, bar_height), radius, radius)
        painter.drawRoundedRect(QRectF(start_x + bar_width + gap, top, bar_width, bar_height), radius, radius)

    def _paint_trash(self, painter: QPainter, rect: QRectF) -> None:
        painter.save()
        painter.setBrush(Qt.NoBrush)
        pen = painter.pen()
        pen.setWidthF(max(1.7, rect.width() * 0.10))
        painter.setPen(pen)
        left = rect.left() + rect.width() * 0.22
        right = rect.right() - rect.width() * 0.22
        top = rect.top() + rect.height() * 0.34
        bottom = rect.bottom() - rect.height() * 0.08
        lid_y = rect.top() + rect.height() * 0.25
        handle_left = rect.left() + rect.width() * 0.40
        handle_right = rect.right() - rect.width() * 0.40
        handle_y = rect.top() + rect.height() * 0.14
        painter.drawLine(QPoint(int(left - rect.width() * 0.08), int(lid_y)), QPoint(int(right + rect.width() * 0.08), int(lid_y)))
        painter.drawLine(QPoint(int(handle_left), int(lid_y - 1)), QPoint(int(handle_left), int(handle_y)))
        painter.drawLine(QPoint(int(handle_left), int(handle_y)), QPoint(int(handle_right), int(handle_y)))
        painter.drawLine(QPoint(int(handle_right), int(handle_y)), QPoint(int(handle_right), int(lid_y - 1)))
        body = QPainterPath()
        body.moveTo(left, top)
        body.lineTo(right, top)
        body.lineTo(right - rect.width() * 0.07, bottom)
        body.quadTo(rect.center().x(), rect.bottom(), left + rect.width() * 0.07, bottom)
        body.closeSubpath()
        painter.drawPath(body)
        painter.drawLine(QPoint(int(rect.center().x() - rect.width() * 0.11), int(top + rect.height() * 0.18)), QPoint(int(rect.center().x() - rect.width() * 0.08), int(bottom - rect.height() * 0.12)))
        painter.drawLine(QPoint(int(rect.center().x() + rect.width() * 0.11), int(top + rect.height() * 0.18)), QPoint(int(rect.center().x() + rect.width() * 0.08), int(bottom - rect.height() * 0.12)))
        painter.restore()

    def _paint_loop(self, painter: QPainter, rect: QRectF) -> None:
        painter.save()
        painter.setBrush(Qt.NoBrush)
        pen = painter.pen()
        pen.setWidthF(max(1.8, rect.width() * 0.12))
        painter.setPen(pen)
        top_y = rect.top() + rect.height() * 0.34
        bottom_y = rect.top() + rect.height() * 0.66
        left_x = rect.left() + rect.width() * 0.20
        right_x = rect.right() - rect.width() * 0.20
        curve = rect.height() * 0.22
        top_path = QPainterPath()
        top_path.moveTo(left_x, top_y)
        top_path.cubicTo(left_x + curve, rect.top(), right_x - curve, rect.top(), right_x, top_y)
        painter.drawPath(top_path)
        bottom_path = QPainterPath()
        bottom_path.moveTo(right_x, bottom_y)
        bottom_path.cubicTo(right_x - curve, rect.bottom(), left_x + curve, rect.bottom(), left_x, bottom_y)
        painter.drawPath(bottom_path)
        painter.setBrush(painter.pen().color())
        painter.drawPolygon(QPolygonF([QPoint(int(right_x), int(top_y)), QPoint(int(right_x - rect.width() * 0.18), int(top_y - rect.height() * 0.16)), QPoint(int(right_x - rect.width() * 0.05), int(top_y + rect.height() * 0.19))]))
        painter.drawPolygon(QPolygonF([QPoint(int(left_x), int(bottom_y)), QPoint(int(left_x + rect.width() * 0.18), int(bottom_y + rect.height() * 0.16)), QPoint(int(left_x + rect.width() * 0.05), int(bottom_y - rect.height() * 0.19))]))
        painter.restore()

    def _paint_shuffle(self, painter: QPainter, rect: QRectF) -> None:
        painter.save()
        painter.setBrush(Qt.NoBrush)
        pen = painter.pen()
        pen.setWidthF(max(1.7, rect.width() * 0.11))
        painter.setPen(pen)
        top = rect.top() + rect.height() * 0.28
        bottom = rect.bottom() - rect.height() * 0.28
        painter.drawLine(QPoint(int(rect.left()), int(top)), QPoint(int(rect.left() + rect.width() * 0.35), int(top)))
        painter.drawLine(QPoint(int(rect.left()), int(bottom)), QPoint(int(rect.left() + rect.width() * 0.35), int(bottom)))
        path = QPainterPath()
        path.moveTo(rect.left() + rect.width() * 0.32, top)
        path.cubicTo(rect.center().x(), top, rect.center().x(), bottom, rect.right() - rect.width() * 0.18, bottom)
        painter.drawPath(path)
        path = QPainterPath()
        path.moveTo(rect.left() + rect.width() * 0.32, bottom)
        path.cubicTo(rect.center().x(), bottom, rect.center().x(), top, rect.right() - rect.width() * 0.18, top)
        painter.drawPath(path)
        painter.setBrush(painter.pen().color())
        painter.drawPolygon(QPolygonF([QPoint(int(rect.right()), int(top)), QPoint(int(rect.right() - rect.width() * 0.18), int(top - rect.height() * 0.14)), QPoint(int(rect.right() - rect.width() * 0.18), int(top + rect.height() * 0.14))]))
        painter.drawPolygon(QPolygonF([QPoint(int(rect.right()), int(bottom)), QPoint(int(rect.right() - rect.width() * 0.18), int(bottom - rect.height() * 0.14)), QPoint(int(rect.right() - rect.width() * 0.18), int(bottom + rect.height() * 0.14))]))
        painter.restore()

    def _paint_burger(self, painter: QPainter, rect: QRectF) -> None:
        for offset in (0.25, 0.5, 0.75):
            y = rect.top() + rect.height() * offset
            painter.drawLine(QPoint(int(rect.left()), int(y)), QPoint(int(rect.right()), int(y)))

    def _paint_plus(self, painter: QPainter, rect: QRectF) -> None:
        painter.drawLine(QPoint(int(rect.center().x()), int(rect.top())), QPoint(int(rect.center().x()), int(rect.bottom())))
        painter.drawLine(QPoint(int(rect.left()), int(rect.center().y())), QPoint(int(rect.right()), int(rect.center().y())))

    def _paint_window_play(self, painter: QPainter, rect: QRectF) -> None:
        painter.save()
        pen = painter.pen()
        pen.setWidthF(max(1.6, rect.width() * 0.08))
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        window = QRectF(rect.left(), rect.top() + rect.height() * 0.08, rect.width() * 0.72, rect.height() * 0.72)
        painter.drawRoundedRect(window, 3, 3)
        painter.drawLine(QPoint(int(window.left()), int(window.top() + window.height() * 0.26)), QPoint(int(window.right()), int(window.top() + window.height() * 0.26)))
        painter.setBrush(pen.color())
        painter.drawPolygon(
            QPolygonF(
                [
                    QPoint(int(rect.left() + rect.width() * 0.52), int(rect.top() + rect.height() * 0.30)),
                    QPoint(int(rect.right()), int(rect.center().y())),
                    QPoint(int(rect.left() + rect.width() * 0.52), int(rect.bottom() - rect.height() * 0.10)),
                ]
            )
        )
        painter.restore()

    def _paint_edit(self, painter: QPainter, rect: QRectF) -> None:
        painter.save()
        painter.setBrush(Qt.NoBrush)
        pen = painter.pen()
        pen.setWidthF(max(1.7, rect.width() * 0.11))
        painter.setPen(pen)
        shaft = QPainterPath()
        shaft.moveTo(rect.left() + rect.width() * 0.20, rect.bottom() - rect.height() * 0.18)
        shaft.lineTo(rect.right() - rect.width() * 0.20, rect.top() + rect.height() * 0.22)
        painter.drawPath(shaft)
        painter.drawLine(
            QPoint(int(rect.right() - rect.width() * 0.34), int(rect.top() + rect.height() * 0.10)),
            QPoint(int(rect.right() - rect.width() * 0.10), int(rect.top() + rect.height() * 0.34)),
        )
        painter.drawLine(
            QPoint(int(rect.left() + rect.width() * 0.12), int(rect.bottom() - rect.height() * 0.08)),
            QPoint(int(rect.left() + rect.width() * 0.28), int(rect.bottom() - rect.height() * 0.12)),
        )
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
        if not self._syncing:
            self.controller.set_volume(value)

    def _sync_volume(self, volume: int, muted: bool) -> None:
        self._syncing = True
        self.volume_slider.setValue(volume)
        self._syncing = False
        self.volume_button.set_volume_state(volume, muted)


class ArtworkLabel(QLabel):
    def __init__(self, size: int, parent: QWidget | None = None):
        super().__init__(parent)
        self._size = size
        self._pixmap = QPixmap()
        self.setFixedSize(size, size)
        self.setObjectName("musicArtwork")
        self.setScaledContents(False)

    def set_artwork(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        painter.setClipPath(path)
        if self._pixmap.isNull():
            painter.fillRect(rect, QColor(24, 36, 52))
            painter.setPen(QPen(QColor(125, 164, 224), 2))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 8, 8)
            return
        scaled = self._pixmap.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = int((self.width() - scaled.width()) / 2)
        y = int((self.height() - scaled.height()) / 2)
        painter.drawPixmap(x, y, scaled)


class MarqueeLabel(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self._offset = 0
        self._direction = 1
        self._hold_ticks = 0
        self._timer = QTimer(self)
        self._timer.setInterval(70)
        self._timer.timeout.connect(self._tick)
        self.setMinimumHeight(28)

    def setText(self, text: str) -> None:
        super().setText(text)
        self._offset = 0
        self._direction = 1
        self._hold_ticks = 12
        self._update_timer()
        self.update()

    def resizeEvent(self, event) -> None:
        self._update_timer()
        super().resizeEvent(event)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.setFont(self.font())
        painter.setPen(self.palette().color(self.foregroundRole()))
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        y = int((self.height() + self.fontMetrics().ascent() - self.fontMetrics().descent()) / 2)
        if text_width <= self.width():
            painter.drawText(0, y, self.text())
            return
        painter.setClipRect(self.rect())
        painter.drawText(-self._offset, y, self.text())

    def _tick(self) -> None:
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        overflow = max(0, text_width - self.width())
        if overflow <= 0:
            self._timer.stop()
            return
        if self._hold_ticks > 0:
            self._hold_ticks -= 1
            return
        self._offset += self._direction
        if self._offset >= overflow:
            self._offset = overflow
            self._direction = -1
            self._hold_ticks = 12
        elif self._offset <= 0:
            self._offset = 0
            self._direction = 1
            self._hold_ticks = 12
        self.update()

    def _update_timer(self) -> None:
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        if text_width > self.width() and self.width() > 0:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
            self._offset = 0


class TrackRowWidget(QFrame):
    enabled_changed = Signal(str, bool)
    delete_requested = Signal(str)
    preview_requested = Signal(str)

    def __init__(self, number: int, record: MusicRecord, service: LauncherService, *, editor: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.record = record
        self.service = service
        self._editor = editor
        self._active = False
        self._hover = 0.0
        self._flash = 0.0
        self.setObjectName("musicTrackRow")
        self.setMinimumHeight(50 if editor else 48)
        self.setMouseTracking(True)
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity_effect)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 6, 10, 6)
        layout.setSpacing(10)

        self.drag_handle = DragHandle()
        self.drag_handle.setToolTip("Drag to reorder")
        layout.addWidget(self.drag_handle)

        self.number_label = QLabel(str(number))
        self.number_label.setObjectName("musicTrackNumber")
        self.number_label.setAlignment(Qt.AlignCenter)
        self.number_label.setFixedWidth(26)
        layout.addWidget(self.number_label)

        self.artwork = ArtworkLabel(34)
        self.artwork.set_artwork(_track_pixmap(record, service, 34))
        layout.addWidget(self.artwork)

        self.name_label = QLabel(record.name)
        self.name_label.setObjectName("musicTrackName")
        self.name_label.setTextInteractionFlags(Qt.NoTextInteraction)
        self.name_label.setToolTip(record.name)
        self.name_label.setMinimumWidth(120)
        layout.addWidget(self.name_label, 1)

        self.date_label = QLabel(_format_date_label(record.date_added))
        self.date_label.setObjectName("musicTrackMeta")
        self.date_label.setFixedWidth(118)
        layout.addWidget(self.date_label)

        self.duration_label = QLabel(_format_time(record.duration_ms) if record.duration_ms else "--:--")
        self.duration_label.setObjectName("musicTrackMeta")
        self.duration_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.duration_label.setFixedWidth(56)
        layout.addWidget(self.duration_label)

        if editor:
            self.preview_button = IconButton("play", role="accent", button_size=34)
            self.preview_button.setToolTip("Preview track")
            self.preview_button.clicked.connect(lambda: self.preview_requested.emit(self.record.music_id))
            layout.addWidget(self.preview_button)
            self.delete_button = IconButton("trash", role="danger", button_size=34)
            self.delete_button.setToolTip("Remove track")
            self.delete_button.clicked.connect(lambda: self.delete_requested.emit(self.record.music_id))
            layout.addWidget(self.delete_button)

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
        if self._editor and hasattr(self, "preview_button"):
            self.preview_button.set_icon_kind("pause" if active else "play")
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
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        accent = self.property("accentColor")
        accent = QColor(accent) if isinstance(accent, QColor) else DEFAULT_ACCENT
        bg = QColor(10, 16, 26, 118)
        hover = QColor(accent)
        hover.setAlpha(42)
        active = QColor(accent)
        active.setAlpha(68 if self._active else 0)
        flash = QColor(accent)
        flash.setAlpha(int(76 * self._flash))
        bg = blend_colors(bg, hover, self._hover)
        bg = blend_colors(bg, active, 1.0 if self._active else 0.0)
        bg = blend_colors(bg, flash, self._flash)
        border = QColor(accent)
        border.setAlpha(115 if self._active else int(60 + (self._hover * 40)))
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 8, 8)

    def _animate(self, animation: QVariantAnimation, start: float, end: float) -> None:
        animation.stop()
        animation.setStartValue(float(start))
        animation.setEndValue(float(end))
        animation.start()

    def _set_value(self, attribute: str, value) -> None:
        setattr(self, attribute, float(value))
        self.update()


class DragHandle(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("musicDragHandle")
        self.setCursor(Qt.OpenHandCursor)
        self.setFixedSize(20, 28)

    def paintEvent(self, event) -> None:
        del event
        color = QColor(190, 210, 240, 150)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        for column in range(2):
            for row in range(3):
                painter.drawEllipse(QRectF(4 + (column * 7), 6 + (row * 7), 3.2, 3.2))


class AnimatedTrackList(QListWidget):
    records_reordered = Signal(list, str)
    track_enabled_changed = Signal(str, bool)
    track_activated = Signal(str)
    selected_track_changed = Signal(object)
    delete_requested = Signal(str)

    def __init__(self, service: LauncherService, *, editor: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.service = service
        self._editor = editor
        self._drag_allowed = False
        self._drag_candidate_id: str | None = None
        self._accent = DEFAULT_ACCENT
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
        self.setSpacing(6)
        self.setMouseTracking(True)
        self.itemSelectionChanged.connect(self._emit_selected_track)

    def set_accent(self, color: QColor) -> None:
        self._accent = QColor(color)
        for index in range(self.count()):
            row = self.itemWidget(self.item(index))
            if isinstance(row, TrackRowWidget):
                row.setProperty("accentColor", self._accent)
                row.update()

    def set_tracks(self, records: list[MusicRecord], current_music_id: str | None = None) -> None:
        selected_id = self.selected_music_id()
        scroll_value = self.verticalScrollBar().value()
        self.clear()
        for index, record in enumerate(records, start=1):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, record.music_id)
            item.setData(Qt.UserRole + 1, record)
            item.setSizeHint(QSize(100, 54 if self._editor else 52))
            self.addItem(item)
            row = TrackRowWidget(index, record, self.service, editor=self._editor)
            row.setProperty("accentColor", self._accent)
            row.enabled_changed.connect(self.track_enabled_changed)
            row.preview_requested.connect(self.track_activated)
            row.delete_requested.connect(self.delete_requested)
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


class PlaylistRowWidget(QFrame):
    def __init__(self, playlist: MusicPlaylistRecord, service: LauncherService, parent: QWidget | None = None):
        super().__init__(parent)
        self.playlist = playlist
        self.service = service
        self._selected = False
        self._compact = False
        self.setObjectName("musicPlaylistRow")
        self.setMinimumHeight(46)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(8, 6, 8, 6)
        self._layout.setSpacing(10)
        self.icon_label = ArtworkLabel(32)
        self.icon_label.set_artwork(_playlist_pixmap(playlist, service, 32))
        self._layout.addWidget(self.icon_label)
        self.name_label = QLabel(playlist.name)
        self.name_label.setObjectName("musicPlaylistName")
        self.name_label.setMinimumWidth(80)
        self._layout.addWidget(self.name_label, 1)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.update()

    def set_compact(self, compact: bool) -> None:
        self._compact = compact
        self.name_label.setVisible(not compact)
        self.setFixedHeight(48)
        if compact:
            self._layout.setContentsMargins(0, 6, 0, 6)
            self._layout.setAlignment(self.icon_label, Qt.AlignCenter)
            self.setFixedWidth(48)
        else:
            self._layout.setContentsMargins(8, 6, 8, 6)
            self._layout.setAlignment(self.icon_label, Qt.Alignment())
            self.setMinimumWidth(0)
            self.setMaximumWidth(16777215)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        accent = self.property("accentColor")
        accent = QColor(accent) if isinstance(accent, QColor) else DEFAULT_ACCENT
        bg = QColor(accent)
        bg.setAlpha(52 if self._selected else 0)
        if self.underMouse() and not self._selected:
            bg.setAlpha(28)
        border = QColor(accent)
        border.setAlpha(90 if self._selected else 0)
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 8, 8)


class PlaylistIconSelectorDialog(QDialog):
    def __init__(self, service: LauncherService, selected_icon_path: str | None, parent: QWidget | None = None):
        super().__init__(parent)
        self.service = service
        self.selected_icon_path = selected_icon_path
        self._tiles: dict[str, QPushButton] = {}
        self._custom_dir = self.service.data_root / "playlist-icons"
        self.setObjectName("musicPlaylistEditorDialog")
        self.setWindowTitle("Pick Playlist Icon")
        self.setModal(True)
        self.setMinimumSize(620, 520)
        self.resize(fitted_window_size(self.parentWidget() or self, 720, 620, minimum_width=620, minimum_height=520))
        self._build_ui()
        self._reload_icons()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(12)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.grid_holder = QWidget()
        self.grid_layout = QGridLayout(self.grid_holder)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(10)
        self.scroll_area.setWidget(self.grid_holder)
        root.addWidget(self.scroll_area, 1)

        footer = QHBoxLayout()
        self.add_button = ModernButton("Add Icon", role="sidebar", height=38, icon_size=0, minimum_width=110)
        self.add_button.clicked.connect(self._add_icon)
        footer.addWidget(self.add_button)
        self.remove_button = ModernButton("Remove Icon", role="danger", height=38, icon_size=0, minimum_width=120)
        self.remove_button.clicked.connect(self._remove_icon)
        footer.addWidget(self.remove_button)
        self.open_button = ModernButton("Open Folder", role="sidebar", height=38, icon_size=0, minimum_width=126)
        self.open_button.clicked.connect(self._open_folder)
        footer.addWidget(self.open_button)
        footer.addStretch()
        self.ok_button = ModernButton("OK", role="accent", height=38, icon_size=0, minimum_width=84)
        self.ok_button.clicked.connect(self.accept)
        footer.addWidget(self.ok_button)
        root.addLayout(footer)
        self.setStyleSheet(_manager_stylesheet(DEFAULT_ACCENT.name()))

    def _reload_icons(self) -> None:
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._tiles.clear()
        icons = self._playlist_icon_paths()
        if self.selected_icon_path not in icons and icons:
            self.selected_icon_path = icons[0]
        for index, icon_path in enumerate(icons):
            button = QPushButton()
            button.setObjectName("musicIconPicker")
            button.setCursor(Qt.PointingHandCursor)
            button.setCheckable(True)
            button.setFixedSize(104, 104)
            pixmap = _load_image_pixmap(icon_path, self.service, 88, fallback_music=False)
            button.setIcon(QIcon(pixmap))
            button.setIconSize(QSize(86, 86))
            button.setChecked(icon_path == self.selected_icon_path)
            button.clicked.connect(lambda _checked=False, path=icon_path: self._select_icon(path))
            self._tiles[icon_path] = button
            self.grid_layout.addWidget(button, index // 5, index % 5)

    def _select_icon(self, icon_path: str) -> None:
        self.selected_icon_path = icon_path
        for path, button in self._tiles.items():
            button.setChecked(path == icon_path)

    def _playlist_icon_paths(self) -> list[str]:
        paths: list[str] = []
        default_dir = self.service.project_root / PLAYLIST_ICON_PREFIX
        if default_dir.is_dir():
            paths.extend(
                f"{PLAYLIST_ICON_PREFIX}/{path.name}"
                for path in sorted(default_dir.iterdir(), key=lambda item: item.name.lower())
                if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
            )
        if self._custom_dir.is_dir():
            paths.extend(
                str(path.resolve())
                for path in sorted(self._custom_dir.iterdir(), key=lambda item: item.name.lower())
                if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
            )
        return paths

    def _add_icon(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Add Playlist Icon", str(Path.home()), "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not path:
            return
        try:
            source = Path(path)
            self._custom_dir.mkdir(parents=True, exist_ok=True)
            target = self._custom_dir / _unique_icon_name(self._custom_dir, source.name)
            shutil.copy2(source, target)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Icon Error", str(exc))
            return
        self.selected_icon_path = str(target.resolve())
        self._reload_icons()

    def _remove_icon(self) -> None:
        selected = _optional_text(self.selected_icon_path)
        if not selected or selected.startswith(PLAYLIST_ICON_PREFIX):
            self.remove_button.flash_invalid()
            return
        try:
            path = Path(selected)
            path.resolve().relative_to(self._custom_dir.resolve())
            path.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Icon Error", str(exc))
            return
        self.selected_icon_path = None
        self._reload_icons()

    def _open_folder(self) -> None:
        self._custom_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._custom_dir)))


class MusicResolveProgressDialog(QDialog):
    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("musicPlaylistEditorDialog")
        self.setWindowTitle("Adding Music")
        self.setModal(False)
        self.setMinimumSize(520, 190)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("musicPlaylistTitle")
        root.addWidget(self.title_label)
        self.status_label = QLabel("Starting...")
        self.status_label.setObjectName("musicTrackMeta")
        root.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("installProgressBar")
        self.progress_bar.setRange(0, 0)
        root.addWidget(self.progress_bar)
        self.setStyleSheet(_manager_stylesheet(DEFAULT_ACCENT.name()))

    def handle_progress(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        text = _optional_text(payload.get("text"))
        if text:
            self.status_label.setText(text)
        maximum = payload.get("maximum")
        value = payload.get("value")
        if maximum is not None:
            try:
                self.progress_bar.setRange(0, max(1, int(maximum)))
            except (TypeError, ValueError):
                pass
        if value is not None:
            try:
                self.progress_bar.setValue(max(0, int(value)))
            except (TypeError, ValueError):
                pass


class MusicPlaylistEditorDialog(QDialog):
    def __init__(self, controller: MusicController, playlist_id: str | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller
        if playlist_id is None:
            self.playlist = self.controller.create_playlist("New Playlist")
        else:
            self.playlist = self.controller.service.get_music_playlist(playlist_id)
        self._icon_path = self.playlist.icon_path
        self._syncing_name = False
        self._progress_dialog: MusicResolveProgressDialog | None = None
        self._rename_timer = QTimer(self)
        self._rename_timer.setSingleShot(True)
        self._rename_timer.setInterval(420)
        self._rename_timer.timeout.connect(self._commit_rename)
        self.setObjectName("musicPlaylistEditorDialog")
        self.setWindowTitle("Playlist Editor")
        self.setWindowIcon(application_icon(self.controller.service.project_root))
        self.setModal(False)
        self.setMinimumSize(720, 560)
        self.resize(fitted_window_size(self.parentWidget() or self, 820, 620, minimum_width=720, minimum_height=560))
        self._build_ui()
        self._connect_controller()
        self._sync_playlist()
        self._apply_style(DEFAULT_ACCENT)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(14)

        top = QHBoxLayout()
        top.setSpacing(14)
        self.icon_button = QPushButton()
        self.icon_button.setObjectName("musicIconPicker")
        self.icon_button.setCursor(Qt.PointingHandCursor)
        self.icon_button.setFixedSize(104, 104)
        self.icon_button.clicked.connect(self._choose_icon)
        top.addWidget(self.icon_button)
        self.name_input = QLineEdit()
        self.name_input.setObjectName("musicEditorNameInput")
        self.name_input.setPlaceholderText("Playlist name")
        self.name_input.textEdited.connect(self._schedule_rename)
        top.addWidget(self.name_input, 1, Qt.AlignTop)
        root.addLayout(top)

        input_row = QHBoxLayout()
        input_row.setSpacing(10)
        self.url_input = QLineEdit()
        self.url_input.setObjectName("musicUrlInput")
        self.url_input.setPlaceholderText("Just put URL of your playlist or music (mostly YT works)")
        self.url_input.returnPressed.connect(self._add_url)
        input_row.addWidget(self.url_input, 1)
        self.add_url_button = ModernButton("Add", role="accent", height=38, icon_size=0, minimum_width=82, horizontal_padding=18, font_point_size=10)
        self.add_url_button.clicked.connect(self._add_url)
        input_row.addWidget(self.add_url_button)
        self.browse_button = ModernButton("Browse", role="toolbar", height=38, icon_size=0, minimum_width=104, horizontal_padding=20, font_point_size=10)
        self.browse_button.clicked.connect(self._browse_music)
        input_row.addWidget(self.browse_button)
        root.addLayout(input_row)

        self.track_list = AnimatedTrackList(self.controller.service, editor=True)
        self.track_list.records_reordered.connect(self._handle_records_reordered)
        self.track_list.track_activated.connect(self.controller.toggle_track_preview)
        self.track_list.delete_requested.connect(self._delete_track)
        root.addWidget(self.track_list, 1)

        footer = QHBoxLayout()
        self.delete_playlist_button = ModernButton("Delete Playlist", role="danger", height=38, icon_size=0, minimum_width=142, horizontal_padding=20, font_point_size=10)
        self.delete_playlist_button.clicked.connect(self._delete_playlist)
        footer.addWidget(self.delete_playlist_button)
        footer.addStretch()
        self.close_button = ModernButton("Done", role="accent", height=38, icon_size=0, minimum_width=92, horizontal_padding=22, font_point_size=10)
        self.close_button.clicked.connect(self.accept)
        footer.addWidget(self.close_button)
        root.addLayout(footer)

    def _connect_controller(self) -> None:
        self.controller.playlists_changed.connect(self._sync_playlist)
        self.controller.tracks_changed.connect(self._sync_playlist)
        self.controller.current_track_changed.connect(self._sync_current_track)
        self.controller.resolving_changed.connect(self._sync_resolving)
        self.controller.resolve_progress.connect(self._sync_resolve_progress)
        self.controller.resolve_failed.connect(lambda message: QMessageBox.warning(self, "Music", message))

    def _sync_playlist(self) -> None:
        self.playlist = self.controller.service.get_music_playlist(self.playlist.playlist_id)
        if not self.name_input.hasFocus():
            self._syncing_name = True
            self.name_input.setText(self.playlist.name)
            self._syncing_name = False
        self._set_icon_preview(_playlist_pixmap(self.playlist, self.controller.service, 96))
        current = self.controller.current_track()
        self.track_list.set_tracks(self.playlist.tracks, current.music_id if current else None)
        pixmap = _playlist_pixmap(self.playlist, self.controller.service, 64)
        self._apply_style(_dominant_color(pixmap))

    def _sync_current_track(self, track: MusicRecord | None) -> None:
        self.track_list.set_current_track_id(track.music_id if track else None)

    def _sync_resolving(self, resolving: bool, url: str) -> None:
        del url
        self.add_url_button.setEnabled(not resolving)
        self.browse_button.setEnabled(not resolving)
        if not resolving and self._progress_dialog is not None:
            self._progress_dialog.accept()
            self._progress_dialog = None

    def _schedule_rename(self, name: str) -> None:
        if self._syncing_name:
            return
        del name
        self._rename_timer.start()

    def _commit_rename(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            return
        self.controller.update_playlist(self.playlist.playlist_id, name=name, icon_path=self._icon_path)

    def _choose_icon(self) -> None:
        dialog = PlaylistIconSelectorDialog(self.controller.service, self._icon_path, self)
        if dialog.exec() != QDialog.Accepted or not dialog.selected_icon_path:
            return
        self._icon_path = dialog.selected_icon_path
        self.controller.update_playlist(self.playlist.playlist_id, icon_path=self._icon_path)

    def _add_url(self) -> None:
        url = self.url_input.text().strip()
        if not url:
            return
        self._open_progress_dialog("Adding Music")
        self.controller.add_music_url(self.playlist.playlist_id, url)
        self.url_input.clear()

    def _browse_music(self) -> None:
        suffixes = " ".join(f"*{suffix}" for suffix in sorted(MUSIC_SUFFIXES))
        paths, _ = QFileDialog.getOpenFileNames(self, "Add Local Music", str(Path.home()), f"Audio Files ({suffixes})")
        for path in paths:
            try:
                self.controller.add_music_file(self.playlist.playlist_id, path)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, "Add Music", str(exc))

    def _delete_track(self, music_id: str) -> None:
        self.controller.remove_track_from_playlist(self.playlist.playlist_id, music_id)

    def _delete_playlist(self) -> None:
        if len(self.controller.playlists()) <= 1:
            QMessageBox.information(self, "Delete Playlist", "At least one playlist must remain.")
            return
        answer = QMessageBox.question(self, "Delete Playlist", f"Delete playlist '{self.playlist.name}'?")
        if answer != QMessageBox.Yes:
            return
        if self.controller.delete_playlist(self.playlist.playlist_id):
            self.accept()

    def _handle_records_reordered(self, ordered_ids: list[str], dropped_music_id: str) -> None:
        self.controller.reorder_playlist_tracks(self.playlist.playlist_id, ordered_ids, dropped_music_id=dropped_music_id)

    def _set_icon_preview(self, pixmap: QPixmap) -> None:
        self.icon_button.setIcon(QIcon(pixmap))
        self.icon_button.setIconSize(QSize(92, 92))

    def _apply_style(self, accent: QColor) -> None:
        accent_hex = accent.name()
        self.setStyleSheet(_manager_stylesheet(accent_hex))
        self.track_list.set_accent(accent)

    def _open_progress_dialog(self, title: str) -> None:
        self._progress_dialog = MusicResolveProgressDialog(title, self)
        self._progress_dialog.show()
        self._progress_dialog.raise_()

    def _sync_resolve_progress(self, payload: object) -> None:
        if self._progress_dialog is not None:
            self._progress_dialog.handle_progress(payload)

    def accept(self) -> None:
        if self.name_input.text().strip():
            self._commit_rename()
        super().accept()


class MusicManagerDialog(QDialog):
    def __init__(self, controller: MusicController, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller
        self._seek_dragging = False
        self._sidebar_collapsed = False
        self._accent = DEFAULT_ACCENT
        self._editor_dialog: MusicPlaylistEditorDialog | None = None
        self._bubble_hide_timer = QTimer(self)
        self._bubble_hide_timer.setSingleShot(True)
        self._bubble_hide_timer.timeout.connect(self._hide_time_bubble)
        self.setObjectName("musicManagerDialog")
        self.setWindowTitle("Music Manager")
        self.setWindowIcon(application_icon(self.controller.service.project_root))
        self.setModal(False)
        self.setMinimumSize(860, 620)
        self.resize(fitted_window_size(self.parentWidget() or self, 1040, 700, minimum_width=860, minimum_height=620))
        self._build_ui()
        self._connect_controller()
        self._sync_all()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        base = QColor("#000000")
        deep = QColor("#07182a")
        accent = QColor(self._accent)
        gradient = painter.window()
        del gradient
        rect = self.rect()
        linear = QColor(deep)
        painter.fillRect(rect, base)
        wash = QColor(accent)
        wash.setAlpha(34)
        painter.fillRect(rect, QColor("#020710"))
        path = QPainterPath()
        path.addEllipse(QRectF(-self.width() * 0.18, -self.height() * 0.24, self.width() * 0.9, self.height() * 0.74))
        painter.fillPath(path, wash)
        lower = QColor(linear)
        lower.setAlpha(116)
        painter.fillRect(rect.adjusted(0, int(self.height() * 0.25), 0, 0), lower)

    def resizeEvent(self, event) -> None:
        self._position_time_bubble(self.seek_slider.value())
        super().resizeEvent(event)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(14)
        root.addLayout(body, 1)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("musicSidebar")
        self.sidebar.setMinimumWidth(224)
        self.sidebar.setMaximumWidth(224)
        side_layout = QVBoxLayout(self.sidebar)
        side_layout.setContentsMargins(10, 10, 10, 10)
        side_layout.setSpacing(10)
        side_header = QHBoxLayout()
        self.side_header = side_header
        side_header.setContentsMargins(0, 0, 0, 0)
        side_header.setSpacing(8)
        self.burger_button = IconButton("burger", role="toolbar", button_size=34)
        self.burger_button.setToolTip("Collapse sidebar")
        self.burger_button.clicked.connect(self._toggle_sidebar)
        side_header.addWidget(self.burger_button)
        self.add_playlist_button = IconButton("plus", role="toolbar", button_size=34)
        self.add_playlist_button.setToolTip("Add playlist")
        self.add_playlist_button.clicked.connect(self._open_add_playlist)
        side_header.addWidget(self.add_playlist_button)
        self.background_play_button = IconButton("window_play", role="toolbar", button_size=34)
        self.background_play_button.setToolTip("Keep music playing when launcher closes")
        self.background_play_button.clicked.connect(lambda: self.controller.set_run_while_closed(not self.controller.run_while_closed))
        side_header.addWidget(self.background_play_button)
        side_header.addStretch()
        side_layout.addLayout(side_header)
        self.playlist_list = QListWidget()
        self.playlist_list.setObjectName("musicPlaylistList")
        self.playlist_list.setFrameShape(QFrame.NoFrame)
        self.playlist_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.playlist_list.setSpacing(6)
        self.playlist_list.itemClicked.connect(self._handle_playlist_clicked)
        side_layout.addWidget(self.playlist_list, 1)
        body.addWidget(self.sidebar)

        main = QFrame()
        main.setObjectName("musicMain")
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(20, 18, 20, 0)
        main_layout.setSpacing(14)
        body.addWidget(main, 1)

        header = QHBoxLayout()
        header.setSpacing(18)
        self.playlist_art = ArtworkLabel(132)
        header.addWidget(self.playlist_art)
        title_block = QVBoxLayout()
        title_block.setSpacing(4)
        title_block.addStretch()
        self.category_label = QLabel("PLAYLIST")
        self.category_label.setObjectName("musicCategoryLabel")
        title_block.addWidget(self.category_label)
        self.title_label = QLabel("Playlist")
        self.title_label.setObjectName("musicPlaylistTitle")
        self.title_label.setWordWrap(True)
        title_block.addWidget(self.title_label)
        title_block.addStretch()
        header.addLayout(title_block, 1)
        main_layout.addLayout(header)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        self.play_playlist_button = ModernButton("Play", role="accent", height=40, icon_size=0, minimum_width=96, horizontal_padding=22, font_point_size=11)
        self.play_playlist_button.clicked.connect(lambda: self.controller.play_playlist(self.controller.current_playlist().playlist_id))
        action_row.addWidget(self.play_playlist_button)
        self.shuffle_button = IconButton("shuffle", role="accent", button_size=40)
        self.shuffle_button.setToolTip("Toggle shuffle")
        self.shuffle_button.clicked.connect(lambda: self.controller.set_shuffle(not self.controller.shuffle_enabled))
        action_row.addWidget(self.shuffle_button)
        self.loop_button = IconButton("loop", role="accent", button_size=40)
        self.loop_button.setToolTip("Toggle loop")
        self.loop_button.clicked.connect(lambda: self.controller.set_loop(not self.controller.loop_enabled))
        action_row.addWidget(self.loop_button)
        action_row.addStretch()
        self.edit_button = IconButton("dots", role="toolbar", button_size=40)
        self.edit_button.setToolTip("Edit playlist")
        self.edit_button.clicked.connect(self._open_edit_playlist)
        action_row.addWidget(self.edit_button)
        main_layout.addLayout(action_row)

        self.track_list = AnimatedTrackList(self.controller.service)
        self.track_list.records_reordered.connect(self._handle_records_reordered)
        self.track_list.track_activated.connect(self.controller.play_track)
        self.track_list.selected_track_changed.connect(lambda *_: None)
        main_layout.addWidget(self.track_list, 1)

        self.playback_dock = QFrame()
        self.playback_dock.setObjectName("musicPlaybackDock")
        dock = QHBoxLayout(self.playback_dock)
        dock.setContentsMargins(14, 10, 14, 10)
        dock.setSpacing(16)
        self.now_art = ArtworkLabel(48)
        dock.addWidget(self.now_art)
        self.now_title = MarqueeLabel("No track")
        self.now_title.setObjectName("musicNowTitle")
        self.now_title.setMinimumWidth(150)
        font = QFont(self.now_title.font())
        font.setPointSize(max(12, font.pointSize() + 2))
        font.setWeight(QFont.Bold)
        self.now_title.setFont(font)
        dock.addWidget(self.now_title, 1)

        center = QVBoxLayout()
        center.setSpacing(4)
        controls = QHBoxLayout()
        controls.setSpacing(10)
        controls.addStretch()
        self.previous_button = IconButton("previous", role="accent", button_size=34)
        self.previous_button.clicked.connect(self.controller.previous_track)
        controls.addWidget(self.previous_button)
        self.play_button = IconButton("play", role="accent", button_size=38)
        self.play_button.clicked.connect(self.controller.toggle_playback)
        controls.addWidget(self.play_button)
        self.next_button = IconButton("next", role="accent", button_size=34)
        self.next_button.clicked.connect(self.controller.next_track)
        controls.addWidget(self.next_button)
        controls.addStretch()
        center.addLayout(controls)
        seek_row = QHBoxLayout()
        seek_row.setSpacing(8)
        self.elapsed_label = QLabel("0:00")
        self.elapsed_label.setObjectName("musicTimeLabel")
        seek_row.addWidget(self.elapsed_label)
        self.seek_holder = QFrame()
        self.seek_holder.setObjectName("musicSeekHolder")
        self.seek_holder.setMinimumHeight(32)
        seek_holder_layout = QVBoxLayout(self.seek_holder)
        seek_holder_layout.setContentsMargins(0, 16, 0, 0)
        self.time_bubble = QLabel("0:00", self.seek_holder)
        self.time_bubble.setObjectName("musicTimeBubble")
        self.time_bubble.setAlignment(Qt.AlignCenter)
        self.time_bubble.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.time_bubble.hide()
        self.seek_slider = ClickSlider(Qt.Horizontal)
        self.seek_slider.setObjectName("musicSeekSlider")
        self.seek_slider.setRange(0, 0)
        self.seek_slider.sliderPressed.connect(self._begin_seek_drag)
        self.seek_slider.sliderMoved.connect(self._preview_seek)
        self.seek_slider.sliderReleased.connect(self._finish_seek_drag)
        seek_holder_layout.addWidget(self.seek_slider)
        seek_row.addWidget(self.seek_holder, 1)
        self.total_label = QLabel("0:00")
        self.total_label.setObjectName("musicTimeLabel")
        seek_row.addWidget(self.total_label)
        center.addLayout(seek_row)
        dock.addLayout(center, 3)

        volume = QHBoxLayout()
        volume.setSpacing(8)
        self.volume_button = IconButton("volume", role="toolbar", button_size=34)
        self.volume_button.clicked.connect(self.controller.toggle_mute)
        volume.addWidget(self.volume_button)
        self.volume_slider = ClickSlider(Qt.Horizontal)
        self.volume_slider.setObjectName("musicVolumeSlider")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setFixedWidth(110)
        self.volume_slider.valueChanged.connect(self._handle_volume_changed)
        volume.addWidget(self.volume_slider)
        dock.addLayout(volume, 1)
        root.addWidget(self.playback_dock)

    def _connect_controller(self) -> None:
        self.controller.playlists_changed.connect(self._sync_playlists)
        self.controller.current_playlist_changed.connect(self._sync_playlist)
        self.controller.tracks_changed.connect(self._sync_tracks)
        self.controller.current_track_changed.connect(self._sync_current_track)
        self.controller.playback_changed.connect(self._sync_playback)
        self.controller.position_changed.connect(self._sync_position)
        self.controller.duration_changed.connect(self._sync_duration)
        self.controller.loop_changed.connect(self._sync_loop)
        self.controller.shuffle_changed.connect(self._sync_shuffle)
        self.controller.background_play_changed.connect(self._sync_background_play)
        self.controller.volume_changed.connect(self._sync_volume)
        self.controller.resolve_failed.connect(lambda message: QMessageBox.warning(self, "Music", message))

    def _sync_all(self) -> None:
        self._sync_playlists()
        self._sync_playlist(self.controller.current_playlist())
        self._sync_tracks()
        self._sync_current_track(self.controller.current_track())
        self._sync_player_timeline()
        self._sync_playback(self.controller.is_playing)
        self._sync_loop(self.controller.loop_enabled)
        self._sync_shuffle(self.controller.shuffle_enabled)
        self._sync_background_play(self.controller.run_while_closed)
        self._sync_volume(self.controller.volume, self.controller.muted)
        if not self.controller.available:
            self.play_button.setEnabled(False)
            self.previous_button.setEnabled(False)
            self.next_button.setEnabled(False)
            self.seek_slider.setEnabled(False)

    def _sync_playlists(self) -> None:
        current_id = self.controller.current_playlist().playlist_id
        self.playlist_list.clear()
        for playlist in self.controller.playlists():
            item = QListWidgetItem()
            item.setData(Qt.UserRole, playlist.playlist_id)
            item.setSizeHint(QSize(52 if self._sidebar_collapsed else 100, 48))
            self.playlist_list.addItem(item)
            row = PlaylistRowWidget(playlist, self.controller.service)
            row.setProperty("accentColor", self._accent)
            row.set_compact(self._sidebar_collapsed)
            row.set_selected(playlist.playlist_id == current_id)
            self.playlist_list.setItemWidget(item, row)
            if playlist.playlist_id == current_id:
                self.playlist_list.setCurrentItem(item)

    def _sync_playlist(self, playlist: MusicPlaylistRecord | None) -> None:
        playlist = playlist or self.controller.current_playlist()
        self.title_label.setText(playlist.name)
        pixmap = _playlist_pixmap(playlist, self.controller.service, 132)
        self.playlist_art.set_artwork(pixmap)
        self._apply_accent(_dominant_color(_track_pixmap(self.controller.current_track(), self.controller.service, 96) if self.controller.current_track() else pixmap))
        self._sync_playlists()

    def _sync_tracks(self) -> None:
        current = self.controller.current_track()
        self.track_list.set_tracks(self.controller.tracks(), current.music_id if current is not None else None)

    def _sync_current_track(self, track: MusicRecord | None) -> None:
        name = track.name if track is not None else "No track"
        self.now_title.setText(name)
        self.now_title.setToolTip(name)
        self.now_art.set_artwork(_track_pixmap(track, self.controller.service, 48))
        self.track_list.set_current_track_id(track.music_id if track is not None else None)
        source_pixmap = _track_pixmap(track, self.controller.service, 96) if track is not None else _playlist_pixmap(self.controller.current_playlist(), self.controller.service, 96)
        self._apply_accent(_dominant_color(source_pixmap))
        QTimer.singleShot(0, self._sync_player_timeline)

    def _sync_player_timeline(self) -> None:
        self._sync_duration(self.controller.duration)
        self._sync_position(self.controller.position)

    def _sync_playback(self, playing: bool) -> None:
        self.play_button.set_icon_kind("pause" if playing else "play")

    def _sync_position(self, position: int) -> None:
        if not self._seek_dragging:
            self.seek_slider.setValue(max(0, int(position)))
        self.elapsed_label.setText(_format_time(position))

    def _sync_duration(self, duration: int) -> None:
        self.seek_slider.setRange(0, max(0, int(duration)))
        self.total_label.setText(_format_time(duration))
        if self._seek_dragging:
            self._preview_seek(self.seek_slider.value())

    def _sync_loop(self, enabled: bool) -> None:
        self.loop_button.set_active(enabled)
        self.loop_button.setToolTip("Loop on" if enabled else "Loop off")

    def _sync_shuffle(self, enabled: bool) -> None:
        self.shuffle_button.set_active(enabled)
        self.shuffle_button.setToolTip("Shuffle on" if enabled else "Shuffle off")

    def _sync_background_play(self, enabled: bool) -> None:
        self.background_play_button.set_active(enabled)
        self.background_play_button.setToolTip("Keep music playing when launcher closes" if enabled else "Stop music when launcher closes")

    def _sync_volume(self, volume: int, muted: bool) -> None:
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(volume)
        self.volume_slider.blockSignals(False)
        self.volume_button.set_volume_state(volume, muted)

    def _handle_volume_changed(self, value: int) -> None:
        self.controller.set_volume(value)

    def _handle_playlist_clicked(self, item: QListWidgetItem) -> None:
        playlist_id = str(item.data(Qt.UserRole))
        self.controller.select_playlist(playlist_id)

    def _toggle_sidebar(self) -> None:
        self._sidebar_collapsed = not self._sidebar_collapsed
        start = self.sidebar.maximumWidth()
        end = 66 if self._sidebar_collapsed else 224
        self.sidebar.setMinimumWidth(66 if self._sidebar_collapsed else 160)
        animation = QPropertyAnimation(self.sidebar, b"maximumWidth", self)
        animation.setDuration(220)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.start()
        self._sidebar_animation = animation
        side_layout = self.sidebar.layout()
        if isinstance(side_layout, QVBoxLayout):
            side_layout.setContentsMargins(7 if self._sidebar_collapsed else 10, 10, 7 if self._sidebar_collapsed else 10, 10)
            side_layout.setAlignment(self.burger_button, Qt.AlignHCenter if self._sidebar_collapsed else Qt.AlignLeft)
        self.side_header.setAlignment(Qt.AlignHCenter if self._sidebar_collapsed else Qt.AlignLeft)
        self.playlist_list.setFixedWidth(52 if self._sidebar_collapsed else 204)
        if not self._sidebar_collapsed:
            self.playlist_list.setMaximumWidth(16777215)
        self.add_playlist_button.setVisible(not self._sidebar_collapsed)
        self.background_play_button.setVisible(not self._sidebar_collapsed)
        for index in range(self.playlist_list.count()):
            row = self.playlist_list.itemWidget(self.playlist_list.item(index))
            if isinstance(row, PlaylistRowWidget):
                row.set_compact(self._sidebar_collapsed)

    def _open_add_playlist(self) -> None:
        self._open_editor(None)

    def _open_edit_playlist(self) -> None:
        self._open_editor(self.controller.current_playlist().playlist_id)

    def _open_editor(self, playlist_id: str | None) -> None:
        self._editor_dialog = MusicPlaylistEditorDialog(self.controller, playlist_id, self)
        self._editor_dialog.destroyed.connect(lambda *_: setattr(self, "_editor_dialog", None))
        self._editor_dialog.show()
        self._editor_dialog.raise_()
        self._editor_dialog.activateWindow()

    def _handle_records_reordered(self, ordered_ids: list[str], dropped_music_id: str) -> None:
        self.controller.reorder_tracks(ordered_ids, dropped_music_id=dropped_music_id)

    def _begin_seek_drag(self) -> None:
        self._seek_dragging = True
        self._preview_seek(self.seek_slider.value())

    def _preview_seek(self, value: int) -> None:
        self.time_bubble.setText(_format_time(value))
        self.time_bubble.adjustSize()
        self._position_time_bubble(value)
        self.time_bubble.show()
        self._bubble_hide_timer.stop()
        self.elapsed_label.setText(_format_time(value))

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
        self.time_bubble.raise_()

    def _hide_time_bubble(self) -> None:
        if not self._seek_dragging:
            self.time_bubble.hide()

    def _apply_accent(self, accent: QColor) -> None:
        if self._accent.name() == QColor(accent).name() and self.styleSheet():
            return
        self._accent = QColor(accent)
        accent_hex = self._accent.name()
        self.setStyleSheet(_manager_stylesheet(accent_hex))
        self.track_list.set_accent(self._accent)
        for button in (self.shuffle_button, self.loop_button, self.play_button, self.previous_button, self.next_button):
            button.setProperty("accentColor", self._accent)
            button.update()
        for index in range(self.playlist_list.count()):
            row = self.playlist_list.itemWidget(self.playlist_list.item(index))
            if isinstance(row, PlaylistRowWidget):
                row.setProperty("accentColor", self._accent)
                row.update()
        self.update()


def _manager_stylesheet(accent: str) -> str:
    return f"""
QDialog#musicManagerDialog {{
    background: transparent;
}}
QDialog#musicPlaylistEditorDialog {{
    background-color: #050a12;
}}
QFrame#musicSidebar, QFrame#musicMain, QFrame#musicPlaybackDock {{
    background-color: rgba(8, 13, 22, 166);
    border: 1px solid rgba(180, 210, 255, 38);
    border-radius: 8px;
}}
QListWidget#musicPlaylistList, QListWidget#musicTrackList {{
    background: transparent;
    border: none;
    outline: 0;
}}
QListWidget#musicPlaylistList::item, QListWidget#musicTrackList::item {{
    background: transparent;
    border: none;
    margin: 0;
    padding: 0;
}}
QListWidget#musicPlaylistList::item:selected, QListWidget#musicTrackList::item:selected {{
    background: transparent;
}}
QLabel#musicCategoryLabel, QLabel#musicTableHeader, QLabel#musicTrackMeta, QLabel#musicTimeLabel {{
    color: rgba(220, 232, 250, 170);
    background: transparent;
    font-size: 12px;
    font-weight: 700;
}}
QLabel#musicPlaylistTitle {{
    color: #f7fbff;
    background: transparent;
    font-size: 34px;
    font-weight: 800;
}}
QLabel#musicPlaylistName, QLabel#musicTrackName, QLabel#musicNowTitle {{
    color: #f7fbff;
    background: transparent;
    font-size: 13px;
    font-weight: 700;
}}
QLabel#musicTrackNumber {{
    color: rgba(218, 234, 255, 190);
    background: transparent;
    font-size: 13px;
    font-weight: 800;
}}
QPushButton#musicAddPlaylistButton {{
    background-color: rgba(255, 255, 255, 24);
    border: 1px solid rgba(255, 255, 255, 48);
    border-radius: 8px;
    color: #f7fbff;
    font-size: 13px;
    font-weight: 800;
    padding: 10px 12px;
    text-align: left;
}}
QPushButton#musicAddPlaylistButton:hover {{
    background-color: rgba(255, 255, 255, 36);
    border-color: {accent};
}}
QPushButton#musicIconPicker {{
    background-color: rgba(255, 255, 255, 20);
    border: 1px solid rgba(255, 255, 255, 56);
    border-radius: 8px;
}}
QPushButton#musicIconPicker:checked {{
    background-color: rgba(93, 168, 255, 46);
    border: 2px solid {accent};
}}
QLineEdit#musicUrlInput, QLineEdit#musicEditorNameInput {{
    background-color: rgba(0, 0, 0, 92);
    border: 1px solid rgba(255, 255, 255, 48);
    border-radius: 8px;
    color: #f7fbff;
    padding: 9px 11px;
    font-size: 13px;
    font-weight: 600;
}}
QLineEdit#musicEditorNameInput {{
    font-size: 24px;
    font-weight: 800;
    padding: 12px 14px;
}}
QLineEdit#musicUrlInput:focus, QLineEdit#musicEditorNameInput:focus {{
    border-color: {accent};
}}
QSlider#musicVolumeSlider::groove:horizontal, QSlider#musicSeekSlider::groove:horizontal {{
    height: 6px;
    border-radius: 3px;
    background-color: rgba(255, 255, 255, 34);
}}
QSlider#musicVolumeSlider::sub-page:horizontal, QSlider#musicSeekSlider::sub-page:horizontal {{
    border-radius: 3px;
    background-color: {accent};
}}
QSlider#musicVolumeSlider::handle:horizontal, QSlider#musicSeekSlider::handle:horizontal {{
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
    background-color: #f7fbff;
    border: 1px solid {accent};
}}
QLabel#musicTimeBubble {{
    color: #f7fbff;
    background-color: rgba(0, 0, 0, 210);
    border: 1px solid {accent};
    border-radius: 8px;
    padding: 3px 8px;
    font-size: 12px;
    font-weight: 700;
}}
"""


def _playlist_pixmap(playlist: MusicPlaylistRecord, service: LauncherService, size: int) -> QPixmap:
    if playlist.icon_path:
        pixmap = _load_image_pixmap(playlist.icon_path, service, size, fallback_music=False)
        if not pixmap.isNull():
            return pixmap
    if playlist.tracks:
        pixmap = _track_pixmap(playlist.tracks[0], service, size)
        if not pixmap.isNull():
            return pixmap
    return _fallback_playlist_pixmap(service, size)


def _track_pixmap(record: MusicRecord | None, service: LauncherService, size: int) -> QPixmap:
    if record is not None:
        for path_text in (record.artwork_path,):
            if path_text:
                pixmap = _load_image_pixmap(path_text, service, size, fallback_music=False)
                if not pixmap.isNull():
                    return pixmap
        if record is not None:
            return _fallback_music_pixmap(service, size, seed=record.music_id)
    return _fallback_music_pixmap(service, size, seed="empty")


def _load_image_pixmap(path_text: str, service: LauncherService, size: int, *, fallback_music: bool) -> QPixmap:
    path = _resolve_image_path(path_text, service)
    cache_key = (str(path), size)
    cached = _PIXMAP_CACHE.get(cache_key)
    if cached is not None and not cached.isNull():
        return cached
    pixmap = QPixmap(str(path)) if path is not None else QPixmap()
    if pixmap.isNull() and fallback_music:
        pixmap = _fallback_music_pixmap(service, size, seed=path_text)
    elif not pixmap.isNull():
        pixmap = pixmap.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    if not pixmap.isNull():
        _PIXMAP_CACHE[cache_key] = pixmap
    return pixmap


def _resolve_image_path(path_text: str | None, service: LauncherService) -> Path | None:
    text = _optional_text(path_text)
    if not text:
        return None
    path = Path(text)
    if path.is_absolute():
        return path
    return (service.project_root / text).resolve()


def _fallback_playlist_pixmap(service: LauncherService, size: int) -> QPixmap:
    folder = service.project_root / PLAYLIST_ICON_PREFIX
    return _fallback_from_folder(folder, service, size, seed="playlist", fallback_color="#1d2f42")


def _fallback_music_pixmap(service: LauncherService, size: int, *, seed: str) -> QPixmap:
    folder = service.project_root / MUSIC_ICON_PREFIX
    return _fallback_from_folder(folder, service, size, seed=seed, fallback_color="#1d2f42")


def _fallback_from_folder(folder: Path, service: LauncherService, size: int, *, seed: str, fallback_color: str) -> QPixmap:
    if folder.is_dir():
        icons = [
            path
            for path in sorted(folder.iterdir(), key=lambda item: item.name.lower())
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        ]
        if icons:
            index = int(hashlib.sha1(seed.encode("utf-8")).hexdigest(), 16) % len(icons)
            return _load_image_pixmap(str(icons[index]), service, size, fallback_music=False)
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(fallback_color))
    if pixmap.isNull():
        pixmap = QPixmap(size, size)
        pixmap.fill(QColor(fallback_color))
    return pixmap


def _settings_icon_path(service: LauncherService) -> str | None:
    path = service.project_root / "assets" / "Settings.png"
    return str(path) if path.is_file() else None


def _dominant_color(pixmap: QPixmap) -> QColor:
    if pixmap.isNull():
        return DEFAULT_ACCENT
    image = pixmap.toImage().scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    red = green = blue = count = 0
    for x in range(image.width()):
        for y in range(image.height()):
            color = QColor(image.pixel(x, y))
            if color.alpha() < 32:
                continue
            if color.lightness() < 28:
                continue
            red += color.red()
            green += color.green()
            blue += color.blue()
            count += 1
    if count <= 0:
        return DEFAULT_ACCENT
    color = QColor(int(red / count), int(green / count), int(blue / count))
    if color.lightness() < 95:
        color = color.lighter(150)
    if color.saturation() < 70:
        color.setHsv(color.hue() if color.hue() >= 0 else 208, 120, max(color.value(), 180))
    return color


def _format_time(position_ms: int) -> str:
    total_seconds = max(0, int(position_ms / 1000))
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}"


def _format_date_label(value: str | None) -> str:
    if not value:
        return "Unknown"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value[:16]
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = now - parsed.astimezone(timezone.utc)
    if delta.days <= 0:
        return "Today"
    if delta.days == 1:
        return "1 day ago"
    if delta.days < 7:
        return f"{delta.days} days ago"
    return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}"


def _best_stream_url(info: dict[str, object]) -> str | None:
    direct = _optional_text(info.get("url"))
    if direct and str(info.get("acodec") or "") != "none":
        return direct
    formats = info.get("formats")
    if not isinstance(formats, list):
        return direct
    audio_formats = [
        item
        for item in formats
        if isinstance(item, dict)
        and item.get("url")
        and item.get("acodec") != "none"
        and item.get("vcodec") in {None, "none"}
    ]
    if not audio_formats:
        audio_formats = [item for item in formats if isinstance(item, dict) and item.get("url") and item.get("acodec") != "none"]
    if not audio_formats:
        return direct
    audio_formats.sort(key=lambda item: float(item.get("abr") or item.get("tbr") or 0), reverse=True)
    return _optional_text(audio_formats[0].get("url"))


def _is_spotify_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "spotify" or "spotify.com" in parsed.netloc.lower()


def _is_youtube_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return "youtube.com" in host or "youtu.be" in host


def _is_youtube_playlist_url(url: str) -> bool:
    parsed = urlparse(url)
    if not _is_youtube_url(url):
        return False
    return "list=" in parsed.query or "/playlist" in parsed.path


def _looks_like_playlist_url(url: str) -> bool:
    parsed = urlparse(url)
    lowered = f"{parsed.path}?{parsed.query}".lower()
    return "playlist" in lowered or "list=" in lowered or "/sets/" in lowered


def _spotify_entity(url: str) -> tuple[str | None, str | None]:
    if url.startswith("spotify:"):
        parts = url.split(":")
        if len(parts) >= 3:
            return parts[1], parts[2]
        return None, None
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2:
        return parts[0], re.sub(r"[^A-Za-z0-9]", "", parts[1])
    return None, None


def _platform_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    if not host:
        return "stream"
    if "youtube" in host or "youtu.be" in host:
        return "youtube"
    if "soundcloud" in host:
        return "soundcloud"
    return host.split(".")[0]


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _unique_icon_name(folder: Path, name: str) -> str:
    suffix = Path(name).suffix.lower()
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "-", Path(name).stem).strip(" .-_") or "playlist-icon"
    candidate = f"{stem}{suffix}"
    index = 2
    while (folder / candidate).exists():
        candidate = f"{stem}-{index}{suffix}"
        index += 1
    return candidate
