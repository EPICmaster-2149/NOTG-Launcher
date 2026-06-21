from __future__ import annotations

import sys
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1] / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import pytest

import core.launcher as launcher_core  # noqa: E402
from core.launcher import (  # noqa: E402
    APP_VERSION,
    AccountAuthenticationError,
    AccountRecord,
    InstallRequest,
    InstallResult,
    LauncherService,
    _microsoft_invalid_app_registration,
    _microsoft_needs_spa_origin,
)


def test_optimized_launch_options_add_safe_modern_flags(tmp_path: Path) -> None:
    service = object.__new__(LauncherService)

    options = service.build_launch_options(
        "Player",
        tmp_path,
        4096,
        optimize_minecraft=True,
        java_major=21,
    )

    args = options["jvmArguments"]
    assert "-Xmx4096M" in args
    assert "-XX:+UseG1GC" in args
    assert any(arg.startswith("-Xms") for arg in args)
    assert "-XX:+ParallelRefProcEnabled" in args
    assert "-XX:+DisableExplicitGC" in args
    assert "-Dfile.encoding=UTF-8" in args


def test_disabled_optimization_keeps_legacy_launch_args(tmp_path: Path) -> None:
    service = object.__new__(LauncherService)

    options = service.build_launch_options(
        "Player",
        tmp_path,
        4096,
        custom_jvm_args="-Dexample=true",
        optimize_minecraft=False,
        java_major=21,
    )

    assert options["jvmArguments"] == [
        "-Xmx4096M",
        "-Dminecraft.launcher.brand=NOTG-Launcher",
        f"-Dminecraft.launcher.version={APP_VERSION}",
        "-Dexample=true",
    ]


def test_legacy_accounts_are_migrated_to_typed_offline_records(tmp_path: Path) -> None:
    service = object.__new__(LauncherService)
    service.accounts_file = tmp_path / "accounts.json"
    service.accounts_file.write_text('{"accounts": ["Player"], "active": "Player"}', encoding="utf-8")

    payload = service._read_accounts_payload()
    account = payload["accounts"][0]
    session = service.get_account_launch_session("Player")

    assert account.account_type == "offline"
    assert account.username == "Player"
    assert payload["active"] == account.account_id
    assert session.username == "Player"
    assert session.access_token == "offline-token"


