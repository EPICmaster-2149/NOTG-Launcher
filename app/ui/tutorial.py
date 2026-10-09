from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory
import zipfile

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QRect,
    QRectF,
    QSettings,
    QSize,
    Qt,
    QTimer,
    QUrl,
    QVariantAnimation,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.launcher import InstanceRecord
from ui.theme import set_theme_accent, theme_palette

VIDEO_TUTORIAL_URL = "https://youtu.be/HhCi_hFdEiI?si=3JCAB4PegzcwAyXz"
GITHUB_URL = "https://github.com/EPICmaster-2149/NOTG-Launcher"
LAUNCHER_WEBSITE_URL = "https://notg-launcher.netlify.app"


@dataclass(frozen=True)
class TourStep:
    section: str
    title: str
    body: str
    surface: str = "home"
    target: str = ""
    page: str = ""
    action: str = ""


STEPS = [
    TourStep(
        "Welcome",
        "Welcome to NOTG Launcher",
        "This is a guide of how to use this launcher, you can skip this by holding the Space for 3 seconds",
    ),
    TourStep(
        "Home",
        "Your instances",
        "The Home screen keeps each Minecraft profile in its own instance. You can manage each one separately.",
        target="instance_list",
    ),
    TourStep(
        "Home",
        "Instance actions",
        "Select an instance to use the sidebar. Launch starts it, Edit opens its settings, and Folder, Copy, and Delete manage its files.",
        target="sidebar",
    ),
    TourStep(
        "Home",
        "Check playtime",
        "This bar shows the current session, the selected instance total, and your total playtime.",
        target="playtime_bar",
    ),
    TourStep(
        "Create",
        "Create a new instance",
        "Select Add Instance, enter a name if wanted, you can also change the icon",
        "add",
        "instanceEditorHeader",
        "Create",
        "seed_add_catalog",
    ),
    TourStep(
        "Create",
        "Choose the game version",
        "Use the version list and filters to find Minecraft releases, snapshots, betas, alphas, and experiments.",
        "add",
        "versionStack",
        "Create",
    ), 
    TourStep(
        "Create",
        "Choose a mod loader",
        "Scroll down to Mod Loader. Select None for vanilla, or NeoForge, Forge, Fabric, or Quilt. The launcher automatically configures compatible loader versions too.",
        "add",
        "loader_side_panel",
        "Create",
        "scroll_add_loader",
    ),
    TourStep(
        "Create",
        "Copy selected files",
        "Here you can copy other instance files, its like synching files between isntances",
        "add",
        "copy_selected_list",
        "Create",
        "select_add_advanced",
    ),
    TourStep(
        "Create",
        "Change RAM",
        "Scroll down to Memory. You can use chang the RAM allocation for the instance.",
        "add",
        "ram_slider",
        "Create",
    ),
    TourStep(
        "Import",
        "Bring in an existing setup",
        "Select Import for a modpack or any minecraft folder of other launcher. Review the files and select a version if NOTG cannot identify one.",
        "add",
        "instanceEditorScroll",
        "Import",
    ),
    TourStep(
        "Modpacks",
        "Install a Modrinth modpack",
        "You can directly browse thruogh the modpacks on Modrinth and install them directly from the launcher.",
        "add",
        "modrinthSelectionSurface",
        "Modpacks",
    ),
    TourStep(
        "Edit",
        "Edit the sample instance",
        "This is edit menu of the instance and you can manage everything here",
        "edit",
        "wholewindow",
        "Minecraft Log",
    ),
    TourStep(
        "Edit",
        "Rename an instance",
        "Change the name here.",
        "edit",
        "name_edit",
        "Minecraft Log",
    ),
    TourStep(
        "Edit",
        "Change the icon",
        "Change the icon here.",
        "edit",
        "icon_edit",
        "Minecraft Log",
    ),
    TourStep(
        "Edit",
        "Pick an icon",
        "Select the icon button to open Pick Icon. Choose from built-in icons or add a custom PNG.",
        "icon",
        "grid_holder",
        action="select_icon",
    ),
    TourStep(
        "Edit",
        "Minecraft Log",
        "Minecraft Log displays the latest output. After a crash, use Search, Copy, Clear, or Bottom to inspect the log without deleting its file.",
        "edit",
        "instanceLogOutput",
        "Minecraft Log",
    ),
    TourStep(
        "Edit",
        "Change or update the version",
        "You can update or change the version and modloader here. BUT THE MODS VERSION WONT CHANGE SO CHECK FOR THAT.",
        "edit",
        "versionStack",
        "Versions",
        "seed_edit_catalog",
    ),
    TourStep(
        "Edit",
        "Manage installed mods",
        "This menu allows you to enable, disable, remove, search, or open folders for installed mods.",
        "edit",
        "modsTable",
        "Mods",
    ),
    TourStep(
        "Edit",
        "Install Mods",
        "You can install mods from Modrinth directly from the launcher.",
        "edit",
        "open_install_mods_button",
        "Install Mods",
    ),
    TourStep(
        "Edit",
        "Manage screenshots",
        "Access in-game screenshots here. Select captures to copy, rename, delete, or open their folder.",
        "edit",
        "screenshotsGrid",
        "Screenshots",
    ),
    TourStep(
        "Edit",
        "Enable Rich Presence",
        "Enable Rich Presence for this instance to show it on Discord while Minecraft is running.",
        "edit",
        "rich_presence_enabled_checkbox",
        "Rich Presence",
    ),
    TourStep(
        "Edit",
        "Rich Presence state",
        "You can change the status lines here",
        "edit",
        "rich_presence_state_input",
        "Rich Presence",
    ),
    TourStep(
        "Edit",
        "Rich Presence details",
        "Details is optional. Leave it empty to let current game activity provide the detail.",
        "edit",
        "rich_presence_details_input",
        "Rich Presence",
    ),
    TourStep(
        "Edit",
        "Adaptive Details",
        "Adaptive Details controls whether the details follow the current game activity.",
        "edit",
        "rich_presence_adaptive_details_checkbox",
        "Rich Presence",
    ),
    TourStep(
        "Edit",
        "Copy selected instance data",
        "Its the same as beofre, you can copy the selected instance data to another instance",
        "edit",
        "copy_selected_list",
        "Advanced",
    ),
    TourStep(
        "Edit",
        "Optimize Minecraft",
        "This will optimise minecraft about 5%, it uses custom launch commands",
        "edit",
        "optimize_minecraft_checkbox",
        "Advanced",
    ),
    TourStep(
        "Edit",
        "Change RAM",
        "Change the RAM for the isntance here, Go Beyond raises the limit, Revert returns to NOTG's recommendation, and Confirm saves the shown amount.",
        "edit",
        "editorRamSlider",
        "Advanced",
    ),
    TourStep(
        "Edit",
        "Custom JVM command",
        "Add JVM arguments only when you understand them, also disable the optimise minecraft feature to use eyou won JVM commands",
        "edit",
        "jvm_args_input",
        "Advanced",
    ),
    TourStep(
        "Edit",
        "Choose Java",
        "Chnsge the Java version if you want to",
        "edit",
        "java_runtime_combo",
        "Advanced",
    ),
    TourStep(
        "Settings",
        "Launcher settings",
        "Nothing much its your general settings",
        "settings",
        "settingsStack",
        "General",
    ),
    TourStep(
        "Settings",
        "Appearance",
        "Here you can customise your entire launcher look.",
        "settings",
        "settingsStack",
        "Appearance",
    ),
    TourStep(
        "Settings",
        "Change background",
        "Open Change Background to choose a built-in or custom wallpaper. NOTG supports photos and video backgrounds, and you can add your own files.",
        "settings",
        "change_background_button",
        "Appearance",
    ),
    TourStep(
        "Settings",
        "Pick a wallpaper",
        "You can add custom photos and videos BUT THE VIDEOS SHOULD NOT BE IN 4K OR YOU WILL SOFT LOCK YOURSELF.",
        "background",
        "grid_holder",
        action="select_background",
    ),
    TourStep(
        "Settings",
        "Set the theme colour",
        "Use the colour wheel to choose the launcher accent colour.",
        "settings",
        "theme_color_wheel",
        "Appearance",
        "change_theme",
    ),
    TourStep(
        "Settings",
        "Updates",
        "Use Updates to check for a newer launcher version, read patch notes, and install an available update.",
        "settings",
        "settingsStack",
        "Updates",
    ),
    TourStep(
        "Music",
        "Music manager",
        "Ya you have a cutom music palyer in this launcher",
        "music",
        "musicMain",
    ),
    TourStep(
        "Music",
        "Playlist controls",
        "You can also use the handles to change the order of the music tracks.",
        "music",
        "play_playlist_button",
    ),
    TourStep(
        "Music",
        "Playback controls",
        "Previous, Play/Pause, and Next control the current track.",
        "music",
        "play_button",
    ),
    TourStep(
        "Music",
        "Seek and volume",
        "Drag the seek bar to move through a track; use the speaker and slider to mute or change volume.",
        "music",
        "seek_slider",
    ),
    TourStep(
        "Music",
        "Playlist sidebar",
        "You can add your own playlist, also can bring musics form Youtube by just pasting the link",
        "music",
        "add_playlist_button",
    ),
    TourStep(
        "Music",
        "Keep music playing when the launcher closes",
        "This button enables you to hear music while palying a game",
        "music",
        "background_play_button",
    ),
    TourStep(
        "Accounts",
        "Choose the account to launch",
        "Select the account button in the top right, then choose an existing account or Manage Accounts.",
        "accounts",
        "accountSplitter",
    ),
    TourStep(
        "Accounts",
        "Add an account",
        "Select Add Account, then choose Offline Account for a local username or Ely.by Account to sign in.",
        "accounts",
        "accountSidebar",
    ),
    TourStep(
        "Accounts",
        "Set skins and capes",
        "Select an account and open Skin & Cape. Offline accounts use local PNG skin and cape files; For online skins you need to have Ely.by account",
        "accounts",
        "accountTabs",
        "Skin & Cape",
    ),
    TourStep(
        "Complete",
        "THAT'S IT, now enjoy playing Minecraft!",
        "",
        target="tutorial_final",
        action="restore_preview",
    ),
]


