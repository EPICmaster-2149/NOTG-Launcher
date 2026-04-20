from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QWidget

THEME_PROPERTY = "notg_theme_mode"


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
            "shadow": QColor(3, 8, 18, 42),
            "shell_top": QColor("#0d1524"),
            "shell_top_hover": QColor("#13233b"),
            "shell_top_selected": QColor("#142337"),
            "shell_bottom": QColor("#09111d"),
            "shell_bottom_hover": QColor("#102036"),
            "shell_bottom_selected": QColor("#101e31"),
            "shell_border": QColor("#1b2a42"),
            "shell_border_hover": QColor("#40679f"),
            "shell_border_selected": QColor("#6e98d4"),
            "info_top": QColor("#16253a"),
            "info_top_hover": QColor("#1d3050"),
            "info_top_selected": QColor("#1a2e49"),
            "info_bottom": QColor("#0f1a2b"),
            "info_bottom_hover": QColor("#15253d"),
            "info_bottom_selected": QColor("#14253b"),
            "info_border": QColor("#2a3d5e"),
            "info_border_hover": QColor("#557eb7"),
            "info_border_selected": QColor("#749fd7"),
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
            "shadow": QColor(106, 128, 162, 26),
            "shell_top": QColor("#f8fbff"),
            "shell_top_hover": QColor("#f2f7ff"),
            "shell_top_selected": QColor("#e9f1ff"),
            "shell_bottom": QColor("#eef3fb"),
            "shell_bottom_hover": QColor("#e8eff9"),
            "shell_bottom_selected": QColor("#dde9fb"),
            "shell_border": QColor("#c8d6e8"),
            "shell_border_hover": QColor("#8bb0e2"),
            "shell_border_selected": QColor("#5f8fd8"),
            "info_top": QColor("#ffffff"),
            "info_top_hover": QColor("#f6f9ff"),
            "info_top_selected": QColor("#eef5ff"),
            "info_bottom": QColor("#f4f7fd"),
            "info_bottom_hover": QColor("#edf2fb"),
            "info_bottom_selected": QColor("#e5eefc"),
            "info_border": QColor("#d2deed"),
            "info_border_hover": QColor("#95b7e5"),
            "info_border_selected": QColor("#6b97d8"),
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


def theme_palette(widget: QWidget | None = None) -> dict[str, Any]:
    return THEME_PALETTES[current_theme_mode(widget)]


def apply_theme(app: QApplication, mode: str) -> str:
    normalized = normalize_theme_mode(mode)
    app.setProperty(THEME_PROPERTY, normalized)

    base_qss = (Path(__file__).with_name("styles.qss")).read_text(encoding="utf-8")
    if normalized == "light":
        light_qss = (Path(__file__).with_name("styles_light.qss")).read_text(encoding="utf-8")
        app.setStyleSheet(f"{base_qss}\n\n{light_qss}")
    else:
        app.setStyleSheet(base_qss)

    refresh_theme(app)
    return normalized


def refresh_theme(app: QApplication | None = None) -> None:
    current_app = app or QApplication.instance()
    if current_app is None:
        return
    for widget in current_app.allWidgets():
        refresh = getattr(widget, "refresh_theme", None)
        if callable(refresh):
            refresh()
        widget.updateGeometry()
        widget.update()
