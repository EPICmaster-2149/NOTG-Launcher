from __future__ import annotations

import subprocess
from datetime import datetime, timezone
import time

import psutil

from core.discord_presence import DiscordRichPresence
from core.ipc import send_ipc_message
from core.launcher import LauncherService, _parse_timestamp


def run_session_monitor(instance_id: str, pid: int, player_name: str) -> int:
    service = LauncherService()
    session = service.get_runtime_session(instance_id)
    if session is None:
        return 1

    session = service.mark_runtime_session_running(instance_id) or session

    instance = service.get_instance(instance_id)

    presence = None
    if instance is not None and instance.rich_presence_enabled:
        started = _parse_timestamp(session.get("started_at"))
        started_at = started.timestamp() if started != datetime.min.replace(tzinfo=timezone.utc) else time.time()
        presence = DiscordRichPresence(
        )
        if presence.connect():
            presence.update(
                state=service.build_instance_rich_presence_state(instance),
                details=service.resolve_instance_rich_presence_details(instance),
                started_at=started_at,
                large_text="NOTG Launcher",
                small_text=instance.name or player_name,
            )

    return_code: int | None = None
    try:
        process = psutil.Process(pid)
        while True:
            try:
                return_code = process.wait(timeout=8)
                break
            except psutil.TimeoutExpired:
                if presence is None:
                    continue
                refreshed = service.get_instance(instance_id)
                if refreshed is None:
                    continue
                presence.update(
                    state=service.build_instance_rich_presence_state(refreshed),
                    details=service.resolve_instance_rich_presence_details(refreshed),
                    started_at=started_at,
                    large_text="NOTG Launcher",
                    small_text=refreshed.name or player_name,
                )
    except (psutil.Error, ValueError):
        return_code = None

    if presence is not None:
        presence.clear()
        presence.close()

    finished_session = service.complete_runtime_session(instance_id, return_code)
    if finished_session is None:
        return 1

    instance = service.get_instance(instance_id)
    if instance is not None:
        elapsed_seconds = _session_elapsed_seconds(finished_session)
        if elapsed_seconds > 0:
            service.record_instance_playtime(instance, elapsed_seconds)

    activate = bool(finished_session.get("close_ui_on_launch")) or str(finished_session.get("status")) == "crashed"
    restore_message = {
        "action": "session-sync",
        "instance_id": instance_id,
        "activate": activate,
    }
    if send_ipc_message(service.launcher_ipc_file, restore_message):
        return 0

    command = service.build_launcher_command("--restore-instance", instance_id)
    if str(finished_session.get("status")) == "crashed":
        command.extend(["--restore-page", "Minecraft Log"])
    kwargs: dict[str, object] = {
        "cwd": str(service.get_launcher_working_directory()),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    elif hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(command, **kwargs)
    return 0


def _session_elapsed_seconds(session: dict[str, object]) -> int:
    started_at = _parse_timestamp(session.get("started_at"))
    ended_at = _parse_timestamp(session.get("ended_at"))
    if started_at == datetime.min.replace(tzinfo=timezone.utc):
        return 0
    if ended_at == datetime.min.replace(tzinfo=timezone.utc):
        ended_at = datetime.now(timezone.utc)
    return max(0, int((ended_at - started_at).total_seconds()))
