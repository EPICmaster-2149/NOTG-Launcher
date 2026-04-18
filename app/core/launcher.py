from __future__ import annotations

import configparser
import hashlib
import json
import shutil
import subprocess
import traceback
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
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


@dataclass(slots=True)
class IconRecord:
    icon_id: str
    name: str
    relative_path: str
    absolute_path: str
    is_default: bool


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
    operation: str = "create"
    modpack_path: str | None = None
    minecraft_import_dir: str | None = None

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
            "operation": self.operation,
            "modpack_path": self.modpack_path,
            "minecraft_import_dir": self.minecraft_import_dir,
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
            operation=str(payload.get("operation", "create")),
            modpack_path=_optional_str(payload.get("modpack_path")),
            minecraft_import_dir=_optional_str(payload.get("minecraft_import_dir")),
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
        self.project_root = project_root or Path(__file__).resolve().parents[2]
        self.assets_root = self.project_root / "assets"
        self.default_icons_root = self.assets_root / "default-instance-icons"
        self.user_icons_root = self.project_root / "app" / "icons"
        self.instances_root = self.project_root / "instances"
        self.runtime_root = self.project_root / "runtime"
        self.staging_root = self.runtime_root / "staging"
        self.logs_root = self.runtime_root / "logs"
        self.default_icon = "assets/default-instance-icons/Grass Block.png"

        for path in (
            self.user_icons_root,
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
            relative_path = self._project_relative(path)
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
        return self._project_relative(target)

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
        return self._project_relative(target)

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

        icon = Path(icon_path)
        if icon.is_absolute():
            resolved_icon = icon
        else:
            resolved_icon = (self.project_root / icon).resolve()

        if resolved_icon.is_file():
            return str(resolved_icon)
        return str(default_icon_path)

    def is_valid_minecraft_dir(self, path: str | Path) -> tuple[bool, str]:
        candidate = Path(path)
        if not candidate.is_dir():
            return False, "Select a folder that contains a launcher instance .minecraft directory."

        marker_hits = 0
        for marker in IMPORTANT_MINECRAFT_MARKERS:
            if (candidate / marker).exists():
                marker_hits += 1

        if candidate.name == ".minecraft" and marker_hits >= 2:
            return True, ""
        if marker_hits >= 3:
            return True, ""
        return False, "That folder does not look like a valid .minecraft directory."

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
        vanilla_version: str | None,
        mod_loader_id: str | None,
        mod_loader_version: str | None,
        icon_path: str | None = None,
        operation: str = "create",
        modpack_path: str | None = None,
        minecraft_import_dir: str | None = None,
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
            operation=operation,
            modpack_path=_optional_str(modpack_path),
            minecraft_import_dir=_optional_str(minecraft_import_dir),
        )

    def finalize_install(self, request: InstallRequest, result: InstallResult) -> InstanceRecord:
        stage_dir = Path(request.stage_dir)
        final_dir = Path(request.final_dir)
        if not stage_dir.exists():
            raise FileNotFoundError(f"Missing staging directory: {stage_dir}")
        if final_dir.exists():
            raise FileExistsError(f"Instance directory already exists: {final_dir}")

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

    def _normalize_icon_reference(self, icon_path: str) -> str:
        candidate = Path(icon_path)
        if candidate.is_absolute():
            return self._project_relative(candidate)
        return icon_path.replace("\\", "/")

    def _project_relative(self, path: Path) -> str:
        try:
            relative = path.resolve().relative_to(self.project_root.resolve())
        except ValueError:
            return str(path.resolve())
        return relative.as_posix()

    def _unique_icon_path(self, safe_name: str, suffix: str) -> Path:
        target = self.user_icons_root / f"{safe_name}{suffix}"
        if not target.exists():
            return target

        for index in range(2, 5000):
            candidate = self.user_icons_root / f"{safe_name}-{index}{suffix}"
            if not candidate.exists():
                return candidate
        raise RuntimeError("Could not allocate a unique icon filename.")