class TutorialOverlay(QWidget):
    """A lightweight instructional layer that follows the launcher's active theme."""

    def __init__(self, tour: "TutorialTour", screen_geometry: QRect):
        super().__init__(
            None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.tour = tour
        self._spotlight = QRectF()
        self._press_rect = QRectF()
        self._press_progress = 0.0
        self._hold_progress = 0.0
        self.setGeometry(screen_geometry)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # The instructional layer must not become the mouse target: eligible
        # launcher controls are filtered below, while other launcher input is blocked.
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setObjectName("tutorialOverlay")

        self.callout = QFrame(self)
        self.callout.setObjectName("tutorialCallout")
        layout = QVBoxLayout(self.callout)
        layout.setContentsMargins(15, 13, 15, 12)
        layout.setSpacing(7)
        hints = QHBoxLayout()
        hints.setContentsMargins(0, 0, 0, 2)
        hints.setSpacing(6)
        self.space_hint = self._make_key_hint("SPACE", "Pause")
        self.left_hint = self._make_key_hint("←", "Previous")
        self.right_hint = self._make_key_hint("→", "Next")
        for hint in (self.space_hint, self.left_hint, self.right_hint):
            hints.addWidget(hint)
        hints.addStretch(1)
        self.step_label = QLabel()
        self.step_label.setObjectName("tutorialStepNumber")
        hints.addWidget(self.step_label)
        self.pause_label = QLabel()
        self.pause_label.setObjectName("tutorialPauseIndicator")
        hints.addWidget(self.pause_label)
        layout.addLayout(hints)
        self.section_label = QLabel()
        self.section_label.setObjectName("tutorialSection")
        layout.addWidget(self.section_label)
        self.title_label = QLabel()
        self.title_label.setObjectName("tutorialTitle")
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        self.body_label = QLabel()
        self.body_label.setObjectName("tutorialBody")
        self.body_label.setWordWrap(True)
        layout.addWidget(self.body_label)
        self._body_opacity = QGraphicsOpacityEffect(self.body_label)
        self.body_label.setGraphicsEffect(self._body_opacity)
        self._body_fade = QVariantAnimation(
            self, duration=170, easingCurve=QEasingCurve.OutCubic
        )
        self._body_fade.valueChanged.connect(self._body_opacity.setOpacity)
        self._move_animation = QVariantAnimation(
            self, duration=300, easingCurve=QEasingCurve.OutCubic
        )
        self._move_animation.valueChanged.connect(self.callout.move)
        self._move_animation.finished.connect(self._refresh_callout_after_move)
        self._centered = False
        self._callout_min_width = min(520, max(320, self.width() - 36))
        self._callout_min_height = 170
        self._layout_revision = 0
        self.callout.setMinimumSize(self._callout_min_width, self._callout_min_height)
        self.callout.setMaximumWidth(max(self._callout_min_width, self.width() - 36))

        self._press_animation = QVariantAnimation(
            self, duration=850, easingCurve=QEasingCurve.OutCubic
        )
        self._press_animation.setStartValue(0.0)
        self._press_animation.setEndValue(1.0)
        self._press_animation.valueChanged.connect(self._set_press_progress)
        self.apply_theme()
        self.set_paused(False)

    def _make_key_hint(self, key: str, description: str) -> QFrame:
        hint = QFrame(self.callout)
        hint.setObjectName("tutorialKeyHint")
        row = QHBoxLayout(hint)
        row.setContentsMargins(5, 3, 6, 3)
        row.setSpacing(4)
        key_label = QLabel(key, hint)
        key_label.setObjectName("tutorialKeyLabel")
        row.addWidget(key_label)
        detail = QLabel(description, hint)
        detail.setObjectName("tutorialKeyDescription")
        row.addWidget(detail)
        opacity = QGraphicsOpacityEffect(hint)
        opacity.setOpacity(0.82)
        hint.setGraphicsEffect(opacity)
        animation = QVariantAnimation(
            hint, duration=260, easingCurve=QEasingCurve.OutCubic
        )
        animation.setKeyValueAt(0.0, 0.82)
        animation.setKeyValueAt(0.22, 1.0)
        animation.setKeyValueAt(0.55, 0.72)
        animation.setKeyValueAt(1.0, 0.9)
        animation.valueChanged.connect(opacity.setOpacity)
        hint._press_animation = animation
        return hint

    @staticmethod
    def animate_hint(hint: QFrame) -> None:
        hint._press_animation.stop()
        hint._press_animation.start()

    def apply_theme(self) -> None:
        roles = theme_palette(self.tour.window)["roles"]
        accent = QColor(roles["accent"])
        surface = QColor(roles["surface_2"])
        card = QColor(roles["card"])
        outline = QColor(roles["outline"])
        text = QColor(roles["text"])
        muted = QColor(roles["text_muted"])
        self.callout.setStyleSheet(
            "QFrame#tutorialCallout {"
            f"background:{card.name()}; border:1px solid {outline.name()}; border-radius:10px;"
            "} QLabel#tutorialSection {"
            f"color:{accent.name()}; font:600 8.5pt 'Segoe UI';"
            "} QLabel#tutorialTitle {"
            f"color:{text.name()}; font:700 14pt 'Segoe UI';"
            "} QLabel#tutorialBody {"
            f"color:{text.name()}; font:9.5pt 'Segoe UI';"
            "}"
        )
        self.setStyleSheet(
            "QFrame#tutorialKeyHint {"
            f"background:{surface.name()}; border:1px solid {outline.name()}; border-radius:5px;"
            "} QLabel#tutorialKeyLabel {"
            f"color:#ffffff; background:{accent.name()}; font:700 8pt 'Segoe UI'; padding:2px 4px; border-radius:3px;"
            "} QLabel#tutorialKeyDescription {"
            f"color:{muted.name()}; font:8pt 'Segoe UI';"
            "} QLabel#tutorialStepNumber {"
            f"color:{muted.name()}; font:600 8.5pt 'Segoe UI'; padding:0 4px;"
            "} QLabel#tutorialPauseIndicator {"
            "color:#ffffff; background:rgba(255,255,255,0.13); border-radius:5px; font:700 8pt 'Segoe UI'; padding:4px 4px;"
            "}"
        )

    def set_content(self, step: TourStep, index: int) -> None:
        self.apply_theme()
        self.section_label.setText(step.section)
        self.title_label.setText(step.title)
        self.body_label.setText(step.body)
        self.step_label.setText(f"{index + 1}/{len(STEPS)}")
        self.callout.layout().invalidate()
        self.callout.layout().activate()
        self._layout_callout(animate=True)
        self._body_opacity.setOpacity(0.0)
        self._body_fade.stop()
        self._body_fade.setStartValue(0.0)
        self._body_fade.setEndValue(1.0)
        self._body_fade.start()
        self._schedule_callout_relayout()

    def set_paused(self, paused: bool) -> None:
        self.pause_label.setText("Ⅱ  PAUSED" if paused else "▶  PLAYING")
        color = "#9c5b19" if paused else "rgba(255,255,255,0.13)"
        self.pause_label.setStyleSheet(
            f"color:#ffffff; background:{color}; border-radius:5px; font:700 8pt 'Segoe UI'; padding:4px 7px;"
        )
        # A stylesheet change invalidates Qt's size-hint cache. Do the same
        # explicitly when the step text changes so first display is identical.
        layout = self.callout.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()
        self._schedule_callout_relayout()

    def _schedule_callout_relayout(self) -> None:
        """Re-measure after Qt has applied new label text and style hints."""
        self._layout_revision += 1
        revision = self._layout_revision
        QTimer.singleShot(0, lambda: self._relayout_callout(revision))

    def _relayout_callout(self, revision: int) -> None:
        if revision != self._layout_revision or not self.isVisible():
            return
        self._measure_callout_contents()
        # Position once after measuring new text. Subsequent spotlight updates
        # during scrolling do not move the card.
        self._layout_callout(animate=False)

    def _refresh_callout_after_move(self) -> None:
        # Moving a child widget can leave its wrapped QLabel with stale paint
        # and height-for-width data until the next event. Refresh only after
        # the geometry animation has reached its final position.
        QTimer.singleShot(0, self._refresh_callout_contents)

    def _measure_callout_contents(self) -> None:
        for label in (self.section_label, self.title_label, self.body_label):
            label.updateGeometry()
        layout = self.callout.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()
            height_for_width = layout.totalHeightForWidth(self.callout.width())
            self.callout.resize(
                self.callout.width(), max(self._callout_min_height, height_for_width)
            )
        for label in (self.section_label, self.title_label, self.body_label):
            label.update()
        self.callout.updateGeometry()
        self.callout.update()

    def _refresh_callout_contents(self) -> None:
        if not self.isVisible() or not self.callout.isVisible():
            return
        self._measure_callout_contents()
        self.callout.repaint()
        self.body_label.repaint()

    def set_centered(self, centered: bool) -> None:
        if self._centered != centered:
            self._centered = centered
            self._layout_callout(animate=False)

    def reposition_for_spotlight(self) -> None:
        """Choose a clear spot beside the target after scrolling has settled."""
        self._layout_callout(animate=True)

    def set_spotlight(self, global_rect: QRect | None) -> None:
        rect = (
            QRectF(global_rect.translated(-self.geometry().topLeft()))
            if global_rect
            else QRectF()
        )
        if rect == self._spotlight:
            return
        self._spotlight = rect
        # Scrolling moves the highlighted control, but the instruction card
        # keeps its position and geometry for the whole step.
        self.update()

    def pulse(self, global_rect: QRect) -> None:
        self._press_rect = QRectF(global_rect.translated(-self.geometry().topLeft()))
        self._press_animation.stop()
        self._press_animation.start()

    def _set_press_progress(self, value: float) -> None:
        self._press_progress = float(value)
        self.update()

    def _layout_callout(self, *, animate: bool) -> None:
        self.callout.ensurePolished()
        max_width = max(280, self.width() - 36)
        min_width = min(520, max(320, max_width))
        self._callout_min_width = min_width
        self.callout.setMinimumSize(
            min_width, min(self._callout_min_height, max(120, self.height() - 36))
        )
        self.callout.setMaximumWidth(max_width)
        body_length = len(self.body_label.text()) if self.body_label.text() else 90
        title_width = (
            self.title_label.fontMetrics().horizontalAdvance(self.title_label.text())
            if self.title_label.text()
            else 0
        )
        desired_width = max(
            title_width + 42, min_width, 380 + min(200, body_length * 0.55)
        )
        self.callout.setFixedWidth(min(max_width, int(desired_width)))
        layout = self.callout.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()
            height_for_width = layout.totalHeightForWidth(self.callout.width())
        else:
            height_for_width = self._callout_min_height
        self.callout.resize(
            self.callout.width(),
            max(self._callout_min_height, height_for_width),
        )
        end_size = self.callout.size()
        margin = 18
        bounds = QRectF(
            margin,
            margin,
            max(0, self.width() - margin * 2),
            max(0, self.height() - margin * 2),
        )
        if self._centered:
            target = QPoint(
                self.width() // 2 - end_size.width() // 2,
                self.height() // 2 - end_size.height() // 2,
            )
            target.setX(
                max(margin, min(target.x(), self.width() - end_size.width() - margin))
            )
            target.setY(
                max(margin, min(target.y(), self.height() - end_size.height() - margin))
            )
        elif not self._spotlight.isNull():
            gap = 16
            focus = self._spotlight.adjusted(-8, -8, 8, 8)
            candidates = [
                QPoint(
                    int(focus.right() + gap),
                    int(focus.center().y() - end_size.height() / 2),
                ),
                QPoint(
                    int(focus.left() - end_size.width() - gap),
                    int(focus.center().y() - end_size.height() / 2),
                ),
                QPoint(
                    int(focus.center().x() - end_size.width() / 2),
                    int(focus.bottom() + gap),
                ),
                QPoint(
                    int(focus.center().x() - end_size.width() / 2),
                    int(focus.top() - end_size.height() - gap),
                ),
            ]
            choices = []
            for point in candidates:
                x = max(
                    int(bounds.left()),
                    min(point.x(), int(bounds.right() - end_size.width())),
                )
                y = max(
                    int(bounds.top()),
                    min(point.y(), int(bounds.bottom() - end_size.height())),
                )
                placed = QRectF(x, y, end_size.width(), end_size.height())
                intersection = placed.intersected(focus)
                overlap = (
                    intersection.width() * intersection.height()
                    if not intersection.isEmpty()
                    else 0
                )
                displacement = abs(x - point.x()) + abs(y - point.y())
                # Never prefer a nearby placement that covers the target when
                # any other side has clear space. If the target fills most of
                # the screen, choose the placement with the least overlap.
                choices.append((overlap * 1_000_000 + displacement, QPoint(x, y)))
            target = min(choices, key=lambda choice: choice[0])[1]
        else:
            topbar = getattr(self.tour.window, "topbar", None)
            if topbar is not None and topbar.isVisible():
                anchor = (
                    topbar.mapToGlobal(QPoint(topbar.width() // 2, topbar.height() + 9))
                    - self.geometry().topLeft()
                )
                target = QPoint(anchor.x() - end_size.width() // 2, anchor.y())
            else:
                target = QPoint(self.width() // 2 - end_size.width() // 2, margin)
            target.setX(
                max(margin, min(target.x(), self.width() - end_size.width() - margin))
            )
            target.setY(
                max(margin, min(target.y(), self.height() - end_size.height() - margin))
            )
        if animate and self.callout.isVisible() and self.callout.pos() != target:
            self._move_animation.stop()
            self._move_animation.setStartValue(self.callout.pos())
            self._move_animation.setEndValue(target)
            self._move_animation.start()
        else:
            self.callout.move(target)
        self.callout.raise_()

    def resizeEvent(self, event) -> None:
        self._callout_min_width = min(520, max(320, self.width() - 36))
        self._layout_callout(animate=False)
        super().resizeEvent(event)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if not self._spotlight.isNull():
            target = self._spotlight.adjusted(-16, -16, 16, 16)
            wash = QColor("#ffffff")
            wash.setAlpha(56)
            painter.setBrush(wash)
            border = QColor("#ffffff")
            border.setAlpha(168)
            painter.setPen(QPen(border, 1.2))
            painter.drawRoundedRect(target, 10, 10)
        if not self._press_rect.isNull() and self._press_progress < 0.98:
            amount = self._press_progress
            rect = self._press_rect.adjusted(
                -4 - 8 * amount, -4 - 8 * amount, 4 + 8 * amount, 4 + 8 * amount
            )
            pulse = QColor("#ffffff")
            pulse.setAlpha(max(0, int(110 * (1.0 - amount))))
            painter.setBrush(pulse)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 8, 8)
        if self._hold_progress > 0 and self.callout.isVisible():
            box = QRectF(self.callout.geometry())
            rail = QRectF(box.left() - 5, box.top(), 3, box.height())
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255, 48))
            painter.drawRoundedRect(rail, 1.5, 1.5)
            filled = QRectF(
                rail.left(),
                rail.top(),
                rail.width(),
                rail.height() * self._hold_progress,
            )
            painter.setBrush(QColor("#ffffff"))
            painter.drawRoundedRect(filled, 1.5, 1.5)

    def set_hold_progress(self, progress: float) -> None:
        self._hold_progress = max(0.0, min(1.0, float(progress)))
        self.update()


class VideoThumbnailButton(QPushButton):
    """Clickable YouTube thumbnail cropped to the standard 16:9 frame."""

    def __init__(self, pixmap: QPixmap, parent: QWidget | None = None):
        super().__init__(parent)
        self._thumbnail = pixmap
        self.setObjectName("tutorialVideoPreview")
        self.setToolTip("Open the video tutorial")
        self.setAccessibleName("Open the video tutorial")
        self.setMinimumSize(320, 180)
        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setCursor(Qt.PointingHandCursor)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return max(180, int(width * 9 / 16))

    def sizeHint(self) -> QSize:
        width = max(640, self.minimumWidth())
        return QSize(width, self.heightForWidth(width))

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(rect, 12, 12)
        painter.setClipPath(clip)
        if not self._thumbnail.isNull():
            scaled = self._thumbnail.scaled(
                self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            source = QRectF(
                (scaled.width() - self.width()) / 2,
                (scaled.height() - self.height()) / 2,
                self.width(),
                self.height(),
            )
            painter.drawPixmap(rect, scaled, source)
        else:
            painter.fillRect(rect, QColor("#252a34"))
        if self.underMouse():
            painter.fillRect(rect, QColor(0, 0, 0, 24))
        center = rect.center()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 152))
        painter.drawEllipse(center, 34, 34)
        triangle = QPainterPath()
        triangle.moveTo(center.x() - 8, center.y() - 14)
        triangle.lineTo(center.x() + 15, center.y())
        triangle.lineTo(center.x() - 8, center.y() + 14)
        triangle.closeSubpath()
        painter.setBrush(QColor("#ffffff"))
        painter.drawPath(triangle)
        painter.setClipping(False)
        painter.setPen(QPen(QColor(255, 255, 255, 170), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)


class TutorialTour(QObject):
    TRANSIENT_PARENTS = {"icon": "edit", "background": "settings"}

    def __init__(self, window: QWidget):
        super().__init__(window)
        self.window = window
        self.app = QApplication.instance()
        self.overlay: TutorialOverlay | None = None
        self.index = 0
        self.paused = False
        self._dialogs: dict[str, QDialog] = {}
        self._active_surface = ""
        self._active_page = ""
        self._allow_close = False
        self._previous_f3_state = None
        self._transition_id = 0
        self._scroll_animation: QVariantAnimation | None = None
        self._scroll_target: QWidget | None = None
        self._preview_workspace: TemporaryDirectory[str] | None = None
        self._preview_instance: InstanceRecord | None = None
        self._preview_card_item: QListWidgetItem | None = None
        self._performed_actions: set[int] = set()
        self._transition_in_progress = False
        self._original_background: str | None = None
        self._original_theme_accent: str | None = None
        self._advance_timer = QTimer(self)
        self._advance_timer.setSingleShot(True)
        self._advance_timer.timeout.connect(self.next)
        self._layout_timer = QTimer(self)
        self._layout_timer.setInterval(180)
        self._layout_timer.timeout.connect(self._sync_overlay)

    @staticmethod
    def was_completed() -> bool:
        return bool(
            QSettings("NOTG", "NOTG-Launcher").value(
                "tutorial/first_run_completed", False, type=bool
            )
        )

    def start(self, *, first_run: bool = False) -> None:
        if self.overlay is not None:
            self.overlay.raise_()
            return
        self._first_run = first_run
        self.index = 0
        self.paused = False
        self._performed_actions.clear()
        self._space_held = False
        self._space_hold_animation = None
        screen = self.window.screen() or self.app.primaryScreen()
        self.overlay = TutorialOverlay(self, screen.geometry())
        self._original_background = (
            self.window.service.get_active_background_reference()
        )
        self._original_theme_accent = self.window.service.get_theme_accent_color()
        self._previous_f3_state = self.window.service.get_f3_kill_enabled()
        try:
            self.window.service.set_f3_kill_enabled(False)
        except Exception:
            pass
        self.app.installEventFilter(self)
        self.overlay.show()
        self.overlay.raise_()
        self._layout_timer.start()
        self._show_step()

    def next(self, *, skip_transition: bool = False) -> None:
        if self.index >= len(STEPS) - 1:
            self.finish()
            return
        self.index += 1
        self._show_step(skip_transition=skip_transition or self._transition_in_progress)

    def previous(self, *, skip_transition: bool = False) -> None:
        if self.index:
            self.index -= 1
            self._show_step(
                skip_transition=skip_transition or self._transition_in_progress
            )

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        if self.overlay is not None:
            self.overlay.set_paused(self.paused)
        if self.paused:
            self._advance_timer.stop()
        else:
            self._schedule_advance()

    def finish(self) -> None:
        if self.overlay is None:
            return
        self._transition_id += 1
        self._advance_timer.stop()
        self._layout_timer.stop()
        if self._space_hold_animation is not None:
            self._space_hold_animation.stop()
        self.app.removeEventFilter(self)
        if self._previous_f3_state is not None:
            try:
                self.window.service.set_f3_kill_enabled(self._previous_f3_state)
            except Exception:
                pass
        self._close_tour_dialogs()
        self._restore_tutorial_appearance()
        self._remove_preview_instance()
        if self._first_run:
            QSettings("NOTG", "NOTG-Launcher").setValue(
                "tutorial/first_run_completed", True
            )
        overlay, self.overlay = self.overlay, None
        overlay.close()
        overlay.deleteLater()

    def eventFilter(self, watched, event) -> bool:
        if self.overlay is None:
            return False
        blocked = (
            QEvent.MouseButtonPress,
            QEvent.MouseButtonRelease,
            QEvent.MouseButtonDblClick,
            QEvent.MouseMove,
            QEvent.Wheel,
            QEvent.KeyPress,
            QEvent.KeyRelease,
            QEvent.Shortcut,
            QEvent.ShortcutOverride,
            QEvent.ContextMenu,
            QEvent.Close,
            QEvent.DragEnter,
            QEvent.DragMove,
            QEvent.Drop,
        )
        if event.type() not in blocked:
            return False
        if isinstance(watched, QWidget) and self._is_overlay_control(watched):
            return False
        if isinstance(watched, QWidget) and watched.window() is self.overlay:
            return False
        if self._is_music_playback_control(watched, event.type()):
            return False
        if isinstance(watched, QWidget):
            top = watched.window()
            if (
                top is not self.window
                and top not in self._dialogs.values()
                and top is not self.overlay
            ):
                return False
        if event.type() in (QEvent.KeyPress, QEvent.KeyRelease):
            return self._handle_tutorial_key(event)
        return not (event.type() == QEvent.Close and self._allow_close)

    def _handle_tutorial_key(self, event) -> bool:
        key = event.key()
        if key == Qt.Key_Space:
            if event.type() == QEvent.KeyPress:
                if event.isAutoRepeat() or self._space_held:
                    return True
                self._space_held = True
                self._space_was_paused = self.paused
                self._advance_timer.stop()
                if self.overlay is not None:
                    self.overlay.animate_hint(self.overlay.space_hint)
                    animation = QVariantAnimation(
                        self, duration=3000, easingCurve=QEasingCurve.Linear
                    )
                    animation.setStartValue(0.0)
                    animation.setEndValue(1.0)
                    animation.valueChanged.connect(self.overlay.set_hold_progress)
                    animation.finished.connect(self._complete_space_hold)
                    self._space_hold_animation = animation
                    animation.start()
                return True
            if event.isAutoRepeat() or not self._space_held:
                return True
            self._space_held = False
            if self._space_hold_animation is not None:
                self._space_hold_animation.stop()
            if self.overlay is not None:
                self.overlay.set_hold_progress(0.0)
            self.paused = not self._space_was_paused
            if self.overlay is not None:
                self.overlay.set_paused(self.paused)
            if self.paused:
                self._advance_timer.stop()
            else:
                self._schedule_advance()
            return True
        if event.type() == QEvent.KeyPress and not event.isAutoRepeat():
            if key == Qt.Key_Left:
                if self.overlay is not None:
                    self.overlay.animate_hint(self.overlay.left_hint)
                self.previous(skip_transition=True)
                return True
            if key == Qt.Key_Right:
                if self.overlay is not None:
                    self.overlay.animate_hint(self.overlay.right_hint)
                self.next(skip_transition=True)
                return True
        return True

    def _complete_space_hold(self) -> None:
        if not self._space_held or self.overlay is None:
            return
        self._space_held = False
        self.finish()

    def _is_music_playback_control(self, watched, event_type) -> bool:
        if event_type not in {
            QEvent.MouseButtonPress,
            QEvent.MouseButtonRelease,
            QEvent.MouseButtonDblClick,
        }:
            return False
        dialog = self._dialogs.get("music")
        if dialog is None or not isinstance(watched, QWidget):
            return False
        playback_buttons = {
            getattr(dialog, "previous_button", None),
            getattr(dialog, "play_button", None),
            getattr(dialog, "next_button", None),
        }
        current = watched
        while current is not None and current is not dialog:
            if current in playback_buttons:
                return True
            current = current.parentWidget()
        return False

    def _is_overlay_control(self, widget: QWidget) -> bool:
        if self.overlay is None:
            return False
        current = widget
        while current is not None:
            if current is self.overlay.callout:
                return True
            current = current.parentWidget()
        return False

    def _show_step(self, *, skip_transition: bool = False) -> None:
        if self.overlay is None:
            return
        if skip_transition:
            # Invalidate a queued button animation before presenting the
            # requested step immediately (arrow-key navigation).
            self._transition_id += 1
        self._advance_timer.stop()
        self.paused = False
        self.overlay.set_paused(False)
        step = STEPS[self.index]
        # Preserve the first-run home screen. A display-only card appears
        # only as the edit portion begins, when no saved instance exists.
        if (
            step.surface == "edit"
            and self._preview_instance is None
            and not self.window.service.load_instances()
        ):
            self._create_preview_instance()
        transient_parent = self.TRANSIENT_PARENTS.get(self._active_surface)
        if transient_parent == step.surface:
            self._close_tour_dialogs(keep={transient_parent})
            self._active_surface = transient_parent
        changing_view = step.surface != self._active_surface or (
            step.page and step.page != self._active_page
        )
        self._transition_in_progress = False
        if (
            changing_view
            and not skip_transition
            and self._transition_rect(step) is not None
        ):
            self._transition_id += 1
            transition_id = self._transition_id
            press_rect = self._transition_rect(step)
            self._set_pressed_state(step)
            # A new tutorial window always starts from a clean desktop: close
            # the old one, then animate the control that opens the next one.
            if (
                step.surface != self._active_surface
                and step.surface not in self.TRANSIENT_PARENTS
            ):
                self._close_tour_dialogs()
                self._active_surface, self._active_page = "", ""
            self.overlay.set_spotlight(None)
            self.overlay.callout.hide()
            self.overlay.pulse(press_rect)
            self._transition_in_progress = True
            QTimer.singleShot(
                850, lambda: self._complete_transition(transition_id, step)
            )
            return
        self._prepare_surface(step)
        self._present(step)

    def _complete_transition(self, transition_id: int, step: TourStep) -> None:
        if self.overlay is None or transition_id != self._transition_id:
            return
        self._transition_in_progress = False
        self._prepare_surface(step)
        self._present(step)

    def _present(self, step: TourStep) -> None:
        if self.overlay is None:
            return
        self._apply_demo_action(step)
        self._resolve_target(step)
        self.overlay.set_centered(step.target == "tutorial_final")
        self.overlay.callout.show()
        self.overlay.set_content(step, self.index)
        self._schedule_advance()

    def _schedule_advance(self) -> None:
        if not self.paused:
            # Dense Rich Presence and Advanced pages move a little faster,
            # while still leaving enough time to read the callout.
            step = STEPS[self.index]
            if step.section == "Edit":
                delay = max(3200, len(step.body) * 40)
            else:
                delay = max(4200, len(step.body) * 40)
            self._advance_timer.start(delay)

    def _transition_rect(self, step: TourStep) -> QRect | None:
        if step.surface != self._active_surface:
            opener = {
                "add": self.window.topbar.buttons.get("Add Instance"),
                "edit": self.window.sidebar.buttons.get("Edit"),
                "settings": self.window.topbar.buttons.get("Settings"),
                "music": self.window.music_widget,
                "accounts": self.window.topbar.account_chip,
                "icon": getattr(self._dialogs.get("edit"), "icon_button", None),
                "background": getattr(
                    self._dialogs.get("settings"), "change_background_button", None
                ),
            }.get(step.surface)
            return self._widget_global_rect(opener)
        dialog = self._dialogs.get(step.surface)
        if dialog is not None and hasattr(dialog, "nav_list"):
            pages = {"Create": 0, "Import": 1, "Modpacks": 2}
            if step.surface == "add" and step.page in pages:
                return self._list_row_global_rect(dialog.nav_list, pages[step.page])
            if step.surface == "edit" and step.page:
                names = getattr(dialog, "PAGE_NAMES", [])
                if step.page in names:
                    return self._list_row_global_rect(
                        dialog.nav_list, names.index(step.page)
                    )
        if step.surface == "settings":
            nav = {
                "General": dialog.general_nav,
                "Appearance": dialog.appearance_nav,
                "Updates": dialog.updates_nav,
            }.get(step.page)
            return self._widget_global_rect(nav)
        if step.surface == "accounts" and step.page:
            tabs = dialog.findChild(QWidget, "accountTabs") if dialog else None
            if tabs is not None and hasattr(tabs, "tabBar"):
                for index in range(tabs.count()):
                    if step.page.lower() in tabs.tabText(index).lower():
                        bar = tabs.tabBar()
                        rect = bar.tabRect(index)
                        return QRect(bar.mapToGlobal(rect.topLeft()), rect.size())
            return self._widget_global_rect(tabs)
        return None

    def _set_pressed_state(self, step: TourStep) -> None:
        if step.surface != self._active_surface:
            widget = {
                "add": self.window.topbar.buttons.get("Add Instance"),
                "edit": self.window.sidebar.buttons.get("Edit"),
                "settings": self.window.topbar.buttons.get("Settings"),
                "icon": getattr(self._dialogs.get("edit"), "icon_button", None),
                "background": getattr(
                    self._dialogs.get("settings"), "change_background_button", None
                ),
            }.get(step.surface)
            if widget is not None and hasattr(widget, "setDown"):
                widget.setDown(True)
                QTimer.singleShot(150, lambda button=widget: button.setDown(False))

    def _prepare_surface(self, step: TourStep) -> None:
        if step.surface == "home":
            self._close_tour_dialogs()
            self.window.show()
            self.window.raise_()
            self._active_surface, self._active_page = "home", ""
            return
        if step.surface != self._active_surface:
            if step.surface not in self.TRANSIENT_PARENTS:
                self._close_tour_dialogs()
            self._active_surface = step.surface
        dialog = self._dialogs.get(step.surface)
        if dialog is None:
            dialog = self._create_dialog(step)
            if dialog is not None:
                self._dialogs[step.surface] = dialog
                dialog.show()
                dialog.raise_()
        if dialog is not None:
            self._select_page(dialog, step)
            dialog.show()
            dialog.raise_()
        self._active_page = step.page

    def _create_dialog(self, step: TourStep) -> QDialog | None:
        if step.surface == "add":
            from ui.add_instance_dialog import AddInstanceDialog

            dialog = AddInstanceDialog(
                self.window.service, self.window, tutorial_preview=True
            )
        elif step.surface == "edit":
            instance = self._preview_instance
            if instance is None:
                instances = self.window.service.load_instances()
                instance = instances[0] if instances else None
            if instance is None:
                return None
            from ui.edit_instance_dialog import EditInstanceDialog

            dialog = EditInstanceDialog(
                self.window.service,
                instance,
                self.window,
                initial_page="Minecraft Log",
            )
            dialog._tutorial_suppress_install_mods = True
        elif step.surface == "settings":
            from ui.settings_dialog import SettingsDialog

            dialog = SettingsDialog(self.window.service, self.window)
        elif step.surface == "music":
            from ui.music import MusicManagerDialog

            dialog = MusicManagerDialog(self.window.music_controller, self.window)
        elif step.surface == "accounts":
            from ui.accounts_dialog import AccountsDialog

            dialog = AccountsDialog(self.window.service, self.window)
        elif step.surface == "icon":
            from ui.icon_selector_dialog import IconSelectorDialog

            dialog = IconSelectorDialog(
                self.window.service, self.window.service.default_icon, self.window
            )
        elif step.surface == "background":
            from ui.background_selector_dialog import BackgroundSelectorDialog

            dialog = BackgroundSelectorDialog(
                self.window.service,
                self.window.service.get_active_background_reference(),
                self.window,
            )
        else:
            return None
        dialog.setModal(False)
        return dialog

    def _select_page(self, dialog: QDialog, step: TourStep) -> None:
        if step.surface == "add":
            dialog.nav_list.setCurrentRow(
                {"Create": 0, "Import": 1, "Modpacks": 2}.get(step.page, 0)
            )
        elif step.surface == "edit":
            dialog._set_page(step.page)
        elif step.surface == "settings":
            dialog._select_page(
                {"General": 0, "Appearance": 1, "Updates": 2}.get(step.page, 0)
            )
        elif step.surface == "accounts" and step.page:
            tabs = dialog.findChild(QWidget, "accountTabs")
            if tabs is not None and hasattr(tabs, "count"):
                for index in range(tabs.count()):
                    if step.page.lower() in tabs.tabText(index).lower():
                        tabs.setCurrentIndex(index)
                        break

    def _close_tour_dialogs(self, *, keep: set[str] | None = None) -> None:
        self._allow_close = True
        retained = set(keep or ())
        for surface, dialog in list(self._dialogs.items()):
            if surface in retained:
                continue
            dialog.close()
            self._dialogs.pop(surface, None)
        self._allow_close = False

    def _create_preview_instance(self) -> None:
        """Build a disposable instance outside the launcher data directory.

        The editor deliberately reads normal files, so a temporary workspace
        gives the tutorial realistic logs, mods, and screenshots without ever
        creating launcher metadata or a launchable saved instance.
        """
        if self._preview_instance is not None:
            return
        self._preview_workspace = TemporaryDirectory(prefix="notg-tutorial-")
        root = Path(self._preview_workspace.name) / "Tutorial World"
        minecraft = root / ".minecraft"
        mods = minecraft / "mods"
        screenshots = minecraft / "screenshots"
        logs = minecraft / "logs"
        mods.mkdir(parents=True, exist_ok=True)
        screenshots.mkdir(parents=True, exist_ok=True)
        logs.mkdir(parents=True, exist_ok=True)
        logs.joinpath("latest.log").write_text(
            "[NOTG Tutorial] Sample Minecraft log\n"
            "[Render thread/INFO]: Loaded tutorial world\n"
            "[Render thread/INFO]: Sample mods are ready.\n",
            encoding="utf-8",
        )
        icon_path = self.window.service.resolve_icon_path(
            self.window.service.default_icon
        )
        for number, name in enumerate(
            ("Tutorial Mod 1", "Tutorial Mod 2", "Tutorial Mod 3"), start=1
        ):
            archive = mods / f"tutorial-mod-{number}.jar"
            metadata = (
                '{"schemaVersion":1,"id":"tutorial_mod_%d","version":"1.0.%d","name":"%s","icon":"icon.png"}'
                % (number, number, name)
            )
            with zipfile.ZipFile(archive, "w") as jar:
                jar.writestr("fabric.mod.json", metadata)
                if Path(icon_path).is_file():
                    jar.write(icon_path, "icon.png")
        backgrounds = [
            record
            for record in self.window.service.list_backgrounds()
            if not record.is_video and Path(record.absolute_path).is_file()
        ]
        for index, record in enumerate(backgrounds[:3], start=1):
            suffix = Path(record.absolute_path).suffix or ".png"
            shutil.copy2(
                record.absolute_path,
                screenshots / f"Tutorial Screenshot {index}{suffix}",
            )
        if not any(screenshots.iterdir()):
            for index, color in enumerate(("#2769b5", "#579d55", "#ba784c"), start=1):
                image = QPixmap(960, 540)
                image.fill(QColor(color))
                image.save(str(screenshots / f"Tutorial Screenshot {index}.png"))
        self._preview_instance = InstanceRecord(
            instance_id="__tutorial_preview__",
            name="Tutorial World",
            vanilla_version="1.21.1",
            installed_version="1.21.1",
            mod_loader_id="fabric",
            mod_loader_version="0.16.9",
            icon_path=self.window.service.default_icon,
            created_at=datetime.now(timezone.utc).isoformat(),
            last_played=None,
            root_dir=root,
            minecraft_dir=minecraft,
            memory_mb=self.window.service.recommended_minecraft_memory_mb(),
            rich_presence_enabled=True,
            rich_presence_state="Exploring the tutorial",
            rich_presence_details="Tutorial World",
        )
        # Display the preview through the same card class used by the home UI,
        # but do not put it into the service or its instance directory.
        from ui.instance_card import InstanceCard
        from ui.version_display import format_launcher_version_label

        if self.window.content_stack.currentIndex() != 0:
            self.window.content_stack.setCurrentIndex(0)
        item = QListWidgetItem()
        card = InstanceCard(
            self._preview_instance.name,
            format_launcher_version_label(
                self._preview_instance.vanilla_version,
                self._preview_instance.loader_name,
            ),
            self._preview_instance.icon_path,
        )
        item.setSizeHint(card.sizeHint())
        item.setData(Qt.UserRole, self._preview_instance)
        self.window.instance_list.addItem(item)
        self.window.instance_list.setItemWidget(item, card)
        card.clicked.connect(lambda: self.window.instance_list.setCurrentItem(item))
        self.window._cards.append((item, card, self._preview_instance))
        self.window.instance_list.setCurrentItem(item)
        self._preview_card_item = item

    def _remove_preview_instance(self) -> None:
        item = self._preview_card_item
        if item is not None:
            row = self.window.instance_list.row(item)
            if row >= 0:
                self.window.instance_list.takeItem(row)
            self.window._cards = [
                card for card in self.window._cards if card[0] is not item
            ]
        self._preview_card_item = None
        self._preview_instance = None
        if self._preview_workspace is not None:
            self._preview_workspace.cleanup()
            self._preview_workspace = None
        # Restore the normal service-backed home list (usually its empty state
        # on first run) after removing the display-only card.
        self.window.refresh_instances()

    def _restore_tutorial_appearance(self) -> None:
        try:
            if self._original_background is None:
                self.window.service.reset_background()
            else:
                self.window.service.set_active_background(self._original_background)
            self.window._refresh_background()
        except Exception:
            pass
        if self._original_theme_accent is not None:
            try:
                saved = self.window.service.set_theme_accent_color(
                    self._original_theme_accent
                )
                set_theme_accent(self.app, saved)
            except Exception:
                pass

    def _apply_demo_action(self, step: TourStep) -> None:
        if not step.action or self.index in self._performed_actions:
            return
        self._performed_actions.add(self.index)
        dialog = self._dialogs.get(step.surface)
        if step.action == "seed_add_catalog":
            if dialog is not None:
                rows = [
                    {
                        "id": "1.21.1",
                        "release_display": "2024-08-08",
                        "type_label": "Release",
                        "type": "release",
                    },
                    {
                        "id": "1.21",
                        "release_display": "2024-06-13",
                        "type_label": "Release",
                        "type": "release",
                    },
                    {
                        "id": "24w33a",
                        "release_display": "Snapshot",
                        "type_label": "Snapshot",
                        "type": "snapshot",
                    },
                ]
                dialog.version_model.set_rows(rows)
                dialog.version_stack.setCurrentIndex(1)
                dialog.version_search.setEnabled(True)
                dialog.version_table.selectRow(0)
                dialog.loader_buttons.get("fabric").setChecked(True)
                dialog.loader_model.set_rows(
                    [
                        {
                            "loader_version": "0.16.9",
                            "loader_name": "Fabric",
                            "minecraft_version": "1.21.1",
                        },
                        {
                            "loader_version": "0.16.7",
                            "loader_name": "Fabric",
                            "minecraft_version": "1.21.1",
                        },
                    ]
                )
                dialog.loader_stack.setCurrentIndex(1)
        elif step.action == "scroll_add_loader" and dialog is not None:
            self._scroll_to_target(dialog.loader_side_panel)
        elif step.action == "select_add_advanced" and dialog is not None:
            dialog.create_tabs.setCurrentIndex(1)
        elif step.action == "seed_edit_catalog" and dialog is not None:
            dialog._version_request_id += (
                1  # Ignore the background catalogue request for this preview.
            )
            dialog.version_model.set_rows(
                [
                    {
                        "id": "1.21.1",
                        "release_display": "2024-08-08",
                        "type_label": "Release",
                        "type": "release",
                    },
                    {
                        "id": "1.21",
                        "release_display": "2024-06-13",
                        "type_label": "Release",
                        "type": "release",
                    },
                ]
            )
            dialog.version_stack.setCurrentIndex(1)
            dialog.version_table.selectRow(0)
        elif step.action == "select_icon" and dialog is not None:
            paths = list(getattr(dialog, "_tiles", {}))
            if len(paths) > 1:
                dialog._select_icon(paths[1])
        elif step.action == "select_background" and dialog is not None:
            tiles = getattr(dialog, "_tiles", {})
            selected = next(
                (
                    record
                    for record in self.window.service.list_backgrounds()
                    if not record.is_video and record.relative_path in tiles
                ),
                None,
            )
            if selected is not None:
                dialog._select_background(selected.relative_path)
                try:
                    self.window.service.set_active_background(selected.relative_path)
                    self.window._refresh_background()
                except Exception:
                    pass
        elif step.action == "change_theme" and dialog is not None:
            color = QColor("#8d45d9")
            dialog.theme_color_wheel.set_color(color)
            dialog._pending_theme_color = color.name()
            dialog._commit_manual_theme_color()
        elif step.action == "restore_preview":
            if self._preview_instance is not None:
                QTimer.singleShot(250, self._remove_preview_instance)
            QTimer.singleShot(650, self._restore_tutorial_appearance)

    def _resolve_target(self, step: TourStep) -> None:
        if self.overlay is None:
            return
        root = self._dialogs.get(step.surface, self.window)
        if step.surface == "edit" and step.page == "Install Mods":
            browser = getattr(root, "_install_mods_dialog", None)
            if isinstance(browser, QWidget) and browser.isVisible():
                root = browser
        direct = {
            "instance_list": self.window.instance_list,
            "sidebar": self.window.sidebar,
            "tutorial_final": None,
        }
        target = direct.get(step.target)
        if target is None and step.target and hasattr(root, step.target):
            target = getattr(root, step.target)
        if target is None and step.target:
            target = root.findChild(QWidget, step.target)
        if target is not None:
            self._scroll_to_target(target)
        self.overlay.set_spotlight(self._widget_global_rect(target))

    def _scroll_to_target(self, target: QWidget) -> None:
        parent = target.parentWidget()
        while parent is not None and not isinstance(parent, QScrollArea):
            parent = parent.parentWidget()
        if not isinstance(parent, QScrollArea) or parent.widget() is None:
            return
        scrollbar = parent.verticalScrollBar()
        target_y = target.mapTo(parent.widget(), QPoint(0, 0)).y()
        desired = max(
            scrollbar.minimum(),
            min(scrollbar.maximum(), target_y - parent.viewport().height() // 3),
        )
        if abs(desired - scrollbar.value()) < 8:
            return
        if self._scroll_animation is not None and self._scroll_target is target:
            return
        if self._scroll_animation is not None:
            self._scroll_animation.stop()
        animation = QVariantAnimation(
            self, duration=950, easingCurve=QEasingCurve.InOutCubic
        )
        animation.setStartValue(scrollbar.value())
        animation.setEndValue(desired)
        animation.valueChanged.connect(
            lambda value, bar=scrollbar: bar.setValue(int(value))
        )
        animation.finished.connect(self._clear_scroll_animation)
        self._scroll_animation = animation
        self._scroll_target = target
        animation.start()

    def _clear_scroll_animation(self) -> None:
        self._scroll_animation = None
        self._scroll_target = None
        if self.overlay is not None:
            step = STEPS[self.index]
            self._resolve_target(step)
            self.overlay.reposition_for_spotlight()

    @staticmethod
    def _widget_global_rect(widget: QWidget | None) -> QRect | None:
        if widget is None or not widget.isVisible():
            return None
        return QRect(widget.mapToGlobal(QPoint(0, 0)), widget.size())

    @staticmethod
    def _list_row_global_rect(widget, index: int) -> QRect | None:
        item = (
            widget.item(index)
            if widget is not None and 0 <= index < widget.count()
            else None
        )
        if item is None:
            return None
        rect = widget.visualItemRect(item)
        return (
            QRect(widget.mapToGlobal(rect.topLeft()), rect.size())
            if not rect.isNull()
            else None
        )

    def _sync_overlay(self) -> None:
        if self.overlay is None:
            return
        screen = self.window.screen() or self.app.primaryScreen()
        if screen and self.overlay.geometry() != screen.geometry():
            self.overlay.setGeometry(screen.geometry())
        self._resolve_target(STEPS[self.index])


class TutorialHelpDialog(QDialog):
    def __init__(self, parent: QWidget, start_tutorial):
        super().__init__(parent)
        self.setWindowTitle("NOTG Launcher Help")
        self.setModal(False)
        self.setObjectName("tutorialHelpDialog")
        self._start_tutorial = start_tutorial
        self._search_matches: list[str] = []
        self._search_index = -1
        self._build_ui()
        screen = parent.screen() or QApplication.primaryScreen()
        available = (
            screen.availableGeometry() if screen is not None else QRect(0, 0, 1080, 720)
        )
        width = max(320, min(1080, available.width() - 40))
        height = max(280, min(720, available.height() - 64))
        self.setMinimumSize(min(860, width), min(590, height))
        self.resize(width, height)
        x = available.left() + (available.width() - width) // 2
        y = available.top() + max(20, (available.height() - height) // 2 + 16)
        y = min(y, available.bottom() - height + 1)
        self.move(x, y)

    def _build_ui(self) -> None:
        roles = theme_palette(self.parentWidget())["roles"]
        text = QColor(roles["text"]).name()
        muted = QColor(roles["text_muted"]).name()
        surface = QColor(roles["surface_2"]).name()
        card = QColor(roles["card"]).name()
        outline = QColor(roles["outline"]).name()
        accent = QColor(roles["accent"]).name()
        self.setStyleSheet(
            f"QDialog#tutorialHelpDialog {{ background:{QColor(roles['background']).name()}; }}"
            f"QFrame#guideSidebar, QFrame#guideTopBar {{ background:{surface}; border:1px solid {outline}; border-radius:12px; }}"
            f"QFrame#tutorialWelcome {{ background:{card}; border:1px solid {outline}; border-radius:14px; }}"
            f"QPushButton#tutorialVideoPreview {{ background:{card}; border:1px solid {outline}; border-radius:12px; padding:0; }}"
            f"QPushButton#tutorialVideoPreview:hover {{ border-color:{accent}; }}"
            f"QTreeWidget {{ background:transparent; border:0; color:{text}; outline:0; padding:5px; }}"
            f"QTreeWidget::item {{ padding:7px 8px; border-radius:6px; }}"
            f"QTreeWidget::item:selected {{ background:{QColor(roles['selected']).name()}; color:{text}; }}"
            f"QTextBrowser {{ background:{card}; border:1px solid {outline}; border-radius:14px; color:{text}; padding:20px; selection-background-color:{accent}; }}"
            f"QLineEdit {{ background:{card}; color:{text}; border:1px solid {outline}; border-radius:17px; padding:8px 14px; }}"
            f"QPushButton {{ background:{card}; color:{text}; border:1px solid {outline}; border-radius:8px; padding:8px 14px; }}"
            f"QPushButton:hover {{ border-color:{accent}; }}"
            f"QPushButton#startTutorial {{ background:{accent}; color:#ffffff; border:0; font-weight:600; }}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 18)
        root.setSpacing(12)

        top = QFrame()
        top.setObjectName("guideTopBar")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(16, 10, 12, 10)
        top_layout.setSpacing(10)
        title = QLabel("Help and guide")
        title.setStyleSheet(f"color:{text}; font:600 15pt 'Segoe UI';")
        top_layout.addWidget(title)
        top_layout.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the guide")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(270)
        self.search.returnPressed.connect(self._find_next)
        self.search.textChanged.connect(self._reset_search)
        top_layout.addWidget(self.search)
        search_button = QPushButton("Search")
        search_button.setToolTip("Find the next matching phrase")
        search_button.clicked.connect(self._find_next)
        top_layout.addWidget(search_button)
        root.addWidget(top)

        body = QHBoxLayout()
        body.setSpacing(12)
        self.nav = QTreeWidget()
        self.nav.setHeaderHidden(True)
        self.nav.setMinimumWidth(245)
        self.nav.setMaximumWidth(295)
        self.nav.itemClicked.connect(self._go_to_item)
        nav_shell = QFrame()
        nav_shell.setObjectName("guideSidebar")
        nav_layout = QVBoxLayout(nav_shell)
        nav_layout.setContentsMargins(8, 10, 8, 10)
        nav_layout.addWidget(self.nav)
        body.addWidget(nav_shell)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_tutorial_page(text, muted, accent))
        self.guide = QTextBrowser()
        self.guide.setOpenExternalLinks(False)
        self.guide.setOpenLinks(False)
        self.pages.addWidget(self.guide)
        body.addWidget(self.pages, 1)
        root.addLayout(body, 1)
        self._load_guide()

    def _build_tutorial_page(self, text: str, muted: str, accent: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(26, 22, 26, 24)
        layout.setSpacing(12)
        card = QFrame()
        card.setObjectName("tutorialWelcome")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 20, 24, 22)
        card_layout.setSpacing(10)
        title = QLabel("Tutorial")
        title.setStyleSheet(f"color:{text}; font:600 22pt 'Segoe UI';")
        card_layout.addWidget(title)
        description = QLabel(
            "If you want help you can read the docs which is towards your left or check the tutorial again."
        )
        description.setWordWrap(True)
        description.setStyleSheet(f"color:{muted}; font:10.5pt 'Segoe UI';")
        card_layout.addWidget(description)
        actions = QHBoxLayout()
        play_label = QLabel("Play the tutorial")
        play_label.setStyleSheet(f"color:{text}; font:600 10.5pt 'Segoe UI';")
        actions.addWidget(play_label)
        start = QPushButton()
        start.setObjectName("startTutorial")
        start.setIcon(self._video_icon())
        start.setIconSize(QSize(17, 17))
        start.setToolTip("Play the tutorial")
        start.setAccessibleName("Play the tutorial")
        start.setFixedSize(40, 34)
        start.clicked.connect(lambda: (self.close(), self._start_tutorial()))
        actions.addWidget(start)
        actions.addStretch()
        card_layout.addLayout(actions)
        thumbnail_path = (
            Path(__file__).resolve().parents[2]
            / "assets"
            / "tutorial-video-thumbnail.jpg"
        )
        thumbnail = VideoThumbnailButton(QPixmap(str(thumbnail_path)))
        thumbnail.clicked.connect(lambda: self._open_video_tutorial("video-tutorial"))
        card_layout.addWidget(thumbnail)
        video_heading = QLabel("Video tutorial")
        video_heading.setStyleSheet(f"color:{text}; font:700 12pt 'Segoe UI';")
        card_layout.insertWidget(3, video_heading)
        links = QHBoxLayout()
        links.setSpacing(10)
        github = QPushButton("GitHub")
        github.setIcon(self._resource_icon("github"))
        github.setIconSize(QSize(18, 18))
        github.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(GITHUB_URL)))
        website = QPushButton("Launcher website")
        website.setIcon(self._resource_icon("web"))
        website.setIconSize(QSize(18, 18))
        website.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(LAUNCHER_WEBSITE_URL))
        )
        links.addWidget(github)
        links.addWidget(website)
        links.addStretch()
        card_layout.addLayout(links)
        layout.addWidget(card)
        return page

    def _open_video_tutorial(self, _link: str) -> None:
        if VIDEO_TUTORIAL_URL:
            QDesktopServices.openUrl(QUrl(VIDEO_TUTORIAL_URL))

    def _video_icon(self) -> QIcon:
        return self.style().standardIcon(QStyle.SP_MediaPlay)

    @staticmethod
    def _resource_icon(kind: str) -> QIcon:
        pixmap = QPixmap(20, 20)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#ffffff"), 1.6))
        painter.setBrush(Qt.NoBrush)
        if kind == "github":
            painter.drawEllipse(3, 3, 14, 14)
            painter.drawLine(6, 13, 6, 17)
            painter.drawLine(14, 13, 14, 17)
            painter.drawLine(7, 8, 9, 10)
            painter.drawLine(13, 8, 11, 10)
        else:
            painter.drawEllipse(3, 3, 14, 14)
            painter.drawLine(3, 10, 17, 10)
            painter.drawEllipse(7, 3, 6, 14)
        painter.end()
        return QIcon(pixmap)

    def _load_guide(self) -> None:
        tutorial_item = QTreeWidgetItem(["Tutorial"])
        tutorial_item.setData(0, Qt.UserRole, "tutorial")
        self.nav.addTopLevelItem(tutorial_item)
        guide_path = Path(__file__).resolve().parents[2] / "docs" / "USER_GUIDE.md"
        try:
            source = guide_path.read_text(encoding="utf-8")
        except OSError:
            source = "# User Guide\n\nThe guide could not be loaded."
        html_parts: list[str] = []
        parents: dict[int, QTreeWidgetItem] = {0: self.nav.invisibleRootItem()}
        for raw_line in source.splitlines():
            heading = re.match(r"^(#{1,3})\s+(.+?)\s*$", raw_line)
            if heading:
                level = len(heading.group(1))
                label = heading.group(2).replace("**", "")
                if level == 1:
                    continue
                anchor = "guide-" + re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
                html_parts.append(
                    f"<a name='{anchor}'></a><h{level}>{escape(label)}</h{level}>"
                )
                item = QTreeWidgetItem([label])
                item.setData(0, Qt.UserRole, anchor)
                parent_level = max((key for key in parents if key < level), default=0)
                parents[parent_level].addChild(item)
                parents[level] = item
                for key in list(parents):
                    if key > level:
                        del parents[key]
                continue
            clean = escape(raw_line.strip())
            clean = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", clean)
            clean = re.sub(r"\*(.+?)\*", r"<i>\1</i>", clean)
            if not clean:
                continue
            elif raw_line.lstrip().startswith("- "):
                html_parts.append(f"<p style='margin-left:18px;'>â€¢ {clean[2:]}</p>")
            elif re.match(r"^\s*\d+\.\s", raw_line):
                html_parts.append(f"<p style='margin-left:18px;'>{clean}</p>")
            else:
                html_parts.append(f"<p>{clean}</p>")
        self.guide.setHtml(
            "<html><head><style>"
            "body { font-family:'Segoe UI'; font-size:10pt; line-height:1.28; } "
            "h2 { font-size:18pt; font-weight:700; margin:22px 0 7px 0; } "
            "h3 { font-size:12pt; font-weight:700; margin:15px 0 5px 0; } "
            "p { margin:3px 0; } b { font-weight:700; }"
            "</style></head><body>" + "\n".join(html_parts) + "</body></html>"
        )
        self.nav.expandToDepth(2)
        self.nav.setCurrentItem(tutorial_item)
        self.pages.setCurrentIndex(0)

    def _go_to_item(self, item: QTreeWidgetItem) -> None:
        anchor = str(item.data(0, Qt.UserRole) or "")
        if anchor == "tutorial":
            self.pages.setCurrentIndex(0)
            return
        self.pages.setCurrentIndex(1)
        self.guide.scrollToAnchor(anchor)

    def _find_next(self) -> None:
        term = self.search.text().strip()
        if not term:
            return
        self.pages.setCurrentIndex(1)
        cursor = self.guide.document().find(
            term, self.guide.textCursor(), QTextDocument.FindFlags()
        )
        if cursor.isNull():
            start = QTextCursor(self.guide.document())
            start.movePosition(QTextCursor.Start)
            cursor = self.guide.document().find(term, start, QTextDocument.FindFlags())
        if not cursor.isNull():
            self.guide.setTextCursor(cursor)
            self.guide.ensureCursorVisible()

    def _reset_search(self, _text: str) -> None:
        cursor = self.guide.textCursor()
        cursor.clearSelection()
        self.guide.setTextCursor(cursor)
