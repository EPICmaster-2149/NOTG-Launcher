from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtGui import QIcon


ICON_SUFFIXES = (".ico", ".png", ".svg", ".jpg", ".jpeg", ".bmp", ".webp")


@lru_cache(maxsize=8)
def application_icon(project_root: str | Path) -> QIcon:
    root = Path(project_root)
    icon_dir = root / "assets" / "app icon"
    for candidate in sorted(icon_dir.iterdir(), key=lambda item: item.name.lower()) if icon_dir.is_dir() else []:
        if candidate.is_file() and candidate.suffix.lower() in ICON_SUFFIXES:
            return QIcon(str(candidate))
    fallback = root / "assets" / "default-instance-icons" / "Grass Block.png"
    return QIcon(str(fallback)) if fallback.is_file() else QIcon()
