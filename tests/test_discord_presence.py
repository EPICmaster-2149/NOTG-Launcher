from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from core import discord_presence  # noqa: E402


class FakePresence:
    instances: list["FakePresence"] = []
    fail_updates_with_images = False

    def __init__(self, application_id: str):
        self.application_id = application_id
        self.connected = False
        self.closed = False
        self.cleared_with_pid: int | None = None
        self.updates: list[dict[str, object]] = []
        FakePresence.instances.append(self)

    def connect(self) -> None:
        self.connected = True

    def update(self, **payload: object) -> None:
        self.updates.append(dict(payload))
        if FakePresence.fail_updates_with_images and "large_image" in payload:
            raise RuntimeError("bad asset")

    def clear(self, pid: int | None = None) -> None:
        self.cleared_with_pid = pid

    def close(self) -> None:
        self.closed = True


def setup_function() -> None:
    FakePresence.instances = []
    FakePresence.fail_updates_with_images = False


def test_update_uses_minecraft_pid_and_clear_matches_it(monkeypatch) -> None:
    monkeypatch.setattr(discord_presence, "Presence", FakePresence)
    presence = discord_presence.DiscordRichPresence()

    presence.update(state="Playing", details="1.21.5", pid=12345)
    presence.clear()

    rpc = FakePresence.instances[0]
    assert rpc.updates[0]["pid"] == 12345
    assert rpc.cleared_with_pid == 12345


def test_update_recovers_without_images_on_asset_failure(monkeypatch) -> None:
    monkeypatch.setattr(discord_presence, "Presence", FakePresence)
    FakePresence.fail_updates_with_images = True
    presence = discord_presence.DiscordRichPresence()

    presence.update(
        state="Playing",
        details="1.21.5",
        pid=12345,
        large_text="NOTG Launcher",
        small_text="Survival",
    )

    first_rpc, retry_rpc = FakePresence.instances
    assert first_rpc.closed
    assert "large_image" in first_rpc.updates[0]
    assert retry_rpc.updates[0]["pid"] == 12345
    assert "large_image" not in retry_rpc.updates[0]
    assert "small_image" not in retry_rpc.updates[0]


def test_activity_text_is_trimmed_to_discord_limit(monkeypatch) -> None:
    monkeypatch.setattr(discord_presence, "Presence", FakePresence)
    presence = discord_presence.DiscordRichPresence()

    presence.update(state="x" * 200, details="y" * 200, pid=12345)

    payload = FakePresence.instances[0].updates[0]
    assert len(payload["state"]) == discord_presence.MAX_ACTIVITY_TEXT_LENGTH
    assert len(payload["details"]) == discord_presence.MAX_ACTIVITY_TEXT_LENGTH
