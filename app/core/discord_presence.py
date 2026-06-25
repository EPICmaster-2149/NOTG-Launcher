from __future__ import annotations

import logging
import time
from typing import Any

try:
    from pypresence import Presence
except ImportError:
    Presence = None

logger = logging.getLogger(__name__)


APPLICATION_ID = "1496879744858325066"
LARGE_IMAGE_KEY = "notg_launcher_logo"
SMALL_IMAGE_KEY = "graphicslogo"
MAX_ACTIVITY_TEXT_LENGTH = 128


class DiscordRichPresence:
    def __init__(self, *, application_id: str = APPLICATION_ID):
        self.application_id = str(application_id).strip()
        self._rpc: Presence | None = None
        self._connected = False
        self._last_payload: tuple[tuple[str, Any], ...] | None = None
        self._image_assets_enabled = True
        self._activity_pid: int | None = None

    def is_configured(self) -> bool:
        return bool(self.application_id) and self.application_id.isdigit()

    def connect(self, max_retries: int = 3, retry_delay: float = 1.0) -> bool:
        if self._connected:
            return True
        if Presence is None:
            logger.debug("Discord Rich Presence skipped because pypresence is not installed.")
            return False
        if not self.is_configured():
            logger.debug("Discord Rich Presence skipped because the application id is not configured.")
            return False

        for attempt in range(max_retries):
            try:
                self._rpc = Presence(self.application_id)
                self._rpc.connect()
                self._connected = True
                logger.info("Connected to Discord RPC")
                return True
            except Exception as exc:
                logger.debug("Discord RPC connection attempt failed: %s", exc)
                self._reset_connection()
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)

        return False

    def update(
        self,
        *,
        state: str,
        details: str,
        pid: int | None = None,
        started_at: float | None = None,
        large_text: str | None = None,
        small_text: str | None = None,
    ) -> None:
        if not self.connect() or self._rpc is None:
            return

        payload: dict[str, Any] = {
            "state": _normalize_activity_text(
                state,
                fallback="Playing Minecraft",
            ),
            "details": _normalize_activity_text(details, fallback="Minecraft"),
        }
        if pid is not None and pid > 0:
            self._activity_pid = int(pid)
            payload["pid"] = self._activity_pid
        if started_at is not None:
            payload["start"] = int(started_at)
        if self._image_assets_enabled:
            payload["large_image"] = LARGE_IMAGE_KEY.lower()
            if large_text:
                payload["large_text"] = _normalize_activity_text(
                    large_text, fallback=""
                )
            payload["small_image"] = SMALL_IMAGE_KEY.lower()
            if small_text:
                payload["small_text"] = _normalize_activity_text(
                    small_text, fallback=""
                )

        normalized_payload = tuple(sorted(payload.items()))
        if normalized_payload == self._last_payload:
            return

        try:
            self._rpc.update(**payload)
            self._last_payload = normalized_payload
        except Exception as exc:
            logger.debug("Discord RPC update failed: %s", exc)
            self._reset_connection()
            if self._image_assets_enabled and (
                "large_image" in payload or "small_image" in payload
            ):
                logger.debug("Retrying Discord RPC update without image assets.")
                self._image_assets_enabled = False
                payload.pop("large_image", None)
                payload.pop("large_text", None)
                payload.pop("small_image", None)
                payload.pop("small_text", None)
                self._update_once(payload)

    def clear(self) -> None:
        if not self._connected or self._rpc is None:
            return
        try:
            if self._activity_pid is not None:
                self._rpc.clear(pid=self._activity_pid)
            else:
                self._rpc.clear()
        except Exception as exc:
            logger.debug("Discord RPC clear failed: %s", exc)
        finally:
            self._last_payload = None

    def close(self) -> None:
        if self._rpc is None:
            return
        try:
            self._rpc.close()
        except Exception as exc:
            logger.debug("Discord RPC close failed: %s", exc)
        finally:
            self._rpc = None
            self._connected = False
            self._last_payload = None

    def _update_once(self, payload: dict[str, Any]) -> None:
        if not self.connect() or self._rpc is None:
            return
        normalized_payload = tuple(sorted(payload.items()))
        try:
            self._rpc.update(**payload)
            self._last_payload = normalized_payload
        except Exception as exc:
            logger.debug("Discord RPC retry failed: %s", exc)
            self._reset_connection()

    def _reset_connection(self) -> None:
        rpc = self._rpc
        self._rpc = None
        self._connected = False
        self._last_payload = None
        if rpc is None:
            return
        try:
            rpc.close()
        except Exception:
            pass


def _normalize_activity_text(value: str | None, *, fallback: str) -> str:
    text = (value or "").strip() or fallback
    if len(text) <= MAX_ACTIVITY_TEXT_LENGTH:
        return text
    return text[:MAX_ACTIVITY_TEXT_LENGTH].rstrip() or fallback