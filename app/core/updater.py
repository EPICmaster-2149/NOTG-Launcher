"""
Auto-updater service for NOTG Launcher.
Checks GitHub releases and manages updates.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
import requests
import hashlib


class UpdateChecker:
    """Checks GitHub for new releases."""
    
    def __init__(self, github_owner: str, github_repo: str, current_version: str):
        self.github_owner = github_owner
        self.github_repo = github_repo
        self.current_version = current_version
        self.api_url = f"https://api.github.com/repos/{github_owner}/{github_repo}/releases/latest"
    
    def get_latest_release(self) -> Optional[Dict[str, Any]]:
        """
        Fetch latest release info from GitHub.
        Returns None if connection fails.
        """
        try:
            response = requests.get(self.api_url, timeout=8)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Failed to check for updates: {e}")
            return None
    
    @staticmethod
    def parse_version(version_str: str) -> Tuple[int, int, int]:
        """Convert 'v1.0.0' or '1.0.0' to (1, 0, 0)."""
        clean = version_str.lstrip('v').strip()
        try:
            parts = clean.split('.')
            return tuple(int(p) for p in parts[:3])  # type: ignore
        except (ValueError, IndexError):
            return (0, 0, 0)
    
    def has_update_available(self, latest_release: Dict[str, Any]) -> bool:
        """Check if newer version exists."""
        latest_tag = latest_release.get('tag_name', '')
        latest_version = self.parse_version(latest_tag)
        current_version = self.parse_version(self.current_version)
        return latest_version > current_version
    
    def get_download_url(self, latest_release: Dict[str, Any]) -> Optional[str]:
        """Extract .zip download URL from release assets (contains exe + _internal)."""
        assets = latest_release.get('assets', [])
        for asset in assets:
            # Look for NOTG-Launcher.zip which contains the full bundled app
            if asset['name'].endswith('.zip'):
                return asset['browser_download_url']
        return None
    
    def get_release_notes(self, latest_release: Dict[str, Any]) -> str:
        """Get formatted release notes."""
        body = latest_release.get('body', '')
        if not body:
            return "No release notes provided."
        return body


class UpdateInstaller:
    """Handles downloading and installing updates."""
    
    def __init__(self, current_exe_path: str, cache_dir: str):
        self.current_exe = Path(current_exe_path)
        self.installation_dir = self.current_exe.parent  # Parent dir (NOTG-Launcher/)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def download_update(self, download_url: str, progress_callback=None):
        """
        Download update ZIP to cache (contains exe + _internal folder).
        Calls progress_callback(percentage) during download.
        Returns path to downloaded ZIP file or None on failure.
        """
        try:
            new_zip = self.cache_dir / "NOTG-Launcher-update.zip"
            
            # Remove old download if exists
            if new_zip.exists():
                new_zip.unlink()
            
            response = requests.get(download_url, stream=True, timeout=30)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(new_zip, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size and progress_callback:
                            percentage = int((downloaded / total_size) * 100)
                            progress_callback(percentage)
            
            # Final callback
            if progress_callback:
                progress_callback(100)
            
            return new_zip
        
        except Exception as e:
            print(f"Download failed: {e}")
            return None
    
    def verify_download(self, zip_path: Path) -> bool:
        """Verify downloaded ZIP is valid and contains required files."""
        if not zip_path.exists():
            return False
        
        # Basic size check - ZIP should be > 1MB
        size = zip_path.stat().st_size
        if size < 1000000:  # Less than 1MB
            return False
        
        # Verify it's a valid ZIP with expected structure
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                namelist = zf.namelist()
                # Should contain NOTG-Launcher.exe and _internal folder
                has_exe = any('NOTG-Launcher.exe' in name for name in namelist)
                has_internal = any('_internal' in name for name in namelist)
                return has_exe and has_internal
        except zipfile.BadZipFile:
            return False
    
    def create_updater_script(self, zip_path: Path) -> Path:
        """
        Create batch script to extract ZIP and swap entire app directory.
        Handles both exe and _internal folder replacement.
        """
        script = self.cache_dir / "updater.bat"
        extract_dir = self.cache_dir / "extracted"
        
        # Build paths with forward slashes for batch compatibility
        zip_str = str(zip_path).replace("\\", "/")
        extract_str = str(extract_dir).replace("\\", "/")
        install_dir_str = str(self.installation_dir).replace("\\", "/")
        current_exe_str = str(self.current_exe).replace("\\", "/")
        old_backup_dir = str(self.installation_dir.with_name(self.installation_dir.name + ".old")).replace("\\", "/")
        backup_name = self.installation_dir.name + ".old"
        
        batch_content = f"""@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM Give main exe time to fully exit