def test_account_ids_disambiguate_duplicate_usernames(tmp_path: Path) -> None:
    service = object.__new__(LauncherService)
    service.accounts_file = tmp_path / "accounts.json"
    service.accounts_file.write_text(
        """
        {
          "version": 2,
          "active": "offline:00000000000000000000000000000001",
          "accounts": [
            {
              "id": "offline:00000000000000000000000000000001",
              "username": "Player",
              "type": "offline",
              "uuid": "00000000-0000-0000-0000-000000000001"
            },
            {
              "id": "microsoft:00000000000000000000000000000002",
              "username": "Player",
              "type": "microsoft",
              "uuid": "00000000000000000000000000000002",
              "access_token": "minecraft-token",
              "refresh_token": "refresh-token",
              "expires_at": "2999-01-01T00:00:00+00:00"
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    selected = service.set_active_account("microsoft:00000000000000000000000000000002")
    session = service.get_account_launch_session("microsoft:00000000000000000000000000000002")

    assert selected == "Player"
    assert session.account_type == "microsoft"
    assert session.access_token == "minecraft-token"
    assert session.uuid == "00000000000000000000000000000002"


def test_microsoft_login_requires_registered_client_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MICROSOFT_CLIENT_ID", raising=False)
    monkeypatch.delenv("NOTG_MICROSOFT_CLIENT_ID", raising=False)
    service = object.__new__(LauncherService)

    assert service._microsoft_client_id() == "88381242-e209-40ca-9fdb-7fb3e37a60f5"


def test_microsoft_login_defaults_to_public_pkce_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MICROSOFT_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("NOTG_MICROSOFT_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("MICROSOFT_REDIRECT_URI", raising=False)
    monkeypatch.delenv("NOTG_MICROSOFT_REDIRECT_URI", raising=False)
    service = object.__new__(LauncherService)

    login = service.begin_microsoft_login()

    assert login["redirect_uri"] == "https://login.microsoftonline.com/common/oauth2/nativeclient"
    assert "code_challenge=" in login["url"]
    assert "client_secret" not in login["url"]
    assert "prompt=select_account" in login["url"]


def test_ely_login_uses_launcher_authserver_with_totp(monkeypatch: pytest.MonkeyPatch) -> None:
    service = object.__new__(LauncherService)
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        ok = True
        reason = "OK"
        text = ""

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "accessToken": "ely-token",
                "selectedProfile": {"id": "00000000000000000000000000000003", "name": "ElyPlayer"},
                "user": {"id": "user-id", "username": "ElyPlayer"},
            }

    def fake_post(url: str, **kwargs: object) -> FakeResponse:
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(launcher_core.requests, "post", fake_post)
    stored: dict[str, object] = {}

    def store_account(account_type: str, payload: dict[str, object]) -> AccountRecord:
        stored["account_type"] = account_type
        stored["payload"] = payload
        return AccountRecord(account_id="ely:test", username="ElyPlayer", account_type="ely")

    monkeypatch.setattr(service, "_store_authenticated_account", store_account)

    service.authenticate_ely_account("player@example.com", "password123", "123456")

    assert captured["url"] == "https://authserver.ely.by/auth/authenticate"
    assert captured["json"]["username"] == "player@example.com"  # type: ignore[index]
    assert captured["json"]["password"] == "password123:123456"  # type: ignore[index]
    assert captured["json"]["requestUser"] is True  # type: ignore[index]
    assert stored["account_type"] == "ely"
    assert stored["payload"]["access_token"] == "ely-token"  # type: ignore[index]


def test_microsoft_spa_registration_error_is_detected() -> None:
    assert _microsoft_needs_spa_origin(
        {
            "error": "invalid_request",
            "error_description": "AADSTS90023: Tokens issued for the 'Single-Page Application' client-type should only be redeemed via cross-origin requests.",
        }
    )


def test_microsoft_invalid_app_registration_error_is_detected() -> None:
    assert _microsoft_invalid_app_registration(
        {
            "error": "invalid_request",
            "error_description": "Invalid app registration, see https://aka.ms/AppRegInfo for more information",
        }
    )


def test_microsoft_completion_requires_java_entitlement(monkeypatch: pytest.MonkeyPatch) -> None:
    service = object.__new__(LauncherService)

    class FakeMicrosoftAccount:
        @staticmethod
        def authenticate_with_xbl(_token: str) -> dict[str, object]:
            return {"Token": "xbl-token", "DisplayClaims": {"xui": [{"uhs": "user-hash"}]}}

        @staticmethod
        def authenticate_with_xsts(_token: str) -> dict[str, str]:
            return {"Token": "xsts-token"}

        @staticmethod
        def authenticate_with_minecraft(_userhash: str, _xsts_token: str) -> dict[str, str]:
            return {"access_token": "minecraft-token"}

    monkeypatch.setattr(launcher_core.minecraft_launcher_lib, "microsoft_account", FakeMicrosoftAccount)
    monkeypatch.setattr(service, "_minecraft_entitlements", lambda _token: {"items": []})

    with pytest.raises(AccountAuthenticationError, match="does not own Minecraft: Java Edition"):
        service._minecraft_profile_from_microsoft_token_response(
            {"access_token": "microsoft-token", "refresh_token": "refresh-token"}
        )


def test_microsoft_completion_explains_missing_java_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    service = object.__new__(LauncherService)

    class FakeMicrosoftAccount:
        @staticmethod
        def authenticate_with_xbl(_token: str) -> dict[str, object]:
            return {"Token": "xbl-token", "DisplayClaims": {"xui": [{"uhs": "user-hash"}]}}

        @staticmethod
        def authenticate_with_xsts(_token: str) -> dict[str, str]:
            return {"Token": "xsts-token"}

        @staticmethod
        def authenticate_with_minecraft(_userhash: str, _xsts_token: str) -> dict[str, str]:
            return {"access_token": "minecraft-token"}

    monkeypatch.setattr(launcher_core.minecraft_launcher_lib, "microsoft_account", FakeMicrosoftAccount)
    monkeypatch.setattr(service, "_minecraft_entitlements", lambda _token: {"items": [{"name": "game_minecraft"}]})
    monkeypatch.setattr(service, "_minecraft_profile", lambda _token: {"error": "NOT_FOUND"})

    with pytest.raises(AccountAuthenticationError, match="no Java profile name exists yet"):
        service._minecraft_profile_from_microsoft_token_response(
            {"access_token": "microsoft-token", "refresh_token": "refresh-token"}
        )


def test_microsoft_completion_returns_profile_after_entitlement_check(monkeypatch: pytest.MonkeyPatch) -> None:
    service = object.__new__(LauncherService)

    class FakeMicrosoftAccount:
        @staticmethod
        def authenticate_with_xbl(_token: str) -> dict[str, object]:
            return {"Token": "xbl-token", "DisplayClaims": {"xui": [{"uhs": "user-hash"}]}}

        @staticmethod
        def authenticate_with_xsts(_token: str) -> dict[str, str]:
            return {"Token": "xsts-token"}

        @staticmethod
        def authenticate_with_minecraft(_userhash: str, _xsts_token: str) -> dict[str, str]:
            return {"access_token": "minecraft-token"}

    monkeypatch.setattr(launcher_core.minecraft_launcher_lib, "microsoft_account", FakeMicrosoftAccount)
    monkeypatch.setattr(service, "_minecraft_entitlements", lambda _token: {"items": [{"name": "product_minecraft"}]})
    monkeypatch.setattr(service, "_minecraft_profile", lambda _token: {"id": "uuid", "name": "Player"})

    profile = service._minecraft_profile_from_microsoft_token_response(
        {"access_token": "microsoft-token", "refresh_token": "refresh-token"}
    )

    assert profile["id"] == "uuid"
    assert profile["name"] == "Player"
    assert profile["access_token"] == "minecraft-token"
    assert profile["refresh_token"] == "refresh-token"


def test_ely_authserver_payload_maps_to_account_profile() -> None:
    service = object.__new__(LauncherService)

    payload = service._ely_authserver_account_payload(
        {
            "accessToken": "ely-token",
            "selectedProfile": {
                "id": "00000000000000000000000000000003",
                "name": "ElyPlayer",
            },
            "user": {
                "id": "user-id",
                "username": "ely-email-user",
            },
        },
        "client-token",
    )

    assert payload["access_token"] == "ely-token"
    assert payload["client_token"] == "client-token"
    assert payload["profile"]["username"] == "ElyPlayer"
    assert payload["profile"]["uuid"] == "00000000000000000000000000000003"
    assert payload["profile"]["ely_user_id"] == "user-id"


def test_custom_gc_and_xms_are_not_duplicated(tmp_path: Path) -> None:
    service = object.__new__(LauncherService)

    options = service.build_launch_options(
        "Player",
        tmp_path,
        4096,
        custom_jvm_args="-XX:+UseZGC -Xms2048M -XX:MaxGCPauseMillis=90",
        optimize_minecraft=True,
        java_major=21,
    )

    args = options["jvmArguments"]
    assert "-XX:+UseG1GC" not in args
    assert args.count("-XX:+UseZGC") == 1
    assert len([arg for arg in args if arg.startswith("-Xms")]) == 1
    assert len([arg for arg in args if arg.startswith("-XX:MaxGCPauseMillis")]) == 1


def test_recommended_memory_stays_within_safe_bounds() -> None:
    service = object.__new__(LauncherService)

    memory_mb = service.recommended_minecraft_memory_mb()

    assert 1024 <= memory_mb <= 12288


def test_install_request_preserves_disabled_optimization(tmp_path: Path) -> None:
    service = object.__new__(LauncherService)
    stage_dir = tmp_path / "stage"
    final_dir = tmp_path / "instances" / "instance"
    minecraft_dir = stage_dir / ".minecraft"
    minecraft_dir.mkdir(parents=True)

    request = InstallRequest(
        instance_id="instance",
        name="Instance",
        vanilla_version="1.21.5",
        mod_loader_id=None,
        mod_loader_version=None,
        icon_path="assets/default-instance-icons/Grass Block.png",
        stage_dir=str(stage_dir),
        final_dir=str(final_dir),
        minecraft_dir=str(minecraft_dir),
        memory_mb=4096,
        optimize_minecraft=False,
    )
    result = InstallResult(
        name="Instance",
        vanilla_version="1.21.5",
        installed_version="1.21.5",
        mod_loader_id=None,
        mod_loader_version=None,
    )

    service.default_icon = "assets/default-instance-icons/Grass Block.png"
    service._normalize_icon_reference = lambda value: str(value)
    service.resolve_icon_path = lambda value: str(value)

    instance = service.finalize_install(request, result)

    assert instance.optimize_minecraft is False
    assert '"optimize_minecraft": false' in (final_dir / "instance.json").read_text(encoding="utf-8")
