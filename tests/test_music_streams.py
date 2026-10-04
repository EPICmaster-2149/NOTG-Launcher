from __future__ import annotations

import sys
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1] / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from ui.music import _best_stream_url, _clean_media_error, _thumbnail_url_from_info, _yt_dlp_node_path  # noqa: E402
from ui.errors import GENERIC_ERROR_CODE, present_error  # noqa: E402


def test_best_stream_url_prefers_opus_audio_only() -> None:
    assert (
        _best_stream_url(
            {
                "formats": [
                    {"url": "https://example.test/video", "acodec": "opus", "vcodec": "vp9", "ext": "webm", "abr": 180},
                    {"url": "https://example.test/m4a", "acodec": "mp4a.40.2", "vcodec": "none", "ext": "m4a", "abr": 128},
                    {"url": "https://example.test/opus", "acodec": "opus", "vcodec": "none", "ext": "webm", "abr": 96},
                ]
            }
        )
        == "https://example.test/opus"
    )


def test_best_stream_url_rejects_mp3() -> None:
    assert (
        _best_stream_url(
            {
                "formats": [
                    {"url": "https://example.test/mp3", "acodec": "mp3", "vcodec": "none", "ext": "mp3", "abr": 320},
                ]
            }
        )
        is None
    )


def test_best_stream_url_prefers_qt_compatible_aac_when_requested() -> None:
    info = {
        "formats": [
            {"url": "https://example.test/opus", "acodec": "opus", "vcodec": "none", "ext": "webm", "abr": 160},
            {"url": "https://example.test/aac", "acodec": "mp4a.40.2", "vcodec": "none", "ext": "m4a", "abr": 128},
        ]
    }
    assert _best_stream_url(info, prefer_qt_compatible=True) == "https://example.test/aac"


def test_thumbnail_url_prefers_direct_thumbnail() -> None:
    assert (
        _thumbnail_url_from_info(
            {
                "thumbnail": "https://i.ytimg.com/vi/example/hqdefault.jpg",
                "thumbnails": [
                    {"url": "https://i.ytimg.com/vi/example/default.jpg", "width": 120, "height": 90},
                ],
            }
        )
        == "https://i.ytimg.com/vi/example/hqdefault.jpg"
    )


def test_thumbnail_url_uses_largest_thumbnail() -> None:
    assert (
        _thumbnail_url_from_info(
            {
                "thumbnails": [
                    {"url": "https://i.ytimg.com/vi/example/default.jpg", "width": 120, "height": 90},
                    {"url": "https://i.ytimg.com/vi/example/maxresdefault.jpg", "width": 1280, "height": 720},
                    {"url": "https://i.ytimg.com/vi/example/mqdefault.jpg", "width": 320, "height": 180},
                ],
            }
        )
        == "https://i.ytimg.com/vi/example/maxresdefault.jpg"
    )


def test_clean_media_error_removes_yt_dlp_terminal_colours() -> None:
    assert (
        _clean_media_error("\x1b[0;31mERROR:\x1b[0m unable to download video data: HTTP Error 403: Forbidden")
        == "unable to download video data: HTTP Error 403: Forbidden"
    )


def test_yt_dlp_node_path_accepts_worker_config_roots(monkeypatch, tmp_path: Path) -> None:
    bundled = tmp_path / "node.exe"
    bundled.touch()
    monkeypatch.setattr("ui.music.shutil.which", lambda _name: None)
    assert _yt_dlp_node_path([tmp_path]) == bundled


def test_music_cache_file_lock_has_actionable_code() -> None:
    error = present_error(
        "Music",
        "[WinError 32] The process cannot access the file because it is being used by another process: "
        "music-stream-cache/example.m4a.part",
    )
    assert error.code == "ERR-MUS-001"
    assert "Wait" in error.guidance


def test_unknown_error_uses_documented_fallback_code() -> None:
    assert present_error("Unexpected", "unclassified fault").code == GENERIC_ERROR_CODE
