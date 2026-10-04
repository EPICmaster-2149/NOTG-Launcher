"""Consistent, user-facing error presentation for NOTG Launcher.

Keep raw exceptions in the caller's logs/debugger. Dialogs must tell players
what happened, what they can do next, and a stable code they can report.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from PySide6.QtWidgets import QMessageBox as _QtMessageBox
from PySide6.QtWidgets import QWidget


GENERIC_ERROR_CODE = "ERROR-404"


@dataclass(frozen=True)
class ErrorPresentation:
    code: str
    heading: str
    guidance: str


def present_error(title: str, detail: object) -> ErrorPresentation:
    """Translate an internal error into a safe, actionable dialog message."""
    raw = _clean_detail(detail)
    haystack = f"{title} {raw}".lower()

    if _is_music_cache_lock(haystack):
        return ErrorPresentation(
            "ERR-MUS-001",
            "Music is already being prepared",
            "Wait for the current download to finish, then press Play once. "
            "The launcher will use the completed cached audio automatically.",
        )
    if "403" in haystack and ("youtube" in haystack or "video data" in haystack):
        return ErrorPresentation(
            "ERR-MUS-002",
            "This online track is temporarily unavailable",
            "Try again shortly. If it continues, update yt-dlp and verify that "
            "the video is public and available in your region.",
        )
    if any(token in haystack for token in ("yt-dlp", "playable audio", "playable stream", "music cache")):
        return ErrorPresentation(
            "ERR-MUS-003",
            "The online music link could not be prepared",
            "Check the link, your internet connection, and that the source is public. "
            "Then try adding or playing it again.",
        )
    if any(token in haystack for token in ("permission denied", "access is denied", "winerror 5", "winerror 32", "being used by another process")):
        return ErrorPresentation(
            "ERR-FILE-001",
            "The launcher cannot access a required file",
            "Close other apps that may be using the file, then try again. "
            "If needed, restart the launcher.",
        )
    if any(token in haystack for token in ("connection", "timeout", "network", "dns", "http error", "ssl")):
        return ErrorPresentation(
            "ERR-NET-001",
            "A network request could not be completed",
            "Check your internet connection and try again. The service may also "
            "be temporarily unavailable.",
        )
    if "java" in haystack:
        return ErrorPresentation(
            "ERR-JAVA-001",
            "Java needs attention",
            "Install or select a compatible Java runtime for the selected Minecraft version, then retry.",
        )
    if any(token in haystack for token in ("modrinth", "modpack", "mod ")):
        return ErrorPresentation(
            "ERR-MOD-001",
            "The mod or modpack operation could not be completed",
            "Check the selected version and connection, then try again.",
        )
    if any(token in haystack for token in ("account", "login", "oauth", "microsoft", "ely.by")):
        return ErrorPresentation(
            "ERR-ACC-001",
            "The account operation could not be completed",
            "Sign in again and verify your account or network connection.",
        )
    if any(token in haystack for token in ("update", "download")):
        return ErrorPresentation(
            "ERR-UPD-001",
            "The update operation could not be completed",
            "Check your internet connection, then try the update again.",
        )
    if any(token in haystack for token in ("install", "instance", "minecraft")):
        return ErrorPresentation(
            "ERR-INS-001",
            "The Minecraft instance operation could not be completed",
            "Check free disk space, the selected version, and required files, then try again.",
        )
    return ErrorPresentation(
        GENERIC_ERROR_CODE,
        "Something unexpected happened",
        "Please try again. If the problem continues, report this code and the action you were taking.",
    )


def _clean_detail(detail: object) -> str:
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(detail or "")).strip()
    return " ".join(text.split())


def _is_music_cache_lock(haystack: str) -> bool:
    return (
        "music-stream-cache" in haystack
        and any(token in haystack for token in ("winerror 32", ".part", "being used by another process"))
    )


class QMessageBox:
    """Drop-in facade for the static QMessageBox calls used by the UI."""

    Yes = _QtMessageBox.Yes
    No = _QtMessageBox.No
    Cancel = _QtMessageBox.Cancel
    Ok = _QtMessageBox.Ok
    StandardButton = _QtMessageBox.StandardButton

    @staticmethod
    def warning(parent: QWidget | None, title: str, detail: object, *args, **kwargs):
        return QMessageBox._show(_QtMessageBox.warning, parent, title, detail, *args, **kwargs)

    @staticmethod
    def critical(parent: QWidget | None, title: str, detail: object, *args, **kwargs):
        return QMessageBox._show(_QtMessageBox.critical, parent, title, detail, *args, **kwargs)

    @staticmethod
    def information(parent: QWidget | None, title: str, text: str, *args, **kwargs):
        return _QtMessageBox.information(parent, title, text, *args, **kwargs)

    @staticmethod
    def question(parent: QWidget | None, title: str, text: str, *args, **kwargs):
        return _QtMessageBox.question(parent, title, text, *args, **kwargs)

    @staticmethod
    def _show(method, parent: QWidget | None, title: str, detail: object, *args, **kwargs):
        error = present_error(title, detail)
        text = f"{error.heading}\n\n{error.guidance}\n\nError code: {error.code}"
        return method(parent, f"{title} — {error.code}", text, *args, **kwargs)
