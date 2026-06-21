from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QWidget

THEME_PROPERTY = "notg_theme_mode"
THEME_ACCENT_PROPERTY = "notg_theme_accent"
DEFAULT_THEME_ACCENT = "#2E45FF"
_PALETTE_CACHE: dict[tuple[str, str], dict[str, Any]] = {}
_BASE_QSS_CACHE: dict[str, str] = {}
_STYLESHEET_CACHE: dict[tuple[str, str], str] = {}
_STYLESHEET_KEY_PROPERTY = "notg_stylesheet_key"


def _mix_color(start: QColor, end: QColor, factor: float, *, alpha: int | None = None) -> QColor:
    factor = max(0.0, min(1.0, factor))
    color = QColor(
        int(start.red() + (end.red() - start.red()) * factor),
        int(start.green() + (end.green() - start.green()) * factor),
        int(start.blue() + (end.blue() - start.blue()) * factor),
        int(start.alpha() + (end.alpha() - start.alpha()) * factor),
    )
    if alpha is not None:
        color.setAlpha(max(0, min(255, int(alpha))))
    return color


def _with_alpha(color: QColor, alpha: int) -> QColor:
    result = QColor(color)
    result.setAlpha(max(0, min(255, int(alpha))))
    return result


def _copy_palette(value: Any) -> Any:
    if isinstance(value, QColor):
        return QColor(value)
    if isinstance(value, dict):
        return {key: _copy_palette(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_copy_palette(item) for item in value)
    if isinstance(value, list):
        return [_copy_palette(item) for item in value]
    return value


def _clamp_channel(value: int) -> int:
    return max(0, min(255, int(value)))


def _hsv_color(base: QColor, *, saturation: int | None = None, value: int | None = None, alpha: int | None = None) -> QColor:
    hue = base.hsvHue()
    if hue < 0:
        hue = QColor(DEFAULT_THEME_ACCENT).hsvHue()
    result = QColor.fromHsv(
        hue,
        _clamp_channel(saturation if saturation is not None else base.hsvSaturation()),
        _clamp_channel(value if value is not None else base.value()),
        _clamp_channel(alpha if alpha is not None else base.alpha()),
    )
    return result


def _readable_text_for(background: QColor, *, light_mode: bool) -> QColor:
    if light_mode:
        return QColor("#102033") if background.lightness() > 138 else QColor("#ffffff")
    return QColor("#f7fbff") if background.lightness() < 150 else QColor("#08111d")


def _qss_rgba(color: QColor, alpha: int | None = None) -> str:
    target = _with_alpha(color, alpha) if alpha is not None else QColor(color)
    return f"rgba({target.red()}, {target.green()}, {target.blue()}, {target.alpha()})"


def _qss_hex(color: QColor) -> str:
    return QColor(color).name()


def _qss_gradient(colors: tuple[QColor, QColor, QColor], *, radial: bool = False) -> str:
    first, middle, last = colors
    if radial:
        return (
            "qradialgradient(cx: 0.18, cy: 0.06, radius: 1.18, fx: 0.18, fy: 0.06, "
            f"stop: 0 {_qss_hex(first)}, stop: 0.38 {_qss_hex(middle)}, stop: 1 {_qss_hex(last)})"
        )
    return (
        "qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1, "
        f"stop: 0 {_qss_rgba(first)}, stop: 1 {_qss_rgba(last)})"
    )


def _tone_roles(accent: QColor, mode: str) -> dict[str, QColor | tuple[QColor, QColor, QColor]]:
    light_mode = mode == "light"
    hue = accent.hsvHue()
    if hue < 0:
        hue = QColor(DEFAULT_THEME_ACCENT).hsvHue()

    if light_mode:
        accent_core = _hsv_color(accent, saturation=max(88, min(168, accent.hsvSaturation())), value=max(142, min(224, accent.value())), alpha=255)
        accent_bright = _hsv_color(accent_core, saturation=min(176, accent_core.hsvSaturation() + 12), value=min(236, accent_core.value() + 16), alpha=255)
        neutral = QColor("#f4f1ea")
        background = _mix_color(neutral, accent_core, 0.045)
        background_mid = _mix_color(QColor("#ebe7df"), accent_core, 0.065)
        surface_1 = _mix_color(QColor("#fbfaf7"), accent_core, 0.05, alpha=230)
        surface_2 = _mix_color(QColor("#f3f0ea"), accent_core, 0.075, alpha=236)
        surface_3 = _mix_color(QColor("#e9e5dd"), accent_core, 0.105, alpha=242)
        card = _mix_color(QColor("#ffffff"), accent_core, 0.055, alpha=234)
        card_hover = _mix_color(QColor("#f6f3ec"), accent_core, 0.115, alpha=242)
        card_active = _mix_color(QColor("#ece7df"), accent_core, 0.17, alpha=246)
        outline = _mix_color(QColor("#b8b0a4"), accent_core, 0.22, alpha=128)
        outline_variant = _mix_color(QColor("#d3ccc1"), accent_core, 0.16, alpha=112)
        separator = _mix_color(QColor("#cfc8bd"), accent_core, 0.13, alpha=112)
        text = QColor("#18202a")
        text_muted = _mix_color(QColor("#5f6470"), accent_core, 0.11)
        text_subtle = _mix_color(QColor("#7d8088"), accent_core, 0.1)
        shadow = QColor(90, 77, 58, 28)
        shadow_strong = QColor(58, 48, 38, 46)
        glow = _with_alpha(accent_bright, 58)
        glow_soft = _with_alpha(accent_bright, 30)
        hover = _with_alpha(_mix_color(QColor("#f6f1e8"), accent_core, 0.22), 216)
        selected = _with_alpha(_mix_color(QColor("#ede6dc"), accent_core, 0.32), 230)
        gradient = (background, background_mid, _mix_color(QColor("#dfdbd3"), accent_core, 0.08))
    else:
        accent_core = _hsv_color(accent, saturation=max(96, min(186, accent.hsvSaturation())), value=max(150, min(218, accent.value())), alpha=255)
        accent_bright = _hsv_color(accent_core, saturation=min(202, accent_core.hsvSaturation() + 16), value=min(238, accent_core.value() + 24), alpha=255)
        background = _mix_color(QColor("#000000"), accent_core, 0.035)
        background_mid = _mix_color(QColor("#080a0e"), accent_core, 0.075)
        surface_1 = _mix_color(QColor("#0d1017"), accent_core, 0.085, alpha=206)
        surface_2 = _mix_color(QColor("#151922"), accent_core, 0.105, alpha=218)
        surface_3 = _mix_color(QColor("#202630"), accent_core, 0.135, alpha=226)
        card = _mix_color(QColor("#10141c"), accent_core, 0.105, alpha=212)
        card_hover = _mix_color(QColor("#171d27"), accent_core, 0.155, alpha=226)
        card_active = _mix_color(QColor("#1d2632"), accent_core, 0.23, alpha=236)
        outline = _mix_color(QColor("#343b49"), accent_core, 0.28, alpha=94)
        outline_variant = _mix_color(QColor("#444c5d"), accent_core, 0.22, alpha=62)
        separator = _mix_color(QColor("#3a4252"), accent_core, 0.22, alpha=66)
        text = QColor("#f3f6fb")
        text_muted = _mix_color(QColor("#9aa4b6"), accent_core, 0.12)
        text_subtle = _mix_color(QColor("#737d8e"), accent_core, 0.14)
        shadow = QColor(0, 0, 0, 74)
        shadow_strong = QColor(0, 0, 0, 118)
        glow = _with_alpha(accent_bright, 72)
        glow_soft = _with_alpha(accent_bright, 34)
        hover = _with_alpha(_mix_color(QColor("#1a202b"), accent_core, 0.24), 222)
        selected = _with_alpha(_mix_color(QColor("#1b2430"), accent_core, 0.36), 232)
        gradient = (background, background_mid, QColor("#000000"))

    accent_soft = _with_alpha(_mix_color(surface_2, accent_core, 0.34), 210 if light_mode else 174)
    accent_muted = _mix_color(surface_3, accent_core, 0.38, alpha=220)
    accent_hover = _mix_color(accent_core, QColor("#ffffff") if not light_mode else QColor("#000000"), 0.12 if not light_mode else 0.08)
    accent_press = _mix_color(accent_core, QColor("#000000"), 0.20)

    return {
        "background": background,
        "background_mid": background_mid,
        "surface_1": surface_1,
        "surface_2": surface_2,
        "surface_3": surface_3,
        "surface_glass": _with_alpha(surface_2, 178 if light_mode else 150),
        "card": card,
        "card_hover": card_hover,
        "card_active": card_active,
        "outline": outline,
        "outline_variant": outline_variant,
        "separator": separator,
        "text": text,
        "text_muted": text_muted,
        "text_subtle": text_subtle,
        "accent": accent_core,
        "accent_bright": accent_bright,
        "accent_hover": accent_hover,
        "accent_press": accent_press,
        "accent_soft": accent_soft,
        "accent_muted": accent_muted,
        "on_accent": _readable_text_for(accent_core, light_mode=light_mode),
        "glow": glow,
        "glow_soft": glow_soft,
        "shadow": shadow,
        "shadow_strong": shadow_strong,
        "hover": hover,
        "selected": selected,
        "gradient": gradient,
        "danger": QColor("#c95168") if light_mode else QColor("#e05c83"),
        "warning": QColor("#c0841f") if light_mode else QColor("#e1aa41"),
        "success": QColor("#2f9a58") if light_mode else QColor("#49d17c"),
    }


def normalize_theme_accent(value: Any) -> str:
    color = QColor(str(value or DEFAULT_THEME_ACCENT))
    return color.name() if color.isValid() else DEFAULT_THEME_ACCENT


def current_theme_accent(widget: QWidget | None = None) -> QColor:
    del widget
    app = QApplication.instance()
    if app is None:
        return QColor(DEFAULT_THEME_ACCENT)
    return QColor(normalize_theme_accent(app.property(THEME_ACCENT_PROPERTY)))


def set_theme_accent(app: QApplication, color: QColor | str) -> str:
    normalized = normalize_theme_accent(color.name() if isinstance(color, QColor) else color)
    if normalize_theme_accent(app.property(THEME_ACCENT_PROPERTY)) == normalized and app.styleSheet():
        return normalized
    app.setProperty(THEME_ACCENT_PROPERTY, normalized)
    _set_application_stylesheet(app)
    refresh_theme(app)
    return normalized


def _button_roles(*, light: bool) -> dict[str, dict[str, QColor]]:
    if not light:
        return {
            "toolbar": {
                "bg": QColor(22, 35, 56, 214),
                "hover": QColor(40, 62, 94, 230),
                "press": QColor(28, 46, 74, 238),
                "active": QColor(54, 84, 126, 232),
                "border": QColor("#39557e"),
                "border_hover": QColor("#7aa6e3"),
                "border_active": QColor("#aac9f4"),
                "text": QColor("#e6efff"),
                "shadow": QColor(8, 17, 31, 74),
            },
            "sidebar": {
                "bg": QColor(34, 50, 80, 208),
                "hover": QColor(44, 66, 103, 224),
                "press": QColor(28, 43, 70, 232),
                "active": QColor(54, 81, 126, 228),
                "border": QColor("#3d567f"),
                "border_hover": QColor("#6b8fc6"),
                "border_active": QColor("#93b7eb"),
                "text": QColor("#edf4ff"),
                "shadow": QColor(8, 16, 29, 76),
            },
            "accent": {
                "bg": QColor(42, 72, 98, 222),
                "hover": QColor(55, 89, 120, 230),
                "press": QColor(33, 61, 84, 236),
                "active": QColor(67, 104, 138, 232),
                "border": QColor("#567da4"),
                "border_hover": QColor("#7ea4cb"),
                "border_active": QColor("#a2c2e5"),
                "text": QColor("#f7fbff"),
                "shadow": QColor(18, 45, 72, 74),
            },
            "warning": {
                "bg": QColor("#5c4a1e"),
                "hover": QColor("#725c24"),
                "press": QColor("#493a18"),
                "active": QColor("#846b2b"),
                "border": QColor("#92733a"),
                "border_hover": QColor("#d3aa52"),
                "border_active": QColor("#f2cd70"),
                "text": QColor("#fff2c7"),
                "shadow": QColor(56, 40, 10, 72),
            },
            "danger": {
                "bg": QColor("#391926"),
                "hover": QColor("#482031"),
                "press": QColor("#331724"),
                "active": QColor("#5c2740"),
                "border": QColor("#75405a"),
                "border_hover": QColor("#b4688b"),
                "border_active": QColor("#d78aa7"),
                "text": QColor("#ffcedd"),
                "shadow": QColor(50, 12, 25, 72),
            },
        }

    return {
        "toolbar": {
            "bg": QColor(248, 251, 255, 232),
            "hover": QColor(241, 247, 255, 242),
            "press": QColor(233, 241, 252, 248),
            "active": QColor(224, 236, 252, 246),
            "border": QColor("#b9cae2"),
            "border_hover": QColor("#8fb0da"),
            "border_active": QColor("#6a97d6"),
            "text": QColor("#16324d"),
            "shadow": QColor(104, 129, 165, 34),
        },
        "sidebar": {
            "bg": QColor(245, 249, 255, 228),
            "hover": QColor(236, 244, 255, 240),
            "press": QColor(230, 239, 252, 248),
            "active": QColor(220, 234, 252, 246),
            "border": QColor("#bfd0e7"),
            "border_hover": QColor("#95b6df"),
            "border_active": QColor("#6f9dd6"),
            "text": QColor("#19324d"),
            "shadow": QColor(108, 132, 170, 34),
        },
        "accent": {
            "bg": QColor("#2f6feb"),
            "hover": QColor("#2563eb"),
            "press": QColor("#1d56d6"),
            "active": QColor("#174bb8"),
            "border": QColor("#245fcb"),
            "border_hover": QColor("#174bb8"),
            "border_active": QColor("#123c94"),
            "text": QColor("#ffffff"),
            "shadow": QColor(56, 102, 179, 44),
        },
        "warning": {
            "bg": QColor("#f0b429"),
            "hover": QColor("#d99a16"),
            "press": QColor("#b7791f"),
            "active": QColor("#a86a16"),
            "border": QColor("#c68512"),
            "border_hover": QColor("#a86a16"),
            "border_active": QColor("#8a5612"),
            "text": QColor("#241400"),
            "shadow": QColor(160, 105, 16, 38),
        },
        "danger": {
            "bg": QColor("#c95168"),
            "hover": QColor("#b4425b"),
            "press": QColor("#9f354f"),
            "active": QColor("#8b2c46"),
            "border": QColor("#ac3f57"),
            "border_hover": QColor("#8f2942"),
            "border_active": QColor("#742137"),
            "text": QColor("#ffffff"),
            "shadow": QColor(139, 48, 69, 38),
        },
    }


THEME_PALETTES: dict[str, dict[str, Any]] = {
    "dark": {
        "window": {
            "overlay": QColor(7, 11, 18, 52),
            "gradient": ("#122036", "#0d1728", "#09111d"),
        },
        "buttons": _button_roles(light=False),
        "line_edit": {
            "border": QColor("#2f496e"),
            "border_focus": QColor("#7bc4ff"),
            "background": QColor("#101a2d"),
            "background_focus": QColor("#12213a"),
            "text": QColor("#f1f6ff"),
            "placeholder": QColor(186, 205, 235, 140),
            "selection": QColor(124, 199, 255, 90),
            "shadow": QColor(123, 196, 255, 120),
        },
        "loader_placeholder": {
            "outer_border": QColor("#253756"),
            "outer_fill": QColor(11, 18, 30, 180),
            "inner_border": QColor("#d5ebff"),
            "inner_fill": QColor(235, 244, 255, 235),
            "text": QColor("#3f5778"),
        },
        "header_icon": {
            "outer_top": QColor("#17263d"),
            "outer_top_hover": QColor("#1d3354"),
            "outer_bottom": QColor("#112036"),
            "outer_bottom_hover": QColor("#182c47"),
            "border": QColor("#43618c"),
            "border_hover": QColor("#7bc4ff"),
            "border_press": QColor("#9bd4ff"),
            "inner_border": QColor("#2e4669"),
            "glow": QColor(126, 194, 255, 54),
        },
        "instance_card": {
            "shadow": QColor(3, 8, 18, 54),
            "shell_top": QColor(13, 21, 36, 188),
            "shell_top_hover": QColor(19, 35, 59, 210),
            "shell_top_selected": QColor(20, 35, 55, 222),
            "shell_bottom": QColor(9, 17, 29, 178),
            "shell_bottom_hover": QColor(16, 32, 54, 204),
            "shell_bottom_selected": QColor(16, 30, 49, 218),
            "shell_border": QColor(74, 111, 166, 118),
            "shell_border_hover": QColor(92, 142, 210, 176),
            "shell_border_selected": QColor(120, 170, 228, 218),
            "info_top": QColor(22, 37, 58, 176),
            "info_top_hover": QColor(29, 48, 80, 202),
            "info_top_selected": QColor(26, 46, 73, 212),
            "info_bottom": QColor(15, 26, 43, 168),
            "info_bottom_hover": QColor(21, 37, 61, 194),
            "info_bottom_selected": QColor(20, 37, 59, 206),
            "info_border": QColor(82, 124, 186, 142),
            "info_border_hover": QColor(102, 154, 220, 188),
            "info_border_selected": QColor(132, 184, 240, 220),
            "text": QColor("#eef5ff"),
            "subtext": QColor("#95abd1"),
            "glow_start": QColor(92, 148, 222, 0),
            "glow_end": QColor(132, 192, 255, 34),
        },
        "icon_tile": {
            "shadow": QColor(4, 8, 17, 44),
            "shadow_hover": QColor(4, 8, 17, 72),
            "outer_top": QColor("#101a2d"),
            "outer_top_hover": QColor("#162540"),
            "outer_top_selected": QColor("#1b345d"),
            "outer_bottom": QColor("#0b1423"),
            "outer_bottom_hover": QColor("#122037"),
            "outer_bottom_selected": QColor("#132a4b"),
            "border": QColor("#253a5d"),
            "border_selected": QColor("#4f7dd0"),
            "border_hover": QColor("#6a9cff"),
            "inner_fill": QColor("#15243a"),
            "inner_fill_hover": QColor("#1a2e4b"),
            "inner_fill_selected": QColor("#1d3760"),
            "inner_border": QColor("#2f486f"),
            "glow_start": QColor(92, 162, 255, 0),
            "glow_end": QColor(128, 201, 255, 72),
        },
        "background_preview": {
            "outer_border": QColor(84, 122, 177, 90),
            "outer_fill": QColor(8, 14, 25, 220),
            "inner_fill": QColor(16, 26, 43, 210),
            "text": QColor("#dce9ff"),
        },
        "status_badge": {
            "launched": {
                "bg": QColor(28, 64, 46, 210),
                "border": QColor("#3f8a62"),
                "text": QColor("#dfffe9"),
                "dot": QColor("#49d17c"),
            },
            "launching": {
                "bg": QColor(26, 50, 82, 214),
                "border": QColor("#4f86d8"),
                "text": QColor("#dcedff"),
                "dot": QColor("#6fb0ff"),
            },
            "quit": {
                "bg": QColor(44, 55, 74, 215),
                "border": QColor("#627897"),
                "text": QColor("#eef4ff"),
                "dot": QColor("#aab8cf"),
            },
            "crashed": {
                "bg": QColor(69, 30, 45, 214),
                "border": QColor("#af5f7d"),
                "text": QColor("#ffe3eb"),
                "dot": QColor("#ff7caa"),
            },
        },
    },
    "light": {
        "window": {
            "overlay": QColor(249, 251, 255, 0),
            "gradient": ("#f7f9fd", "#eef3f9", "#e6edf7"),
        },
        "buttons": _button_roles(light=True),
        "line_edit": {
            "border": QColor("#c9d8eb"),
            "border_focus": QColor("#5f8fd8"),
            "background": QColor("#ffffff"),
            "background_focus": QColor("#f8fbff"),
            "text": QColor("#17324d"),
            "placeholder": QColor(94, 115, 146, 150),
            "selection": QColor(96, 148, 222, 70),
            "shadow": QColor(103, 149, 219, 78),
        },
        "loader_placeholder": {
            "outer_border": QColor("#d3dfef"),
            "outer_fill": QColor(246, 249, 253, 236),
            "inner_border": QColor("#b6cae4"),
            "inner_fill": QColor(255, 255, 255, 245),
            "text": QColor("#506885"),
        },
        "header_icon": {
            "outer_top": QColor("#f7fbff"),
            "outer_top_hover": QColor("#eff5ff"),
            "outer_bottom": QColor("#edf3fb"),
            "outer_bottom_hover": QColor("#e7eef9"),
            "border": QColor("#bfd1e8"),
            "border_hover": QColor("#80a8dc"),
            "border_press": QColor("#5f8fd8"),
            "inner_border": QColor("#d1deed"),
            "glow": QColor(95, 143, 216, 44),
        },
        "instance_card": {
            "shadow": QColor(106, 128, 162, 34),
            "shell_top": QColor(248, 251, 255, 202),
            "shell_top_hover": QColor(242, 247, 255, 222),
            "shell_top_selected": QColor(233, 241, 255, 232),
            "shell_bottom": QColor(238, 243, 251, 190),
            "shell_bottom_hover": QColor(232, 239, 249, 214),
            "shell_bottom_selected": QColor(221, 233, 251, 228),
            "shell_border": QColor(160, 184, 218, 154),
            "shell_border_hover": QColor(117, 158, 218, 206),
            "shell_border_selected": QColor(95, 143, 216, 232),
            "info_top": QColor(255, 255, 255, 210),
            "info_top_hover": QColor(246, 249, 255, 226),
            "info_top_selected": QColor(238, 245, 255, 236),
            "info_bottom": QColor(244, 247, 253, 198),
            "info_bottom_hover": QColor(237, 242, 251, 218),
            "info_bottom_selected": QColor(229, 238, 252, 232),
            "info_border": QColor(166, 190, 222, 170),
            "info_border_hover": QColor(126, 168, 225, 214),
            "info_border_selected": QColor(107, 151, 216, 236),
            "text": QColor("#17324d"),
            "subtext": QColor("#607693"),
            "glow_start": QColor(95, 143, 216, 0),
            "glow_end": QColor(95, 143, 216, 42),
        },
        "icon_tile": {
            "shadow": QColor(112, 135, 169, 24),
            "shadow_hover": QColor(112, 135, 169, 42),
            "outer_top": QColor("#f8fbff"),
            "outer_top_hover": QColor("#f1f6ff"),
            "outer_top_selected": QColor("#e9f1ff"),
            "outer_bottom": QColor("#eef3fb"),
            "outer_bottom_hover": QColor("#e7eef9"),
            "outer_bottom_selected": QColor("#dde9fb"),
            "border": QColor("#c8d8ea"),
            "border_selected": QColor("#7fa5d9"),
            "border_hover": QColor("#5f8fd8"),
            "inner_fill": QColor("#ffffff"),
            "inner_fill_hover": QColor("#f5f9ff"),
            "inner_fill_selected": QColor("#ecf4ff"),
            "inner_border": QColor("#d3dfee"),
            "glow_start": QColor(95, 143, 216, 0),
            "glow_end": QColor(95, 143, 216, 56),
        },
        "background_preview": {
            "outer_border": QColor(176, 194, 221, 120),
            "outer_fill": QColor(243, 247, 252, 236),
            "inner_fill": QColor(255, 255, 255, 224),
            "text": QColor("#536b87"),
        },
        "status_badge": {
            "launched": {
                "bg": QColor(231, 247, 238, 235),
                "border": QColor("#7ab68f"),
                "text": QColor("#21583a"),
                "dot": QColor("#2f9a58"),
            },
            "launching": {
                "bg": QColor(232, 241, 255, 236),
                "border": QColor("#82a9df"),
                "text": QColor("#204978"),
                "dot": QColor("#3a78d1"),
            },
            "quit": {
                "bg": QColor(240, 244, 250, 236),
                "border": QColor("#aebdd2"),
                "text": QColor("#42566f"),
                "dot": QColor("#748aa3"),
            },
            "crashed": {
                "bg": QColor(252, 235, 239, 236),
                "border": QColor("#d392a2"),
                "text": QColor("#7d2f45"),
                "dot": QColor("#c84f70"),
            },
        },
    },
}


def normalize_theme_mode(mode: Any) -> str:
    return "light" if str(mode).strip().lower() == "light" else "dark"


def current_theme_mode(widget: QWidget | None = None) -> str:
    del widget
    app = QApplication.instance()
    if app is None:
        return "dark"
    return normalize_theme_mode(app.property(THEME_PROPERTY))


def _accented_palette(base: dict[str, Any], mode: str) -> dict[str, Any]:
    accent = current_theme_accent()
    cache_key = (mode, normalize_theme_accent(accent.name()))
    cached = _PALETTE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    roles = _tone_roles(accent, mode)
    light_mode = mode == "light"
    palette = _copy_palette(base)
    palette["roles"] = roles

    buttons = {role: dict(colors) for role, colors in palette["buttons"].items()}
    buttons["toolbar"] = {
        "bg": roles["surface_2"],
        "hover": roles["hover"],
        "press": roles["surface_1"],
        "active": roles["selected"],
        "border": roles["outline_variant"],
        "border_hover": _with_alpha(roles["accent"], 136 if light_mode else 118),
        "border_active": _with_alpha(roles["accent_bright"], 178 if light_mode else 160),
        "text": roles["text"],
        "shadow": roles["shadow"],
    }
    buttons["sidebar"] = {
        "bg": roles["card"],
        "hover": roles["card_hover"],
        "press": roles["surface_1"],
        "active": roles["card_active"],
        "border": roles["outline_variant"],
        "border_hover": _with_alpha(roles["accent"], 132 if light_mode else 108),
        "border_active": _with_alpha(roles["accent_bright"], 178 if light_mode else 154),
        "text": roles["text"],
        "shadow": roles["shadow"],
    }
    buttons["accent"] = {
        "bg": _with_alpha(roles["accent"], 244 if light_mode else 226),
        "hover": _with_alpha(roles["accent_hover"], 248 if light_mode else 236),
        "press": _with_alpha(roles["accent_press"], 252 if light_mode else 242),
        "active": _with_alpha(roles["accent_bright"], 246 if light_mode else 232),
        "border": _with_alpha(roles["accent_press"], 220 if light_mode else 168),
        "border_hover": _with_alpha(roles["accent_bright"], 240 if light_mode else 218),
        "border_active": _with_alpha(roles["accent_bright"], 255 if light_mode else 238),
        "text": roles["on_accent"],
        "shadow": _with_alpha(roles["accent_press"], 48 if light_mode else 80),
    }
    buttons["danger"]["bg"] = _with_alpha(roles["danger"], 222 if light_mode else 116)
    buttons["danger"]["hover"] = _with_alpha(roles["danger"], 238 if light_mode else 148)
    buttons["danger"]["active"] = _with_alpha(roles["danger"], 248 if light_mode else 176)
    buttons["warning"]["bg"] = _with_alpha(roles["warning"], 226 if light_mode else 128)
    buttons["warning"]["hover"] = _with_alpha(roles["warning"], 242 if light_mode else 158)
    palette["buttons"] = buttons

    palette["window"] = {
        "overlay": _with_alpha(roles["background"], 28 if light_mode else 64),
        "gradient": tuple(_qss_hex(color) for color in roles["gradient"]),
        "ambient": {
            # make primary ambient fully transparent to remove top-left tint
            "primary": _with_alpha(roles["glow"], 0),
            "secondary": _with_alpha(roles["accent_muted"], 42 if light_mode else 36),
            "tertiary": _with_alpha(roles["surface_3"], 76 if light_mode else 58),
            "vignette": QColor(255, 255, 255, 0) if light_mode else QColor(0, 0, 0, 96),
        },
    }

    palette["line_edit"] = {
        "border": roles["outline_variant"],
        "border_focus": _with_alpha(roles["accent_bright"], 224),
        "background": _with_alpha(roles["surface_1"], 242 if light_mode else 226),
        "background_focus": _with_alpha(roles["surface_2"], 248 if light_mode else 236),
        "text": roles["text"],
        "placeholder": _with_alpha(roles["text_muted"], 150),
        "selection": _with_alpha(roles["accent"], 62 if light_mode else 82),
        "shadow": _with_alpha(roles["accent"], 68 if light_mode else 92),
    }

    palette["loader_placeholder"] = {
        "outer_border": roles["outline_variant"],
        "outer_fill": _with_alpha(roles["surface_1"], 226),
        "inner_border": _with_alpha(roles["outline"], 158),
        "inner_fill": _with_alpha(roles["card"], 238),
        "text": roles["text_muted"],
    }

    palette["header_icon"] = {
        "outer_top": roles["surface_3"],
        "outer_top_hover": roles["card_hover"],
        "outer_bottom": roles["surface_2"],
        "outer_bottom_hover": roles["card_active"],
        "border": roles["outline"],
        "border_hover": _with_alpha(roles["accent_bright"], 196),
        "border_press": _with_alpha(roles["accent_bright"], 230),
        "inner_border": roles["outline_variant"],
        "glow": roles["glow"],
    }

    palette["instance_card"] = {
        "shadow": roles["shadow_strong"] if not light_mode else roles["shadow"],
        # make instance cards more transparent so background shows through
        "shell_top": _with_alpha(roles["card"], 196 if light_mode else 170),
        "shell_top_hover": roles["card_hover"],
        "shell_top_selected": roles["card_active"],
        "shell_bottom": _with_alpha(roles["surface_1"], 186 if light_mode else 160),
        "shell_bottom_hover": _with_alpha(roles["surface_2"], 190 if light_mode else 170),
        "shell_bottom_selected": _with_alpha(roles["selected"], 206 if light_mode else 186),
        "shell_border": roles["outline_variant"],
        "shell_border_hover": _with_alpha(roles["accent"], 120 if light_mode else 100),
        "shell_border_selected": _with_alpha(roles["accent_bright"], 170 if light_mode else 150),
        "info_top": _with_alpha(roles["surface_3"], 180 if light_mode else 150),
        "info_top_hover": _with_alpha(roles["card_hover"], 200 if light_mode else 176),
        "info_top_selected": _with_alpha(roles["accent_soft"], 200 if light_mode else 176),
        "info_bottom": _with_alpha(roles["surface_2"], 170 if light_mode else 140),
        "info_bottom_hover": _with_alpha(roles["surface_3"], 180 if light_mode else 150),
        "info_bottom_selected": _with_alpha(roles["accent_muted"], 190 if light_mode else 160),
        "info_border": roles["outline_variant"],
        "info_border_hover": _with_alpha(roles["accent"], 120 if light_mode else 100),
        "info_border_selected": _with_alpha(roles["accent_bright"], 170 if light_mode else 150),
        "text": roles["text"],
        "subtext": roles["text_muted"],
        "glow_start": _with_alpha(roles["accent_bright"], 0),
        "glow_end": roles["glow"],
    }

    palette["icon_tile"] = {
        "shadow": roles["shadow"],
        "shadow_hover": roles["shadow_strong"],
        "outer_top": roles["card"],
        "outer_top_hover": roles["card_hover"],
        "outer_top_selected": roles["card_active"],
        "outer_bottom": roles["surface_1"],
        "outer_bottom_hover": roles["surface_2"],
        "outer_bottom_selected": roles["accent_muted"],
        "border": roles["outline_variant"],
        "border_selected": _with_alpha(roles["accent_bright"], 210),
        "border_hover": _with_alpha(roles["accent"], 176),
        "inner_fill": roles["surface_2"],
        "inner_fill_hover": roles["surface_3"],
        "inner_fill_selected": roles["accent_soft"],
        "inner_border": roles["outline"],
        "glow_start": _with_alpha(roles["accent_bright"], 0),
        "glow_end": roles["glow"],
    }

    palette["background_preview"] = {
        "outer_border": roles["outline"],
        "outer_fill": _with_alpha(roles["surface_1"], 236),
        "inner_fill": _with_alpha(roles["card"], 224),
        "text": roles["text_muted"],
    }

    status = palette["status_badge"]
    status["launched"]["bg"] = _with_alpha(roles["success"], 42 if light_mode else 58)
    status["launched"]["border"] = _with_alpha(roles["success"], 170)
    status["launched"]["dot"] = roles["success"]
    status["launching"]["bg"] = _with_alpha(roles["accent"], 42 if light_mode else 58)
    status["launching"]["border"] = _with_alpha(roles["accent_bright"], 170)
    status["launching"]["dot"] = roles["accent_bright"]
    status["quit"]["bg"] = _with_alpha(roles["surface_3"], 220 if light_mode else 168)
    status["quit"]["border"] = roles["outline"]
    status["quit"]["text"] = roles["text"]
    status["quit"]["dot"] = roles["text_subtle"]
    status["crashed"]["bg"] = _with_alpha(roles["danger"], 42 if light_mode else 58)
    status["crashed"]["border"] = _with_alpha(roles["danger"], 170)
    status["crashed"]["dot"] = roles["danger"]

    _PALETTE_CACHE[cache_key] = palette
    return palette


def theme_palette(widget: QWidget | None = None) -> dict[str, Any]:
    mode = current_theme_mode(widget)
    return _accented_palette(THEME_PALETTES[mode], mode)


def apply_theme(app: QApplication, mode: str) -> str:
    normalized = normalize_theme_mode(mode)
    if current_theme_mode() == normalized and app.styleSheet():
        return normalized
    app.setProperty(THEME_PROPERTY, normalized)
    _set_application_stylesheet(app)
    refresh_theme(app)
    return normalized


def _stylesheet_base_path() -> Path:
    if hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / "ui"
    return Path(__file__).with_name("styles.qss").parent


def _read_qss(name: str) -> str:
    cached = _BASE_QSS_CACHE.get(name)
    if cached is not None:
        return cached
    text = (_stylesheet_base_path() / name).read_text(encoding="utf-8")
    _BASE_QSS_CACHE[name] = text
    return text


def _set_application_stylesheet(app: QApplication) -> None:
    mode = current_theme_mode()
    accent = normalize_theme_accent(current_theme_accent().name())
    cache_key = (mode, accent)
    if app.property(_STYLESHEET_KEY_PROPERTY) == cache_key and app.styleSheet():
        return
    cached = _STYLESHEET_CACHE.get(cache_key)
    if cached is not None:
        app.setStyleSheet(cached)
        app.setProperty(_STYLESHEET_KEY_PROPERTY, cache_key)
        return
    base_qss = _read_qss("styles.qss")
    parts = [base_qss]
    if mode == "light":
        parts.append(_read_qss("styles_light.qss"))
    parts.append(_dynamic_stylesheet(theme_palette()))
    stylesheet = "\n\n".join(parts)
    _STYLESHEET_CACHE[cache_key] = stylesheet
    app.setStyleSheet(stylesheet)
    app.setProperty(_STYLESHEET_KEY_PROPERTY, cache_key)


def _dynamic_stylesheet(palette: dict[str, Any]) -> str:
    roles = palette["roles"]
    buttons = palette["buttons"]
    line_edit = palette["line_edit"]
    gradient = roles["gradient"]

    bg = roles["background"]
    surface_1 = roles["surface_1"]
    surface_2 = roles["surface_2"]
    surface_3 = roles["surface_3"]
    glass = roles["surface_glass"]
    card = roles["card"]
    card_hover = roles["card_hover"]
    card_active = roles["card_active"]
    outline = roles["outline"]
    outline_variant = roles["outline_variant"]
    separator = roles["separator"]
    text = roles["text"]
    text_muted = roles["text_muted"]
    text_subtle = roles["text_subtle"]
    accent = roles["accent"]
    accent_bright = roles["accent_bright"]
    accent_soft = roles["accent_soft"]
    selected = roles["selected"]
    hover = roles["hover"]
    danger = roles["danger"]
    warning = roles["warning"]

    return f"""
/* Generated NOTG theme ecosystem. Keep after static QSS so palette roles win. */
QWidget {{
    color: {_qss_hex(text)};
    selection-background-color: {_qss_rgba(accent, 96)};
    selection-color: {_qss_hex(roles["on_accent"])};
}}

QWidget#topBar,
QFrame#brandPanel,
QFrame#accountChip,
QFrame#musicControl,
QFrame#playtimeBar {{
    background-color: {_qss_rgba(glass)};
    border: 1px solid {_qss_rgba(outline_variant)};
}}

QWidget#actionPopup,
QMessageBox {{
    background-color: {_qss_rgba(surface_1, 246)};
    border: 1px solid {_qss_rgba(outline)};
}}

QFrame#brandMark {{
    background-color: {_qss_gradient((accent_bright, accent, accent), radial=False)};
    border: 1px solid {_qss_rgba(accent_bright, 150)};
}}

QFrame#musicControlDivider,
QFrame#sideDivider,
QFrame#editorPrimaryDivider,
QFrame#editorSectionDivider {{
    background-color: {_qss_rgba(separator)};
    border: none;
}}

QLabel#accountAvatar {{
    background: transparent;
    border: none;
    color: {_qss_hex(text)};
}}

QLabel#accountName,
QLabel#brandWordmark,
QLabel#instanceInfoName,
QLabel#emptyStateTitle,
QLabel#editorPageTitle,
QLabel#editorCompactPageTitle,
QLabel#settingsPageTitle,
QLabel#settingsSidebarTitle,
QLabel#settingsFieldTitle,
QLabel#accountsTitle,
QLabel#installProgressTitle,
QLabel#installProgressSummary,
QLabel#settingsTitle,
QLabel#editorImportCaption,
QLabel#editorSectionTitle,
QLabel#editorFilterTitle,
QLabel#musicCurrentLabel,
QLabel#musicTrackName,
QLabel#playtimePrimary,
QLabel#playtimeTotal {{
    color: {_qss_hex(text)};
}}

QLabel#instanceInfoVersion,
QLabel#emptyStateText,
QLabel#editorSubtitle,
QLabel#accountsSubtitle,
QLabel#settingsSubtitle,
QLabel#settingsCaption,
QLabel#editorStatusText,
QLabel#installProgressStatus,
QLabel#playtimeSecondary,
QLabel#musicTrackSource,
QLabel#musicTrackMeta,
QLabel#musicTimeLabel {{
    color: {_qss_hex(text_muted)};
}}

QLabel#editorEyebrow,
QLabel#musicTrackNumber,
QLabel#musicLoopLabel,
QCheckBox#musicCompactCheck {{
    color: {_qss_hex(accent_bright)};
}}

QFrame#sidePanel {{
    /* Instance window: ~90% transparent (barely visible); keep border visible */
    background-color: {_qss_rgba(card, 16)};
    border: 1px solid {_qss_rgba(outline_variant, 220)};
}}

QFrame#sidePreview {{
    background-color: {_qss_rgba(card, 18)};
    border: 1px solid {_qss_rgba(outline_variant, 210)};
}}

QFrame#contentSurface {{
    /* Content surface inside instance window: ~90% transparent (barely visible) */
    background-color: {_qss_rgba(card, 14)};
    border: 1px solid {_qss_rgba(outline_variant, 220)};
}}

QFrame#emptyStateCard {{
    background-color: {_qss_rgba(card, 18)};
    border: 1px solid {_qss_rgba(outline_variant, 210)};
}}

QFrame#sidePreview,
QFrame#instanceEditorHeader,
QFrame#installProgressHeader,
QFrame#accountsHeader,
QFrame#settingsHeader,
QFrame#settingsPreviewCard,
QFrame#settingsSidebar,
QFrame#settingsContent,
QFrame#settingsSectionCard,
QFrame#iconPresentationSurface,
QFrame#releaseNotesPreview,
QFrame#editorSelectionSurface,
QFrame#editorSidePanel {{
    background-color: {_qss_rgba(card)};
    border: 1px solid {_qss_rgba(outline_variant)};
}}

QFrame#settingsContent,
QFrame#instanceEditorContent {{
    background-color: {_qss_rgba(surface_1, 220)};
    border: 1px solid {_qss_rgba(outline_variant)};
}}

QFrame#settingsSectionCard,
QFrame#editorSelectionSurface {{
    background-color: {_qss_rgba(surface_2, 208)};
}}

QDialog#instanceEditor,
QDialog#editInstanceDialog,
QDialog#installProgressDialog,
QDialog#iconSelectorDialog,
QDialog#backgroundSelectorDialog,
QDialog#accountsDialog,
QDialog#musicManagerDialog,
QDialog#settingsDialog {{
    background-color: {_qss_gradient(gradient, radial=True)};
}}

QFrame#instanceEditorNav {{
    background-color: {_qss_rgba(surface_1, 226)};
    border: 1px solid {_qss_rgba(outline_variant)};
}}

QListWidget#instanceEditorNavList::item,
QTabWidget#editorCreateTabs QTabBar::tab {{
    background-color: {_qss_rgba(surface_2)};
    border: 1px solid {_qss_rgba(outline_variant)};
    color: {_qss_hex(text)};
}}

QListWidget#instanceEditorNavList::item:hover,
QTabWidget#editorCreateTabs QTabBar::tab:hover:!selected {{
    background-color: {_qss_rgba(card_hover)};
}}

QListWidget#instanceEditorNavList::item:selected,
QTabWidget#editorCreateTabs QTabBar::tab:selected {{
    background: {_qss_gradient((selected, accent_soft, selected), radial=False)};
    border: 1px solid {_qss_rgba(accent_bright, 178)};
    color: {_qss_hex(text)};
}}

QLineEdit#accountsInput,
QComboBox#editorComboBox,
QComboBox#editorComboBox QAbstractItemView,
QComboBox#editorComboBox QLineEdit,
QListWidget#editorTransferList,
QLineEdit#musicUrlInput,
QLineEdit#musicEditorNameInput {{
    background-color: {_qss_rgba(line_edit["background"])};
    border: 1px solid {_qss_rgba(line_edit["border"])};
    color: {_qss_hex(line_edit["text"])};
    selection-background-color: {_qss_rgba(line_edit["selection"])};
}}

QLineEdit#accountsInput:focus,
QComboBox#editorComboBox:hover,
QComboBox#editorComboBox:focus,
QLineEdit#musicUrlInput:focus,
QLineEdit#musicEditorNameInput:focus {{
    background-color: {_qss_rgba(line_edit["background_focus"])};
    border: 1px solid {_qss_rgba(line_edit["border_focus"])};
}}

QTableView#catalogTable,
QTableView#versionCatalogTable,
QTableView#loaderCatalogTable,
QTableWidget#modsTable,
QPlainTextEdit#installLogOutput,
QPlainTextEdit#instanceLogOutput,
QListWidget#screenshotsGrid,
QListWidget#musicTrackList,
QListView#musicTrackList,
QListWidget#musicPlaylistList {{
    background-color: {_qss_rgba(surface_1, 218)};
    alternate-background-color: {_qss_rgba(surface_2, 206)};
    border: 1px solid {_qss_rgba(outline_variant)};
    color: {_qss_hex(text)};
    gridline-color: {_qss_rgba(separator)};
}}

QListWidget#screenshotsGrid::item {{
    background-color: {_qss_rgba(card)};
    border: 1px solid {_qss_rgba(outline_variant)};
}}

QTableView#catalogTable::item:selected,
QTableView#versionCatalogTable::item:selected,
QTableView#loaderCatalogTable::item:selected,
QTableWidget#modsTable::item:selected,
QListWidget#screenshotsGrid::item:selected,
QComboBox#editorComboBox QAbstractItemView::item:selected,
QListWidget#editorTransferList::item:selected {{
    background-color: {_qss_rgba(selected)};
    color: {_qss_hex(text)};
}}

QTableView#catalogTable::item:hover,
QTableView#versionCatalogTable::item:hover,
QTableView#loaderCatalogTable::item:hover,
QTableWidget#modsTable::item:hover,
QListWidget#screenshotsGrid::item:hover {{
    background-color: {_qss_rgba(hover)};
}}

QHeaderView::section {{
    background-color: {_qss_rgba(surface_2, 238)};
    color: {_qss_hex(text_muted)};
    border-right: 1px solid {_qss_rgba(separator)};
    border-bottom: 1px solid {_qss_rgba(separator)};
}}

QScrollBar:vertical {{
    background: transparent;
    width: 9px;
    margin: 7px 0 7px 0;
}}

QScrollBar::handle:vertical {{
    background: {_qss_rgba(_mix_color(surface_3, accent, 0.22), 132)};
    border-radius: 4px;
    min-height: 36px;
}}

QScrollBar::handle:vertical:hover {{
    background: {_qss_rgba(accent_bright, 176)};
}}

QSlider#editorRamSlider::groove:horizontal,
QSlider#musicVolumeSlider::groove:horizontal,
QSlider#musicSeekSlider::groove:horizontal {{
    background-color: {_qss_rgba(surface_2, 226)};
    border: 1px solid {_qss_rgba(outline_variant)};
}}

QSlider#editorRamSlider::sub-page:horizontal,
QSlider#musicVolumeSlider::sub-page:horizontal,
QSlider#musicSeekSlider::sub-page:horizontal,
QProgressBar#installProgressBar::chunk {{
    background: {_qss_gradient((accent, accent_bright, accent), radial=False)};
}}

QSlider#editorRamSlider::handle:horizontal,
QSlider#musicVolumeSlider::handle:horizontal,
QSlider#musicSeekSlider::handle:horizontal {{
    background-color: {_qss_hex(roles["on_accent"])};
    border: 1px solid {_qss_rgba(accent_bright, 220)};
}}

QProgressBar#installProgressBar {{
    background-color: {_qss_rgba(surface_1, 238)};
    border: 1px solid {_qss_rgba(outline_variant)};
    color: {_qss_hex(text)};
}}

QCheckBox#editorFilterCheck,
QRadioButton#editorFilterRadio,
QCheckBox#musicTrackCheck,
QCheckBox#musicCompactCheck {{
    color: {_qss_hex(text)};
}}

QCheckBox#editorFilterCheck::indicator:unchecked,
QRadioButton#editorFilterRadio::indicator:unchecked,
QCheckBox#musicTrackCheck::indicator:unchecked,
QCheckBox#musicCompactCheck::indicator:unchecked {{
    border: 1px solid {_qss_rgba(outline)};
    background-color: {_qss_rgba(surface_1, 232)};
}}

QCheckBox#editorFilterCheck::indicator:checked,
QRadioButton#editorFilterRadio::indicator:checked,
QCheckBox#musicTrackCheck::indicator:checked,
QCheckBox#musicCompactCheck::indicator:checked {{
    border: 1px solid {_qss_rgba(accent_bright, 232)};
    background-color: {_qss_rgba(accent, 220)};
}}

QLabel#musicTimeBubble {{
    color: {_qss_hex(text)};
    background-color: {_qss_rgba(surface_3, 244)};
    border: 1px solid {_qss_rgba(accent_bright, 166)};
}}

QTextBrowser#releaseNotesText {{
    color: {_qss_hex(text)};
    selection-background-color: {_qss_rgba(accent, 76)};
}}

QTextBrowser#releaseNotesText a {{
    color: {_qss_hex(accent_bright)};
}}

QMessageBox QPushButton {{
    background-color: {_qss_rgba(buttons["toolbar"]["bg"])};
    border: 1px solid {_qss_rgba(buttons["toolbar"]["border"])};
    color: {_qss_hex(buttons["toolbar"]["text"])};
}}

QMessageBox QPushButton:hover {{
    background-color: {_qss_rgba(buttons["toolbar"]["hover"])};
    border: 1px solid {_qss_rgba(buttons["toolbar"]["border_hover"])};
}}

QPlainTextEdit#installLogOutput,
QPlainTextEdit#instanceLogOutput {{
    color: {_qss_hex(QColor("#2ed36f") if current_theme_mode() == "light" else QColor("#74ff86"))};
}}

QPushButton#musicAddPlaylistButton,
QPushButton#musicIconPicker {{
    background-color: {_qss_rgba(surface_2, 212)};
    border: 1px solid {_qss_rgba(outline_variant)};
    color: {_qss_hex(text)};
}}

QPushButton#musicAddPlaylistButton:hover,
QPushButton#musicIconPicker:hover {{
    background-color: {_qss_rgba(card_hover)};
    border: 1px solid {_qss_rgba(accent_bright, 170)};
}}

QPushButton#musicIconPicker:checked {{
    background-color: {_qss_rgba(accent_soft)};
    border: 2px solid {_qss_rgba(accent_bright, 230)};
}}
"""


def refresh_theme(app: QApplication | None = None) -> None:
    current_app = app or QApplication.instance()
    if current_app is None:
        return
    for widget in current_app.allWidgets():
        refresh = getattr(widget, "refresh_theme", None)
        if callable(refresh):
            refresh()
        widget.update()
