from __future__ import annotations

import configparser
import gzip
import hashlib
import ipaddress
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import tomllib
import traceback
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import urlparse

import psutil
from platformdirs import PlatformDirs

try:
    from version import APP_VERSION
except ImportError:  # pragma: no cover - defensive for isolated imports
    APP_VERSION = "0.0.0"


EXPERIMENT_TYPES = {
    "experiment",
    "experimental",
    "experiments",
}

KNOWN_VERSION_TYPES = {
    "release",
    "snapshot",
    "old_beta",
    "old_alpha",
}

IMPORTANT_MINECRAFT_MARKERS = (
    "mods",
    "config",
    "resourcepacks",
    "shaderpacks",
    "saves",
    "options.txt",
    "servers.dat",
    "logs",
    "crash-reports",
)

REQUIRED_IMPORT_MARKERS = (
    "saves",
    "mods",
    "options.txt",
)

EXCLUDED_COPY_NAMES = {
    "assets",
    "bin",
    "crash-reports",
    "downloads",
    "launcher_accounts.json",
    "launcher_profiles.json",
    "libraries",
    "logs",
    "natives",
    "runtime",
    "tmp",
    "versions",
    "webcache",
}

EXCLUDED_COPY_SUFFIXES = (
    ".log",
    ".tmp",
)

DEFAULT_MEMORY_MB = 2048

ARCHIVE_ICON_CANDIDATES = (
    "icon.png",
    "pack.png",
    "instance.png",
    "logo.png",
    ".minecraft/icon.png",
    ".minecraft/pack.png",
    "overrides/icon.png",
    "overrides/pack.png",
    "client-overrides/icon.png",
    "client-overrides/pack.png",
)

MMCPACK_LOADER_UIDS = {
    "net.minecraftforge": "forge",
    "net.fabricmc.fabric-loader": "fabric",
    "org.quiltmc.quilt-loader": "quilt",
    "net.neoforged.neoforge": "neoforge",
    "net.neoforged": "neoforge",
}

APP_NAME = "NOTG Launcher"
USER_ICON_PREFIX = "user-icons"
USER_BACKGROUND_PREFIX = "user-backgrounds"
USER_MUSIC_PREFIX = "user-music"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
VIDEO_SUFFIXES = {".mp4", ".m4v", ".mov", ".avi", ".mkv", ".webm", ".wmv"}
BACKGROUND_SUFFIXES = IMAGE_SUFFIXES | VIDEO_SUFFIXES
MUSIC_SUFFIXES = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus", ".wma"}
BACKGROUND_FILE_NAME = "active-background"
MUSIC_FILE_NAME = "music"
JAVA_DOWNLOAD_URL = "https://www.oracle.com/in/java/technologies/downloads/#java25"
UNSET = object()
SESSION_STATUS_TO_INSTANCE_STATUS = {
    "launching": "Launching",
    "running": "Launched",
    "finished": "Quit",
    "stopped": "Quit",
    "crashed": "Crashed",
}


class _LazyModuleProxy:
    def __init__(self, module_name: str):
        self._module_name = module_name
        self._module = None

    def _load(self):
        if self._module is None:
            self._module = __import__(self._module_name)
        return self._module

    def __getattr__(self, name: str) -> Any:
        return getattr(self._load(), name)


minecraft_launcher_lib = _LazyModuleProxy("minecraft_launcher_lib")


@dataclass(slots=True)
class IconRecord:
    icon_id: str
    name: str
    relative_path: str
    absolute_path: str
    is_default: bool


@dataclass(slots=True)
class BackgroundRecord:
    background_id: str
    name: str
    relative_path: str
    absolute_path: str
    is_default: bool
    is_video: bool


@dataclass(slots=True)
class MusicRecord:
    music_id: str
    name: str
    relative_path: str
    absolute_path: str
    is_default: bool
    enabled: bool = True


@dataclass(slots=True)
class JavaRuntimeCandidate:
    executable_path: str
    major_version: int
    label: str


class JavaCompatibilityError(RuntimeError):
    """Raised when no installed Java runtime can launch the selected Minecraft version."""


@dataclass(slots=True)
class InstanceRecord:
    instance_id: str
    name: str
    vanilla_version: str
    installed_version: str
    mod_loader_id: str | None
    mod_loader_version: str | None
    icon_path: str
    created_at: str
    last_played: str | None
    root_dir: Path
    minecraft_dir: Path
    memory_mb: int = DEFAULT_MEMORY_MB
    total_played_seconds: int = 0
    rich_presence_enabled: bool = True
    rich_presence_state: str | None = None
    rich_presence_details: str | None = None
    rich_presence_adaptive_details: bool = True
    status: str = "Quit"
    pid: int | None = None

    @property
    def version_label(self) -> str:
        return f"Version {self.vanilla_version} | {self.loader_name}"

    @property
    def compact_version_label(self) -> str:
        return f"Version {self.vanilla_version} | {self.loader_name}"

    @property
    def loader_name(self) -> str:
        if not self.mod_loader_id:
            return "Vanilla"
        return minecraft_launcher_lib.mod_loader.get_mod_loader(self.mod_loader_id).get_name()

    def to_metadata(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "name": self.name,
            "vanilla_version": self.vanilla_version,
            "installed_version": self.installed_version,
            "mod_loader_id": self.mod_loader_id,
            "mod_loader_version": self.mod_loader_version,
            "icon_path": self.icon_path,
            "created_at": self.created_at,
            "last_played": self.last_played,
            "memory_mb": self.memory_mb,
            "total_played_seconds": self.total_played_seconds,
            "rich_presence_enabled": self.rich_presence_enabled,
            "rich_presence_state": self.rich_presence_state,
            "rich_presence_details": self.rich_presence_details,
            "rich_presence_adaptive_details": self.rich_presence_adaptive_details,
        }

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any], root_dir: Path) -> "InstanceRecord":
        icon_path = str(metadata.get("icon_path", "assets/default-instance-icons/Grass Block.png"))
        return cls(
            instance_id=str(metadata["instance_id"]),
            name=str(metadata["name"]),
            vanilla_version=str(metadata["vanilla_version"]),
            installed_version=str(metadata["installed_version"]),
            mod_loader_id=_optional_str(metadata.get("mod_loader_id")),
            mod_loader_version=_optional_str(metadata.get("mod_loader_version")),
            icon_path=icon_path,
            created_at=str(metadata.get("created_at", _utc_now())),
            last_played=_optional_str(metadata.get("last_played")),
            memory_mb=_coerce_memory_mb(metadata.get("memory_mb")),
            total_played_seconds=_coerce_non_negative_int(metadata.get("total_played_seconds")),
            rich_presence_enabled=bool(metadata.get("rich_presence_enabled", True)),
            rich_presence_state=_optional_str(metadata.get("rich_presence_state")),
            rich_presence_details=_optional_str(metadata.get("rich_presence_details")),
            rich_presence_adaptive_details=bool(metadata.get("rich_presence_adaptive_details", True)),
            root_dir=root_dir,
            minecraft_dir=root_dir / ".minecraft",
        )


@dataclass(slots=True)
class InstallRequest:
    instance_id: str
    name: str
    vanilla_version: str | None
    mod_loader_id: str | None
    mod_loader_version: str | None
    icon_path: str
    stage_dir: str
    final_dir: str
    minecraft_dir: str
    memory_mb: int = DEFAULT_MEMORY_MB
    operation: str = "create"
    modpack_path: str | None = None
    minecraft_import_dir: str | None = None
    copy_source_instance_id: str | None = None
    copy_user_data: list[str] | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "name": self.name,
            "vanilla_version": self.vanilla_version,
            "mod_loader_id": self.mod_loader_id,
            "mod_loader_version": self.mod_loader_version,
            "icon_path": self.icon_path,
            "stage_dir": self.stage_dir,
            "final_dir": self.final_dir,
            "minecraft_dir": self.minecraft_dir,
            "memory_mb": self.memory_mb,
            "operation": self.operation,
            "modpack_path": self.modpack_path,
            "minecraft_import_dir": self.minecraft_import_dir,
            "copy_source_instance_id": self.copy_source_instance_id,
            "copy_user_data": list(self.copy_user_data or []),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "InstallRequest":
        return cls(
            instance_id=str(payload["instance_id"]),
            name=str(payload["name"]),
            vanilla_version=_optional_str(payload.get("vanilla_version")),
            mod_loader_id=_optional_str(payload.get("mod_loader_id")),
            mod_loader_version=_optional_str(payload.get("mod_loader_version")),
            icon_path=str(payload["icon_path"]),
            stage_dir=str(payload["stage_dir"]),
            final_dir=str(payload["final_dir"]),
            minecraft_dir=str(payload["minecraft_dir"]),
            memory_mb=_coerce_memory_mb(payload.get("memory_mb")),
            operation=str(payload.get("operation", "create")),
            modpack_path=_optional_str(payload.get("modpack_path")),
            minecraft_import_dir=_optional_str(payload.get("minecraft_import_dir")),
            copy_source_instance_id=_optional_str(payload.get("copy_source_instance_id")),
            copy_user_data=_coerce_str_list(payload.get("copy_user_data")),
        )


@dataclass(slots=True)
class InstallResult:
    name: str
    vanilla_version: str
    installed_version: str
    mod_loader_id: str | None
    mod_loader_version: str | None
    icon_path: str | None = None
    staged_icon_path: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "vanilla_version": self.vanilla_version,
            "installed_version": self.installed_version,
            "mod_loader_id": self.mod_loader_id,
            "mod_loader_version": self.mod_loader_version,
            "icon_path": self.icon_path,
            "staged_icon_path": self.staged_icon_path,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "InstallResult":
        return cls(
            name=str(payload["name"]),
            vanilla_version=str(payload["vanilla_version"]),
            installed_version=str(payload["installed_version"]),
            mod_loader_id=_optional_str(payload.get("mod_loader_id")),
            mod_loader_version=_optional_str(payload.get("mod_loader_version")),
            icon_path=_optional_str(payload.get("icon_path")),
            staged_icon_path=_optional_str(payload.get("staged_icon_path")),
        )


