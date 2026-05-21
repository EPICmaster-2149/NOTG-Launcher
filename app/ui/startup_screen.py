
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from PySide6.QtCore import QEasingCurve, QEventLoop, QPointF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QApplication, QWidget


INTRO_MARKER_VERSION = 1
INTRO_MARKER_NAME = "startup_intro_v1.json"
DEVELOPER_ACCOUNT_NAME = "NOTG_Launcher"
SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧")

NOTG_ASCII_LOGO = (
    "███╗   ██╗ ██████╗ ████████╗ ██████╗",
    "████╗  ██║██╔═══██╗╚══██╔══╝██╔════╝",
    "██╔██╗ ██║██║   ██║   ██║   ██║  ███╗",
    "██║╚██╗██║██║   ██║   ██║   ██║   ██║",
    "██║ ╚████║╚██████╔╝   ██║   ╚██████╔╝",
    "╚═╝  ╚═══╝ ╚═════╝    ╚═╝    ╚═════╝",
    "",
    "██╗      █████╗ ██╗   ██╗███╗   ██╗ ██████╗██╗  ██╗███████╗██████╗",
    "██║     ██╔══██╗██║   ██║████╗  ██║██╔════╝██║  ██║██╔════╝██╔══██╗",
    "██║     ███████║██║   ██║██╔██╗ ██║██║     ███████║█████╗  ██████╔╝",
    "██║     ██╔══██║██║   ██║██║╚██╗██║██║     ██╔══██║██╔══╝  ██╔══██╗",
    "███████╗██║  ██║╚██████╔╝██║ ╚████║╚██████╗██║  ██║███████╗██║  ██║",
    "╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝",
)


@dataclass(slots=True)
class ActivityEntry:
    text: str
    active: bool = True
    completed: bool = False