timeout /t 3 /nobreak

REM Extract ZIP to temp location
cd /d "{extract_str}"
powershell -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; [System.IO.Compression.ZipFile]::ExtractToDirectory('{zip_str}', '.')" >nul 2>&1

if not exist "{extract_str}/NOTG-Launcher/NOTG-Launcher.exe" (
    echo Update extraction failed
    exit /b 1
)

REM Backup old installation
if exist "{install_dir_str}" (
    if exist "{old_backup_dir}" rmdir /s /q "{old_backup_dir}" 2>nul
    cd /d "{install_dir_str}/.."
    for /f "tokens=*" %%A in ("{install_dir_str}") do (
        set "oldname=%%~nA"
    )
    ren "{install_dir_str}" "{backup_name}"
)

REM Move new files to installation location
if exist "{extract_dir}/NOTG-Launcher" (
    move /Y "{extract_str}/NOTG-Launcher" "{install_dir_str}"
)

REM Launch new exe
if exist "{current_exe_str}" (
    start "" "{current_exe_str}"
) else (
    echo Update failed: exe not found
    exit /b 1
)

REM Cleanup old installation in background
if exist "{old_backup_dir}" (
    timeout /t 10 /nobreak
    rmdir /s /q "{old_backup_dir}" 2>nul
)

REM Clean up extracted files and this script
if exist "{extract_str}" rmdir /s /q "{extract_str}" 2>nul
del "%~f0" 2>nul
"""
        
        script.write_text(batch_content, encoding='utf-8')
        return script
    
    def extract_update_zip(self, zip_path: Path) -> Optional[Path]:
        """
        Extract ZIP file to cache directory.
        Returns path to extracted NOTG-Launcher folder or None on failure.
        """
        try:
            extract_dir = self.cache_dir / "extracted"
            if extract_dir.exists():
                shutil.rmtree(extract_dir)
            extract_dir.mkdir(parents=True, exist_ok=True)
            
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(extract_dir)
            
            # Find NOTG-Launcher folder in extracted content
            launcher_folder = extract_dir / "NOTG-Launcher"
            if launcher_folder.exists():
                return launcher_folder
            
            # Try finding it if wrapped in another folder
            for item in extract_dir.iterdir():
                if item.is_dir() and "NOTG-Launcher" in item.name:
                    return item
            
            print(f"Could not find NOTG-Launcher folder in extracted ZIP")
            return None
        except Exception as e:
            print(f"ZIP extraction failed: {e}")
            return None
    
    def apply_update(self, zip_path: Path) -> bool:
        """
        Start update process: extract ZIP and launch batch script.
        Returns True if update started successfully.
        """
        try:
            if not zip_path.exists():
                print(f"Update file not found: {zip_path}")
                return False
            
            # Verify ZIP before attempting update
            if not self.verify_download(zip_path):
                print(f"Invalid or corrupted update file: {zip_path}")
                return False
            
            script = self.create_updater_script(zip_path)
            
            # Launch batch script detached from this process
            subprocess.Popen(
                str(script),
                shell=True,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            )
            return True
        except Exception as e:
            print(f"Failed to apply update: {e}")
            return False
    
    def cleanup_cache(self):
        """Remove old files from cache."""
        try:
            for file in self.cache_dir.glob("NOTG-Launcher-*.zip"):
                file.unlink()
            for file in self.cache_dir.glob("*.bat"):
                file.unlink()
            # Clean extracted folder
            extracted = self.cache_dir / "extracted"
            if extracted.exists():
                shutil.rmtree(extracted, ignore_errors=True)
        except Exception as e:
            print(f"Cleanup error: {e}")


class UpdateState:
    """Tracks update check state in local config."""
    
    def __init__(self, state_file: Path):
        self.state_file = state_file
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
    
    def get_state(self) -> Dict[str, Any]:
        """Load current state."""
        try:
            if self.state_file.exists():
                return json.loads(self.state_file.read_text(encoding='utf-8'))
        except Exception:
            pass
        return {
            "last_check": None,
            "available_version": None,
            "release_notes": None,
            "download_url": None,
            "downloaded_path": None,
        }
    
    def save_state(self, state: Dict[str, Any]):
        """Save state."""
        try:
            self.state_file.write_text(json.dumps(state, indent=2), encoding='utf-8')
        except Exception as e:
            print(f"Failed to save state: {e}")
