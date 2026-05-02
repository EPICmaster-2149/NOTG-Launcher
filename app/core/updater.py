"""
Auto-updater service for NOTG Launcher.
Checks GitHub releases and manages updates.
"""

import json
import shutil
import subprocess
import zipfile
from pathlib import Path, PurePosixPath
from typing import Optional, Tuple, Dict, Any
import requests


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
        zip_assets = [asset for asset in assets if str(asset.get('name', '')).lower().endswith('.zip')]
        if not zip_assets:
            return None

        def score(asset: Dict[str, Any]) -> tuple[int, int]:
            name = str(asset.get('name', '')).lower()
            rank = 0
            repo_name = self.github_repo.lower()
            if repo_name in name:
                rank += 100
            if "launcher" in name:
                rank += 40
            if "windows" in name or "win" in name:
                rank += 10
            return (rank, int(asset.get('size') or 0))

        best_asset = max(zip_assets, key=score)
        return str(best_asset.get('browser_download_url') or "")
    
    def get_release_notes(self, latest_release: Dict[str, Any]) -> str:
        """Get formatted release notes."""
        body = latest_release.get('body', '')
        if not body:
            return "No release notes provided."
        return body


class UpdateInstaller:
    """Handles downloading and installing updates."""
    
    def __init__(self, current_exe_path: str, cache_dir: str):
        self.current_exe = Path(current_exe_path).resolve()
        self.installation_dir = self.current_exe.parent
        self.cache_dir = Path(cache_dir).resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.expected_exe_name = self.current_exe.name
        self.expected_install_dir_name = self.installation_dir.name

    @property
    def _download_zip_path(self) -> Path:
        return self.cache_dir / f"{self.expected_install_dir_name}-update.zip"

    @staticmethod
    def _zip_prefix(root: PurePosixPath, child: str = "") -> str:
        parts = [part for part in root.parts if part not in {"", "."}]
        if child:
            parts.append(child)
        return "/".join(parts)

    def _inspect_release_members(self, names: list[str]) -> Optional[tuple[PurePosixPath, str]]:
        normalized = [name.rstrip("/") for name in names if name and name.rstrip("/")]
        candidates: list[tuple[int, PurePosixPath, str]] = []
        seen: set[tuple[str, str]] = set()

        for name in normalized:
            path = PurePosixPath(name)
            if not path.name.lower().endswith(".exe"):
                continue

            root = path.parent
            candidate_key = (str(root), path.name.lower())
            if candidate_key in seen:
                continue
            seen.add(candidate_key)

            internal_prefix = self._zip_prefix(root, "_internal")
            has_internal = any(
                entry == internal_prefix or entry.startswith(f"{internal_prefix}/")
                for entry in normalized
            ) if internal_prefix else any(
                entry == "_internal" or entry.startswith("_internal/")
                for entry in normalized
            )
            if not has_internal:
                continue

            score = 10
            if path.name.lower() == self.expected_exe_name.lower():
                score += 100
            root_name = root.name.lower() if str(root) not in {"", "."} else ""
            if root_name == self.expected_install_dir_name.lower():
                score += 20
            if str(root) in {"", "."}:
                score += 5
            candidates.append((score, root, path.name))

        if not candidates:
            return None

        candidates.sort(key=lambda item: item[0], reverse=True)
        _, package_root, exe_name = candidates[0]
        return package_root, exe_name

    def _inspect_release_zip(self, zip_path: Path) -> Optional[tuple[PurePosixPath, str]]:
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                return self._inspect_release_members(zf.namelist())
        except zipfile.BadZipFile:
            return None
    
    def download_update(self, download_url: str, progress_callback=None):
        """
        Download update ZIP to cache (contains exe + _internal folder).
        Calls progress_callback(percentage) during download.
        Returns path to downloaded ZIP file or None on failure.
        """
        try:
            self.cleanup_cache()
            new_zip = self._download_zip_path
            
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
        
        size = zip_path.stat().st_size
        if size < 1000000:
            return False
        
        return self._inspect_release_zip(zip_path) is not None
    
    def create_updater_script(self, zip_path: Path) -> Path:
        """
        Create a detached batch updater that mirrors the original working flow:
        extract the release, rename the current install to .old, move the new
        root folder into place, launch it, then clean up.
        """
        layout = self._inspect_release_zip(zip_path)
        if layout is None:
            raise RuntimeError("Update ZIP does not contain a launcher executable and _internal folder.")

        package_root, package_exe_name = layout
        package_root_parts = [part for part in package_root.parts if part not in {"", "."}]
        package_relative = "\\".join(package_root_parts)

        script = self.cache_dir / "updater.bat"
        extract_dir = self.cache_dir / "extracted"
        log_path = self.cache_dir / "updater.log"
        backup_dir = self.installation_dir.with_name(self.installation_dir.name + ".old")
        backup_name = backup_dir.name

        if package_relative:
            package_set_line = f'set "PACKAGE=%EXTRACT%\\{package_relative}"'
        else:
            package_set_line = 'set "PACKAGE=%EXTRACT%"'

        batch_content = f"""@echo off
chcp 65001 >nul
setlocal

set "ZIP={zip_path}"
set "CACHE={self.cache_dir}"
set "EXTRACT={extract_dir}"
set "INSTALL={self.installation_dir}"
set "EXE={self.current_exe}"
set "BACKUP={backup_dir}"
set "BACKUP_NAME={backup_name}"
set "EXPECTED_EXE={self.expected_exe_name}"
set "PACKAGE_EXE={package_exe_name}"
set "LOG={log_path}"
{package_set_line}

break > "%LOG%"
call :log Updater started.
cd /d "%CACHE%"

ping 127.0.0.1 -n 4 >nul

call :log Extracting update archive.
if exist "%EXTRACT%" rmdir /s /q "%EXTRACT%" >>"%LOG%" 2>&1
mkdir "%EXTRACT%" >>"%LOG%" 2>&1
if errorlevel 1 goto fail

powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath $env:ZIP -DestinationPath $env:EXTRACT -Force" >>"%LOG%" 2>&1
if errorlevel 1 (
    call :log PowerShell extraction failed. Trying tar fallback.
    tar -xf "%ZIP%" -C "%EXTRACT%" >>"%LOG%" 2>&1
    if errorlevel 1 goto fail_extract
)

if not exist "%PACKAGE%\\%PACKAGE_EXE%" goto fail_layout
if not exist "%PACKAGE%\\_internal" goto fail_layout

if /I not "%PACKAGE_EXE%"=="%EXPECTED_EXE%" (
    call :log Renaming executable to installed launcher name.
    ren "%PACKAGE%\\%PACKAGE_EXE%" "%EXPECTED_EXE%" >>"%LOG%" 2>&1
    if errorlevel 1 goto fail
)

call :log Backing up current installation.
if exist "%BACKUP%" rmdir /s /q "%BACKUP%" >>"%LOG%" 2>&1
if exist "%INSTALL%" (
    ren "%INSTALL%" "%BACKUP_NAME%" >>"%LOG%" 2>&1
    if errorlevel 1 goto fail
)

call :log Moving updated launcher into place.
move /Y "%PACKAGE%" "%INSTALL%" >>"%LOG%" 2>&1
if errorlevel 1 goto rollback

if not exist "%EXE%" goto rollback

call :log Launching updated launcher.
start "" /D "%INSTALL%" "%EXE%"

call :log Cleaning old install and updater files.
call :retry_rmdir "%BACKUP%"
if exist "%EXTRACT%" rmdir /s /q "%EXTRACT%" >>"%LOG%" 2>&1
if exist "%ZIP%" del /f /q "%ZIP%" >>"%LOG%" 2>&1

call :log Updater completed successfully.
if exist "%LOG%" del /f /q "%LOG%" >nul 2>&1
set "SELF=%~f0"
start "" /min powershell.exe -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Remove-Item -LiteralPath $env:SELF -Force -ErrorAction SilentlyContinue"
exit /b 0

:rollback
call :log Update failed after backup. Restoring previous install.
if exist "%INSTALL%" rmdir /s /q "%INSTALL%" >>"%LOG%" 2>&1
if exist "%BACKUP%" ren "%BACKUP%" "{self.installation_dir.name}" >>"%LOG%" 2>&1
goto fail

:fail_extract
call :log Extraction failed.
goto fail

:fail_layout
call :log Extracted update layout was not valid.
call :log Expected package path: %PACKAGE%
goto fail

:fail
call :log Updater failed. Leaving ZIP, BAT, and log for diagnosis.
exit /b 1

:retry_rmdir
set "TARGET=%~1"
for /L %%I in (1,1,20) do (
    if not exist "%TARGET%" exit /b 0
    rmdir /s /q "%TARGET%" >>"%LOG%" 2>&1
    if not exist "%TARGET%" exit /b 0
    ping 127.0.0.1 -n 2 >nul
)
exit /b 0

:log
echo %date% %time% %*>>"%LOG%"
exit /b 0
"""

        script.write_text(batch_content, encoding="utf-8")
        return script
    
    def extract_update_zip(self, zip_path: Path) -> Optional[Path]:
        """
        Extract ZIP file to cache directory.
        Returns the extracted package directory or root.
        """
        try:
            layout = self._inspect_release_zip(zip_path)
            if layout is None:
                return None

            extract_dir = self.cache_dir / "extracted"
            if extract_dir.exists():
                shutil.rmtree(extract_dir)
            extract_dir.mkdir(parents=True, exist_ok=True)
            
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(extract_dir)

            package_root, _ = layout
            if str(package_root) in {"", "."}:
                return extract_dir
            return extract_dir.joinpath(*package_root.parts)
        except Exception as e:
            print(f"ZIP extraction failed: {e}")
            return None
    
    def apply_update(self, zip_path: Path) -> bool:
        """
        Start update process by launching a detached batch updater.
        Returns True if update started successfully.
        """
        try:
            if not zip_path.exists():
                print(f"Update file not found: {zip_path}")
                return False
            
            if not self.verify_download(zip_path):
                print(f"Invalid or corrupted update file: {zip_path}")
                return False
            
            script = self.create_updater_script(zip_path)
            creationflags = 0
            for flag_name in ("CREATE_NEW_PROCESS_GROUP", "DETACHED_PROCESS", "CREATE_NO_WINDOW"):
                creationflags |= int(getattr(subprocess, flag_name, 0))

            subprocess.Popen(
                [
                    "cmd.exe",
                    "/c",
                    str(script),
                ],
                close_fds=True,
                creationflags=creationflags,
                cwd=str(self.cache_dir),
            )
            return True
        except Exception as e:
            print(f"Failed to apply update: {e}")
            return False

    def cleanup_stale_update_artifacts(self):
        """
        Best-effort cleanup for safe leftovers from previous update attempts.

        Do not remove update ZIPs, scripts, or logs here. If an update failed,
        the next manual launch should keep those files available for retry and
        diagnosis instead of silently discarding them.
        """
        for path in (self.cache_dir / "extracted", self.cache_dir / "staged"):
            try:
                if path.exists():
                    shutil.rmtree(path, ignore_errors=True)
            except Exception:
                # Leftovers may still be locked by Windows during startup.
                pass

        backup_pattern = f"{self.expected_install_dir_name}.old*"
        for path in self.installation_dir.parent.glob(backup_pattern):
            try:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                elif path.exists():
                    path.unlink(missing_ok=True)
            except Exception:
                # Backup cleanup is best-effort; update retry files are preserved.
                pass
    
    def cleanup_cache(self):
        """Remove old files from cache."""
        try:
            for file in self.cache_dir.glob("*-update.zip"):
                file.unlink()
            for file in self.cache_dir.glob("*.ps1"):
                file.unlink()
            for file in self.cache_dir.glob("*.bat"):
                file.unlink()
            for file in self.cache_dir.glob("updater*.log"):
                file.unlink()
            extracted = self.cache_dir / "extracted"
            if extracted.exists():
                shutil.rmtree(extracted, ignore_errors=True)
            staged = self.cache_dir / "staged"
            if staged.exists():
                shutil.rmtree(staged, ignore_errors=True)
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