class StartupUpdateWindow(QWidget):
    intro_finished = Signal()

    def __init__(self, *, mode: str = "startup", developer_mode: bool = False):
        super().__init__()
        self._mode = mode
        self._developer_mode = developer_mode
        self._visible_logo_lines = 0
        self._display_progress = 0.0
        self._target_progress = 0.0
        self._activities: list[ActivityEntry] = []
        self._spinner_index = 0
        self._final_state = False
        self._final_message = "Starting the Launcher..."
        self._error_message = ""

        self.setObjectName("startupUpdateWindow")
        self.setWindowTitle("NOTG Launcher")
        self.setMinimumSize(760, 480)
        self.resize(940, 580)
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        flags = Qt.Window | Qt.FramelessWindowHint
        self.setWindowFlags(flags)

        self._logo_timer = QTimer(self)
        self._logo_timer.setInterval(105)
        self._logo_timer.timeout.connect(self._reveal_next_logo_line)

        self._frame_timer = QTimer(self)
        self._frame_timer.setInterval(70)
        self._frame_timer.timeout.connect(self._tick)
        self._frame_timer.start()

    def start_logo_animation(self) -> None:
        self._visible_logo_lines = 0
        self._logo_timer.start()
        self.update()

    def add_activity(self, text: str) -> None:
        self.complete_current_activity()
        self._activities.append(ActivityEntry(text=text))
        max_entries = 6
        if len(self._activities) > max_entries:
            self._activities = self._activities[-max_entries:]
        self.update()

    def complete_current_activity(self) -> None:
        for entry in reversed(self._activities):
            if entry.active:
                entry.active = False
                entry.completed = True
                break

    def set_progress(self, value: float) -> None:
        self._target_progress = max(0.0, min(100.0, float(value)))
        self.update()

    def set_error(self, message: str) -> None:
        self.complete_current_activity()
        self._error_message = message
        self._target_progress = self._display_progress
        self.update()

    def show_final_starting(self) -> None:
        self.complete_current_activity()
        self._final_state = True
        self._target_progress = 100.0
        self._display_progress = 100.0
        self.update()

    def run_intro_sequence(self) -> None:
        self.show()
        self._center_on_screen()
        self.start_logo_animation()
        QTimer.singleShot(950, lambda: self.add_activity("Preparing startup environment..."))
        QTimer.singleShot(950, lambda: self.set_progress(18))
        QTimer.singleShot(1450, lambda: self.add_activity("Loading launcher profile..."))
        QTimer.singleShot(1450, lambda: self.set_progress(46))
        QTimer.singleShot(1950, lambda: self.add_activity("Syncing local data..."))
        QTimer.singleShot(1950, lambda: self.set_progress(72))
        QTimer.singleShot(2450, lambda: self.add_activity("Opening launcher..."))
        QTimer.singleShot(2450, lambda: self.set_progress(100))
        QTimer.singleShot(3050, self.show_final_starting)
        QTimer.singleShot(4250, self._finish_intro)

    def _finish_intro(self) -> None:
        self.complete_current_activity()
        self.intro_finished.emit()
        self.close()

    def _center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        self.move(available.center() - self.rect().center())

    def _reveal_next_logo_line(self) -> None:
        if self._visible_logo_lines >= len(NOTG_ASCII_LOGO):
            self._logo_timer.stop()
            return
        self._visible_logo_lines += 1
        self.update()

    def _tick(self) -> None:
        self._spinner_index = (self._spinner_index + 1) % len(SPINNER_FRAMES)
        delta = self._target_progress - self._display_progress
        if abs(delta) < 0.18:
            self._display_progress = self._target_progress
        else:
            self._display_progress += delta * 0.18
        self.update()

    def paintEvent(self, event) -> None:  # noqa: D401
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        rect = QRectF(self.rect())
        self._paint_background(painter, rect)
        logo_rect = self._paint_logo(painter, rect)

        if self._developer_mode:
            self._paint_developer_badge(painter, rect)

        if self._error_message:
            self._paint_error(painter, rect, logo_rect)
        elif self._final_state:
            self._paint_final_state(painter, rect, logo_rect)
        else:
            self._paint_activity_area(painter, rect, logo_rect)

        super().paintEvent(event)

    def _paint_background(self, painter: QPainter, rect: QRectF) -> None:
        base = QLinearGradient(rect.topLeft(), rect.bottomRight())
        base.setColorAt(0.0, QColor("#000000"))
        base.setColorAt(0.52, QColor("#0b0d12"))
        base.setColorAt(1.0, QColor("#121212"))
        painter.fillRect(rect, base)

        glow = QRadialGradient(QPointF(rect.width() * 0.45, rect.height() * 0.26), rect.width() * 0.72)
        glow.setColorAt(0.0, QColor(46, 69, 255, 42))
        glow.setColorAt(0.45, QColor(14, 23, 48, 18))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(rect, glow)

        lower = QRadialGradient(QPointF(rect.width() * 0.78, rect.height() * 0.92), rect.width() * 0.55)
        lower.setColorAt(0.0, QColor(255, 191, 64, 22))
        lower.setColorAt(0.42, QColor(24, 18, 9, 8))
        lower.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(rect, lower)

    def _paint_logo(self, painter: QPainter, rect: QRectF) -> QRectF:
        lines = NOTG_ASCII_LOGO[: self._visible_logo_lines]
        font = self._logo_font(rect)
        metrics = QFontMetricsF(font)
        line_height = metrics.lineSpacing()
        max_width = max((metrics.horizontalAdvance(line) for line in NOTG_ASCII_LOGO), default=0.0)
        logo_height = line_height * len(NOTG_ASCII_LOGO)
        x = (rect.width() - max_width) / 2.0
        y = max(26.0, rect.height() * 0.08)

        painter.setFont(font)
        for index, line in enumerate(lines):
            baseline = y + metrics.ascent() + index * line_height
            point = QPointF(x, baseline)
            for color, offset in (
                (QColor("#1b4cff"), QPointF(-1.2, 0.8)),
                (QColor("#ff5b36"), QPointF(1.1, 0.6)),
                (QColor("#ffd34d"), QPointF(0.8, 1.4)),
            ):
                painter.setPen(color)
                painter.drawText(point + offset, line)
            painter.setPen(QColor("#f7f8fb"))
            painter.drawText(point, line)

        return QRectF(x, y, max_width, logo_height)

    def _logo_font(self, rect: QRectF) -> QFont:
        families = set(QFontDatabase.families())
        family = "Courier New"
        for candidate in ("Cascadia Mono", "Consolas", "Lucida Console", "DejaVu Sans Mono", "Courier New"):
            if candidate in families:
                family = candidate
                break

        font = QFont(family)
        font.setStyleHint(QFont.Monospace)
        font.setFixedPitch(True)
        font.setKerning(False)
        font.setLetterSpacing(QFont.PercentageSpacing, 100)

        target_width = rect.width() * 0.82
        target_height = rect.height() * 0.42
        best_size = 8
        for size in range(8, 30):
            font.setPointSize(size)
            metrics = QFontMetricsF(font)
            width = max(metrics.horizontalAdvance(line) for line in NOTG_ASCII_LOGO)
            height = metrics.lineSpacing() * len(NOTG_ASCII_LOGO)
            if width <= target_width and height <= target_height:
                best_size = size
            else:
                break
        font.setPointSize(best_size)
        return font

    def _paint_developer_badge(self, painter: QPainter, rect: QRectF) -> None:
        font = QFont("Segoe UI", 9)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        text = "Developer Mode Enabled"
        padding_x = 13
        badge = QRectF(
            rect.width() - metrics.horizontalAdvance(text) - padding_x * 2 - 26,
            22,
            metrics.horizontalAdvance(text) + padding_x * 2,
            28,
        )
        path = QPainterPath()
        path.addRoundedRect(badge, 10, 10)
        painter.fillPath(path, QColor(46, 69, 255, 42))
        painter.setPen(QPen(QColor(118, 139, 255, 92), 1))
        painter.drawPath(path)
        painter.setPen(QColor("#dbe2ff"))
        painter.drawText(badge, Qt.AlignCenter, text)

    def _paint_activity_area(self, painter: QPainter, rect: QRectF, logo_rect: QRectF) -> None:
        width = min(rect.width() * 0.72, 760.0)
        x = (rect.width() - width) / 2.0
        y = logo_rect.bottom() + 34
        self._paint_log_rows(painter, QRectF(x, y, width, 156))
        self._paint_progress(painter, QRectF(x, y + 174, width, 34))

    def _paint_log_rows(self, painter: QPainter, area: QRectF) -> None:
        font = QFont("Segoe UI", 10)
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        row_height = 24.0
        for index, entry in enumerate(self._activities[-6:]):
            row = QRectF(area.left(), area.top() + index * row_height, area.width(), row_height)
            if entry.active:
                prefix = SPINNER_FRAMES[self._spinner_index]
                color = QColor("#f6f8ff")
            else:
                prefix = "✓"
                color = QColor("#8f98ad")
            painter.setPen(color)
            painter.drawText(row.left(), row.top() + metrics.ascent() + 2, f"{prefix} {entry.text}")

    def _paint_progress(self, painter: QPainter, area: QRectF) -> None:
        percent = int(round(self._display_progress))

        # ASCII progress blocks
        blocks = 34
        filled = int((percent / 100.0) * blocks)

        # Spinner animation
        spinner = SPINNER_FRAMES[self._spinner_index]

        # Final text
        text = (
            f"{spinner} "
            + "["
            + ("█" * filled)
            + ("_" * (blocks - filled))
            + f"] {percent}%"
        )

        # Font
        font = self._mono_font(10)
        painter.setFont(font)

        # Color
        painter.setPen(QColor("#dfe6ff"))

        # Draw centered
        painter.drawText(
            QRectF(area.left(), area.top(), area.width(), 24),
            Qt.AlignCenter,
            text,
        )

    def _paint_final_state(self, painter: QPainter, rect: QRectF, logo_rect: QRectF) -> None:
        font = QFont("Segoe UI", 12)
        font.setWeight(QFont.Medium)
        painter.setFont(font)
        painter.setPen(QColor("#f5f7ff"))
        text = f"{SPINNER_FRAMES[self._spinner_index]} {self._final_message}"
        painter.drawText(QRectF(0, logo_rect.bottom() + 54, rect.width(), 40), Qt.AlignCenter, text)

    def _paint_error(self, painter: QPainter, rect: QRectF, logo_rect: QRectF) -> None:
        font = QFont("Segoe UI", 10)
        painter.setFont(font)
        painter.setPen(QColor("#ffb4a8"))
        painter.drawText(
            QRectF(rect.width() * 0.14, logo_rect.bottom() + 38, rect.width() * 0.72, 92),
            Qt.AlignHCenter | Qt.TextWordWrap,
            self._error_message,
        )

    def _mono_font(self, point_size: int) -> QFont:
        font = QFont("Consolas" if sys.platform == "win32" else "DejaVu Sans Mono", point_size)
        font.setStyleHint(QFont.Monospace)
        font.setFixedPitch(True)
        font.setKerning(False)
        font.setLetterSpacing(QFont.PercentageSpacing, 100)
        return font


