"""Discord Rich Presence integration for NOTG Launcher."""

from __future__ import annotations

import logging
import time
from typing import Any

try:
    from pypresence import Presence
except ImportError:  # pragma: no cover - depends on local environment
    Presence = None

logger = logging.getLogger(__name__)


APPLICATION_ID = "1496879744858325066"
LARGE_IMAGE_KEY = "graphicslogo"
SMALL_IMAGE_KEY = "notg_launcher_logo"

_PLACEHOLDER_VALUES = {
    "",
    "YOUR_APP_ID_HERE",
    "YOUR_LARGE_IMAGE_KEY_HERE",
    "YOUR_SMALL_IMAGE_KEY_HERE",
}


def _is_placeholder(value: str) -> bool:
    return str(value).strip() in _PLACEHOLDER_VALUES


class DiscordRichPresence:
    """Maintain a single Discord RPC connection for one runtime session."""

    def __init__(self, *, application_id: str = APPLICATION_ID):
        self.application_id = str(application_id).strip()
        self._rpc: Presence | None = None
        self._connected = False
        self._last_payload: tuple[tuple[str, Any], ...] | None = None

    def is_configured(self) -> bool:
        return self.application_id.isdigit() and not _is_placeholder(self.application_id)

    def connect(self, max_retries: int = 2, retry_delay: float = 1.0) -> bool:
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
            except Exception as exc:  # noqa: BLE001
                logger.debug("Discord RPC connection attempt failed: %s", exc)
                self._rpc = None
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)

        return False

    def update(
        self,
        *,
        state: str,
        details: str,
        started_at: float | None = None,
        large_text: str | None = None,
        small_text: str | None = None,
    ) -> None:
        if not self.connect() or self._rpc is None:
            return

        payload: dict[str, Any] = {
            "state": state,
            "details": details,
        }
        if started_at is not None:
            payload["start"] = int(started_at)
        if not _is_placeholder(LARGE_IMAGE_KEY):
            payload["large_image"] = LARGE_IMAGE_KEY.lower()
        if large_text:
            payload["large_text"] = large_text
        if not _is_placeholder(SMALL_IMAGE_KEY):
            payload["small_image"] = SMALL_IMAGE_KEY.lower()
        if small_text:
            payload["small_text"] = small_text

        normalized_payload = tuple(sorted(payload.items()))
        if normalized_payload == self._last_payload:
            return

        try:
            self._rpc.update(**payload)
            self._last_payload = normalized_payload
        except Exception as exc:  # noqa: BLE001
            logger.debug("Discord RPC update failed: %s", exc)

    def clear(self) -> None:
        if not self._connected or self._rpc is None:
            return
        try:
            self._rpc.clear()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Discord RPC clear failed: %s", exc)
        finally:
            self._last_payload = None

    def close(self) -> None:
        if self._rpc is None:
            return
        try:
            self._rpc.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Discord RPC close failed: %s", exc)
        finally:
            self._rpc = None
            self._connected = False
            self._last_payload = None
