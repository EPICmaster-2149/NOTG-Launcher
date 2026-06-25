from __future__ import annotations

import logging
import sys
from typing import Any, Callable

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QTimer, Signal

logger = logging.getLogger(__name__)


class WinEventFilter(QAbstractNativeEventFilter):
    def __init__(self, callback: Callable[[int], None]):
        super().__init__()
        self._callback = callback
        self._registered: dict[int, int] = {}
        self._next_id = 1

    def register_hotkey(self, modifiers: int, key: int) -> int:
        if sys.platform != "win32":
            return 0

        import ctypes
        from ctypes import wintypes

        hwnd = int(self._get_main_window_hwnd()) if hasattr(self, '_hwnd') else 0
        if not hwnd:
            logger.warning("Cannot register global hotkey: no window handle available")
            return 0

        hotkey_id = self._next_id
        self._next_id += 1

        user32 = ctypes.windll.user32
        result = user32.RegisterHotKey(hwnd, hotkey_id, modifiers, key)
        if result:
            self._registered[hotkey_id] = (modifiers << 16) | key
            logger.debug(f"Registered global hotkey id={hotkey_id}")
            return hotkey_id
        else:
            logger.warning(f"Failed to register global hotkey id={hotkey_id}")
            return 0

    def unregister_hotkey(self, hotkey_id: int) -> bool:
        if sys.platform != "win32":
            return False

        import ctypes

        user32 = ctypes.windll.user32
        hwnd = int(self._get_main_window_hwnd()) if hasattr(self, '_hwnd') else 0
        result = user32.UnregisterHotKey(hwnd, hotkey_id)
        self._registered.pop(hotkey_id, None)
        return bool(result)

    def set_hwnd(self, hwnd: int) -> None:
        self._hwnd = hwnd

    def _get_main_window_hwnd(self) -> int:
        return getattr(self, '_hwnd', 0)

    def nativeEventFilter(self, eventType: bytes, message: int) -> tuple[bool, int]:
        if sys.platform != "win32":
            return (False, 0)

        if eventType != b"windows_generic_MSG":
            return (False, 0)

        from ctypes import wintypes, Structure, POINTER

        class MSG(Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM),
                ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD),
                ("pt", POINTER(wintypes.POINT)),
            ]

        try:
            msg = ctypes.cast(message, POINTER(MSG)).contents
        except Exception:
            return (False, 0)

        WM_HOTKEY = 0x0312
        if msg.message == WM_HOTKEY:
            hotkey_id = int(msg.wParam)
            if hotkey_id in self._registered:
                logger.debug(f"Global hotkey fired: id={hotkey_id}")
                self._callback(hotkey_id)
                return (True, 0)

        return (False, 0)


class GlobalHotkeyManager(QObject):
    f3_m_triggered = Signal()

    VK_F3 = 0x72
    VK_M = 0x4D
    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    MOD_SHIFT = 0x0004
    MOD_WIN = 0x0008
    MOD_NOREPEAT = 0x4000

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._event_filter: WinEventFilter | None = None
        self._f3_m_id: int = 0
        self._alt_f4_blocked_id: int = 0
        self._installed = False
        self._enabled = False

    def install(self, win_id: int) -> None:
        if sys.platform != "win32":
            logger.info("Global hotkeys are only supported on Windows")
            return

        if self._installed:
            return

        from PySide6.QtCore import QCoreApplication

        self._event_filter = WinEventFilter(self._on_hotkey)
        self._event_filter.set_hwnd(win_id)
        QCoreApplication.instance().installNativeEventFilter(self._event_filter)
        self._installed = True

    def uninstall(self) -> None:
        if not self._installed:
            return

        self.unregister_all()

        from PySide6.QtCore import QCoreApplication

        if self._event_filter is not None:
            QCoreApplication.instance().removeNativeEventFilter(self._event_filter)
            self._event_filter = None
        self._installed = False

    def register_f3_m(self) -> bool:
        if self._event_filter is None:
            return False

        modifiers = self.MOD_NOREPEAT
        self._f3_m_id = self._event_filter.register_hotkey(modifiers, self.VK_F3)
        return self._f3_m_id != 0

    def unregister_f3_m(self) -> None:
        if self._event_filter is not None and self._f3_m_id:
            self._event_filter.unregister_hotkey(self._f3_m_id)
            self._f3_m_id = 0

    def unregister_all(self) -> None:
        self.unregister_f3_m()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def _on_hotkey(self, hotkey_id: int) -> None:
        if not self._enabled:
            return

        if hotkey_id == self._f3_m_id:
            if sys.platform == "win32":
                import ctypes
                user32 = ctypes.windll.user32
                m_pressed = bool(user32.GetAsyncKeyState(self.VK_M) & 0x8000)
                if m_pressed:
                    QTimer.singleShot(0, self.f3_m_triggered.emit)