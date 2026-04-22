"""
Update settings panel for NOTG Launcher settings dialog.
Handles UI for checking and installing updates.
"""

from PySide6.QtCore import QThread, Signal, Qt, QSize, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, 
    QTextEdit, QMessageBox
)
from PySide6.QtGui import QFont, QTextCursor

from core.updater import UpdateChecker, UpdateInstaller, UpdateState
from ui.topbar import ModernButton
from ui.responsive import scaled_px
from ui.theme import theme_palette
from version import APP_VERSION
from pathlib import Path
import sys


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
            exe_path = installer.download_update(self.progress.emit)
            
            if exe_path and installer.verify_download(exe_path):
                self.download_complete.emit(str(exe_path))
            else:
                self.error.emit("Downloaded file verification failed")
        
        except Exception as e:
            self.error.emit(f"Download error: {str(e)}")


class ReleaseNotesPreview(QFrame):
    """Custom widget to display release notes with proper styling."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("releaseNotesPreview")
        self.setMinimumHeight(200)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        
        self.text_display = QTextEdit()
        self.text_display.setReadOnly(True)
        self.text_display.setObjectName("releaseNotesText")
        self.text_display.setFrameShape(QFrame.NoFrame)
        
        # Use monospace font for better code/changelog readability
        font = QFont("Courier New" if sys.platform == "win32" else "Monospace", 9)
        self.text_display.setFont(font)
        
        layout.addWidget(self.text_display)
    
    def set_content(self, content: str):
        """Set the content to display."""
        self.text_display.setText(content)
        self.text_display.moveCursor(QTextCursor.MoveOperation.Start)


class UpdateSettingsPanel(QWidget):
    """Update settings panel for settings dialog."""
    
    install_requested = Signal(str, str)  # (new_exe_path, version)
    
    def __init__(self, parent=None, github_owner: str = "YourUsername", github_repo: str = "NOTG-Launcher"):
        super().__init__(parent)
        self.github_owner = github_owner
        self.github_repo = github_repo
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
            self.current_exe = str(Path(__file__).resolve().parents[2] / "dist" / "NOTG-Launcher" / "NOTG-Launcher.exe")
        
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
        self.preview = ReleaseNotesPreview()
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
            self.preview.set_content(notes)
            self.install_button.setEnabled(True)
            
            # Save state
            state = self.update_state.get_state()
            state["available_version"] = version
            state["release_notes"] = notes
            state["download_url"] = download_url
            self.update_state.save_state(state)
        else:
            self.status_label.setText("You have the latest version")
            self.preview.set_content("Up to date")
            self.install_button.setEnabled(False)
    
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