def run_install_task(task: dict[str, Any], event_queue: Any) -> None:
    try:
        request = InstallRequest.from_payload(task)
        stage_dir = Path(request.stage_dir)
        minecraft_dir = Path(request.minecraft_dir)
        stage_dir.mkdir(parents=True, exist_ok=True)
        minecraft_dir.mkdir(parents=True, exist_ok=True)

        _queue_event(event_queue, "status", text="Preparing instance directory")
        _queue_event(event_queue, "log", text=f"Staging install in {stage_dir.name}")

        callback = {
            "setStatus": lambda text: _install_status(event_queue, text),
            "setProgress": lambda value: _queue_event(event_queue, "progress", value=int(value)),
            "setMax": lambda maximum: _queue_event(event_queue, "max", value=max(1, int(maximum))),
        }

        if request.operation == "create":
            result = _run_standard_install(request, callback, event_queue)
        elif request.operation == "import_modpack":
            result = _run_modpack_import(request, callback, event_queue)
        elif request.operation == "import_minecraft":
            result = _run_minecraft_directory_import(request, callback, event_queue)
        else:
            raise ValueError(f"Unsupported install operation: {request.operation}")

        _queue_event(event_queue, "complete", result=result.to_payload())
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


def _run_standard_install(
    request: InstallRequest,
    callback: dict[str, Any],
    event_queue: Any,
) -> InstallResult:
    vanilla_version = _required_str(request.vanilla_version, "Minecraft version")
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
    source_dir = Path(_required_str(request.minecraft_import_dir, ".minecraft folder"))
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Minecraft directory not found: {source_dir}")

    valid, message = LauncherService(Path(__file__).resolve().parents[2]).is_valid_minecraft_dir(source_dir)
    if not valid:
        raise ValueError(message)

    minecraft_dir = Path(request.minecraft_dir)
    _queue_event(event_queue, "status", text="Copying imported files")
    _queue_event(event_queue, "log", text=f"Copying {source_dir} into the new instance")
    _copy_tree_with_progress(source_dir, minecraft_dir, event_queue, "Copying imported files")

    metadata = _infer_minecraft_metadata(minecraft_dir)
    if metadata is None:
        raise RuntimeError(
            "The selected .minecraft folder does not expose a launch version. "
            "Import a self-contained export or a folder with recognizable version metadata."
        )

    vanilla_version, installed_version, mod_loader_id, mod_loader_version = metadata
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
    if mod_loader_id:
        loader = minecraft_launcher_lib.mod_loader.get_mod_loader(mod_loader_id)
        loader_name = loader.get_name()
        _queue_event(event_queue, "status", text=f"Installing {loader_name}")
        _queue_event(
            event_queue,
            "log",
            text=f"Installing {loader_name} for Minecraft {vanilla_version}",
        )
        return loader.install(
            vanilla_version,
            minecraft_dir,
            loader_version=mod_loader_version,
            callback=callback,
        )

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
        _extract_archive_mappings(zf, mappings, minecraft_dir, event_queue, "Extracting imported files")

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
        _extract_archive_mappings(zf, mappings, minecraft_dir, event_queue, "Extracting imported files")

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
        _extract_archive_mappings(zf, mappings, minecraft_dir, event_queue, "Extracting imported files")

    metadata = _infer_minecraft_metadata(minecraft_dir)
    if metadata is None:
        raise RuntimeError(
            "The selected archive was extracted, but the launcher could not determine a Minecraft version from it."
        )

    vanilla_version, installed_version, mod_loader_id, mod_loader_version = metadata
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


def _copy_tree_with_progress(source: Path, destination: Path, event_queue: Any, status_text: str) -> None:
    files = [path for path in source.rglob("*") if path.is_file()]
    _queue_event(event_queue, "max", value=max(1, len(files)))
    if not files:
        _queue_event(event_queue, "progress", value=1)
        return

    for index, file_path in enumerate(files, start=1):
        relative_path = file_path.relative_to(source)
        target = destination / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, target)
        _queue_event(event_queue, "progress", value=index)

    _queue_event(event_queue, "status", text=status_text)


def _extract_archive_mappings(
    zf: zipfile.ZipFile,
    mappings: list[tuple[str, str]],
    destination_root: Path,
    event_queue: Any,
    status_text: str,
) -> None:
    if not mappings:
        _queue_event(event_queue, "max", value=1)
        _queue_event(event_queue, "progress", value=1)
        return

    _queue_event(event_queue, "max", value=len(mappings))
    for index, (archive_name, destination_name) in enumerate(mappings, start=1):
        if not destination_name:
            continue
        target_path = _safe_path_join(destination_root, destination_name)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(archive_name, "r") as source_handle:
            with target_path.open("wb") as target_handle:
                shutil.copyfileobj(source_handle, target_handle)
        _queue_event(event_queue, "progress", value=index)
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


def _install_status(event_queue: Any, text: str) -> None:
    _queue_event(event_queue, "status", text=_summarize_install_status(text))
    _queue_event(event_queue, "log", text=text)


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


def _required_str(value: Any, label: str) -> str:
    text = _optional_str(value)
    if not text:
        raise ValueError(f"Missing {label}.")
    return text
