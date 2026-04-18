from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import minecraft_launcher_lib
import psutil


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
    status: str = "Quit"
    pid: int | None = None

    @property
    def version_label(self) -> str:
        if self.mod_loader_id:
            return f"{self.vanilla_version} • {self.loader_name}"
        return self.vanilla_version

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
        }

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any], root_dir: Path) -> "InstanceRecord":
        icon_path = str(metadata.get("icon_path", "assets/Dirt.png"))
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
            root_dir=root_dir,
            minecraft_dir=root_dir / ".minecraft",
        )


@dataclass(slots=True)
class InstallRequest:
    instance_id: str
    name: str
    vanilla_version: str
    mod_loader_id: str | None
    mod_loader_version: str | None
    icon_path: str
    stage_dir: str
    final_dir: str
    minecraft_dir: str

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
        }


class LauncherService:
    def __init__(self, project_root: Path | None = None):
        self.project_root = project_root or Path(__file__).resolve().parents[2]
        self.assets_root = self.project_root / "assets"
        self.instances_root = self.project_root / "instances"
        self.runtime_root = self.project_root / "runtime"
        self.staging_root = self.runtime_root / "staging"
        self.logs_root = self.runtime_root / "logs"
        self.default_icon = "assets/Dirt.png"

        for path in (
            self.instances_root,
            self.runtime_root,
            self.staging_root,
            self.logs_root,
        ):
            path.mkdir(parents=True, exist_ok=True)

        self._version_cache: list[dict[str, Any]] | None = None
        self._loader_support_cache: dict[str, set[str]] = {}
        self._loader_versions_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def get_player_name(self) -> str:
        return "player1"

    def get_default_icon_path(self) -> str:
        return str((self.project_root / self.default_icon).resolve())

    def resolve_icon_path(self, icon_path: str | None) -> str:
        default_icon_path = (self.project_root / self.default_icon).resolve()
        if not icon_path:
            return str(default_icon_path)

        icon = Path(icon_path)
        if icon.is_absolute():
            resolved_icon = icon
        else:
            resolved_icon = (self.project_root / icon).resolve()

        if resolved_icon.is_file():
            return str(resolved_icon)
        return str(default_icon_path)

    def load_instances(self) -> list[InstanceRecord]:
        instances: list[InstanceRecord] = []
        for instance_dir in sorted(self.instances_root.iterdir(), key=lambda item: item.name.lower()):
            metadata_path = instance_dir / "instance.json"
            if not metadata_path.is_file():
                continue

            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                instance = InstanceRecord.from_metadata(metadata, instance_dir)
                instance.icon_path = self.resolve_icon_path(instance.icon_path)
                instances.append(instance)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue

        instances.sort(key=lambda item: _parse_timestamp(item.created_at), reverse=True)
        return instances

    def prepare_install_request(
        self,
        name: str,
        vanilla_version: str,
        mod_loader_id: str | None,
        mod_loader_version: str | None,
    ) -> InstallRequest:
        instance_name = name.strip() or self.default_instance_name(vanilla_version, mod_loader_id)
        slug = _slugify(instance_name)[:40] or "instance"
        instance_id = f"{slug}-{uuid.uuid4().hex[:8]}"
        final_dir = self.instances_root / instance_id
        stage_dir = self.staging_root / instance_id
        minecraft_dir = stage_dir / ".minecraft"

        return InstallRequest(
            instance_id=instance_id,
            name=instance_name,
            vanilla_version=vanilla_version,
            mod_loader_id=mod_loader_id,
            mod_loader_version=mod_loader_version,
            icon_path=self.default_icon,
            stage_dir=str(stage_dir),
            final_dir=str(final_dir),
            minecraft_dir=str(minecraft_dir),
        )

    def finalize_install(self, request: InstallRequest, installed_version: str) -> InstanceRecord:
        stage_dir = Path(request.stage_dir)
        final_dir = Path(request.final_dir)
        if not stage_dir.exists():
            raise FileNotFoundError(f"Missing staging directory: {stage_dir}")
        if final_dir.exists():
            raise FileExistsError(f"Instance directory already exists: {final_dir}")

        metadata = {
            "instance_id": request.instance_id,
            "name": request.name,
            "vanilla_version": request.vanilla_version,
            "installed_version": installed_version,
            "mod_loader_id": request.mod_loader_id,
            "mod_loader_version": request.mod_loader_version,
            "icon_path": request.icon_path,
            "created_at": _utc_now(),
            "last_played": None,
        }
        (stage_dir / "instance.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        shutil.move(str(stage_dir), str(final_dir))

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

    def is_experiment_type(self, version_type: str) -> bool:
        normalized = version_type.lower().replace("-", "_")
        return normalized not in KNOWN_VERSION_TYPES or normalized in EXPERIMENT_TYPES

    def build_launch_options(self, player_name: str, game_directory: Path) -> dict[str, Any]:
        return {
            "username": player_name,
            "uuid": _offline_uuid(player_name),
            "token": "offline-token",
            "launcherName": "NOTG Launcher",
            "launcherVersion": "0.1",
            "gameDirectory": str(game_directory),
        }

    def launch_instance(self, instance: InstanceRecord, player_name: str) -> subprocess.Popen[Any]:
        minecraft_directory = instance.minecraft_dir
        minecraft_launcher_lib.install.install_minecraft_version(
            instance.installed_version,
            minecraft_directory,
        )
        command = minecraft_launcher_lib.command.get_minecraft_command(
            instance.installed_version,
            minecraft_directory,
            self.build_launch_options(player_name, minecraft_directory),
        )

        kwargs: dict[str, Any] = {"cwd": str(minecraft_directory)}
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True

        return subprocess.Popen(command, **kwargs)

    def open_instance_dir(self, instance: InstanceRecord) -> Path:
        return instance.root_dir

    def terminate_process_tree(self, pid: int) -> None:
        terminate_process_tree(pid)


def run_install_task(task: dict[str, Any], event_queue: Any) -> None:
    try:
        stage_dir = Path(task["stage_dir"])
        minecraft_dir = Path(task["minecraft_dir"])
        stage_dir.mkdir(parents=True, exist_ok=True)
        minecraft_dir.mkdir(parents=True, exist_ok=True)

        _queue_event(event_queue, "status", text="Preparing instance directory")
        _queue_event(event_queue, "log", text=f"Staging install in {stage_dir.name}")

        callback = {
            "setStatus": lambda text: _install_status(event_queue, text),
            "setProgress": lambda value: _queue_event(event_queue, "progress", value=int(value)),
            "setMax": lambda maximum: _queue_event(event_queue, "max", value=max(1, int(maximum))),
        }

        loader_id = _optional_str(task.get("mod_loader_id"))
        loader_version = _optional_str(task.get("mod_loader_version"))
        if loader_id:
            loader = minecraft_launcher_lib.mod_loader.get_mod_loader(loader_id)
            loader_name = loader.get_name()
            _queue_event(event_queue, "status", text=f"Installing {loader_name}")
            _queue_event(
                event_queue,
                "log",
                text=f"Installing {loader_name} for Minecraft {task['vanilla_version']}",
            )
            installed_version = loader.install(
                task["vanilla_version"],
                minecraft_dir,
                loader_version=loader_version,
                callback=callback,
            )
        else:
            _queue_event(event_queue, "status", text="Installing Minecraft")
            _queue_event(
                event_queue,
                "log",
                text=f"Installing Minecraft {task['vanilla_version']}",
            )
            minecraft_launcher_lib.install.install_minecraft_version(
                task["vanilla_version"],
                minecraft_dir,
                callback=callback,
            )
            installed_version = task["vanilla_version"]

        _queue_event(event_queue, "complete", installed_version=installed_version)
    except BaseException as exc:  # noqa: BLE001
        _queue_event(
            event_queue,
            "error",
            message=str(exc),
            traceback=traceback.format_exc(),
        )


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


def _install_status(event_queue: Any, text: str) -> None:
    _queue_event(event_queue, "status", text=_summarize_install_status(text))
    _queue_event(event_queue, "log", text=text)


def _summarize_install_status(text: str) -> str:
    normalized = text.lower()
    if "requesting" in normalized or "downloading" in normalized:
        return "Downloading files…"
    if "extract" in normalized:
        return "Extracting files…"
    if "forge" in normalized or "fabric" in normalized or "quilt" in normalized or "neo" in normalized:
        return "Installing mod loader…"
    if "version" in normalized or "jar" in normalized or "asset" in normalized:
        return "Installing Minecraft files…"
    if "prepare" in normalized:
        return "Preparing instance directory…"
    return "Installing instance…"


def _queue_event(event_queue: Any, event_type: str, **payload: Any) -> None:
    event_queue.put({"type": event_type, **payload})


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


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