class UpdateApplyWorker(QThread):
    activity = Signal(str)
    progress = Signal(float)
    failed = Signal(str)
    ready_to_launch = Signal(list, str)

    def __init__(self, manifest_path: Path):
        super().__init__()
        self.manifest_path = manifest_path
        self.manifest: dict[str, Any] = {}

    def run(self) -> None:
        try:
            self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            zip_path = Path(str(self.manifest["zip_path"])).resolve()
            cache_dir = Path(str(self.manifest["cache_dir"])).resolve()
            install_dir = Path(str(self.manifest["install_dir"])).resolve()
            expected_exe_name = str(self.manifest["expected_exe_name"])

            self._step("Preparing startup environment...", 2)
            self._wait_for_launcher_exit(int(self.manifest.get("launcher_pid") or 0))

            self._step("Verifying downloaded files...", 8)
            package_root, package_exe_name = self._inspect_release_zip(zip_path)

            extract_dir = cache_dir / "extracted"
            self._step("Extracting launcher update...", 12)
            package_dir = self._extract_zip(zip_path, extract_dir, package_root, 12, 48)

            if not (package_dir / package_exe_name).is_file() or not (package_dir / "_internal").is_dir():
                raise RuntimeError("The update package is missing the launcher executable or _internal folder.")

            if package_exe_name.lower() != expected_exe_name.lower():
                os.replace(package_dir / package_exe_name, package_dir / expected_exe_name)

            backup_dir = install_dir.with_name(f"{install_dir.name}.old")
            self._step("Replacing launcher binaries...", 52)
            self._replace_installation(package_dir, install_dir, backup_dir, expected_exe_name)

            self._step("Cleaning temporary files...", 92)
            self._remove_tree(extract_dir, retries=8)
            try:
                zip_path.unlink(missing_ok=True)
            except OSError:
                pass

            self._step("Restarting launcher services...", 98)
            launch_exe = install_dir / expected_exe_name
            if not launch_exe.is_file():
                raise RuntimeError("The updated launcher executable was not found after installation.")
            self.progress.emit(100.0)
            self.ready_to_launch.emit([str(launch_exe)], str(install_dir))
        except Exception as exc:  # noqa: BLE001
            self._write_failure_log(str(exc))
            self.failed.emit(f"Update failed: {exc}")

    def _step(self, text: str, progress: float) -> None:
        self.activity.emit(text)
        self.progress.emit(progress)

    def _wait_for_launcher_exit(self, pid: int) -> None:
        if pid <= 0:
            time.sleep(0.8)
            return
        try:
            import psutil

            process = psutil.Process(pid)
            process.wait(timeout=35)
            return
        except Exception:
            pass
        time.sleep(1.4)

    def _inspect_release_zip(self, zip_path: Path) -> tuple[PurePosixPath, str]:
        if not zip_path.is_file():
            raise RuntimeError("Downloaded update package was not found.")
        try:
            with zipfile.ZipFile(zip_path, "r") as archive:
                archive.testzip()
                names = archive.namelist()
        except zipfile.BadZipFile as exc:
            raise RuntimeError("Downloaded update package is not a valid ZIP file.") from exc

        expected_exe_name = str(self.manifest.get("expected_exe_name") or "").lower()
        normalized = [name.rstrip("/") for name in names if name and name.rstrip("/")]
        candidates: list[tuple[int, PurePosixPath, str]] = []
        for name in normalized:
            path = PurePosixPath(name)
            if not path.name.lower().endswith(".exe"):
                continue
            root = path.parent
            internal_prefix = _zip_prefix(root, "_internal")
            has_internal = any(entry == internal_prefix or entry.startswith(f"{internal_prefix}/") for entry in normalized)
            if not has_internal:
                continue
            score = 100 if path.name.lower() == expected_exe_name else 10
            if root.name.lower() == str(self.manifest.get("expected_install_dir_name") or "").lower():
                score += 20
            candidates.append((score, root, path.name))

        if not candidates:
            raise RuntimeError("Update ZIP does not contain a launcher executable and _internal folder.")
        candidates.sort(key=lambda item: item[0], reverse=True)
        _, package_root, package_exe_name = candidates[0]
        return package_root, package_exe_name

    def _extract_zip(self, zip_path: Path, extract_dir: Path, package_root: PurePosixPath, start: float, end: float) -> Path:
        self._remove_tree(extract_dir, retries=5)
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as archive:
            members = archive.infolist()
            total = max(1, len(members))
            for index, member in enumerate(members, start=1):
                self._extract_member(archive, member, extract_dir)
                self.progress.emit(start + ((end - start) * index / total))

        if str(package_root) in {"", "."}:
            return extract_dir
        return extract_dir.joinpath(*package_root.parts)

    def _extract_member(self, archive: zipfile.ZipFile, member: zipfile.ZipInfo, target_root: Path) -> None:
        target = (target_root / member.filename).resolve()
        root = target_root.resolve()
        if root != target and root not in target.parents:
            raise RuntimeError("Update ZIP contains an unsafe path.")
        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(member, "r") as source, target.open("wb") as destination:
            shutil.copyfileobj(source, destination, length=1024 * 1024)

    def _replace_installation(self, package_dir: Path, install_dir: Path, backup_dir: Path, expected_exe_name: str) -> None:
        self._remove_tree(backup_dir, retries=10)
        if install_dir.exists():
            self._rename_with_retries(install_dir, backup_dir)
        install_dir.mkdir(parents=True, exist_ok=True)

        try:
            files = [path for path in package_dir.rglob("*") if path.is_file()]
            total = max(1, len(files))
            halfway = max(1, total // 3)
            for index, source in enumerate(files, start=1):
                if index == halfway:
                    self.activity.emit("Updating assets...")
                relative = source.relative_to(package_dir)
                target = install_dir / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                self.progress.emit(56 + (31 * index / total))

            if not (install_dir / expected_exe_name).is_file():
                raise RuntimeError("Updated launcher executable was not copied into place.")
        except Exception:
            self._remove_tree(install_dir, retries=5)
            if backup_dir.exists() and not install_dir.exists():
                self._rename_with_retries(backup_dir, install_dir)
            raise

        self._remove_tree(backup_dir, retries=8)

    def _rename_with_retries(self, source: Path, target: Path) -> None:
        last_error: Exception | None = None
        for _ in range(24):
            try:
                source.rename(target)
                return
            except OSError as exc:
                last_error = exc
                time.sleep(0.35)
        raise RuntimeError(f"Could not move existing launcher installation: {last_error}")

    def _remove_tree(self, path: Path, *, retries: int) -> None:
        if not path.exists():
            return
        for _ in range(retries):
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                return
            except OSError:
                time.sleep(0.25)
        shutil.rmtree(path, ignore_errors=True)

    def _write_failure_log(self, message: str) -> None:
        try:
            cache_dir = Path(str(self.manifest.get("cache_dir") or self.manifest_path.parent))
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / "updater-python.log").write_text(message, encoding="utf-8")
        except Exception:
            pass


