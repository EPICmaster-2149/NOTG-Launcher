"""
Update settings panel for NOTG Launcher settings dialog.
Handles UI for checking and installing updates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

from PySide6.QtCore import QThread, Signal, Qt, QSize, QTimer, QUrl
from PySide6.QtGui import QFont, QImage, QTextCursor, QTextDocument
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkDiskCache, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QTextBrowser, QMessageBox
)

from core.updater import UpdateChecker, UpdateInstaller, UpdateState
from ui.topbar import ModernButton
from ui.responsive import scaled_px
from ui.theme import theme_palette
from version import APP_VERSION
import sys


def _resolve_dev_executable() -> str:
    project_root = Path(__file__).resolve().parents[2]
    dist_root = project_root / "dist"
    candidates = [
        dist_root / "NOTG-Launcher" / "NOTG-Launcher.exe",
        dist_root / "NOTG Launcher" / "NOTG Launcher.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    matches = sorted(dist_root.glob("*/*.exe"))
    if matches:
        return str(matches[0])

    return str(candidates[0])


class CheckUpdateWorker(QThread):
    """Worker thread for checking updates - prevents UI freezing."""
    
    check_complete = Signal(bool, str, str, str)  # has_update, version, notes, download_url
    error = Signal(str)
    
    def __init__(self, github_owner: str, github_repo: str):
        super().__init__()
        self.checker = UpdateChecker(github_owner, github_repo, APP_VERSION)
    
    def run(self):
        """Run in background thread."""
        try:
            release = self.checker.get_latest_release()
            if not release:
                self.error.emit("Could not connect to GitHub. Check your internet connection.")
                return
            
            has_update = self.checker.has_update_available(release)
            new_version = release.get('tag_name', 'Unknown')
            release_notes = self.checker.get_release_notes(release)
            download_url = self.checker.get_download_url(release) or ""
            
            self.check_complete.emit(has_update, new_version, release_notes, download_url)
        
        except Exception as e:
            self.error.emit(f"Error checking for updates: {str(e)}")


class DownloadUpdateWorker(QThread):
    """Worker thread for downloading updates."""
    
    progress = Signal(int)
    download_complete = Signal(str)  # path to downloaded file
    error = Signal(str)
    
    def __init__(self, download_url: str, cache_dir: str, current_exe: str):
        super().__init__()
        self.download_url = download_url
        self.cache_dir = cache_dir
        self.current_exe = current_exe
    
    def run(self):
        """Download in background."""
        try:
            installer = UpdateInstaller(self.current_exe, self.cache_dir)
            zip_path = installer.download_update(self.download_url, self.progress.emit)
            
            if zip_path and installer.verify_download(zip_path):
                self.download_complete.emit(str(zip_path))
            else:
                self.error.emit("Downloaded file verification failed")
        
        except Exception as e:
            self.error.emit(f"Download error: {str(e)}")


@dataclass(slots=True)
class ReleaseNotesContext:
    owner: str
    repo: str
    ref: str

    @property
    def link_base(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}/blob/{self.ref}/"

    @property
    def repository_root(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}/blob/{self.ref}/"


class ReleaseNotesBrowser(QTextBrowser):
    def __init__(self, cache_dir: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._context: ReleaseNotesContext | None = None
        self._raw_markdown = ""
        self._loaded_images: dict[str, QImage] = {}
        self._pending_replies: dict[str, QNetworkReply] = {}
        self._placeholder = QImage(2, 2, QImage.Format_ARGB32_Premultiplied)
        self._placeholder.fill(Qt.transparent)

        self._network = QNetworkAccessManager(self)
        cache = QNetworkDiskCache(self)
        cache_path = Path(cache_dir) / "release-notes-images"
        cache_path.mkdir(parents=True, exist_ok=True)
        cache.setCacheDirectory(str(cache_path))
        self._network.setCache(cache)

        self.setReadOnly(True)
        self.setObjectName("releaseNotesText")
        self.setFrameShape(QFrame.NoFrame)
        self.setOpenExternalLinks(True)
        self.setOpenLinks(True)
        self.document().setDocumentMargin(4)

    def set_release_notes(self, markdown: str, context: ReleaseNotesContext | None = None) -> None:
        self._context = context
        self._raw_markdown = (markdown or "").strip() or "No release notes available."
        self.document().setBaseUrl(QUrl(context.link_base if context else "https://github.com/"))
        self.document().setDefaultStyleSheet(self._document_css())
        self.setMarkdown(_rewrite_markdown_images(self._raw_markdown, context))
        self.moveCursor(QTextCursor.MoveOperation.Start)
        self._refresh_loaded_images()
        self.viewport().update()

    def refresh_theme(self) -> None:
        self.document().setDefaultStyleSheet(self._document_css())
        self._refresh_loaded_images()
        self.viewport().update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_loaded_images()

    def loadResource(self, resource_type: int, name: QUrl):
        image_resource = getattr(QTextDocument, "ImageResource", QTextDocument.ResourceType.ImageResource)
        if resource_type == image_resource:
            url = name.toString()
            if url in self._loaded_images:
                return self._scaled_image(self._loaded_images[url])
            if url.startswith(("http://", "https://")):
                self._queue_image(url)
                return self._placeholder
        return super().loadResource(resource_type, name)

    def _queue_image(self, url: str) -> None:
        if url in self._pending_replies or url in self._loaded_images:
            return
        reply = self._network.get(QNetworkRequest(QUrl(url)))
        self._pending_replies[url] = reply
        reply.finished.connect(lambda target=url, current=reply: self._handle_image_loaded(target, current))

    def _handle_image_loaded(self, url: str, reply: QNetworkReply) -> None:
        self._pending_replies.pop(url, None)
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                return
            data = bytes(reply.readAll())
        finally:
            reply.deleteLater()

        image = QImage()
        if not image.loadFromData(data):
            return
        self._loaded_images[url] = image
        self._update_image_resource(url, image)

    def _refresh_loaded_images(self) -> None:
        for url, image in self._loaded_images.items():
            self._update_image_resource(url, image)

    def _update_image_resource(self, url: str, image: QImage) -> None:
        image_resource = getattr(QTextDocument, "ImageResource", QTextDocument.ResourceType.ImageResource)
        self.document().addResource(image_resource, QUrl(url), self._scaled_image(image))
        self.document().markContentsDirty(0, self.document().characterCount())
        self.viewport().update()

    def _scaled_image(self, image: QImage) -> QImage:
        target_width = max(220, self.viewport().width() - 40)
        if image.width() <= target_width or target_width <= 0:
            return image
        return image.scaledToWidth(target_width, Qt.SmoothTransformation)

    def _document_css(self) -> str:
        palette = theme_palette(self)
        base_text = palette["line_edit"]["text"].name()
        heading = palette["buttons"]["sidebar"]["text"].name()
        muted = palette["loader_placeholder"]["text"].name()
        link = palette["buttons"]["accent"]["bg"].name()
        return (
            "body { margin: 0; color: %s; font-size: 13px; line-height: 1.5; }"
            "p { margin: 0 0 10px 0; }"
            "h1, h2, h3, h4 { color: %s; font-weight: 700; margin: 16px 0 8px 0; }"
            "ul, ol { margin: 6px 0 12px 20px; }"
            "li { margin: 0 0 4px 0; }"
            "blockquote { margin: 10px 0; padding-left: 12px; color: %s; }"
            "a { color: %s; text-decoration: none; }"
            "img { margin: 8px 0; }"
        ) % (base_text, heading, muted, link)


class ReleaseNotesPreview(QFrame):
    """Custom widget to display release notes with proper styling."""
    
    def __init__(self, cache_dir: str, github_owner: str, github_repo: str, parent=None):
        super().__init__(parent)
        self.setObjectName("releaseNotesPreview")
        self.setMinimumHeight(200)
        self._github_owner = github_owner
        self._github_repo = github_repo
        self._context: ReleaseNotesContext | None = None
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        
        self.text_display = ReleaseNotesBrowser(cache_dir, self)
        
        font = QFont("Segoe UI" if sys.platform == "win32" else "Sans Serif", 10)
        self.text_display.setFont(font)
        
        layout.addWidget(self.text_display)
    
    def set_content(self, content: str, *, release_ref: str | None = None):
        """Set the content to display."""
        self._context = (
            ReleaseNotesContext(self._github_owner, self._github_repo, release_ref)
            if release_ref
            else None
        )
        self.text_display.set_release_notes(content, self._context)

    def refresh_theme(self) -> None:
        self.text_display.refresh_theme()


class UpdateSettingsPanel(QWidget):
    """Update settings panel for settings dialog."""
    
    install_requested = Signal(str, str)  # (new_exe_path, version)
    
    def __init__(self, parent=None, github_owner: str = "YourUsername", github_repo: str = "NOTG-Launcher"):
        super().__init__(parent)
        self.github_owner = github_owner
        self.github_repo = github_repo  # GitHub repo (uses hyphen)
        self.check_worker = None
        self.download_worker = None
        self.downloaded_exe = None
        self.latest_version = None
        self.download_url = None
        
        # Get cache and exe paths
        from core.launcher import LauncherService
        service = LauncherService()
        self.cache_dir = str(service.cache_root)
        
        if getattr(sys, "frozen", False):
            self.current_exe = sys.executable
        else:
            self.current_exe = _resolve_dev_executable()
        
        self.state_file = Path(self.cache_dir) / "update_state.json"
        self.update_state = UpdateState(self.state_file)
        
        self._build_ui()
    
    def _build_ui(self):
        """Build the UI."""
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(12)
        
        # Title
        title = QLabel("Update")
        title.setObjectName("editorSectionTitle")
        root_layout.addWidget(title)
        
        # Check button row
        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(10)
        
        self.check_button = ModernButton(
            "Check for Updates",
            role="accent",
            height=36,
            icon_size=0,
            minimum_width=140,
            horizontal_padding=20,
            font_point_size=10,
            parent=self
        )
        self.check_button.clicked.connect(self._on_check_updates)
        button_row.addWidget(self.check_button)
        
        # Version display
        self.version_label = QLabel(f"Current: v{APP_VERSION}")
        self.version_label.setObjectName("settingsCaption")
        button_row.addWidget(self.version_label, 1, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        button_row.addStretch()
        
        root_layout.addLayout(button_row)
        
        # Release notes preview
        self.preview = ReleaseNotesPreview(self.cache_dir, self.github_owner, self.github_repo)
        self.preview.set_content("Up to date")
        root_layout.addWidget(self.preview, 1)
        
        # Install button row
        install_row = QHBoxLayout()
        install_row.setContentsMargins(0, 0, 0, 0)
        install_row.setSpacing(10)
        
        self.install_button = ModernButton(
            "Install Update",
            role="accent",
            height=36,
            icon_size=0,
            minimum_width=140,
            horizontal_padding=20,
            font_point_size=10,
            parent=self
        )
        self.install_button.clicked.connect(self._on_install_update)
        self.install_button.setEnabled(False)
        install_row.addWidget(self.install_button)
        
        # Status label
        self.status_label = QLabel("")
        self.status_label.setObjectName("settingsCaption")
        install_row.addWidget(self.status_label, 1, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        install_row.addStretch()
        
        root_layout.addLayout(install_row)
    
    def _on_check_updates(self):
        """Handle check updates button click."""
        if self.check_worker and self.check_worker.isRunning():
            self.status_label.setText("Already checking...")
            return
        
        self.status_label.setText("Checking for updates...")
        self.check_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self.preview.set_content("Checking for updates...")
        
        self.check_worker = CheckUpdateWorker(self.github_owner, self.github_repo)
        self.check_worker.check_complete.connect(self._on_check_complete)
        self.check_worker.error.connect(self._on_check_error)
        self.check_worker.start()
    
    def _on_check_complete(self, has_update: bool, version: str, notes: str, download_url: str):
        """Called when check completes."""
        self.check_button.setEnabled(True)
        self.latest_version = version
        self.download_url = download_url
        
        if has_update:
            self.status_label.setText(f"Update available: {version}")
            self.install_button.setEnabled(True)
            
            # Save state
            state = self.update_state.get_state()
            state["available_version"] = version
            state["release_notes"] = notes
            state["download_url"] = download_url
            self.update_state.save_state(state)
        else:
            self.status_label.setText("You have the latest version")
            self.install_button.setEnabled(False)
        self.preview.set_content(notes, release_ref=version)
    
    def _on_check_error(self, error: str):
        """Called on check error."""
        self.check_button.setEnabled(True)
        self.status_label.setText("Check failed")
        self.preview.set_content(f"Error: {error}")
        
        QMessageBox.warning(self, "Update Check Failed", error)
    
    def _on_install_update(self):
        """Handle install update button click."""
        if not self.download_url:
            QMessageBox.warning(self, "Error", "No download URL available")
            return
        
        self.status_label.setText("Downloading update...")
        self.install_button.setEnabled(False)
        self.check_button.setEnabled(False)
        self.preview.set_content("Downloading update...\nPlease wait, this may take a few minutes.")
        
        self.download_worker = DownloadUpdateWorker(
            self.download_url,
            self.cache_dir,
            self.current_exe
        )
        self.download_worker.progress.connect(self._on_download_progress)
        self.download_worker.download_complete.connect(self._on_download_complete)
        self.download_worker.error.connect(self._on_download_error)
        self.download_worker.start()
    
    def _on_download_progress(self, percentage: int):
        """Called during download."""
        self.status_label.setText(f"Downloading: {percentage}%")
    
    def _on_download_complete(self, exe_path: str):
        """Called when download completes."""
        self.downloaded_exe = exe_path
        self.status_label.setText("Update ready. Restarting application...")
        self.preview.set_content("Update downloaded successfully!\nThe application will now restart to apply the update.")
        
        # Give UI time to update before restarting
        QTimer.singleShot(2000, self._apply_update)
    
    def _on_download_error(self, error: str):
        """Called on download error."""
        self.status_label.setText("Download failed")
        self.install_button.setEnabled(True)
        self.check_button.setEnabled(True)
        self.preview.set_content(f"Error: {error}")
        
        QMessageBox.critical(self, "Download Failed", error)
    
    def _apply_update(self):
        """Apply the downloaded update."""
        if not self.downloaded_exe:
            QMessageBox.critical(self, "Error", "No download file found")
            return
        
        try:
            installer = UpdateInstaller(self.current_exe, self.cache_dir)
            if installer.apply_update(Path(self.downloaded_exe)):
                # Update will be applied after app closes
                # Close settings dialog and main app
                self.window().close()
                from PySide6.QtWidgets import QApplication
                QApplication.instance().quit()
            else:
                QMessageBox.critical(self, "Error", "Failed to start update process")
                self.install_button.setEnabled(True)
                self.check_button.setEnabled(True)
        
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Update error: {str(e)}")
            self.install_button.setEnabled(True)
            self.check_button.setEnabled(True)
    
    def set_metrics(self, font_size: int = None):
        """Update metrics for responsive layout."""
        if font_size:
            font = self.check_button.font()
            font.setPointSize(font_size)


def _rewrite_markdown_images(markdown: str, context: ReleaseNotesContext | None) -> str:
    image_pattern = re.compile(r"!\[([^\]]*)\]\((<[^>]+>|[^)\s]+)([^)]*)\)")
    html_image_pattern = re.compile(r'(<img\b[^>]*\bsrc=["\'])([^"\']+)(["\'])', re.IGNORECASE)

    def replace_markdown(match: re.Match[str]) -> str:
        alt_text, url_token, suffix = match.groups()
        resolved = _resolve_image_url(url_token.strip("<>"), context)
        wrapped = f"<{resolved}>" if url_token.startswith("<") else resolved
        return f"![{alt_text}]({wrapped}{suffix})"

    def replace_html(match: re.Match[str]) -> str:
        prefix, source, suffix = match.groups()
        return f"{prefix}{_resolve_image_url(source, context)}{suffix}"

    updated = image_pattern.sub(replace_markdown, markdown)
    return html_image_pattern.sub(replace_html, updated)


def _resolve_image_url(url: str, context: ReleaseNotesContext | None) -> str:
    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"}:
        return _normalize_github_image_url(url)
    if context is None:
        return url
    if url.startswith("/"):
        return _normalize_github_image_url(f"{context.repository_root}{url.lstrip('/')}")
    return _normalize_github_image_url(urljoin(context.link_base, url))


def _normalize_github_image_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return url
    if parsed.netloc == "raw.githubusercontent.com":
        return url
    if parsed.netloc != "github.com":
        return url

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 5 and parts[2] == "blob":
        owner, repo, _, ref = parts[:4]
        remainder = "/".join(parts[4:])
        return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{remainder}"
    return url
