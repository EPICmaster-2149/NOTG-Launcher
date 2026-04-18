from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImageReader, QPixmap, QPixmapCache


def load_scaled_icon(path: str | Path, width: int, height: int) -> QPixmap:
    resolved = str(Path(path).resolve())
    cache_key = f"icon::{resolved}::{width}x{height}"

    cached = QPixmap()
    if QPixmapCache.find(cache_key, cached):
        return cached

    reader = QImageReader(resolved)
    reader.setAutoTransform(True)
    if reader.canRead():
        source_size = reader.size()
        if source_size.isValid():
            reader.setScaledSize(source_size.scaled(QSize(width, height), Qt.KeepAspectRatio))
        image = reader.read()
        pixmap = QPixmap.fromImage(image) if not image.isNull() else QPixmap()
    else:
        pixmap = QPixmap(resolved)

    if pixmap.isNull():
        return pixmap

    scaled = pixmap.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    QPixmapCache.insert(cache_key, scaled)
    return scaled
