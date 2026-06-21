from __future__ import annotations

import sys
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1] / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from ui.music import _best_stream_url, _thumbnail_url_from_info  # noqa: E402


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
