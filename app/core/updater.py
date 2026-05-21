"""
Auto-updater service for NOTG Launcher.
Checks GitHub releases and manages updates.
"""

import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Optional, Tuple, Dict, Any
import requests


UPDATER_EXE_NAME = "NOTG Updater.exe"
UPDATER_RUNTIME_DIR_NAME = "updater-runtime"
UPDATE_MANIFEST_NAME = "update_manifest.json"


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
    
    def create_update_manifest(self, zip_path: Path) -> Path:
        """Write the update handoff manifest consumed by the Python updater."""
        layout = self._inspect_release_zip(zip_path)
        if layout is None:
            raise RuntimeError("Update ZIP does not contain a launcher executable and _internal folder.")

        package_root, package_exe_name = layout
        manifest = self.cache_dir / UPDATE_MANIFEST_NAME
        payload = {
            "zip_path": str(zip_path.resolve()),
            "cache_dir": str(self.cache_dir),
            "install_dir": str(self.installation_dir),
            "current_exe": str(self.current_exe),
            "expected_exe_name": self.expected_exe_name,
            "expected_install_dir_name": self.expected_install_dir_name,
            "package_root": [part for part in package_root.parts if part not in {"", "."}],
            "package_exe_name": package_exe_name,
            "launcher_pid": os.getpid(),
            "schema_version": 1,
        }
        manifest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return manifest

    def _stage_updater_process(self, manifest_path: Path) -> tuple[list[str], Path]:
        """
        Stage a silent updater runtime outside the install directory.

        Windows keeps running executables locked, so the updater cannot execute
        from the folder it is about to replace.
        """
        runtime_dir = self.cache_dir / UPDATER_RUNTIME_DIR_NAME
        if runtime_dir.exists():
            shutil.rmtree(runtime_dir, ignore_errors=True)
        runtime_dir.mkdir(parents=True, exist_ok=True)

        bundled_updater = self.installation_dir / UPDATER_EXE_NAME
        if bundled_updater.is_file():
            staged_updater = runtime_dir / UPDATER_EXE_NAME
            shutil.copy2(bundled_updater, staged_updater)
            return [str(staged_updater), "--manifest", str(manifest_path)], runtime_dir

        if getattr(sys, "frozen", False):
            staged_exe = runtime_dir / self.current_exe.name
            shutil.copy2(self.current_exe, staged_exe)
            internal_dir = self.installation_dir / "_internal"
            if internal_dir.is_dir():
                shutil.copytree(internal_dir, runtime_dir / "_internal", dirs_exist_ok=True)
            return [str(staged_exe), "--run-updater", str(manifest_path)], runtime_dir

        project_root = Path(__file__).resolve().parents[2]
        python = Path(sys.executable)
        if sys.platform == "win32":
            pythonw = python.with_name("pythonw.exe")
            if pythonw.is_file():
                python = pythonw
        return [str(python), str(project_root / "app" / "main.py"), "--run-updater", str(manifest_path)], project_root

    @staticmethod
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
        Start update process by launching a detached Python updater.
        Returns True if update started successfully.
        """
        try:
            if not zip_path.exists():
                print(f"Update file not found: {zip_path}")
                return False
            
            if not self.verify_download(zip_path):
                print(f"Invalid or corrupted update file: {zip_path}")
                return False
            
            manifest = self.create_update_manifest(zip_path)
            command, cwd = self._stage_updater_process(manifest)
            self._hidden_popen(command, cwd=cwd)
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
        for path in (self.cache_dir / "extracted", self.cache_dir / "staged", self.cache_dir / UPDATER_RUNTIME_DIR_NAME):
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
            python_log = self.cache_dir / "updater-python.log"
            if python_log.exists():
                python_log.unlink()
            manifest = self.cache_dir / UPDATE_MANIFEST_NAME
            if manifest.exists():
                manifest.unlink()
            extracted = self.cache_dir / "extracted"
            if extracted.exists():
                shutil.rmtree(extracted, ignore_errors=True)
            staged = self.cache_dir / "staged"
            if staged.exists():
                shutil.rmtree(staged, ignore_errors=True)
            updater_runtime = self.cache_dir / UPDATER_RUNTIME_DIR_NAME
            if updater_runtime.exists():
                shutil.rmtree(updater_runtime, ignore_errors=True)
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
