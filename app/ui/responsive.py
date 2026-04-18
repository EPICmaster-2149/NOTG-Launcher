from __future__ import annotations

from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget


_BASE_SCREEN_WIDTH = 1440
_BASE_SCREEN_HEIGHT = 900


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def available_geometry(widget: QWidget | None = None) -> QRect:
    screen = None
    if widget is not None:
        handle = widget.windowHandle()
        if handle is not None:
            screen = handle.screen()
        if screen is None and widget.window() is not None and widget.window().windowHandle() is not None:
            screen = widget.window().windowHandle().screen()

    if screen is None:
        screen = QGuiApplication.primaryScreen()

    return screen.availableGeometry() if screen is not None else QRect(0, 0, _BASE_SCREEN_WIDTH, _BASE_SCREEN_HEIGHT)


def screen_scale(widget: QWidget | None = None, minimum: float = 0.78, maximum: float = 1.18) -> float:
    geometry = available_geometry(widget)
    width_scale = geometry.width() / _BASE_SCREEN_WIDTH
    height_scale = geometry.height() / _BASE_SCREEN_HEIGHT
    return clamp(min(width_scale, height_scale), minimum, maximum)


def scaled_px(
    widget: QWidget | None,
    value: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
    scale_min: float = 0.78,
    scale_max: float = 1.18,
) -> int:
    scaled = int(round(value * screen_scale(widget, minimum=scale_min, maximum=scale_max)))
    if minimum is not None:
        scaled = max(minimum, scaled)
    if maximum is not None:
        scaled = min(maximum, scaled)
    return scaled


def fitted_window_size(
    widget: QWidget | None,
    base_width: int,
    base_height: int,
    *,
    width_ratio: float = 0.9,
    height_ratio: float = 0.9,
    minimum_width: int = 960,
    minimum_height: int = 640,
) -> QSize:
    geometry = available_geometry(widget)
    target_width = min(scaled_px(widget, base_width, minimum=minimum_width), int(geometry.width() * width_ratio))
    target_height = min(scaled_px(widget, base_height, minimum=minimum_height), int(geometry.height() * height_ratio))
    return QSize(max(minimum_width, target_width), max(minimum_height, target_height))