class LauncherService:
    def __init__(self, project_root: Path | None = None):
        if hasattr(sys, '_MEIPASS'):
            self.project_root = Path(sys._MEIPASS)
        else:
            self.project_root = project_root or Path(__file__).resolve().parents[2]
        self.install_root = self.project_root
        self.assets_root = self.project_root / "assets"
        self.default_icons_root = self.assets_root / "default-instance-icons"
        self.legacy_user_icons_root = self.project_root / "app" / "icons"
        self.legacy_instances_root = self.project_root / "instances"

        dirs = PlatformDirs(appname=APP_NAME, appauthor=False, ensure_exists=False)
        self.data_root = Path(dirs.user_data_dir).resolve()
        self.config_root = Path(dirs.user_config_dir).resolve()
        self.cache_root = Path(dirs.user_cache_dir).resolve()
        self.accounts_file = self.config_root / "accounts.json"
        self.background_settings_file = self.config_root / "background.json"
        self.music_settings_file = self.config_root / "music.json"
        self.user_icons_root = self.data_root / "icons"
        self.user_music_root = self.data_root / "MUSIC"
        self.instances_root = self.data_root / "instances"
        self.runtime_root = self.data_root / "runtime"
        self.staging_root = self.runtime_root / "staging"
        self.sessions_root = self.runtime_root / "sessions"
        self.launcher_ipc_file = self.runtime_root / "launcher-ipc.json"
        self.logs_root = Path(dirs.user_log_dir).resolve()
        self.backgrounds_root = self.data_root / "backgrounds"
        self.default_background_root = self.assets_root / "default-background"
        self.default_music_root = self.assets_root / "default-musics"
        self.legacy_default_music_root = self.assets_root / "deafult-musics"
        self.generated_icons_root = self.cache_root / "generated-icons"
        self.default_icon = "assets/default-instance-icons/Grass Block.png"
        self._server_resolution_cache: dict[tuple[str, int | None], set[str]] = {}

        for path in (
            self.data_root,
            self.config_root,
            self.cache_root,
            self.user_icons_root,
            self.user_music_root,
            self.instances_root,
            self.runtime_root,
            self.staging_root,
            self.sessions_root,
            self.logs_root,
            self.generated_icons_root,
        ):
            path.mkdir(parents=True, exist_ok=True)

        self._bootstrap_legacy_storage()
        self._ensure_account_store()

        self._version_cache: list[dict[str, Any]] | None = None
        self._loader_support_cache: dict[str, set[str]] = {}
        self._loader_versions_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def get_player_name(self) -> str:
        return self._read_accounts_payload()["active"]

    def list_accounts(self) -> list[str]:
        return list(self._read_accounts_payload()["accounts"])

    def set_active_account(self, player_name: str) -> str:
        normalized = self._normalize_account_name(player_name)
        payload = self._read_accounts_payload()
        if normalized not in payload["accounts"]:
            raise ValueError("That account does not exist.")
        payload["active"] = normalized
        self._write_accounts_payload(payload)
        return normalized

    def add_account(self, player_name: str) -> str:
        normalized = self._normalize_account_name(player_name)
        payload = self._read_accounts_payload()
        if normalized.lower() in {name.lower() for name in payload["accounts"]}:
            raise ValueError("That account already exists.")
        payload["accounts"].append(normalized)
        payload["active"] = normalized
        payload["accounts"].sort(key=str.lower)
        self._write_accounts_payload(payload)
        return normalized

    def delete_account(self, player_name: str) -> str:
        normalized = self._normalize_account_name(player_name)
        payload = self._read_accounts_payload()
        if normalized not in payload["accounts"]:
            raise ValueError("That account does not exist.")
        if len(payload["accounts"]) == 1:
            raise ValueError("At least one account must remain.")

        payload["accounts"] = [name for name in payload["accounts"] if name != normalized]
        if payload["active"] == normalized:
            payload["active"] = payload["accounts"][0]
        self._write_accounts_payload(payload)
        return payload["active"]

    def get_default_icon_path(self) -> str:
        return str((self.project_root / self.default_icon).resolve())

    def icons_folder(self) -> Path:
        return self.user_icons_root

    def list_instance_icons(self) -> list[IconRecord]:
        icons: list[IconRecord] = []
        default_path = self.resolve_icon_path(self.default_icon)
        default_key = str(Path(default_path).resolve())

        default_candidates = sorted(
            self.default_icons_root.glob("*.png"),
            key=lambda item: (0 if str(item.resolve()) == default_key else 1, item.name.lower()),
        )
        for path in default_candidates:
            relative_path = self._project_relative(path)
            icons.append(
                IconRecord(
                    icon_id=relative_path,
                    name=path.stem,
                    relative_path=relative_path,
                    absolute_path=str(path.resolve()),
                    is_default=True,
                )
            )

        user_candidates = sorted(self.user_icons_root.glob("*.png"), key=lambda item: item.name.lower())
        for path in user_candidates:
            relative_path = self._user_icon_reference(path)
            icons.append(
                IconRecord(
                    icon_id=relative_path,
                    name=path.stem,
                    relative_path=relative_path,
                    absolute_path=str(path.resolve()),
                    is_default=False,
                )
            )

        return icons

    def store_user_icon(self, source_path: str | Path, preferred_name: str | None = None) -> str:
        source = Path(source_path)
        if not source.is_file():
            raise FileNotFoundError(f"Icon file not found: {source}")

        safe_name = _slugify(preferred_name or source.stem) or "icon"
        target = self._unique_icon_path(safe_name, ".png")
        shutil.copy2(source, target)
        return self._user_icon_reference(target)

    def promote_staged_icon(self, staged_icon_path: str | Path, preferred_name: str | None = None) -> str:
        staged = Path(staged_icon_path)
        if not staged.is_file():
            raise FileNotFoundError(f"Missing staged icon: {staged}")

        suffix = staged.suffix.lower() if staged.suffix else ".png"
        if suffix != ".png":
            suffix = ".png"
        safe_name = _slugify(preferred_name or staged.stem) or "icon"
        target = self._unique_icon_path(safe_name, suffix)
        shutil.copy2(staged, target)
        return self._user_icon_reference(target)

    def remove_user_icon(self, icon_path: str | Path) -> bool:
        icon = Path(self.resolve_icon_path(str(icon_path)))
        try:
            icon.relative_to(self.user_icons_root.resolve())
        except ValueError:
            return False

        if not icon.is_file():
            return False
        icon.unlink()
        return True

    def resolve_icon_path(self, icon_path: str | None) -> str:
        default_icon_path = (self.project_root / self.default_icon).resolve()
        if not icon_path:
            return str(default_icon_path)

        normalized = str(icon_path).replace("\\", "/")
        if normalized.startswith(f"{USER_ICON_PREFIX}/"):
            relative = normalized[len(USER_ICON_PREFIX) + 1 :]
            resolved_icon = (self.user_icons_root / relative).resolve()
        else:
            icon = Path(normalized)
            if icon.is_absolute():
                resolved_icon = icon
            else:
                resolved_icon = (self.project_root / icon).resolve()

        if resolved_icon.is_file():
            return str(resolved_icon)
        return str(default_icon_path)

    def is_valid_minecraft_dir(self, path: str | Path) -> tuple[bool, str]:
        if self.resolve_minecraft_import_source(path) is not None:
            return True, ""
        return (
            False,
            "Select a folder that contains `saves`, `mods`, and `options.txt`, or a folder whose `.minecraft` child does.",
        )

    def resolve_minecraft_import_source(self, path: str | Path) -> Path | None:
        candidate = Path(path)
        if not candidate.is_dir():
            return None

        for probe in (candidate, candidate / ".minecraft"):
            if not probe.is_dir():
                continue
            if all((probe / marker).exists() for marker in REQUIRED_IMPORT_MARKERS):
                return probe
        return None

    def get_instance(self, instance_id: str) -> InstanceRecord | None:
        for instance in self.load_instances():
            if instance.instance_id == instance_id:
                return instance
        return None

    def list_copyable_user_data(self, instance_id: str) -> list[dict[str, str]]:
        instance = self.get_instance(instance_id)
        if instance is None or not instance.minecraft_dir.is_dir():
            return []

        entries: list[dict[str, str]] = []
        for entry in sorted(instance.minecraft_dir.iterdir(), key=lambda item: item.name.lower()):
            name = entry.name
            lowered = name.lower()
            if lowered in EXCLUDED_COPY_NAMES or name.startswith("."):
                continue
            if any(lowered.endswith(suffix) for suffix in EXCLUDED_COPY_SUFFIXES):
                continue

            label = _format_copy_entry_label(entry)
            entries.append(
                {
                    "path": name,
                    "label": label,
                    "kind": "folder" if entry.is_dir() else "file",
                }
            )
        return entries

    def load_instances(self) -> list[InstanceRecord]:
        runtime_sessions = self.list_runtime_sessions()
        instances: list[InstanceRecord] = []
        for instance_dir in sorted(self.instances_root.iterdir(), key=lambda item: item.name.lower()):
            metadata_path = instance_dir / "instance.json"
            if not metadata_path.is_file():
                continue

            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                instance = InstanceRecord.from_metadata(metadata, instance_dir)
                instance.icon_path = self.resolve_icon_path(instance.icon_path)
                self._apply_runtime_session(instance, runtime_sessions.get(instance.instance_id))
                instances.append(instance)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue

        instances.sort(key=lambda item: _parse_timestamp(item.created_at), reverse=True)
        return instances

    def delete_instance(self, instance: InstanceRecord) -> None:
        if instance.root_dir.exists():
            shutil.rmtree(instance.root_dir)
        self.clear_runtime_session(instance.instance_id)

    def instance_metadata_path(self, instance: InstanceRecord) -> Path:
        return instance.root_dir / "instance.json"

    def update_instance(
        self,
        instance: InstanceRecord,
        *,
        name: str | None = None,
        icon_path: str | None = None,
        memory_mb: int | None = None,
        vanilla_version: str | None = None,
        installed_version: str | None = None,
        mod_loader_id: Any = UNSET,
        mod_loader_version: Any = UNSET,
        last_played: str | None = None,
        total_played_seconds: int | None = None,
        rich_presence_enabled: bool | None = None,
        rich_presence_state: Any = UNSET,
        rich_presence_details: Any = UNSET,
        rich_presence_adaptive_details: bool | None = None,
    ) -> InstanceRecord:
        metadata_path = self.instance_metadata_path(instance)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

        if name is not None:
            normalized_name = name.strip()
            if not normalized_name:
                raise ValueError("Instance name cannot be empty.")
            metadata["name"] = normalized_name
        if icon_path is not None:
            metadata["icon_path"] = self._normalize_icon_reference(icon_path)
        if memory_mb is not None:
            metadata["memory_mb"] = _coerce_memory_mb(memory_mb)
        if vanilla_version is not None:
            metadata["vanilla_version"] = vanilla_version
        if installed_version is not None:
            metadata["installed_version"] = installed_version
        if mod_loader_id is not UNSET:
            metadata["mod_loader_id"] = mod_loader_id
        if mod_loader_version is not UNSET:
            metadata["mod_loader_version"] = mod_loader_version
        if last_played is not None:
            metadata["last_played"] = last_played
        if total_played_seconds is not None:
            metadata["total_played_seconds"] = _coerce_non_negative_int(total_played_seconds)
        if rich_presence_enabled is not None:
            metadata["rich_presence_enabled"] = bool(rich_presence_enabled)
        if rich_presence_state is not UNSET:
            metadata["rich_presence_state"] = _optional_str(rich_presence_state)
        if rich_presence_details is not UNSET:
            metadata["rich_presence_details"] = _optional_str(rich_presence_details)
        if rich_presence_adaptive_details is not None:
            metadata["rich_presence_adaptive_details"] = bool(rich_presence_adaptive_details)

        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        refreshed = InstanceRecord.from_metadata(metadata, instance.root_dir)
        refreshed.icon_path = self.resolve_icon_path(refreshed.icon_path)
        return refreshed

    def rename_instance(self, instance: InstanceRecord, new_name: str) -> InstanceRecord:
        return self.update_instance(instance, name=new_name)

    def set_instance_icon(self, instance: InstanceRecord, icon_path: str) -> InstanceRecord:
        return self.update_instance(instance, icon_path=icon_path)

    def set_instance_memory(self, instance: InstanceRecord, memory_mb: int) -> InstanceRecord:
        return self.update_instance(instance, memory_mb=memory_mb)

    def set_instance_rich_presence(
        self,
        instance: InstanceRecord,
        *,
        enabled: bool,
        state: str | None,
        details: str | None,
        adaptive_details: bool | None = None,
    ) -> InstanceRecord:
        changes: dict[str, Any] = {
            "rich_presence_enabled": enabled,
            "rich_presence_state": state,
            "rich_presence_details": details,
        }
        if adaptive_details is not None:
            changes["rich_presence_adaptive_details"] = adaptive_details
        return self.update_instance(instance, **changes)

    def build_instance_rich_presence_state(self, instance: InstanceRecord) -> str:
        return instance.rich_presence_state or "Playing Minecraft"

    def build_instance_rich_presence_details(self, instance: InstanceRecord) -> str:
        return instance.compact_version_label

    def resolve_instance_rich_presence_details(self, instance: InstanceRecord) -> str:
        if instance.rich_presence_details:
            return instance.rich_presence_details
        if instance.rich_presence_adaptive_details:
            activity = self.detect_instance_activity(instance)
            if activity:
                return activity
        return self.build_instance_rich_presence_details(instance)

    def detect_instance_activity(self, instance: InstanceRecord) -> str | None:
        log_path = self.get_instance_latest_log_path(instance)
        if not log_path.is_file():
            return None
        try:
            with log_path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - 96_000), os.SEEK_SET)
                text = handle.read().decode("utf-8", errors="replace")
        except OSError:
            return None
        server_addresses = self.get_instance_server_addresses(instance)
        return _detect_minecraft_activity_from_log(
            text,
            server_addresses=server_addresses,
            resolver=self._resolve_server_host,
        )

    def get_instance_server_addresses(self, instance: InstanceRecord) -> list[str]:
        return _read_servers_dat_addresses(instance.minecraft_dir / "servers.dat")

    def _resolve_server_host(self, host: str, port: int | None = None) -> set[str]:
        normalized_host = _normalize_server_host(host)
        if not normalized_host or _is_ip_address(normalized_host):
            return {normalized_host} if normalized_host else set()

        cache_key = (normalized_host.lower(), port)
        cached = self._server_resolution_cache.get(cache_key)
        if cached is not None:
            return set(cached)

        resolved: set[str] = set()
        try:
            for _, _, _, _, sockaddr in socket.getaddrinfo(normalized_host, port or 25565, type=socket.SOCK_STREAM):
                if sockaddr:
                    resolved.add(_normalize_server_host(str(sockaddr[0])))
        except OSError:
            resolved = set()
        self._server_resolution_cache[cache_key] = set(resolved)
        return resolved

    def duplicate_instance(self, instance: InstanceRecord, preferred_name: str | None = None) -> InstanceRecord:
        target_name = self._allocate_duplicate_name(preferred_name or f"{instance.name} Copy")
        slug = _slugify(target_name)[:40] or "instance"
        instance_id = f"{slug}-{uuid.uuid4().hex[:8]}"
        target_dir = self.instances_root / instance_id
        if target_dir.exists():
            raise FileExistsError(f"Instance directory already exists: {target_dir}")

        shutil.copytree(instance.root_dir, target_dir)
        metadata_path = target_dir / "instance.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["instance_id"] = instance_id
        metadata["name"] = target_name
        metadata["created_at"] = _utc_now()
        metadata["last_played"] = None
        metadata["total_played_seconds"] = 0
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        duplicated = InstanceRecord.from_metadata(metadata, target_dir)
        duplicated.icon_path = self.resolve_icon_path(duplicated.icon_path)
        return duplicated

    def prepare_duplicate_request(
        self,
        instance: InstanceRecord,
        *,
        preferred_name: str | None = None,
    ) -> InstallRequest:
        target_name = self._allocate_duplicate_name(preferred_name or f"{instance.name} Copy")
        slug = _slugify(target_name)[:40] or "instance"
        instance_id = f"{slug}-{uuid.uuid4().hex[:8]}"
        final_dir = self.instances_root / instance_id
        stage_dir = self.staging_root / f"{instance_id}-duplicate"
        minecraft_dir = stage_dir / ".minecraft"
        return InstallRequest(
            instance_id=instance_id,
            name=target_name,
            vanilla_version=instance.vanilla_version,
            mod_loader_id=instance.mod_loader_id,
            mod_loader_version=instance.mod_loader_version,
            icon_path=self._normalize_icon_reference(instance.icon_path),
            stage_dir=str(stage_dir),
            final_dir=str(final_dir),
            minecraft_dir=str(minecraft_dir),
            memory_mb=instance.memory_mb,
            operation="duplicate_instance",
            modpack_path=None,
            minecraft_import_dir=None,
            copy_source_instance_id=instance.instance_id,
            copy_user_data=None,
        )

    def prepare_reinstall_request(
        self,
        instance: InstanceRecord,
        *,
        vanilla_version: str,
        mod_loader_id: str | None,
        mod_loader_version: str | None,
    ) -> InstallRequest:
        stage_dir = self.staging_root / f"{instance.instance_id}-reinstall-{uuid.uuid4().hex[:8]}"
        minecraft_dir = stage_dir / ".minecraft"
        copy_entries = [entry["path"] for entry in self.list_copyable_user_data(instance.instance_id)]
        return InstallRequest(
            instance_id=instance.instance_id,
            name=instance.name,
            vanilla_version=vanilla_version,
            mod_loader_id=mod_loader_id,
            mod_loader_version=mod_loader_version,
            icon_path=self._normalize_icon_reference(instance.icon_path),
            stage_dir=str(stage_dir),
            final_dir=str(instance.root_dir),
            minecraft_dir=str(minecraft_dir),
            memory_mb=instance.memory_mb,
            operation="reinstall",
            modpack_path=None,
            minecraft_import_dir=None,
            copy_source_instance_id=instance.instance_id,
            copy_user_data=copy_entries,
        )

    def prepare_copy_userdata_request(
        self,
        instance: InstanceRecord,
        *,
        source_instance_id: str,
        copy_user_data: list[str],
    ) -> InstallRequest:
        stage_dir = self.staging_root / f"{instance.instance_id}-copy-{uuid.uuid4().hex[:8]}"
        minecraft_dir = stage_dir / ".minecraft"
        return InstallRequest(
            instance_id=instance.instance_id,
            name=instance.name,
            vanilla_version=instance.vanilla_version,
            mod_loader_id=instance.mod_loader_id,
            mod_loader_version=instance.mod_loader_version,
            icon_path=self._normalize_icon_reference(instance.icon_path),
            stage_dir=str(stage_dir),
            final_dir=str(instance.root_dir),
            minecraft_dir=str(minecraft_dir),
            memory_mb=instance.memory_mb,
            operation="copy_userdata",
            modpack_path=None,
            minecraft_import_dir=None,
            copy_source_instance_id=source_instance_id,
            copy_user_data=copy_user_data,
        )

    def get_instance_mods_dir(self, instance: InstanceRecord) -> Path:
        return instance.minecraft_dir / "mods"

    def get_instance_configs_dir(self, instance: InstanceRecord) -> Path:
        return instance.minecraft_dir / "config"

    def get_instance_screenshots_dir(self, instance: InstanceRecord) -> Path:
        return instance.minecraft_dir / "screenshots"

    def get_instance_latest_log_path(self, instance: InstanceRecord) -> Path:
        return instance.minecraft_dir / "logs" / "latest.log"

    def get_latest_crash_report(self, instance: InstanceRecord) -> Path | None:
        crash_dir = instance.minecraft_dir / "crash-reports"
        if not crash_dir.is_dir():
            return None
        reports = sorted(
            [path for path in crash_dir.glob("*.txt") if path.is_file()],
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        return reports[0] if reports else None

    def get_default_background_path(self) -> str | None:
        defaults = self._default_background_records()
        if defaults:
            return defaults[0].absolute_path
        return None

    def backgrounds_folder(self) -> Path:
        return self.backgrounds_root

    def list_backgrounds(self) -> list[BackgroundRecord]:
        return [*self._default_background_records(), *self._user_background_records()]

    def get_active_background_reference(self) -> str | None:
        payload = self._read_background_payload()
        mode = str(payload.get("mode", "default"))
        file_name = _optional_str(payload.get("file_name"))
        if mode == "custom" and file_name:
            reference = f"{USER_BACKGROUND_PREFIX}/{file_name}"
            candidate = self._resolve_background_candidate(reference)
            try:
                candidate.relative_to(self.backgrounds_root.resolve())
            except ValueError:
                candidate = None
            if candidate is not None and candidate.is_file():
                return reference
        if mode == "default" and file_name:
            candidate = self.default_background_root / file_name
            if candidate.is_file() and candidate.suffix.lower() in BACKGROUND_SUFFIXES:
                return self._project_relative(candidate)
        defaults = self._default_background_records()
        return defaults[0].relative_path if defaults else None

    def get_active_background_path(self) -> str | None:
        reference = self.get_active_background_reference()
        if not reference:
            return self.get_default_background_path()
        resolved = Path(self.resolve_background_path(reference))
        return str(resolved) if resolved.is_file() else self.get_default_background_path()

    def set_custom_background(self, source_path: str | Path) -> str:
        reference = self.store_user_background(source_path)
        return self.set_active_background(reference)

    def store_user_background(self, source_path: str | Path, preferred_name: str | None = None) -> str:
        source = Path(source_path)
        if not source.is_file():
            raise FileNotFoundError(f"Background file not found: {source}")
        suffix = source.suffix.lower()
        if suffix not in BACKGROUND_SUFFIXES:
            raise ValueError("Choose an image or video background file.")

        self.backgrounds_root.mkdir(parents=True, exist_ok=True)
        safe_name = _slugify(preferred_name or source.stem) or BACKGROUND_FILE_NAME
        target = self._unique_background_path(safe_name, suffix)
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        return self._user_background_reference(target)

    def set_active_background(self, background_path: str | Path) -> str:
        resolved = self._resolve_background_candidate(str(background_path))
        if resolved is None or not resolved.is_file():
            raise FileNotFoundError(f"Background file not found: {background_path}")
        if resolved.suffix.lower() not in BACKGROUND_SUFFIXES:
            raise ValueError("Choose an image or video background file.")

        payload = self._read_background_payload()
        try:
            user_relative = resolved.resolve().relative_to(self.backgrounds_root.resolve())
        except ValueError:
            user_relative = None

        if user_relative is not None:
            payload.update({"mode": "custom", "file_name": user_relative.as_posix()})
        else:
            try:
                default_relative = resolved.resolve().relative_to(self.default_background_root.resolve())
            except ValueError as exc:
                raise ValueError("Background must be a default asset or a user background.") from exc
            payload.update({"mode": "default", "file_name": default_relative.as_posix()})
        self._write_background_payload(payload)
        return str(resolved.resolve())

    def remove_user_background(self, background_path: str | Path) -> bool:
        background = self._resolve_background_candidate(str(background_path))
        if background is None:
            return False
        try:
            background.relative_to(self.backgrounds_root.resolve())
        except ValueError:
            return False

        if not background.is_file():
            return False
        was_active = self.get_active_background_path() == str(background.resolve())
        background.unlink()
        if was_active:
            self.reset_background()
        return True

    def reset_background(self) -> None:
        payload = self._read_background_payload()
        payload.pop("file_name", None)
        payload["mode"] = "default"
        self._write_background_payload(payload)

    def resolve_background_path(self, background_path: str | None) -> str:
        default_path = self.get_default_background_path()
        resolved_background = self._resolve_background_candidate(background_path)
        if resolved_background.is_file():
            return str(resolved_background)
        return default_path or str(resolved_background)

    def _resolve_background_candidate(self, background_path: str | None) -> Path:
        if not background_path:
            default_path = self.get_default_background_path()
            return Path(default_path).resolve() if default_path else self.default_background_root.resolve()

        normalized = str(background_path).replace("\\", "/")
        if normalized.startswith(f"{USER_BACKGROUND_PREFIX}/"):
            relative = normalized[len(USER_BACKGROUND_PREFIX) + 1 :]
            return (self.backgrounds_root / relative).resolve()

        candidate = Path(normalized)
        if candidate.is_absolute():
            return candidate.resolve()
        return (self.project_root / candidate).resolve()

    def get_close_ui_on_launch(self) -> bool:
        return bool(self._read_background_payload().get("close_ui_on_launch", True))

    def set_close_ui_on_launch(self, enabled: bool) -> bool:
        payload = self._read_background_payload()
        payload["close_ui_on_launch"] = bool(enabled)
        self._write_background_payload(payload)
        return bool(payload["close_ui_on_launch"])

    def get_theme_mode(self) -> str:
        mode = str(self._read_background_payload().get("theme", "dark")).strip().lower()
        return "light" if mode == "light" else "dark"

    def set_theme_mode(self, mode: str) -> str:
        payload = self._read_background_payload()
        payload["theme"] = "light" if str(mode).strip().lower() == "light" else "dark"
        self._write_background_payload(payload)
        return str(payload["theme"])

    def music_folder(self) -> Path:
        return self.user_music_root

    def list_music_tracks(self) -> list[MusicRecord]:
        return self._ordered_music_records(self._read_music_payload())

    def get_music_volume(self) -> int:
        return _coerce_volume_percent(self._read_music_payload().get("volume"), 75)

    def set_music_volume(self, volume: int) -> int:
        payload = self._read_music_payload()
        payload["volume"] = _coerce_volume_percent(volume, payload.get("volume", 55))
        if payload["volume"] > 0:
            payload["last_nonzero_volume"] = payload["volume"]
        self._write_music_payload(payload)
        return int(payload["volume"])

    def get_music_last_nonzero_volume(self) -> int:
        return _coerce_volume_percent(self._read_music_payload().get("last_nonzero_volume"), 75) or 75

    def get_music_muted(self) -> bool:
        return bool(self._read_music_payload().get("muted", False))

    def set_music_muted(self, muted: bool) -> bool:
        payload = self._read_music_payload()
        payload["muted"] = bool(muted)
        self._write_music_payload(payload)
        return bool(payload["muted"])

    def get_music_loop(self) -> bool:
        return bool(self._read_music_payload().get("loop", True))

    def set_music_loop(self, enabled: bool) -> bool:
        payload = self._read_music_payload()
        payload["loop"] = bool(enabled)
        self._write_music_payload(payload)
        return bool(payload["loop"])

    def get_music_run_while_closed(self) -> bool:
        return bool(self._read_music_payload().get("run_while_launcher_closed", False))

    def set_music_run_while_closed(self, enabled: bool) -> bool:
        payload = self._read_music_payload()
        payload["run_while_launcher_closed"] = bool(enabled)
        self._write_music_payload(payload)
        return bool(payload["run_while_launcher_closed"])

    def get_music_resume_checkpoint_enabled(self) -> bool:
        return bool(self._read_music_payload().get("resume_checkpoint", True))

    def set_music_resume_checkpoint_enabled(self, enabled: bool) -> bool:
        payload = self._read_music_payload()
        payload["resume_checkpoint"] = bool(enabled)
        self._write_music_payload(payload)
        return bool(payload["resume_checkpoint"])

    def get_music_checkpoint(self) -> tuple[str | None, int]:
        payload = self._read_music_payload()
        return _optional_str(payload.get("checkpoint_music_id")), _coerce_non_negative_int(payload.get("checkpoint_position_ms"))

    def set_music_checkpoint(self, music_id: str | None, position_ms: int) -> None:
        payload = self._read_music_payload()
        payload["checkpoint_music_id"] = _optional_str(music_id)
        payload["checkpoint_position_ms"] = _coerce_non_negative_int(position_ms)
        self._write_music_payload(payload)

    def get_active_music_id(self) -> str | None:
        return _optional_str(self._read_music_payload().get("current_music_id"))

    def set_active_music_id(self, music_id: str | None) -> str | None:
        payload = self._read_music_payload()
        normalized = _optional_str(music_id)
        available = {record.music_id for record in self._music_records_from_disk(payload)}
        payload["current_music_id"] = normalized if normalized in available else None
        self._write_music_payload(payload)
        return _optional_str(payload.get("current_music_id"))

    def set_music_order(self, music_ids: list[str]) -> list[MusicRecord]:
        payload = self._read_music_payload()
        records = self._ordered_music_records(payload, preferred_order=music_ids)
        payload["order"] = [record.music_id for record in records]
        payload["disabled"] = [record.music_id for record in records if not record.enabled]
        self._write_music_payload(payload)
        return records

    def set_music_enabled(self, music_id: str, enabled: bool) -> list[MusicRecord]:
        payload = self._read_music_payload()
        available = {record.music_id for record in self._music_records_from_disk(payload)}
        if music_id not in available:
            raise FileNotFoundError(f"Music file not found: {music_id}")

        disabled = set(_coerce_str_list(payload.get("disabled")))
        if enabled:
            disabled.discard(music_id)
        else:
            disabled.add(music_id)
        payload["disabled"] = list(disabled)

        records = self._ordered_music_records(payload)
        payload["order"] = [record.music_id for record in records]
        payload["disabled"] = [record.music_id for record in records if not record.enabled]
        self._write_music_payload(payload)
        return records

    def store_user_music(self, source_path: str | Path, preferred_name: str | None = None) -> str:
        source = Path(source_path)
        if not source.is_file():
            raise FileNotFoundError(f"Music file not found: {source}")
        suffix = source.suffix.lower()
        if suffix not in MUSIC_SUFFIXES:
            raise ValueError("Choose a supported audio file.")

        self.user_music_root.mkdir(parents=True, exist_ok=True)
        safe_name = _slugify_filename(preferred_name or source.stem) or MUSIC_FILE_NAME
        target = self._unique_music_path(safe_name, suffix)
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)

        reference = self._user_music_reference(target)
        payload = self._read_music_payload()
        order = _coerce_str_list(payload.get("order"))
        if reference not in order:
            order.append(reference)
        payload["order"] = order
        self._write_music_payload(payload)
        return reference

    def remove_user_music(self, music_path: str | Path) -> bool:
        music = self._resolve_music_candidate(str(music_path))
        if music is None:
            return False
        try:
            music.relative_to(self.user_music_root.resolve())
        except ValueError:
            return False

        if not music.is_file():
            return False
        reference = self._user_music_reference(music)
        music.unlink()

        payload = self._read_music_payload()
        payload["order"] = [item for item in _coerce_str_list(payload.get("order")) if item != reference]
        payload["disabled"] = [item for item in _coerce_str_list(payload.get("disabled")) if item != reference]
        if _optional_str(payload.get("current_music_id")) == reference:
            payload["current_music_id"] = None
        self._write_music_payload(payload)
        return True

    def resolve_music_path(self, music_path: str | None) -> str | None:
        resolved_music = self._resolve_music_candidate(music_path)
        if resolved_music is not None and resolved_music.is_file() and resolved_music.suffix.lower() in MUSIC_SUFFIXES:
            return str(resolved_music)
        return None

    def list_mods(self, instance: InstanceRecord) -> list[dict[str, Any]]:
        mods_dir = self.get_instance_mods_dir(instance)
        if not mods_dir.is_dir():
            return []

        rows: list[dict[str, Any]] = []
        for path in sorted(mods_dir.iterdir(), key=lambda item: item.name.lower()):
            if not path.is_file():
                continue
            lowered = path.name.lower()
            if lowered.endswith(".disabled"):
                archive_name = path.name[:-9]
            else:
                archive_name = path.name

            if Path(archive_name).suffix.lower() not in {".jar", ".zip"}:
                continue

            metadata = _read_mod_metadata(path, self.generated_icons_root)
            rows.append(
                {
                    "file_name": path.name,
                    "path": str(path.resolve()),
                    "enabled": not lowered.endswith(".disabled"),
                    "icon_path": metadata.get("icon_path"),
                    "name": metadata.get("name") or _friendly_archive_name(path.name),
                    "version": metadata.get("version") or "Unknown",
                    "last_modified": _format_file_timestamp(path),
                    "provider": metadata.get("provider") or "Unknown",
                }
            )
        return rows

    def set_mod_enabled(self, instance: InstanceRecord, file_name: str, enabled: bool) -> Path:
        source = _safe_local_path_join(self.get_instance_mods_dir(instance), file_name)
        if not source.is_file():
            raise FileNotFoundError(f"Mod file not found: {file_name}")

        is_enabled = not source.name.lower().endswith(".disabled")
        if is_enabled == enabled:
            return source

        if enabled:
            if not source.name.lower().endswith(".disabled"):
                return source
            target_name = re.sub(r"\.disabled$", "", source.name, flags=re.IGNORECASE)
        else:
            target_name = f"{source.name}.disabled"

        target = source.with_name(target_name)
        if target.exists():
            raise FileExistsError(f"A mod file named '{target.name}' already exists.")

        source.rename(target)
        return target

    def remove_mods(self, instance: InstanceRecord, file_names: list[str]) -> None:
        mods_dir = self.get_instance_mods_dir(instance)
        for file_name in file_names:
            target = _safe_local_path_join(mods_dir, file_name)
            if target.is_file():
                target.unlink()

    def list_screenshots(self, instance: InstanceRecord) -> list[dict[str, Any]]:
        screenshots_dir = self.get_instance_screenshots_dir(instance)
        if not screenshots_dir.is_dir():
            return []

        rows: list[dict[str, Any]] = []
        for path in sorted(
            [candidate for candidate in screenshots_dir.iterdir() if candidate.is_file() and candidate.suffix.lower() in IMAGE_SUFFIXES],
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            rows.append(
                {
                    "file_name": path.name,
                    "path": str(path.resolve()),
                    "label": _format_screenshot_label(path),
                    "modified_timestamp": path.stat().st_mtime,
                }
            )
        return rows

    def rename_screenshot(self, instance: InstanceRecord, file_name: str, new_stem: str) -> Path:
        screenshots_dir = self.get_instance_screenshots_dir(instance)
        source = _safe_local_path_join(screenshots_dir, file_name)
        if not source.is_file():
            raise FileNotFoundError(f"Screenshot not found: {file_name}")

        cleaned = _slugify_filename(new_stem)
        if not cleaned:
            raise ValueError("Screenshot name cannot be empty.")

        target = screenshots_dir / f"{cleaned}{source.suffix.lower()}"
        if target.exists() and target.resolve() != source.resolve():
            raise FileExistsError(f"A screenshot named '{target.name}' already exists.")

        source.rename(target)
        return target

    def delete_screenshots(self, instance: InstanceRecord, file_names: list[str]) -> None:
        screenshots_dir = self.get_instance_screenshots_dir(instance)
        for file_name in file_names:
            target = _safe_local_path_join(screenshots_dir, file_name)
            if target.is_file():
                target.unlink()

    def prepare_install_request(
        self,
        name: str,
        vanilla_version: str | None,
        mod_loader_id: str | None,
        mod_loader_version: str | None,
        icon_path: str | None = None,
        memory_mb: int | None = None,
        operation: str = "create",
        modpack_path: str | None = None,
        minecraft_import_dir: str | None = None,
        copy_source_instance_id: str | None = None,
        copy_user_data: list[str] | None = None,
    ) -> InstallRequest:
        normalized_name = name.strip()
        if operation == "create" and vanilla_version:
            instance_name = normalized_name or self.default_instance_name(vanilla_version, mod_loader_id)
        else:
            instance_name = normalized_name or self.default_import_name(modpack_path, minecraft_import_dir)

        slug = _slugify(instance_name)[:40] or "instance"
        instance_id = f"{slug}-{uuid.uuid4().hex[:8]}"
        final_dir = self.instances_root / instance_id
        stage_dir = self.staging_root / instance_id
        minecraft_dir = stage_dir / ".minecraft"

        selected_icon = icon_path or self.default_icon
        icon_relative = self._normalize_icon_reference(selected_icon)

        return InstallRequest(
            instance_id=instance_id,
            name=instance_name,
            vanilla_version=_optional_str(vanilla_version),
            mod_loader_id=mod_loader_id,
            mod_loader_version=mod_loader_version,
            icon_path=icon_relative,
            stage_dir=str(stage_dir),
            final_dir=str(final_dir),
            minecraft_dir=str(minecraft_dir),
            memory_mb=_coerce_memory_mb(memory_mb),
            operation=operation,
            modpack_path=_optional_str(modpack_path),
            minecraft_import_dir=_optional_str(minecraft_import_dir),
            copy_source_instance_id=_optional_str(copy_source_instance_id),
            copy_user_data=_sanitize_copy_user_data(copy_user_data),
        )

    def finalize_install(self, request: InstallRequest, result: InstallResult) -> InstanceRecord:
        stage_dir = Path(request.stage_dir)
        final_dir = Path(request.final_dir)
        if not stage_dir.exists():
            raise FileNotFoundError(f"Missing staging directory: {stage_dir}")
        replace_existing = request.operation in {"reinstall", "copy_userdata"}
        existing_metadata: dict[str, Any] = {}
        if final_dir.exists() and not replace_existing:
            raise FileExistsError(f"Instance directory already exists: {final_dir}")
        if replace_existing and (final_dir / "instance.json").is_file():
            existing_metadata = json.loads((final_dir / "instance.json").read_text(encoding="utf-8"))

        resolved_icon = result.icon_path or request.icon_path
        if result.staged_icon_path:
            resolved_icon = self.promote_staged_icon(result.staged_icon_path, result.name)
        if not resolved_icon:
            resolved_icon = self.default_icon

        metadata = {
            "instance_id": request.instance_id,
            "name": result.name,
            "vanilla_version": result.vanilla_version,
            "installed_version": result.installed_version,
            "mod_loader_id": result.mod_loader_id,
            "mod_loader_version": result.mod_loader_version,
            "icon_path": self._normalize_icon_reference(resolved_icon),
            "created_at": existing_metadata.get("created_at", _utc_now()),
            "last_played": existing_metadata.get("last_played"),
            "memory_mb": _coerce_memory_mb(request.memory_mb),
            "total_played_seconds": _coerce_non_negative_int(existing_metadata.get("total_played_seconds")),
            "rich_presence_enabled": bool(existing_metadata.get("rich_presence_enabled", True)),
            "rich_presence_state": _optional_str(existing_metadata.get("rich_presence_state")),
            "rich_presence_details": _optional_str(existing_metadata.get("rich_presence_details")),
            "rich_presence_adaptive_details": bool(existing_metadata.get("rich_presence_adaptive_details", True)),
        }
        (stage_dir / "instance.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        backup_dir: Path | None = None
        try:
            if replace_existing and final_dir.exists():
                backup_dir = final_dir.with_name(f"{final_dir.name}.backup-{uuid.uuid4().hex[:8]}")
                final_dir.rename(backup_dir)
            shutil.move(str(stage_dir), str(final_dir))
        except Exception:
            if backup_dir is not None and backup_dir.exists() and not final_dir.exists():
                backup_dir.rename(final_dir)
            raise
        finally:
            if backup_dir is not None and backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)

        instance = InstanceRecord.from_metadata(metadata, final_dir)
        instance.icon_path = self.resolve_icon_path(instance.icon_path)
        return instance

    def cleanup_install(self, request: InstallRequest) -> None:
        stage_dir = Path(request.stage_dir)
        if stage_dir.exists():
            shutil.rmtree(stage_dir, ignore_errors=True)

    def refresh_instance_last_played(self, instance: InstanceRecord) -> InstanceRecord:
        metadata_path = instance.root_dir / "instance.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["last_played"] = _utc_now()
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        refreshed = InstanceRecord.from_metadata(metadata, instance.root_dir)
        refreshed.icon_path = self.resolve_icon_path(refreshed.icon_path)
        return refreshed

    def record_instance_playtime(self, instance: InstanceRecord, seconds: int) -> InstanceRecord:
        metadata_path = instance.root_dir / "instance.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["total_played_seconds"] = _coerce_non_negative_int(metadata.get("total_played_seconds")) + max(0, seconds)
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        refreshed = InstanceRecord.from_metadata(metadata, instance.root_dir)
        refreshed.icon_path = self.resolve_icon_path(refreshed.icon_path)
        return refreshed

    def get_version_catalog(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        if self._version_cache is not None and not force_refresh:
            return self._version_cache

        versions = []
        for entry in minecraft_launcher_lib.utils.get_version_list():
            version_type = str(entry["type"])
            release_time = entry.get("releaseTime")
            versions.append(
                {
                    "id": str(entry["id"]),
                    "type": version_type,
                    "type_label": _format_version_type(version_type),
                    "release_time": release_time,
                    "release_display": _format_release_date(release_time),
                }
            )

        versions.sort(
            key=lambda item: item["release_time"] or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        self._version_cache = versions
        return versions

    def get_mod_loader_ids(self) -> list[str]:
        return list(minecraft_launcher_lib.mod_loader.list_mod_loader())

    def get_mod_loader_name(self, loader_id: str) -> str:
        return minecraft_launcher_lib.mod_loader.get_mod_loader(loader_id).get_name()

    def get_loader_supported_versions(self, loader_id: str) -> set[str]:
        if loader_id in self._loader_support_cache:
            return self._loader_support_cache[loader_id]

        loader = minecraft_launcher_lib.mod_loader.get_mod_loader(loader_id)
        supported = set(loader.get_minecraft_versions(False))
        self._loader_support_cache[loader_id] = supported
        return supported

    def get_loader_versions(
        self,
        loader_id: str,
        minecraft_version: str,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        cache_key = (loader_id, minecraft_version)
        if cache_key in self._loader_versions_cache and not force_refresh:
            return self._loader_versions_cache[cache_key]

        loader = minecraft_launcher_lib.mod_loader.get_mod_loader(loader_id)
        versions = loader.get_loader_versions(minecraft_version, False)
        loader_name = loader.get_name()
        rows = [
            {
                "loader_version": version,
                "loader_name": loader_name,
                "minecraft_version": minecraft_version,
            }
            for version in versions
        ]
        self._loader_versions_cache[cache_key] = rows
        return rows

    def default_instance_name(self, vanilla_version: str, mod_loader_id: str | None) -> str:
        if mod_loader_id:
            loader_name = self.get_mod_loader_name(mod_loader_id)
            return f"{loader_name} {vanilla_version}"
        return vanilla_version

    def default_import_name(
        self,
        modpack_path: str | None = None,
        minecraft_import_dir: str | None = None,
    ) -> str:
        if modpack_path:
            return Path(modpack_path).stem or "Imported Instance"
        if minecraft_import_dir:
            source = Path(minecraft_import_dir)
            if source.name == ".minecraft" and source.parent.name:
                return source.parent.name
            return source.name or "Imported Instance"
        return "Imported Instance"

    def validate_install_request(self, request: InstallRequest) -> None:
        stage_dir = Path(request.stage_dir)
        final_dir = Path(request.final_dir)
        minecraft_dir = Path(request.minecraft_dir)
        replace_existing = request.operation in {"reinstall", "copy_userdata"}

        if replace_existing:
            instance = self.get_instance(request.instance_id)
            if instance is None:
                raise FileNotFoundError("The target instance no longer exists.")
            if instance.status.lower() in {"launching", "launched"} or self.runtime_session_pid(instance.instance_id):
                raise RuntimeError("Stop the instance before changing its files.")
            if not final_dir.is_dir():
                raise FileNotFoundError(f"Instance directory not found: {final_dir}")
            if not (final_dir / "instance.json").is_file():
                raise FileNotFoundError(f"Instance metadata not found: {final_dir / 'instance.json'}")
        elif final_dir.exists():
            raise FileExistsError(f"Instance directory already exists: {final_dir}")

        stage_dir.parent.mkdir(parents=True, exist_ok=True)
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        _assert_directory_writable(stage_dir.parent, "staging folder")
        _assert_directory_writable(final_dir.parent, "instances folder")
        if replace_existing:
            _assert_directory_writable(final_dir, "instance folder")

        if request.operation in {"create", "reinstall"} and request.vanilla_version:
            self.select_java_runtime(request.vanilla_version, minecraft_dir)

    def required_java_major(self, version: str, minecraft_dir: Path) -> int:
        required = _minimum_java_major_for_minecraft_version(version)
        try:
            runtime_info = minecraft_launcher_lib.runtime.get_version_runtime_information(version, minecraft_dir)
        except Exception:
            runtime_info = None
        if runtime_info:
            try:
                required = max(required, int(runtime_info.get("javaMajorVersion") or 0))
            except (TypeError, ValueError):
                pass
        return max(required, 8)

    def select_java_runtime(self, version: str, minecraft_dir: Path) -> JavaRuntimeCandidate:
        required_major = self.required_java_major(version, minecraft_dir)
        candidates = self._java_runtime_candidates(version, minecraft_dir)
        compatible = [candidate for candidate in candidates if candidate.major_version >= required_major]
        if compatible:
            compatible.sort(key=lambda candidate: (candidate.major_version, candidate.label.lower()), reverse=True)
            return compatible[0]

        detected = sorted({candidate.major_version for candidate in candidates}, reverse=True)
        if detected:
            found_text = f" Highest detected Java version is {detected[0]}."
        else:
            found_text = " Java was not found."
        raise JavaCompatibilityError(
            f"Java {required_major} or newer is required for Minecraft {version}.{found_text}"
        )

    def _java_runtime_candidates(self, version: str, minecraft_dir: Path) -> list[JavaRuntimeCandidate]:
        candidates: list[JavaRuntimeCandidate] = []
        seen: set[str] = set()

        def add_candidate(executable: str | os.PathLike | None, label: str) -> None:
            if not executable:
                return
            candidate = _java_candidate_from_executable(executable, label)
            if candidate is None:
                return
            key = str(Path(candidate.executable_path).resolve()).lower()
            if key in seen:
                return
            seen.add(key)
            candidates.append(candidate)

        try:
            runtime_info = minecraft_launcher_lib.runtime.get_version_runtime_information(version, minecraft_dir)
        except Exception:
            runtime_info = None
        if runtime_info:
            runtime_name = _optional_str(runtime_info.get("name"))
            if runtime_name:
                add_candidate(
                    minecraft_launcher_lib.runtime.get_executable_path(runtime_name, minecraft_dir),
                    f"Mojang runtime {runtime_name}",
                )

        java_home = _optional_str(os.environ.get("JAVA_HOME"))
        if java_home:
            add_candidate(Path(java_home) / "bin" / _java_executable_name(), "JAVA_HOME")

        for executable_name in ("java.exe", "javaw.exe", "java"):
            add_candidate(shutil.which(executable_name), "PATH")

        try:
            system_roots = minecraft_launcher_lib.java_utils.find_system_java_versions()
        except Exception:
            system_roots = []
        for root in system_roots:
            add_candidate(Path(root) / "bin" / _java_executable_name(), Path(root).name)

        return candidates

    def is_experiment_type(self, version_type: str) -> bool:
        normalized = version_type.lower().replace("-", "_")
        return normalized not in KNOWN_VERSION_TYPES or normalized in EXPERIMENT_TYPES

    def build_launch_options(
        self,
        player_name: str,
        game_directory: Path,
        memory_mb: int | None = None,
        java_executable: str | None = None,
    ) -> dict[str, Any]:
        resolved_memory = _coerce_memory_mb(memory_mb)
        options: dict[str, Any] = {
            "username": player_name,
            "uuid": _offline_uuid(player_name),
            "token": "offline-token",
            "launcherName": "vanilla",
            "launcherVersion": "vanilla",
            "gameDirectory": str(game_directory),
            "jvmArguments": [
                f"-Xmx{resolved_memory}M",
                "-Dminecraft.launcher.brand=vanilla",
                "-Dminecraft.launcher.version=vanilla",
            ],
            "enableLoggingConfig": True,
        }
        if java_executable:
            options["executablePath"] = java_executable
            options["defaultExecutablePath"] = java_executable
        return options

    def launch_instance(self, instance: InstanceRecord, player_name: str) -> subprocess.Popen[Any]:
        minecraft_directory = instance.minecraft_dir
        java_runtime = self.select_java_runtime(instance.installed_version, minecraft_directory)
        command = minecraft_launcher_lib.command.get_minecraft_command(
            instance.installed_version,
            minecraft_directory,
            self.build_launch_options(
                player_name,
                minecraft_directory,
                instance.memory_mb,
                java_runtime.executable_path,
            ),
        )
        _normalize_minecraft_version_argument(command, instance.vanilla_version)

        kwargs: dict[str, Any] = {
            "cwd": str(minecraft_directory),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        elif hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True

        return subprocess.Popen(command, **kwargs)

    def build_launcher_command(self, *args: str) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, *args]
        main_path = self.project_root / "app" / "main.py"
        return [sys.executable, str(main_path), *args]

    def get_launcher_working_directory(self) -> Path:
        if getattr(sys, "frozen", False):
            return self.data_root
        return self.project_root

    def spawn_session_monitor(self, instance_id: str, pid: int, player_name: str) -> int | None:
        command = self.build_launcher_command(
            "--monitor-session",
            instance_id,
            "--pid",
            str(pid),
            "--player-name",
            player_name,
        )
        kwargs: dict[str, Any] = {
            "cwd": str(self.get_launcher_working_directory()),
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        elif hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True

        monitor = subprocess.Popen(command, **kwargs)
        return int(monitor.pid) if getattr(monitor, "pid", None) else None

    def get_runtime_session_path(self, instance_id: str) -> Path:
        return self.sessions_root / f"{instance_id}.json"

    def list_runtime_sessions(self) -> dict[str, dict[str, Any]]:
        sessions: dict[str, dict[str, Any]] = {}
        if not self.sessions_root.is_dir():
            return sessions

        for path in sorted(self.sessions_root.glob("*.json"), key=lambda item: item.name.lower()):
            payload = self._read_runtime_session_payload(path)
            instance_id = _optional_str(payload.get("instance_id"))
            if instance_id:
                sessions[instance_id] = payload
        return sessions

    def get_runtime_session(self, instance_id: str) -> dict[str, Any] | None:
        payload = self._read_runtime_session_payload(self.get_runtime_session_path(instance_id))
        return payload or None

    def register_runtime_session(
        self,
        instance: InstanceRecord,
        *,
        pid: int,
        player_name: str,
        close_ui_on_launch: bool,
    ) -> dict[str, Any]:
        payload = {
            "instance_id": instance.instance_id,
            "instance_name": instance.name,
            "pid": int(pid),
            "monitor_pid": None,
            "player_name": player_name,
            "status": "launching",
            "outcome": None,
            "exit_code": None,
            "started_at": _utc_now(),
            "ended_at": None,
            "stop_requested": False,
            "attention_needed": False,
            "attention_page": None,
            "close_ui_on_launch": bool(close_ui_on_launch),
        }
        self._write_runtime_session_payload(self.get_runtime_session_path(instance.instance_id), payload)
        return payload

    def attach_runtime_monitor(self, instance_id: str, monitor_pid: int | None) -> dict[str, Any] | None:
        if monitor_pid is None:
            return self.get_runtime_session(instance_id)
        return self.update_runtime_session(instance_id, monitor_pid=int(monitor_pid))

    def mark_runtime_session_running(self, instance_id: str) -> dict[str, Any] | None:
        session = self.get_runtime_session(instance_id)
        if session is None:
            return None
        if _optional_str(session.get("status")) in {"finished", "stopped", "crashed"}:
            return session
        return self.update_runtime_session(instance_id, status="running")

    def mark_runtime_session_stop_requested(self, instance_id: str) -> dict[str, Any] | None:
        session = self.get_runtime_session(instance_id)
        if session is None:
            return None
        return self.update_runtime_session(instance_id, stop_requested=True)

    def complete_runtime_session(self, instance_id: str, exit_code: int | None) -> dict[str, Any] | None:
        session = self.get_runtime_session(instance_id)
        if session is None:
            return None

        if bool(session.get("stop_requested")):
            final_status = "stopped"
        elif exit_code in (0, None):
            final_status = "finished"
        else:
            final_status = "crashed"

        payload = self.update_runtime_session(
            instance_id,
            pid=None,
            monitor_pid=None,
            status=final_status,
            outcome=final_status,
            exit_code=exit_code,
            ended_at=_utc_now(),
            attention_needed=final_status == "crashed",
            attention_page="Minecraft Log" if final_status == "crashed" else None,
        )
        return payload

    def clear_runtime_session(self, instance_id: str) -> None:
        path = self.get_runtime_session_path(instance_id)
        if path.is_file():
            path.unlink(missing_ok=True)

    def claim_runtime_attention(self) -> list[dict[str, Any]]:
        claimed: list[dict[str, Any]] = []
        for instance_id, payload in self.list_runtime_sessions().items():
            if not bool(payload.get("attention_needed")):
                continue
            claimed.append(payload)
            self.update_runtime_session(instance_id, attention_needed=False)
        return claimed

    def update_runtime_session(self, instance_id: str, **changes: Any) -> dict[str, Any] | None:
        path = self.get_runtime_session_path(instance_id)
        payload = self._read_runtime_session_payload(path)
        if not payload:
            return None
        payload.update(changes)
        payload["instance_id"] = instance_id
        self._write_runtime_session_payload(path, payload)
        return payload

    def runtime_session_pid(self, instance_id: str) -> int | None:
        session = self.get_runtime_session(instance_id)
        if session is None:
            return None
        try:
            pid = int(session.get("pid"))
        except (TypeError, ValueError):
            return None
        return pid if pid > 0 else None

    def runtime_session_started_at(self, instance_id: str) -> str | None:
        session = self.get_runtime_session(instance_id)
        return _optional_str(session.get("started_at")) if session else None

    def terminate_runtime_session(self, instance_id: str) -> bool:
        session = self.get_runtime_session(instance_id)
        if session is None:
            return False
        pid = self.runtime_session_pid(instance_id)
        self.mark_runtime_session_stop_requested(instance_id)
        if pid is not None:
            self.terminate_process_tree(pid)
        self.update_runtime_session(
            instance_id,
            pid=None,
            monitor_pid=None,
            status="stopped",
            outcome="stopped",
            ended_at=_utc_now(),
            attention_needed=False,
            attention_page=None,
        )
        return True

    def open_instance_dir(self, instance: InstanceRecord) -> Path:
        return instance.root_dir

    def terminate_process_tree(self, pid: int) -> None:
        terminate_process_tree(pid)

    def _normalize_icon_reference(self, icon_path: str) -> str:
        normalized = icon_path.replace("\\", "/")
        if normalized.startswith(f"{USER_ICON_PREFIX}/"):
            return normalized

        candidate = Path(normalized)
        if candidate.is_absolute():
            return self._path_reference(candidate)
        return self._path_reference((self.project_root / candidate).resolve())

    def _path_reference(self, path: Path) -> str:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(self.user_icons_root.resolve())
        except ValueError:
            pass
        else:
            return f"{USER_ICON_PREFIX}/{relative.as_posix()}"

        return self._project_relative(resolved)

    def _project_relative(self, path: Path) -> str:
        try:
            relative = path.resolve().relative_to(self.project_root.resolve())
        except ValueError:
            return str(path.resolve())
        return relative.as_posix()

    def _user_icon_reference(self, path: Path) -> str:
        relative = path.resolve().relative_to(self.user_icons_root.resolve())
        return f"{USER_ICON_PREFIX}/{relative.as_posix()}"

    def _unique_icon_path(self, safe_name: str, suffix: str) -> Path:
        target = self.user_icons_root / f"{safe_name}{suffix}"
        if not target.exists():
            return target

        for index in range(2, 5000):
            candidate = self.user_icons_root / f"{safe_name}-{index}{suffix}"
            if not candidate.exists():
                return candidate
        raise RuntimeError("Could not allocate a unique icon filename.")

    def _default_background_records(self) -> list[BackgroundRecord]:
        if not self.default_background_root.is_dir():
            return []
        records: list[BackgroundRecord] = []
        for path in sorted(self.default_background_root.iterdir(), key=_default_background_sort_key):
            if not path.is_file() or path.suffix.lower() not in BACKGROUND_SUFFIXES:
                continue
            relative_path = self._project_relative(path)
            records.append(
                BackgroundRecord(
                    background_id=relative_path,
                    name=_friendly_asset_name(path.stem),
                    relative_path=relative_path,
                    absolute_path=str(path.resolve()),
                    is_default=True,
                    is_video=path.suffix.lower() in VIDEO_SUFFIXES,
                )
            )
        return records

    def _user_background_records(self) -> list[BackgroundRecord]:
        if not self.backgrounds_root.is_dir():
            return []
        records: list[BackgroundRecord] = []
        for path in sorted(self.backgrounds_root.iterdir(), key=lambda item: item.name.lower()):
            if not path.is_file() or path.suffix.lower() not in BACKGROUND_SUFFIXES:
                continue
            relative_path = self._user_background_reference(path)
            records.append(
                BackgroundRecord(
                    background_id=relative_path,
                    name=_friendly_asset_name(path.stem),
                    relative_path=relative_path,
                    absolute_path=str(path.resolve()),
                    is_default=False,
                    is_video=path.suffix.lower() in VIDEO_SUFFIXES,
                )
            )
        return records

    def _unique_background_path(self, safe_name: str, suffix: str) -> Path:
        target = self.backgrounds_root / f"{safe_name}{suffix}"
        if not target.exists():
            return target

        for index in range(2, 5000):
            candidate = self.backgrounds_root / f"{safe_name}-{index}{suffix}"
            if not candidate.exists():
                return candidate
        raise RuntimeError("Could not allocate a unique background filename.")

    def _user_background_reference(self, path: Path) -> str:
        relative = path.resolve().relative_to(self.backgrounds_root.resolve())
        return f"{USER_BACKGROUND_PREFIX}/{relative.as_posix()}"

    def _default_music_records(self) -> list[MusicRecord]:
        roots: list[Path] = []
        if self.default_music_root.is_dir():
            roots.append(self.default_music_root)
        if self.legacy_default_music_root.is_dir() and self.legacy_default_music_root.resolve() != self.default_music_root.resolve():
            roots.append(self.legacy_default_music_root)

        records: list[MusicRecord] = []
        seen: set[str] = set()
        for root in roots:
            for path in sorted(root.iterdir(), key=lambda item: item.name.lower()):
                if not path.is_file() or path.suffix.lower() not in MUSIC_SUFFIXES:
                    continue
                relative_path = self._project_relative(path)
                if relative_path in seen:
                    continue
                seen.add(relative_path)
                records.append(
                    MusicRecord(
                        music_id=relative_path,
                        name=_friendly_asset_name(path.stem),
                        relative_path=relative_path,
                        absolute_path=str(path.resolve()),
                        is_default=True,
                        enabled=True,
                    )
                )
        return records

    def _user_music_records(self) -> list[MusicRecord]:
        if not self.user_music_root.is_dir():
            return []
        records: list[MusicRecord] = []
        for path in sorted(self.user_music_root.iterdir(), key=lambda item: item.name.lower()):
            if not path.is_file() or path.suffix.lower() not in MUSIC_SUFFIXES:
                continue
            relative_path = self._user_music_reference(path)
            records.append(
                MusicRecord(
                    music_id=relative_path,
                    name=_friendly_asset_name(path.stem),
                    relative_path=relative_path,
                    absolute_path=str(path.resolve()),
                    is_default=False,
                    enabled=True,
                )
            )
        return records

    def _music_records_from_disk(self, payload: dict[str, Any]) -> list[MusicRecord]:
        disabled = set(_coerce_str_list(payload.get("disabled")))
        records = [*self._default_music_records(), *self._user_music_records()]
        for record in records:
            record.enabled = record.music_id not in disabled
        return records

    def _ordered_music_records(
        self,
        payload: dict[str, Any],
        *,
        preferred_order: list[str] | None = None,
    ) -> list[MusicRecord]:
        records = self._music_records_from_disk(payload)
        records_by_id = {record.music_id: record for record in records}
        order = _coerce_str_list(preferred_order if preferred_order is not None else payload.get("order"))

        ordered: list[MusicRecord] = []
        seen: set[str] = set()
        for music_id in order:
            record = records_by_id.get(music_id)
            if record is None or music_id in seen:
                continue
            ordered.append(record)
            seen.add(music_id)

        for record in records:
            if record.music_id not in seen:
                ordered.append(record)
                seen.add(record.music_id)

        return [record for record in ordered if record.enabled] + [record for record in ordered if not record.enabled]

    def _unique_music_path(self, safe_name: str, suffix: str) -> Path:
        target = self.user_music_root / f"{safe_name}{suffix}"
        if not target.exists():
            return target

        for index in range(2, 5000):
            candidate = self.user_music_root / f"{safe_name}-{index}{suffix}"
            if not candidate.exists():
                return candidate
        raise RuntimeError("Could not allocate a unique music filename.")

    def _user_music_reference(self, path: Path) -> str:
        relative = path.resolve().relative_to(self.user_music_root.resolve())
        return f"{USER_MUSIC_PREFIX}/{relative.as_posix()}"

    def _resolve_music_candidate(self, music_path: str | None) -> Path | None:
        text = _optional_str(music_path)
        if not text:
            return None

        normalized = text.replace("\\", "/")
        if normalized.startswith(f"{USER_MUSIC_PREFIX}/"):
            relative = normalized[len(USER_MUSIC_PREFIX) + 1 :]
            return (self.user_music_root / relative).resolve()

        candidate = Path(normalized)
        if candidate.is_absolute():
            return candidate.resolve()
        return (self.project_root / candidate).resolve()

    def _bootstrap_legacy_storage(self) -> None:
        self._copy_tree_if_target_empty(self.legacy_instances_root, self.instances_root)
        self._copy_tree_if_target_empty(self.legacy_user_icons_root, self.user_icons_root)

    def _ensure_account_store(self) -> None:
        if self.accounts_file.is_file():
            payload = self._read_accounts_payload()
            self._write_accounts_payload(payload)
            return
        self._write_accounts_payload({"accounts": ["player1"], "active": "player1"})

    def _read_background_payload(self) -> dict[str, Any]:
        payload = {
            "mode": "default",
            "close_ui_on_launch": True,
            "theme": "dark",
        }
        if not self.background_settings_file.is_file():
            return payload
        try:
            loaded = json.loads(self.background_settings_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return payload
        if not isinstance(loaded, dict):
            return payload
        mode = _optional_str(loaded.get("mode"))
        file_name = _optional_str(loaded.get("file_name"))
        if mode in {"custom", "default"} and file_name:
            payload = {"mode": mode, "file_name": file_name}
        payload["close_ui_on_launch"] = bool(loaded.get("close_ui_on_launch", True))
        payload["theme"] = "light" if str(loaded.get("theme", "dark")).strip().lower() == "light" else "dark"
        return payload

    def _write_background_payload(self, payload: dict[str, Any]) -> None:
        payload = dict(payload)
        payload["close_ui_on_launch"] = bool(payload.get("close_ui_on_launch", True))
        payload["theme"] = "light" if str(payload.get("theme", "dark")).strip().lower() == "light" else "dark"
        self.background_settings_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _read_music_payload(self) -> dict[str, Any]:
        default_payload: dict[str, Any] = {
            "order": [],
            "disabled": [],
            "volume": 75,
            "last_nonzero_volume": 75,
            "muted": False,
            "loop": True,
            "run_while_launcher_closed": False,
            "resume_checkpoint": True,
            "checkpoint_music_id": None,
            "checkpoint_position_ms": 0,
            "current_music_id": None,
        }
        if not self.music_settings_file.is_file():
            return default_payload
        try:
            loaded = json.loads(self.music_settings_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default_payload
        if not isinstance(loaded, dict):
            return default_payload

        payload = dict(default_payload)
        payload["order"] = _coerce_str_list(loaded.get("order"))
        payload["disabled"] = _coerce_str_list(loaded.get("disabled"))
        payload["volume"] = _coerce_volume_percent(loaded.get("volume"), default_payload["volume"])
        payload["last_nonzero_volume"] = _coerce_volume_percent(
            loaded.get("last_nonzero_volume"),
            payload["volume"] or default_payload["last_nonzero_volume"],
        ) or default_payload["last_nonzero_volume"]
        payload["muted"] = bool(loaded.get("muted", default_payload["muted"]))
        payload["loop"] = bool(loaded["loop"]) if "loop" in loaded else default_payload["loop"]
        payload["run_while_launcher_closed"] = bool(loaded.get("run_while_launcher_closed", default_payload["run_while_launcher_closed"]))
        payload["resume_checkpoint"] = bool(loaded.get("resume_checkpoint", default_payload["resume_checkpoint"]))
        payload["checkpoint_music_id"] = _optional_str(loaded.get("checkpoint_music_id"))
        payload["checkpoint_position_ms"] = _coerce_non_negative_int(loaded.get("checkpoint_position_ms"))
        payload["current_music_id"] = _optional_str(loaded.get("current_music_id"))
        return payload

    def _write_music_payload(self, payload: dict[str, Any]) -> None:
        normalized: dict[str, Any] = {
            "order": _coerce_str_list(payload.get("order")),
            "disabled": _coerce_str_list(payload.get("disabled")),
            "volume": _coerce_volume_percent(payload.get("volume"), 75),
            "last_nonzero_volume": _coerce_volume_percent(payload.get("last_nonzero_volume"), 75) or 75,
            "muted": bool(payload.get("muted", False)),
            "loop": bool(payload.get("loop", True)),
            "run_while_launcher_closed": bool(payload.get("run_while_launcher_closed", False)),
            "resume_checkpoint": bool(payload.get("resume_checkpoint", True)),
            "checkpoint_music_id": _optional_str(payload.get("checkpoint_music_id")),
            "checkpoint_position_ms": _coerce_non_negative_int(payload.get("checkpoint_position_ms")),
            "current_music_id": _optional_str(payload.get("current_music_id")),
        }
        if normalized["volume"] > 0:
            normalized["last_nonzero_volume"] = normalized["volume"]
        self.music_settings_file.write_text(json.dumps(normalized, indent=2), encoding="utf-8")

    def _read_runtime_session_payload(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_runtime_session_payload(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _apply_runtime_session(self, instance: InstanceRecord, session: dict[str, Any] | None) -> None:
        if not session:
            return
        status = _optional_str(session.get("status"))
        if not status:
            return
        instance.status = SESSION_STATUS_TO_INSTANCE_STATUS.get(status, instance.status)
        try:
            pid = int(session.get("pid"))
        except (TypeError, ValueError):
            pid = None
        instance.pid = pid if pid and pid > 0 else None

    def _copy_tree_if_target_empty(self, source: Path, destination: Path) -> None:
        if not source.exists() or not source.is_dir():
            return
        if source.resolve() == destination.resolve():
            return
        if any(destination.iterdir()):
            return
        shutil.copytree(source, destination, dirs_exist_ok=True)

    def _read_accounts_payload(self) -> dict[str, Any]:
        default_payload = {"accounts": ["player1"], "active": "player1"}
        if not self.accounts_file.is_file():
            return default_payload

        try:
            payload = json.loads(self.accounts_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default_payload

        accounts = payload.get("accounts")
        active = _optional_str(payload.get("active"))
        if not isinstance(accounts, list):
            return default_payload

        normalized_accounts: list[str] = []
        seen: set[str] = set()
        for value in accounts:
            try:
                normalized = self._normalize_account_name(value)
            except ValueError:
                continue
            lowered = normalized.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            normalized_accounts.append(normalized)

        if not normalized_accounts:
            normalized_accounts = ["player1"]

        if not active or active not in normalized_accounts:
            active = normalized_accounts[0]

        return {"accounts": normalized_accounts, "active": active}

    def _write_accounts_payload(self, payload: dict[str, Any]) -> None:
        normalized = {
            "accounts": list(payload["accounts"]),
            "active": str(payload["active"]),
        }
        self.accounts_file.write_text(json.dumps(normalized, indent=2), encoding="utf-8")

    def _normalize_account_name(self, value: Any) -> str:
        text = _required_str(value, "Account name")
        if len(text) > 32:
            raise ValueError("Account names must be 32 characters or fewer.")
        return text

    def _allocate_duplicate_name(self, base_name: str) -> str:
        normalized_base = base_name.strip() or "Instance Copy"
        existing = {instance.name.lower() for instance in self.load_instances()}
        if normalized_base.lower() not in existing:
            return normalized_base
        for index in range(2, 5000):
            candidate = f"{normalized_base} {index}"
            if candidate.lower() not in existing:
                return candidate
        raise RuntimeError("Could not allocate a unique instance name.")


def run_install_task(task: dict[str, Any], event_queue: Any) -> None:
    try:
        request = InstallRequest.from_payload(task)
        stage_dir = Path(request.stage_dir)
        minecraft_dir = Path(request.minecraft_dir)
        stage_dir.mkdir(parents=True, exist_ok=True)
        minecraft_dir.mkdir(parents=True, exist_ok=True)

        progress = _InstallProgressReporter(event_queue)
        progress.begin_phase(0.03)
        _queue_event(event_queue, "status", text="Preparing instance directory")
        _queue_event(event_queue, "log", text=f"Staging install in {stage_dir.name}")

        callback = {
            "setStatus": lambda text: _install_status(event_queue, text, progress),
            "setProgress": lambda value: progress.set_phase_progress(value),
            "setMax": lambda maximum: progress.set_phase_max(maximum),
            "_progress": progress,
        }

        if request.operation == "create":
            result = _run_standard_install(request, callback, event_queue)
        elif request.operation == "import_modpack":
            result = _run_modpack_import(request, callback, event_queue)
        elif request.operation == "import_minecraft":
            result = _run_minecraft_directory_import(request, callback, event_queue)
        elif request.operation == "reinstall":
            result = _run_reinstall(request, callback, event_queue)
        elif request.operation == "duplicate_instance":
            result = _run_duplicate_instance(request, callback, event_queue)
        elif request.operation == "copy_userdata":
            result = _run_copy_userdata(request, callback, event_queue)
        else:
            raise ValueError(f"Unsupported install operation: {request.operation}")

        progress.complete()
        _queue_event(event_queue, "complete", result=result.to_payload())
    except BaseException as exc:  # noqa: BLE001
        _queue_event(
            event_queue,
            "error",
            message=str(exc),
            traceback=traceback.format_exc(),
        )


class _InstallProgressReporter:
    def __init__(self, event_queue: Any):
        self.event_queue = event_queue
        self.completed_weight = 0.0
        self.phase_weight = 0.0
        self.phase_max = 1
        self.phase_value = 0
        self.segment_start = 0.0
        self.segment_weight = 1.0
        self.install_profile = "vanilla"
        self.loader_installer_seen = False
        self.last_percent = 0
        _queue_event(self.event_queue, "max", value=100)
        _queue_event(self.event_queue, "progress", value=0)

    def begin_phase(self, weight: float) -> None:
        self.completed_weight = min(0.97, self.completed_weight + self.phase_weight)
        self.phase_weight = max(0.0, min(1.0, float(weight)))
        self.phase_max = 1
        self.phase_value = 0
        self.segment_start = 0.0
        self.segment_weight = 1.0
        self._emit()

    def set_install_profile(self, profile: str) -> None:
        self.install_profile = "mod_loader" if profile == "mod_loader" else "vanilla"
        self.loader_installer_seen = False

    def note_status(self, text: str) -> None:
        segment = self._install_progress_segment(text)
        if segment is None:
            return
        self.segment_start, self.segment_weight = segment
        self.phase_max = 1
        self.phase_value = 0
        self._emit()

    def set_phase_max(self, maximum: Any) -> None:
        try:
            self.phase_max = max(1, int(maximum))
        except (TypeError, ValueError):
            self.phase_max = 1
        self.phase_value = min(self.phase_value, self.phase_max)
        self._emit()

    def set_phase_progress(self, value: Any) -> None:
        try:
            self.phase_value = max(0, int(value))
        except (TypeError, ValueError):
            self.phase_value = 0
        self.phase_value = min(self.phase_value, self.phase_max)
        self._emit()

    def complete(self) -> None:
        self.completed_weight = 1.0
        self.phase_weight = 0.0
        self.phase_value = 0
        self.phase_max = 1
        self.segment_start = 0.0
        self.segment_weight = 1.0
        self._emit(force=100)

    def _emit(self, *, force: int | None = None) -> None:
        if force is None:
            fraction = 0.0 if self.phase_max <= 0 else self.phase_value / self.phase_max
            phase_fraction = self.segment_start + self.segment_weight * fraction
            percent = int(math.floor((self.completed_weight + self.phase_weight * phase_fraction) * 100))
            percent = min(99, max(self.last_percent, percent))
        else:
            percent = max(0, min(100, int(force)))
        self.last_percent = percent
        _queue_event(self.event_queue, "progress", value=percent)

    def _install_progress_segment(self, text: str) -> tuple[float, float] | None:
        normalized = str(text).strip().lower()
        if self.install_profile != "mod_loader":
            return _vanilla_install_progress_segment(normalized)

        if normalized == "running installer" or normalized.startswith("running processor"):
            self.loader_installer_seen = True
            return (0.56, 0.08)

        if normalized.startswith("download ") and "installer" in normalized:
            return (0.52, 0.04)

        if normalized == "download libraries":
            return (0.64, 0.12) if self.loader_installer_seen else (0.04, 0.17)
        if normalized == "download assets":
            return (0.76, 0.12) if self.loader_installer_seen else (0.21, 0.24)
        if normalized == "install java runtime":
            return (0.88, 0.04) if self.loader_installer_seen else (0.45, 0.06)
        if normalized == "installation complete":
            return (0.94, 0.0) if self.loader_installer_seen else (0.52, 0.0)
        return None


def terminate_process_tree(pid: int) -> None:
    try:
        process = psutil.Process(pid)
    except psutil.Error:
        return

    children = process.children(recursive=True)
    for child in reversed(children):
        try:
            child.terminate()
        except psutil.Error:
            continue

    try:
        process.terminate()
    except psutil.Error:
        pass

    _, alive = psutil.wait_procs(children + [process], timeout=2.5)
    for proc in alive:
        try:
            proc.kill()
        except psutil.Error:
            continue


def _run_standard_install(
    request: InstallRequest,
    callback: dict[str, Any],
    event_queue: Any,
) -> InstallResult:
    progress = _progress_reporter_from_callback(callback)
    if request.copy_source_instance_id and request.copy_user_data:
        service = LauncherService(Path(__file__).resolve().parents[2])
        source_instance = service.get_instance(request.copy_source_instance_id)
        if source_instance is None:
            raise FileNotFoundError("The selected source instance no longer exists.")

        if progress is not None:
            progress.begin_phase(0.17)
        _queue_event(event_queue, "status", text="Copying selected instance data")
        _queue_event(event_queue, "log", text=f"Copying user data from {source_instance.name}")
        _copy_selected_user_data(
            source_instance.minecraft_dir,
            Path(request.minecraft_dir),
            request.copy_user_data,
            event_queue,
            progress,
        )

    vanilla_version = _required_str(request.vanilla_version, "Minecraft version")
    if progress is not None:
        progress.begin_phase(0.77 if request.copy_user_data else 0.94)
    installed_version = _install_dependency_stack(
        vanilla_version,
        request.mod_loader_id,
        request.mod_loader_version,
        Path(request.minecraft_dir),
        callback,
        event_queue,
    )
    return InstallResult(
        name=request.name,
        vanilla_version=vanilla_version,
        installed_version=installed_version,
        mod_loader_id=request.mod_loader_id,
        mod_loader_version=request.mod_loader_version,
        icon_path=request.icon_path,
    )


def _run_reinstall(
    request: InstallRequest,
    callback: dict[str, Any],
    event_queue: Any,
) -> InstallResult:
    progress = _progress_reporter_from_callback(callback)
    service = LauncherService(Path(__file__).resolve().parents[2])
    existing_instance = service.get_instance(request.instance_id)
    if existing_instance is None:
        raise FileNotFoundError("The instance being reinstalled no longer exists.")

    vanilla_version = _required_str(request.vanilla_version, "Minecraft version")
    if request.copy_source_instance_id and request.copy_user_data:
        if progress is not None:
            progress.begin_phase(0.20)
        _queue_event(event_queue, "status", text="Restoring instance data")
        _queue_event(event_queue, "log", text=f"Restoring saved data from {existing_instance.name}")
        _copy_selected_user_data(
            existing_instance.minecraft_dir,
            Path(request.minecraft_dir),
            request.copy_user_data,
            event_queue,
            progress,
        )

    if progress is not None:
        progress.begin_phase(0.74 if request.copy_user_data else 0.94)
    installed_version = _install_dependency_stack(
        vanilla_version,
        request.mod_loader_id,
        request.mod_loader_version,
        Path(request.minecraft_dir),
        callback,
        event_queue,
    )

    return InstallResult(
        name=request.name,
        vanilla_version=vanilla_version,
        installed_version=installed_version,
        mod_loader_id=request.mod_loader_id,
        mod_loader_version=request.mod_loader_version,
        icon_path=request.icon_path,
    )


def _run_copy_userdata(
    request: InstallRequest,
    callback: dict[str, Any],
    event_queue: Any,
) -> InstallResult:
    progress = _progress_reporter_from_callback(callback)
    service = LauncherService(Path(__file__).resolve().parents[2])
    source_instance = service.get_instance(_required_str(request.copy_source_instance_id, "Copy source instance"))
    target_instance = service.get_instance(request.instance_id)
    if source_instance is None:
        raise FileNotFoundError("The selected source instance no longer exists.")
    if target_instance is None:
        raise FileNotFoundError("The target instance no longer exists.")

    stage_dir = Path(request.stage_dir)
    minecraft_dir = Path(request.minecraft_dir)

    _queue_event(event_queue, "status", text="Staging current instance")
    _queue_event(event_queue, "log", text=f"Creating a staged copy of {target_instance.name}")
    if progress is not None:
        progress.begin_phase(0.46)
    _copy_tree_with_progress(target_instance.root_dir, stage_dir, event_queue, "Staging current instance", progress)

    if request.copy_user_data:
        if progress is not None:
            progress.begin_phase(0.48)
        _queue_event(event_queue, "status", text="Replacing selected files")
        _queue_event(event_queue, "log", text=f"Replacing data from {source_instance.name}")
        _remove_selected_user_data(minecraft_dir, request.copy_user_data)
        _copy_selected_user_data(
            source_instance.minecraft_dir,
            minecraft_dir,
            request.copy_user_data,
            event_queue,
            progress,
        )

    return InstallResult(
        name=target_instance.name,
        vanilla_version=target_instance.vanilla_version,
        installed_version=target_instance.installed_version,
        mod_loader_id=target_instance.mod_loader_id,
        mod_loader_version=target_instance.mod_loader_version,
        icon_path=request.icon_path,
    )


def _run_duplicate_instance(
    request: InstallRequest,
    callback: dict[str, Any],
    event_queue: Any,
) -> InstallResult:
    progress = _progress_reporter_from_callback(callback)
    service = LauncherService(Path(__file__).resolve().parents[2])
    source_instance = service.get_instance(_required_str(request.copy_source_instance_id, "Source instance"))
    if source_instance is None:
        raise FileNotFoundError("The instance being copied no longer exists.")

    stage_dir = Path(request.stage_dir)
    _queue_event(event_queue, "status", text="Copying instance files")
    _queue_event(event_queue, "log", text=f"Copying all files from {source_instance.name}")
    if progress is not None:
        progress.begin_phase(0.94)
    _copy_tree_with_progress(source_instance.root_dir, stage_dir, event_queue, "Copying instance files", progress)

    return InstallResult(
        name=request.name,
        vanilla_version=source_instance.vanilla_version,
        installed_version=source_instance.installed_version,
        mod_loader_id=source_instance.mod_loader_id,
        mod_loader_version=source_instance.mod_loader_version,
        icon_path=request.icon_path,
    )


def _run_modpack_import(
    request: InstallRequest,
    callback: dict[str, Any],
    event_queue: Any,
) -> InstallResult:
    archive = Path(_required_str(request.modpack_path, "Modpack archive"))
    if not archive.is_file():
        raise FileNotFoundError(f"Modpack file not found: {archive}")

    _queue_event(event_queue, "log", text=f"Inspecting archive {archive.name}")
    archive_kind = _classify_archive(archive)
    _queue_event(event_queue, "log", text=f"Detected archive format: {archive_kind}")

    if archive_kind == "mrpack":
        return _import_mrpack_archive(request, archive, callback, event_queue)
    if archive_kind == "prism":
        return _import_prism_archive(request, archive, callback, event_queue)
    if archive_kind == "curseforge":
        return _import_curseforge_archive(request, archive, callback, event_queue)
    return _import_generic_archive(request, archive, callback, event_queue)


def _run_minecraft_directory_import(
    request: InstallRequest,
    callback: dict[str, Any],
    event_queue: Any,
) -> InstallResult:
    progress = _progress_reporter_from_callback(callback)
    raw_source_dir = Path(_required_str(request.minecraft_import_dir, ".minecraft folder"))
    service = LauncherService(Path(__file__).resolve().parents[2])
    source_dir = service.resolve_minecraft_import_source(raw_source_dir)
    if source_dir is None:
        valid, message = service.is_valid_minecraft_dir(raw_source_dir)
        if not valid:
            raise ValueError(message)
        raise FileNotFoundError(f"Minecraft directory not found: {raw_source_dir}")

    minecraft_dir = Path(request.minecraft_dir)
    _queue_event(event_queue, "status", text="Copying imported files")
    _queue_event(event_queue, "log", text=f"Copying {source_dir} into the new instance")
    if progress is not None:
        progress.begin_phase(0.45)
    _copy_tree_with_progress(source_dir, minecraft_dir, event_queue, "Copying imported files", progress)

    metadata = _infer_minecraft_metadata(minecraft_dir)
    if metadata is None:
        raise RuntimeError(
            "The selected .minecraft folder does not expose a launch version. "
            "Import a self-contained export or a folder with recognizable version metadata."
        )

    vanilla_version, installed_version, mod_loader_id, mod_loader_version = metadata
    if progress is not None:
        progress.begin_phase(0.49)
    installed_version = _ensure_dependency_stack(
        minecraft_dir,
        vanilla_version,
        installed_version,
        mod_loader_id,
        mod_loader_version,
        callback,
        event_queue,
    )

    staged_icon_path = _stage_folder_icon(source_dir, Path(request.stage_dir))
    resolved_name = request.name.strip()
    if not resolved_name:
        if source_dir.name == ".minecraft" and source_dir.parent.name:
            resolved_name = source_dir.parent.name
        else:
            resolved_name = source_dir.name or "Imported Instance"

    return InstallResult(
        name=resolved_name,
        vanilla_version=vanilla_version,
        installed_version=installed_version,
        mod_loader_id=mod_loader_id,
        mod_loader_version=mod_loader_version,
        icon_path=request.icon_path,
        staged_icon_path=str(staged_icon_path) if staged_icon_path else None,
    )


def _install_dependency_stack(
    vanilla_version: str,
    mod_loader_id: str | None,
    mod_loader_version: str | None,
    minecraft_dir: Path,
    callback: dict[str, Any],
    event_queue: Any,
) -> str:
    progress = _progress_reporter_from_callback(callback)
    if mod_loader_id:
        loader = minecraft_launcher_lib.mod_loader.get_mod_loader(mod_loader_id)
        loader_name = loader.get_name()
        _queue_event(event_queue, "status", text=f"Installing {loader_name}")
        _queue_event(
            event_queue,
            "log",
            text=f"Installing {loader_name} for Minecraft {vanilla_version}",
        )
        if progress is not None:
            progress.set_install_profile("mod_loader")
        try:
            return loader.install(
                vanilla_version,
                minecraft_dir,
                loader_version=mod_loader_version,
                callback=callback,
            )
        finally:
            if progress is not None:
                progress.set_install_profile("vanilla")

    _queue_event(event_queue, "status", text="Installing Minecraft")
    _queue_event(
        event_queue,
        "log",
        text=f"Installing Minecraft {vanilla_version}",
    )
    minecraft_launcher_lib.install.install_minecraft_version(
        vanilla_version,
        minecraft_dir,
        callback=callback,
    )
    return vanilla_version


def _ensure_dependency_stack(
    minecraft_dir: Path,
    vanilla_version: str,
    installed_version: str,
    mod_loader_id: str | None,
    mod_loader_version: str | None,
    callback: dict[str, Any],
    event_queue: Any,
) -> str:
    if _installed_version_present(minecraft_dir, installed_version):
        _queue_event(event_queue, "log", text="Imported files already contain launch metadata.")
        return installed_version

    _queue_event(
        event_queue,
        "log",
        text="Imported files are missing launch metadata; installing the required Minecraft files now.",
    )
    return _install_dependency_stack(
        vanilla_version,
        mod_loader_id,
        mod_loader_version,
        minecraft_dir,
        callback,
        event_queue,
    )


def _import_mrpack_archive(
    request: InstallRequest,
    archive: Path,
    callback: dict[str, Any],
    event_queue: Any,
) -> InstallResult:
    progress = _progress_reporter_from_callback(callback)
    with zipfile.ZipFile(archive, "r") as zf:
        prefix, stripped_files = _archive_file_index(zf)
        manifest_name = prefix + "modrinth.index.json"
        with zf.open(manifest_name, "r") as file_handle:
            index = json.load(file_handle)

        staged_icon_path = _stage_archive_icon(zf, stripped_files, Path(request.stage_dir))

    dependencies = index.get("dependencies", {})
    vanilla_version = _required_str(dependencies.get("minecraft"), "Modrinth Minecraft version")
    mod_loader_id, mod_loader_version = _loader_from_mrpack_dependencies(dependencies)

    _queue_event(event_queue, "status", text="Importing modpack")
    _queue_event(event_queue, "log", text=f"Installing Modrinth pack {archive.name}")
    if progress is not None:
        progress.begin_phase(0.94)
    minecraft_launcher_lib.mrpack.install_mrpack(
        archive,
        Path(request.minecraft_dir),
        modpack_directory=Path(request.minecraft_dir),
        callback=callback,
    )

    resolved_name = request.name.strip() or str(index.get("name") or archive.stem)
    installed_version = minecraft_launcher_lib.mrpack.get_mrpack_launch_version(archive)

    return InstallResult(
        name=resolved_name,
        vanilla_version=vanilla_version,
        installed_version=installed_version,
        mod_loader_id=mod_loader_id,
        mod_loader_version=mod_loader_version,
        icon_path=request.icon_path,
        staged_icon_path=str(staged_icon_path) if staged_icon_path else None,
    )


def _import_prism_archive(
    request: InstallRequest,
    archive: Path,
    callback: dict[str, Any],
    event_queue: Any,
) -> InstallResult:
    progress = _progress_reporter_from_callback(callback)
    minecraft_dir = Path(request.minecraft_dir)
    stage_dir = Path(request.stage_dir)

    with zipfile.ZipFile(archive, "r") as zf:
        prefix, stripped_files = _archive_file_index(zf)
        mmc_manifest = _load_json_from_zip(zf, prefix + "mmc-pack.json")
        instance_cfg_text = _read_text_from_zip(zf, prefix + "instance.cfg")
        staged_icon_path = _stage_archive_icon(zf, stripped_files, stage_dir)

        if any(name.startswith("patches/") or name.startswith("jarmods/") for name in stripped_files.values()):
            raise RuntimeError(
                "This MultiMC/Prism export depends on patch or jarmod metadata that this build cannot launch safely yet."
            )

        vanilla_version, mod_loader_id, mod_loader_version = _metadata_from_mmc_manifest(mmc_manifest)
        if progress is not None:
            progress.begin_phase(0.55)
        installed_version = _install_dependency_stack(
            vanilla_version,
            mod_loader_id,
            mod_loader_version,
            minecraft_dir,
            callback,
            event_queue,
        )

        _queue_event(event_queue, "status", text="Extracting imported files")
        mappings = []
        for original_name, stripped_name in stripped_files.items():
            if stripped_name.startswith(".minecraft/"):
                mappings.append((original_name, stripped_name[len(".minecraft/"):]))
        if not mappings:
            raise RuntimeError("This Prism/MultiMC export does not contain a .minecraft folder.")
        if progress is not None:
            progress.begin_phase(0.39)
        _extract_archive_mappings(zf, mappings, minecraft_dir, event_queue, "Extracting imported files", progress)

    config_name = _name_from_instance_cfg(instance_cfg_text)
    resolved_name = request.name.strip() or config_name or archive.stem
    return InstallResult(
        name=resolved_name,
        vanilla_version=vanilla_version,
        installed_version=installed_version,
        mod_loader_id=mod_loader_id,
        mod_loader_version=mod_loader_version,
        icon_path=request.icon_path,
        staged_icon_path=str(staged_icon_path) if staged_icon_path else None,
    )


def _import_curseforge_archive(
    request: InstallRequest,
    archive: Path,
    callback: dict[str, Any],
    event_queue: Any,
) -> InstallResult:
    progress = _progress_reporter_from_callback(callback)
    minecraft_dir = Path(request.minecraft_dir)
    stage_dir = Path(request.stage_dir)

    with zipfile.ZipFile(archive, "r") as zf:
        prefix, stripped_files = _archive_file_index(zf)
        manifest = _load_json_from_zip(zf, prefix + "manifest.json")
        staged_icon_path = _stage_archive_icon(zf, stripped_files, stage_dir)

        file_entries = manifest.get("files") or []
        if file_entries:
            raise RuntimeError(
                "This CurseForge export references external CurseForge-hosted files. "
                "This build does not ship a CurseForge download API, so please import a .mrpack, "
                "a self-contained Prism/MultiMC export, or a full .minecraft folder instead."
            )

        minecraft_block = manifest.get("minecraft") or {}
        vanilla_version = _required_str(minecraft_block.get("version"), "CurseForge Minecraft version")
        mod_loader_id, mod_loader_version = _loader_from_curseforge_manifest(minecraft_block)
        if progress is not None:
            progress.begin_phase(0.55)
        installed_version = _install_dependency_stack(
            vanilla_version,
            mod_loader_id,
            mod_loader_version,
            minecraft_dir,
            callback,
            event_queue,
        )

        mappings = []
        for original_name, stripped_name in stripped_files.items():
            if stripped_name.startswith("overrides/"):
                mappings.append((original_name, stripped_name[len("overrides/"):]))
        _queue_event(event_queue, "status", text="Extracting imported files")
        if progress is not None:
            progress.begin_phase(0.39)
        _extract_archive_mappings(zf, mappings, minecraft_dir, event_queue, "Extracting imported files", progress)

    resolved_name = request.name.strip() or str(manifest.get("name") or archive.stem)
    return InstallResult(
        name=resolved_name,
        vanilla_version=vanilla_version,
        installed_version=installed_version,
        mod_loader_id=mod_loader_id,
        mod_loader_version=mod_loader_version,
        icon_path=request.icon_path,
        staged_icon_path=str(staged_icon_path) if staged_icon_path else None,
    )


def _import_generic_archive(
    request: InstallRequest,
    archive: Path,
    callback: dict[str, Any],
    event_queue: Any,
) -> InstallResult:
    progress = _progress_reporter_from_callback(callback)
    minecraft_dir = Path(request.minecraft_dir)
    stage_dir = Path(request.stage_dir)

    with zipfile.ZipFile(archive, "r") as zf:
        prefix, stripped_files = _archive_file_index(zf)
        staged_icon_path = _stage_archive_icon(zf, stripped_files, stage_dir)
        mappings: list[tuple[str, str]] = []
        root_mode = "flat"

        if any(name.startswith(".minecraft/") for name in stripped_files.values()):
            root_mode = "minecraft-root"
            for original_name, stripped_name in stripped_files.items():
                if stripped_name.startswith(".minecraft/"):
                    mappings.append((original_name, stripped_name[len(".minecraft/"):]))
        else:
            for original_name, stripped_name in stripped_files.items():
                if stripped_name in ARCHIVE_ICON_CANDIDATES:
                    continue
                if stripped_name.endswith("manifest.json") or stripped_name.endswith("mmc-pack.json") or stripped_name.endswith("instance.cfg"):
                    continue
                mappings.append((original_name, stripped_name))

        _queue_event(event_queue, "status", text="Extracting imported files")
        _queue_event(event_queue, "log", text=f"Extracting archive in {root_mode} mode")
        if progress is not None:
            progress.begin_phase(0.45)
        _extract_archive_mappings(zf, mappings, minecraft_dir, event_queue, "Extracting imported files", progress)

    metadata = _infer_minecraft_metadata(minecraft_dir)
    if metadata is None:
        raise RuntimeError(
            "The selected archive was extracted, but the launcher could not determine a Minecraft version from it."
        )

    vanilla_version, installed_version, mod_loader_id, mod_loader_version = metadata
    if progress is not None:
        progress.begin_phase(0.49)
    installed_version = _ensure_dependency_stack(
        minecraft_dir,
        vanilla_version,
        installed_version,
        mod_loader_id,
        mod_loader_version,
        callback,
        event_queue,
    )

    resolved_name = request.name.strip() or archive.stem
    return InstallResult(
        name=resolved_name,
        vanilla_version=vanilla_version,
        installed_version=installed_version,
        mod_loader_id=mod_loader_id,
        mod_loader_version=mod_loader_version,
        icon_path=request.icon_path,
        staged_icon_path=str(staged_icon_path) if staged_icon_path else None,
    )


def _installed_version_present(minecraft_dir: Path, installed_version: str) -> bool:
    version_dir = minecraft_dir / "versions" / installed_version
    if not version_dir.is_dir():
        return False
    json_file = version_dir / f"{installed_version}.json"
    return json_file.is_file()


def _infer_minecraft_metadata(
    minecraft_dir: Path,
) -> tuple[str, str, str | None, str | None] | None:
    launcher_version = _read_last_version_id(minecraft_dir)
    if launcher_version:
        version_json = minecraft_dir / "versions" / launcher_version / f"{launcher_version}.json"
        if version_json.is_file():
            metadata = _metadata_from_version_json(version_json)
            if metadata:
                return metadata

        parsed = _parse_installed_version(launcher_version)
        if parsed[0]:
            return (
                parsed[0],
                launcher_version,
                parsed[1],
                parsed[2],
            )

    version_candidates = sorted(
        minecraft_dir.glob("versions/*/*.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for candidate in version_candidates:
        metadata = _metadata_from_version_json(candidate)
        if metadata:
            return metadata

    for candidate in (
        minecraft_dir / "bin" / "version.json",
        minecraft_dir / "version.json",
    ):
        metadata = _metadata_from_version_json(candidate)
        if metadata:
            return metadata

    return None


def _metadata_from_version_json(
    json_path: Path,
) -> tuple[str, str, str | None, str | None] | None:
    if not json_path.is_file():
        return None

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    installed_version = _optional_str(data.get("id")) or json_path.stem
    inherits_from = _optional_str(data.get("inheritsFrom"))
    vanilla_version, mod_loader_id, mod_loader_version = _parse_installed_version(
        installed_version,
        inherits_from,
    )
    if vanilla_version:
        return vanilla_version, installed_version, mod_loader_id, mod_loader_version

    if inherits_from:
        return inherits_from, installed_version, mod_loader_id, mod_loader_version

    return None


def _read_last_version_id(minecraft_dir: Path) -> str | None:
    launcher_profiles = minecraft_dir / "launcher_profiles.json"
    if not launcher_profiles.is_file():
        return None

    try:
        data = json.loads(launcher_profiles.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    profiles = data.get("profiles")
    if not isinstance(profiles, dict):
        return None

    selected_profile = _optional_str(data.get("selectedProfile"))
    if selected_profile and isinstance(profiles.get(selected_profile), dict):
        version_id = _optional_str(profiles[selected_profile].get("lastVersionId"))
        if version_id:
            return version_id

    for profile in profiles.values():
        if not isinstance(profile, dict):
            continue
        version_id = _optional_str(profile.get("lastVersionId"))
        if version_id:
            return version_id
    return None


def _archive_file_index(zf: zipfile.ZipFile) -> tuple[str, dict[str, str]]:
    file_names = [name for name in zf.namelist() if not name.endswith("/")]
    if not file_names:
        return "", {}

    top_levels = {PurePosixPath(name).parts[0] for name in file_names if PurePosixPath(name).parts}
    prefix = ""
    if len(top_levels) == 1:
        only_root = next(iter(top_levels))
        stripped = {name: name[len(only_root) + 1 :] for name in file_names if name.startswith(f"{only_root}/")}
        if _looks_like_archive_root(stripped.values()):
            prefix = f"{only_root}/"
            return prefix, stripped
    return prefix, {name: name for name in file_names}


def _looks_like_archive_root(names: Any) -> bool:
    known_markers = (
        "modrinth.index.json",
        "manifest.json",
        "mmc-pack.json",
        "instance.cfg",
        ".minecraft/",
        "mods/",
        "config/",
        "bin/",
        "versions/",
    )
    for name in names:
        if any(str(name).startswith(marker) or str(name) == marker for marker in known_markers):
            return True
    return False


def _classify_archive(archive: Path) -> str:
    with zipfile.ZipFile(archive, "r") as zf:
        _, stripped_files = _archive_file_index(zf)
        names = set(stripped_files.values())
        if "modrinth.index.json" in names or archive.suffix.lower() == ".mrpack":
            return "mrpack"
        if "mmc-pack.json" in names or "instance.cfg" in names:
            return "prism"
        if "manifest.json" in names:
            return "curseforge"
        return "generic"


def _load_json_from_zip(zf: zipfile.ZipFile, file_name: str) -> dict[str, Any]:
    with zf.open(file_name, "r") as file_handle:
        return json.load(file_handle)


def _read_text_from_zip(zf: zipfile.ZipFile, file_name: str) -> str:
    try:
        with zf.open(file_name, "r") as file_handle:
            return file_handle.read().decode("utf-8", errors="replace")
    except KeyError:
        return ""


def _metadata_from_mmc_manifest(
    mmc_manifest: dict[str, Any],
) -> tuple[str, str | None, str | None]:
    components = mmc_manifest.get("components")
    if not isinstance(components, list):
        raise RuntimeError("mmc-pack.json does not contain a components list.")

    vanilla_version: str | None = None
    mod_loader_id: str | None = None
    mod_loader_version: str | None = None

    for component in components:
        if not isinstance(component, dict):
            continue
        uid = _optional_str(component.get("uid"))
        version = _optional_str(component.get("version"))
        if uid == "net.minecraft" and version:
            vanilla_version = version
            continue
        if uid in MMCPACK_LOADER_UIDS and version:
            mod_loader_id = MMCPACK_LOADER_UIDS[uid]
            mod_loader_version = version

    if not vanilla_version:
        raise RuntimeError("mmc-pack.json does not expose a Minecraft version.")
    return vanilla_version, mod_loader_id, mod_loader_version


def _name_from_instance_cfg(instance_cfg_text: str) -> str | None:
    if not instance_cfg_text.strip():
        return None

    parser = configparser.ConfigParser()
    try:
        parser.read_string(instance_cfg_text)
    except configparser.Error:
        return None

    if parser.has_option("General", "name"):
        return _optional_str(parser.get("General", "name"))
    return None


def _loader_from_mrpack_dependencies(dependencies: dict[str, Any]) -> tuple[str | None, str | None]:
    for key, loader_id in (
        ("forge", "forge"),
        ("neoforge", "neoforge"),
        ("fabric-loader", "fabric"),
        ("quilt-loader", "quilt"),
    ):
        version = _optional_str(dependencies.get(key))
        if version:
            return loader_id, version
    return None, None


def _loader_from_curseforge_manifest(minecraft_block: dict[str, Any]) -> tuple[str | None, str | None]:
    mod_loaders = minecraft_block.get("modLoaders") or []
    if not isinstance(mod_loaders, list):
        return None, None

    selected_entry = None
    for entry in mod_loaders:
        if isinstance(entry, dict) and entry.get("primary"):
            selected_entry = entry
            break
    if selected_entry is None and mod_loaders:
        selected_entry = mod_loaders[0]

    if not isinstance(selected_entry, dict):
        return None, None

    loader_id = _optional_str(selected_entry.get("id"))
    if not loader_id:
        return None, None

    lowered = loader_id.lower()
    for prefix, mapped_id in (
        ("forge-", "forge"),
        ("neoforge-", "neoforge"),
        ("fabric-", "fabric"),
        ("fabric-loader-", "fabric"),
        ("quilt-", "quilt"),
        ("quilt-loader-", "quilt"),
    ):
        if lowered.startswith(prefix):
            return mapped_id, loader_id[len(prefix) :]
    return None, None


def _parse_installed_version(
    installed_version: str,
    fallback_vanilla: str | None = None,
) -> tuple[str | None, str | None, str | None]:
    if installed_version.startswith("fabric-loader-"):
        remainder = installed_version[len("fabric-loader-") :]
        loader_version, _, vanilla_version = remainder.rpartition("-")
        return vanilla_version or fallback_vanilla, "fabric", loader_version or None

    if installed_version.startswith("quilt-loader-"):
        remainder = installed_version[len("quilt-loader-") :]
        loader_version, _, vanilla_version = remainder.rpartition("-")
        return vanilla_version or fallback_vanilla, "quilt", loader_version or None

    if "-forge-" in installed_version:
        vanilla_version, _, loader_version = installed_version.partition("-forge-")
        return vanilla_version or fallback_vanilla, "forge", loader_version or None

    if installed_version.startswith("neoforge-"):
        loader_version = installed_version[len("neoforge-") :]
        return fallback_vanilla, "neoforge", loader_version or None

    return installed_version or fallback_vanilla, None, None


def _stage_archive_icon(
    zf: zipfile.ZipFile,
    stripped_files: dict[str, str],
    stage_dir: Path,
) -> Path | None:
    normalized_lookup = {name.lower(): original for original, name in stripped_files.items()}
    for candidate in ARCHIVE_ICON_CANDIDATES:
        original_name = normalized_lookup.get(candidate.lower())
        if not original_name:
            continue
        return _write_staged_icon(zf.read(original_name), stage_dir, Path(candidate).name)
    return None


def _stage_folder_icon(source_dir: Path, stage_dir: Path) -> Path | None:
    for candidate in ("icon.png", "pack.png", "instance.png", "logo.png"):
        icon_path = source_dir / candidate
        if icon_path.is_file():
            target = stage_dir / f".import-{candidate}"
            shutil.copy2(icon_path, target)
            return target
    return None


def _write_staged_icon(content: bytes, stage_dir: Path, file_name: str) -> Path:
    target = stage_dir / f".import-{Path(file_name).name}"
    target.write_bytes(content)
    return target


def _copy_selected_user_data(
    source_root: Path,
    destination_root: Path,
    selected_entries: list[str],
    event_queue: Any,
    progress: "_InstallProgressReporter | None" = None,
) -> None:
    entries = _sanitize_copy_user_data(selected_entries)
    if not entries:
        _set_progress_max(event_queue, progress, 1)
        _set_progress_value(event_queue, progress, 1)
        return

    files_to_copy: list[tuple[Path, Path]] = []
    empty_dirs: list[Path] = []
    for entry_name in entries:
        source_path = _safe_local_path_join(source_root, entry_name)
        if not source_path.exists():
            continue

        if source_path.is_dir():
            directory_files = [path for path in source_path.rglob("*") if path.is_file()]
            if not directory_files:
                empty_dirs.append(destination_root / entry_name)
                continue
            for file_path in directory_files:
                files_to_copy.append((file_path, destination_root / file_path.relative_to(source_root)))
        else:
            files_to_copy.append((source_path, destination_root / entry_name))

    for directory in empty_dirs:
        directory.mkdir(parents=True, exist_ok=True)

    _set_progress_max(event_queue, progress, max(1, len(files_to_copy)))
    if not files_to_copy:
        _set_progress_value(event_queue, progress, 1)
        return

    for index, (source_path, target_path) in enumerate(files_to_copy, start=1):
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        _set_progress_value(event_queue, progress, index)

    _queue_event(event_queue, "status", text="Copying selected instance data")


def _remove_selected_user_data(destination_root: Path, selected_entries: list[str]) -> None:
    for entry_name in _sanitize_copy_user_data(selected_entries):
        target_path = _safe_local_path_join(destination_root, entry_name)
        if not target_path.exists():
            continue
        if target_path.is_dir():
            shutil.rmtree(target_path, ignore_errors=True)
        else:
            target_path.unlink(missing_ok=True)


def _copy_tree_with_progress(
    source: Path,
    destination: Path,
    event_queue: Any,
    status_text: str,
    progress: "_InstallProgressReporter | None" = None,
) -> None:
    files = [path for path in source.rglob("*") if path.is_file()]
    _set_progress_max(event_queue, progress, max(1, len(files)))
    if not files:
        _set_progress_value(event_queue, progress, 1)
        return

    for index, file_path in enumerate(files, start=1):
        relative_path = file_path.relative_to(source)
        target = destination / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, target)
        _set_progress_value(event_queue, progress, index)

    _queue_event(event_queue, "status", text=status_text)


def _extract_archive_mappings(
    zf: zipfile.ZipFile,
    mappings: list[tuple[str, str]],
    destination_root: Path,
    event_queue: Any,
    status_text: str,
    progress: "_InstallProgressReporter | None" = None,
) -> None:
    if not mappings:
        _set_progress_max(event_queue, progress, 1)
        _set_progress_value(event_queue, progress, 1)
        return

    _set_progress_max(event_queue, progress, len(mappings))
    for index, (archive_name, destination_name) in enumerate(mappings, start=1):
        if not destination_name:
            continue
        target_path = _safe_path_join(destination_root, destination_name)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(archive_name, "r") as source_handle:
            with target_path.open("wb") as target_handle:
                shutil.copyfileobj(source_handle, target_handle)
        _set_progress_value(event_queue, progress, index)
    _queue_event(event_queue, "status", text=status_text)


def _safe_path_join(root: Path, relative_name: str) -> Path:
    relative_path = PurePosixPath(relative_name)
    safe_parts = [part for part in relative_path.parts if part not in ("", ".", "..")]
    candidate = root.joinpath(*safe_parts).resolve()
    resolved_root = root.resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise RuntimeError(f"Archive entry would escape the instance directory: {relative_name}") from exc
    return candidate


def _safe_local_path_join(root: Path, relative_name: str) -> Path:
    safe_parts = [part for part in Path(relative_name).parts if part not in ("", ".", "..")]
    candidate = root.joinpath(*safe_parts).resolve()
    resolved_root = root.resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise RuntimeError(f"Path would escape the instance directory: {relative_name}") from exc
    return candidate


def _progress_reporter_from_callback(callback: dict[str, Any]) -> "_InstallProgressReporter | None":
    progress = callback.get("_progress")
    return progress if isinstance(progress, _InstallProgressReporter) else None


def _set_progress_max(event_queue: Any, progress: "_InstallProgressReporter | None", maximum: int) -> None:
    if progress is not None:
        progress.set_phase_max(maximum)
    else:
        _queue_event(event_queue, "max", value=max(1, int(maximum)))


def _set_progress_value(event_queue: Any, progress: "_InstallProgressReporter | None", value: int) -> None:
    if progress is not None:
        progress.set_phase_progress(value)
    else:
        _queue_event(event_queue, "progress", value=int(value))


def _install_status(event_queue: Any, text: str, progress: "_InstallProgressReporter | None" = None) -> None:
    if progress is not None:
        progress.note_status(text)
    _queue_event(event_queue, "status", text=_summarize_install_status(text))
    _queue_event(event_queue, "log", text=text)


def _vanilla_install_progress_segment(normalized: str) -> tuple[float, float] | None:
    if normalized == "download libraries":
        return (0.08, 0.27)
    if normalized == "download assets":
        return (0.35, 0.38)
    if normalized == "install java runtime":
        return (0.73, 0.17)
    if normalized == "running installer":
        return (0.90, 0.06)
    if normalized == "installation complete":
        return (0.96, 0.0)
    return None


def _summarize_install_status(text: str) -> str:
    normalized = text.lower()
    if "requesting" in normalized or "downloading" in normalized:
        return "Downloading files..."
    if "extract" in normalized:
        return "Extracting files..."
    if "forge" in normalized or "fabric" in normalized or "quilt" in normalized or "neo" in normalized:
        return "Installing mod loader..."
    if "version" in normalized or "jar" in normalized or "asset" in normalized:
        return "Installing Minecraft files..."
    if "prepare" in normalized:
        return "Preparing instance directory..."
    return "Installing instance..."


def _queue_event(event_queue: Any, event_type: str, **payload: Any) -> None:
    event_queue.put({"type": event_type, **payload})


def _assert_directory_writable(directory: Path, label: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(prefix=".notg-write-", dir=directory, delete=True):
            pass
    except OSError as exc:
        raise RuntimeError(f"The {label} is not writable: {directory}") from exc


def _minimum_java_major_for_minecraft_version(version: str) -> int:
    normalized = str(version).strip().lower()
    release_match = re.match(r"^1\.(\d+)", normalized)
    if release_match:
        minor = int(release_match.group(1))
        if minor >= 26:
            return 25
        if minor >= 21:
            return 21
        if minor >= 18:
            return 17
        if minor == 17:
            return 16
        return 8

    snapshot_match = re.match(r"^(\d{2})w", normalized)
    if snapshot_match and int(snapshot_match.group(1)) >= 26:
        return 25
    if snapshot_match and int(snapshot_match.group(1)) >= 24:
        return 21
    return 8


def _java_executable_name() -> str:
    return "java.exe" if os.name == "nt" else "java"


def _java_candidate_from_executable(executable: str | os.PathLike, label: str) -> JavaRuntimeCandidate | None:
    path = Path(executable)
    if not path.is_file():
        return None
    try:
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()  # type: ignore[attr-defined]
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore[attr-defined]
            startupinfo.wShowWindow = subprocess.SW_HIDE  # type: ignore[attr-defined]
        completed = subprocess.run(
            [str(path), "-version"],
            capture_output=True,
            text=True,
            timeout=5,
            startupinfo=startupinfo,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    version_text = f"{completed.stdout}\n{completed.stderr}"
    major = _parse_java_major(version_text)
    if major <= 0:
        return None
    return JavaRuntimeCandidate(str(path.resolve()), major, label)


def _parse_java_major(version_text: str) -> int:
    match = re.search(r'version\s+"([^"]+)"', version_text)
    if not match:
        match = re.search(r"\b(?:openjdk|java)\s+version\s+([0-9][^\s]*)", version_text, flags=re.IGNORECASE)
    if not match:
        return 0

    version = match.group(1)
    parts = re.findall(r"\d+", version)
    if not parts:
        return 0
    if parts[0] == "1" and len(parts) > 1:
        return int(parts[1])
    return int(parts[0])


def _normalize_minecraft_version_argument(command: list[str], vanilla_version: str) -> None:
    try:
        version_index = command.index("--version")
    except ValueError:
        return
    value_index = version_index + 1
    if value_index < len(command):
        command[value_index] = vanilla_version


class _NbtParseError(ValueError):
    pass


class _NbtReader:
    def __init__(self, data: bytes):
        self._data = memoryview(data)
        self._offset = 0

    def _read(self, length: int) -> bytes:
        if self._offset + length > len(self._data):
            raise _NbtParseError("Unexpected end of NBT data.")
        chunk = self._data[self._offset : self._offset + length].tobytes()
        self._offset += length
        return chunk

    def read_u8(self) -> int:
        return self._read(1)[0]

    def read_i16(self) -> int:
        return int.from_bytes(self._read(2), "big", signed=True)

    def read_u16(self) -> int:
        return int.from_bytes(self._read(2), "big", signed=False)

    def read_i32(self) -> int:
        return int.from_bytes(self._read(4), "big", signed=True)

    def read_string(self) -> str:
        length = self.read_u16()
        return self._read(length).decode("utf-8", errors="replace")

    def read_payload(self, tag_type: int) -> Any:
        if tag_type == 0:
            return None
        if tag_type == 1:
            return int.from_bytes(self._read(1), "big", signed=True)
        if tag_type == 2:
            return self.read_i16()
        if tag_type == 3:
            return self.read_i32()
        if tag_type == 4:
            return int.from_bytes(self._read(8), "big", signed=True)
        if tag_type == 5:
            self._read(4)
            return None
        if tag_type == 6:
            self._read(8)
            return None
        if tag_type == 7:
            self._read(max(0, self.read_i32()))
            return None
        if tag_type == 8:
            return self.read_string()
        if tag_type == 9:
            child_type = self.read_u8()
            length = max(0, self.read_i32())
            return [self.read_payload(child_type) for _ in range(length)]
        if tag_type == 10:
            compound: dict[str, Any] = {}
            while True:
                child_type = self.read_u8()
                if child_type == 0:
                    break
                name = self.read_string()
                compound[name] = self.read_payload(child_type)
            return compound
        if tag_type == 11:
            self._read(max(0, self.read_i32()) * 4)
            return None
        if tag_type == 12:
            self._read(max(0, self.read_i32()) * 8)
            return None
        raise _NbtParseError(f"Unsupported NBT tag type: {tag_type}")


def _read_servers_dat_addresses(path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        data = path.read_bytes()
        if data.startswith(b"\x1f\x8b"):
            data = gzip.decompress(data)
        reader = _NbtReader(data)
        root_type = reader.read_u8()
        if root_type != 10:
            return []
        reader.read_string()
        root = reader.read_payload(root_type)
    except (OSError, EOFError, _NbtParseError, gzip.BadGzipFile, UnicodeDecodeError):
        return []

    if not isinstance(root, dict):
        return []
    servers = root.get("servers")
    if not isinstance(servers, list):
        return []

    addresses: list[str] = []
    for entry in servers:
        if not isinstance(entry, dict):
            continue
        address = _optional_str(entry.get("ip"))
        if address:
            addresses.append(address)
    return addresses


def _detect_minecraft_activity_from_log(
    text: str,
    *,
    server_addresses: list[str] | None = None,
    resolver: Callable[[str, int | None], set[str]] | None = None,
) -> str | None:
    activity: str | None = None
    configured_addresses = list(server_addresses or [])
    for line in text.splitlines():
        lowered = line.lower()
        if _is_minecraft_disconnect_log_line(lowered):
            activity = None
            continue

        connect_match = re.search(r"Connecting to\s+(.+?)(?:,\s*(\d+)|\s*$)", line, flags=re.IGNORECASE)
        if connect_match:
            server = connect_match.group(1).strip()
            port = _optional_int(connect_match.group(2))
            if server:
                display_address = _resolve_display_server_address(
                    server,
                    port,
                    configured_addresses,
                    resolver=resolver,
                )
                activity = _format_server_activity(display_address)
                continue

        if (
            "starting integrated minecraft server" in lowered
            or "starting integrated server" in lowered
            or "integrated server" in lowered
            or "saving and pausing game" in lowered
        ):
            activity = "Playing in singleplayer"
    return activity


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_server_activity(address: str) -> str:
    normalized = address.lower()
    if "mineberry" in normalized or "bw-lobby" in normalized or "65.20.73.213" in normalized:
        return "Playing in Mineberry"
    if "amplifiedsmp" in normalized:
        return "Playing in Amplified SMP"
    return f"Playing in {address}"


def _is_minecraft_disconnect_log_line(lowered_line: str) -> bool:
    disconnect_markers = (
        "disconnecting from server",
        "disconnected from server",
        "disconnecting packet listener",
        "lost connection",
        "connection lost",
        "timed out",
        "timeout",
        "server closed",
        "connection reset",
        "connection refused",
        "end of stream",
        "internal exception",
        "aborting connection",
        "closed connection",
        "stopping client connection",
    )
    return any(marker in lowered_line for marker in disconnect_markers)


def _resolve_display_server_address(
    logged_address: str,
    logged_port: int | None,
    configured_addresses: list[str],
    *,
    resolver: Callable[[str, int | None], set[str]] | None = None,
) -> str:
    logged_host, parsed_logged_port = _split_server_address(logged_address)
    logged_port = logged_port or parsed_logged_port
    normalized_logged_host = _normalize_server_host(logged_host)
    if not normalized_logged_host:
        return logged_address

    for configured_address in configured_addresses:
        configured_host, configured_port = _split_server_address(configured_address)
        if not _ports_match(logged_port, configured_port):
            continue
        if _normalize_server_host(configured_host).lower() == normalized_logged_host.lower():
            return configured_address

    if not _is_ip_address(normalized_logged_host):
        return logged_address

    logged_ip = _parse_ip_address(normalized_logged_host)
    if logged_ip is None:
        return logged_address

    for configured_address in configured_addresses:
        configured_host, configured_port = _split_server_address(configured_address)
        if not _ports_match(logged_port, configured_port):
            continue
        configured_ip = _parse_ip_address(configured_host)
        if configured_ip is not None and configured_ip == logged_ip:
            return configured_address

    if resolver is None:
        return _single_configured_address_for_port(configured_addresses, logged_port) or logged_address

    for configured_address in configured_addresses:
        configured_host, configured_port = _split_server_address(configured_address)
        if not _ports_match(logged_port, configured_port):
            continue
        resolved_hosts = resolver(configured_host, configured_port or logged_port)
        if any(_parse_ip_address(host) == logged_ip for host in resolved_hosts):
            return configured_address

    return _single_configured_address_for_port(configured_addresses, logged_port) or logged_address


def _single_configured_address_for_port(configured_addresses: list[str], logged_port: int | None) -> str | None:
    candidates = []
    for configured_address in configured_addresses:
        _, configured_port = _split_server_address(configured_address)
        if _ports_match(logged_port, configured_port):
            candidates.append(configured_address)
    return candidates[0] if len(candidates) == 1 else None


def _split_server_address(address: str) -> tuple[str, int | None]:
    text = str(address).strip()
    if text.startswith("/"):
        text = text[1:].strip()
    if text.startswith("[") and "]" in text:
        host, _, remainder = text[1:].partition("]")
        if remainder.startswith(":"):
            return host, _optional_int(remainder[1:])
        return host, None
    if text.count(":") == 1:
        host, port = text.rsplit(":", 1)
        parsed_port = _optional_int(port)
        if parsed_port is not None:
            return host, parsed_port
    return text, None


def _normalize_server_host(host: str) -> str:
    normalized = str(host).strip().strip("[]")
    if normalized.startswith("/"):
        normalized = normalized[1:].strip()
    return normalized.rstrip(".")


def _ports_match(logged_port: int | None, configured_port: int | None) -> bool:
    return logged_port is None or configured_port is None or logged_port == configured_port


def _is_ip_address(host: str) -> bool:
    return _parse_ip_address(host) is not None


def _parse_ip_address(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(_normalize_server_host(host))
    except ValueError:
        return None


def _friendly_asset_name(value: str) -> str:
    cleaned = re.sub(r"[_\-]+", " ", str(value)).strip()
    return cleaned.title() if cleaned else "Background"


def _default_background_sort_key(path: Path) -> tuple[int, str]:
    return (0 if path.name.lower() == "Black Hole.mp4" else 1, path.name.lower())


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)

    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            pass
        else:
            return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    return datetime.min.replace(tzinfo=timezone.utc)


def _offline_uuid(player_name: str) -> str:
    digest = bytearray(hashlib.md5(f"OfflinePlayer:{player_name}".encode("utf-8")).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(digest)))


def _format_release_date(value: Any) -> str:
    if isinstance(value, datetime):
        return f"{value.month}/{value.day}/{str(value.year)[-2:]}"
    return "Unknown"


def _format_file_timestamp(path: Path) -> str:
    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return "Unknown"
    return modified.strftime("%m/%d/%y %I:%M %p")


def _format_screenshot_label(path: Path) -> str:
    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return path.stem
    return modified.strftime("%Y-%m-%d %I:%M:%S %p")


def _format_version_type(version_type: str) -> str:
    normalized = version_type.replace("_", " ").strip()
    if not normalized:
        return "Unknown"
    return normalized.title()


def _slugify(text: str) -> str:
    result = []
    previous_dash = False
    for char in text.lower():
        if char.isalnum():
            result.append(char)
            previous_dash = False
            continue
        if not previous_dash:
            result.append("-")
            previous_dash = True

    return "".join(result).strip("-")


def _slugify_filename(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "-", text.strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-_")
    return cleaned


def _friendly_archive_name(file_name: str) -> str:
    display_name = file_name[:-9] if file_name.lower().endswith(".disabled") else file_name
    stem = Path(display_name).stem
    return stem.replace("_", " ").replace("-", " ").strip() or stem


def _read_mod_metadata(path: Path, cache_root: Path) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "name": _friendly_archive_name(path.name),
        "version": "Unknown",
        "provider": "Unknown",
        "icon_path": None,
    }

    try:
        with zipfile.ZipFile(path, "r") as archive:
            names = set(archive.namelist())
            manifest = _read_manifest_properties(archive)

            if "fabric.mod.json" in names:
                data = json.loads(_read_text_from_zip(archive, "fabric.mod.json") or "{}")
                metadata.update(_mod_metadata_from_fabric(data))
            elif "quilt.mod.json" in names:
                data = json.loads(_read_text_from_zip(archive, "quilt.mod.json") or "{}")
                metadata.update(_mod_metadata_from_quilt(data))
            elif "META-INF/neoforge.mods.toml" in names:
                metadata.update(_mod_metadata_from_toml(_read_text_from_zip(archive, "META-INF/neoforge.mods.toml")))
            elif "META-INF/mods.toml" in names:
                metadata.update(_mod_metadata_from_toml(_read_text_from_zip(archive, "META-INF/mods.toml")))
            elif "mcmod.info" in names:
                raw = _read_text_from_zip(archive, "mcmod.info")
                if raw:
                    metadata.update(_mod_metadata_from_mcmod_info(json.loads(raw)))

            icon_reference = metadata.get("icon_reference")
            if not metadata.get("version") or metadata.get("version") == "${file.jarVersion}":
                metadata["version"] = manifest.get("Implementation-Version") or manifest.get("Specification-Version") or "Unknown"
            if not metadata.get("name") or metadata.get("name") == "Unknown":
                metadata["name"] = manifest.get("Implementation-Title") or metadata["name"]

            extracted_icon = _extract_mod_icon(archive, icon_reference, path, cache_root)
            if extracted_icon is not None:
                metadata["icon_path"] = str(extracted_icon.resolve())
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError, tomllib.TOMLDecodeError):
        return metadata

    metadata.pop("icon_reference", None)
    return metadata


def _mod_metadata_from_fabric(data: dict[str, Any]) -> dict[str, Any]:
    authors = data.get("authors")
    contact = data.get("contact") if isinstance(data.get("contact"), dict) else {}
    icon_reference = data.get("icon")
    if isinstance(icon_reference, dict):
        ordered_icons = [value for _, value in sorted(icon_reference.items(), key=lambda item: item[0])]
        icon_reference = ordered_icons[-1] if ordered_icons else None
    return {
        "name": _optional_str(data.get("name")) or _optional_str(data.get("id")) or "Unknown",
        "version": _optional_str(data.get("version")) or "Unknown",
        "provider": _guess_provider(contact.get("homepage"), contact.get("sources"), authors),
        "icon_reference": _optional_str(icon_reference),
    }


def _mod_metadata_from_quilt(data: dict[str, Any]) -> dict[str, Any]:
    quilt_loader = data.get("quilt_loader") if isinstance(data.get("quilt_loader"), dict) else {}
    metadata = quilt_loader.get("metadata") if isinstance(quilt_loader.get("metadata"), dict) else {}
    contributors = metadata.get("contributors")
    authors = list(contributors.keys()) if isinstance(contributors, dict) else contributors
    contact = metadata.get("contact") if isinstance(metadata.get("contact"), dict) else {}
    icon_reference = metadata.get("icon")
    if isinstance(icon_reference, dict):
        ordered_icons = [value for _, value in sorted(icon_reference.items(), key=lambda item: item[0])]
        icon_reference = ordered_icons[-1] if ordered_icons else None
    return {
        "name": _optional_str(metadata.get("name")) or _optional_str(quilt_loader.get("id")) or "Unknown",
        "version": _optional_str(quilt_loader.get("version")) or "Unknown",
        "provider": _guess_provider(contact.get("homepage"), contact.get("sources"), authors),
        "icon_reference": _optional_str(icon_reference),
    }


def _mod_metadata_from_toml(text: str) -> dict[str, Any]:
    if not text.strip():
        return {}
    data = tomllib.loads(text)
    mods = data.get("mods")
    if not isinstance(mods, list) or not mods:
        return {}
    first_mod = mods[0] if isinstance(mods[0], dict) else {}
    return {
        "name": _optional_str(first_mod.get("displayName")) or _optional_str(first_mod.get("modId")) or "Unknown",
        "version": _optional_str(first_mod.get("version")) or "Unknown",
        "provider": _guess_provider(first_mod.get("displayURL"), first_mod.get("authors")),
        "icon_reference": _optional_str(first_mod.get("logoFile")),
    }


def _mod_metadata_from_mcmod_info(data: Any) -> dict[str, Any]:
    entry = data[0] if isinstance(data, list) and data else data
    if not isinstance(entry, dict):
        return {}
    return {
        "name": _optional_str(entry.get("name")) or _optional_str(entry.get("modid")) or "Unknown",
        "version": _optional_str(entry.get("version")) or "Unknown",
        "provider": _guess_provider(entry.get("url"), entry.get("authorList")),
        "icon_reference": _optional_str(entry.get("logoFile")),
    }


def _read_manifest_properties(archive: zipfile.ZipFile) -> dict[str, str]:
    manifest_text = _read_text_from_zip(archive, "META-INF/MANIFEST.MF")
    properties: dict[str, str] = {}
    if not manifest_text:
        return properties
    for line in manifest_text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        properties[key.strip()] = value.strip()
    return properties


def _guess_provider(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            stripped = value.strip()
            if stripped.startswith("http://") or stripped.startswith("https://"):
                parsed = urlparse(stripped)
                host = (parsed.netloc or "").lower().removeprefix("www.")
                if host:
                    return host
            return stripped.split(",")[0].strip() or "Unknown"
        if isinstance(value, dict):
            provider = _guess_provider(*value.values())
            if provider != "Unknown":
                return provider
        if isinstance(value, list):
            provider = _guess_provider(*value)
            if provider != "Unknown":
                return provider
    return "Unknown"


def _extract_mod_icon(
    archive: zipfile.ZipFile,
    icon_reference: Any,
    mod_path: Path,
    cache_root: Path,
) -> Path | None:
    icon_name = _optional_str(icon_reference)
    if not icon_name:
        return None
    normalized = icon_name.replace("\\", "/").strip("/")
    if not normalized or normalized not in archive.namelist():
        return None
    if Path(normalized).suffix.lower() not in IMAGE_SUFFIXES:
        return None

    try:
        icon_bytes = archive.read(normalized)
    except KeyError:
        return None

    digest = hashlib.sha1(f"{mod_path.resolve()}::{mod_path.stat().st_mtime}::{normalized}".encode("utf-8")).hexdigest()
    cache_root.mkdir(parents=True, exist_ok=True)
    target = cache_root / f"{digest}{Path(normalized).suffix.lower()}"
    if not target.exists():
        target.write_bytes(icon_bytes)
    return target


def _format_copy_entry_label(entry: Path) -> str:
    display = entry.name.replace("_", " ")
    display = display[:-4] if display.lower().endswith(".txt") else display
    suffix = "Folder" if entry.is_dir() else "File"
    return f"{display} ({suffix})"


def _sanitize_copy_user_data(values: list[str] | None) -> list[str]:
    if not values:
        return []

    sanitized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _optional_str(value)
        if not text:
            continue
        normalized = Path(text).as_posix().strip("/")
        if not normalized or normalized in seen:
            continue
        top_level = normalized.split("/", 1)[0]
        lowered = top_level.lower()
        if lowered in EXCLUDED_COPY_NAMES or top_level.startswith("."):
            continue
        sanitized.append(top_level)
        seen.add(top_level)
    return sanitized


def _coerce_non_negative_int(value: Any, default: int = 0) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, number)


def _coerce_memory_mb(value: Any) -> int:
    try:
        memory_mb = int(value)
    except (TypeError, ValueError):
        return max(1024, min(_system_memory_cap_mb(), DEFAULT_MEMORY_MB))
    return max(1024, min(_system_memory_cap_mb(), memory_mb))


def _coerce_volume_percent(value: Any, default: int = 75) -> int:
    try:
        volume = int(value)
    except (TypeError, ValueError):
        volume = int(default)
    return max(0, min(100, volume))


def _system_memory_cap_mb() -> int:
    try:
        total_mb = int(psutil.virtual_memory().total / (1024 * 1024))
    except Exception:  # noqa: BLE001
        total_mb = 65536
    return max(1024, total_mb)


def _coerce_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if _optional_str(item)]


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _required_str(value: Any, label: str) -> str:
    text = _optional_str(value)
    if not text:
        raise ValueError(f"Missing {label}.")
    return text