def run_update_manifest(manifest_path: str | Path) -> int:
    window = StartupUpdateWindow(mode="update")
    window.show()
    window._center_on_screen()
    window.start_logo_animation()

    worker = UpdateApplyWorker(Path(manifest_path).resolve())

    def handle_ready(command: list[str], cwd: str) -> None:
        window.set_progress(100)
        QTimer.singleShot(500, window.show_final_starting)
        QTimer.singleShot(2500, lambda: _launch_and_quit(command, cwd, worker, window))

    worker.activity.connect(window.add_activity)
    worker.progress.connect(window.set_progress)
    worker.failed.connect(window.set_error)
    worker.ready_to_launch.connect(handle_ready)
    worker.start()
    return QApplication.instance().exec()


def _launch_and_quit(command: list[str], cwd: str, worker: QThread, window: QWidget) -> None:
    try:
        _hidden_popen(command, cwd=Path(cwd))
    finally:
        worker.quit()
        window.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()


def _hidden_popen(command: list[str], *, cwd: Path) -> subprocess.Popen[Any]:
    kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    creationflags = 0
    for flag_name in ("CREATE_NO_WINDOW", "DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP"):
        creationflags |= int(getattr(subprocess, flag_name, 0))
    if creationflags:
        kwargs["creationflags"] = creationflags
    if sys.platform == "win32" and hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()  # type: ignore[attr-defined]
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore[attr-defined]
        startupinfo.wShowWindow = subprocess.SW_HIDE  # type: ignore[attr-defined]
        kwargs["startupinfo"] = startupinfo
    return subprocess.Popen(command, **kwargs)


def should_show_startup_intro(service: Any, developer_mode: bool) -> bool:
    if developer_mode:
        return True
    always_show = getattr(service, "get_always_show_loading_screen", lambda: True)
    if bool(always_show()):
        return True
    return not startup_intro_marker(service).is_file()


def startup_intro_marker(service: Any) -> Path:
    return Path(service.config_root) / INTRO_MARKER_NAME


def mark_startup_intro_seen(service: Any) -> None:
    marker = startup_intro_marker(service)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"version": INTRO_MARKER_VERSION, "completed": True}, indent=2), encoding="utf-8")


def run_startup_intro(service: Any, *, developer_mode: bool) -> bool:
    window = StartupUpdateWindow(mode="startup", developer_mode=developer_mode)
    loop = QEventLoop()
    completed = {"value": False}

    def finish() -> None:
        completed["value"] = True
        loop.quit()

    window.intro_finished.connect(finish)
    window.run_intro_sequence()
    loop.exec()
    if completed["value"]:
        mark_startup_intro_seen(service)
    return completed["value"]


def _zip_prefix(root: PurePosixPath, child: str = "") -> str:
    parts = [part for part in root.parts if part not in {"", "."}]
    if child:
        parts.append(child)
    return "/".join(parts)
