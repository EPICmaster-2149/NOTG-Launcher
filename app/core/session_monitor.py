from __future__ import annotations

import subprocess
from datetime import datetime, timezone

import psutil

from core.ipc import send_ipc_message
from core.launcher import LauncherService, _parse_timestamp


def run_session_monitor(instance_id: str, pid: int, player_name: str) -> int:
    del player_name
    service = LauncherService()
    session = service.get_runtime_session(instance_id)
    if session is None:
        return 1

    service.mark_runtime_session_running(instance_id)

    return_code: int | None = None
    try:
        process = psutil.Process(pid)
        return_code = process.wait()
    except (psutil.Error, ValueError):
        return_code = None

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
        "cwd": str(service.project_root),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
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
