"""Global hotkey — summon the quick-ask palette from anywhere, offline.

On Windows this uses ``RegisterHotKey`` (via ``ctypes``, no dependency) plus a Qt
native event filter that catches ``WM_HOTKEY`` and fires the callback on the GUI
thread. It is entirely opt-in and degrades to a no-op — with an honest log line —
where registration is unavailable or the platform isn't Windows, so the app never
crashes over a hotkey it couldn't grab.

Registering a *system-wide* hotkey is an OS integration, not a network one: it
touches no sockets and the offline guard is unaffected.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Callable

from PySide6.QtCore import QAbstractNativeEventFilter, QObject

_WM_HOTKEY = 0x0312
_MOD_ALT = 0x0001
_MOD_CONTROL = 0x0002
_MOD_SHIFT = 0x0004
_MOD_NOREPEAT = 0x4000
_VK_SPACE = 0x20


class _HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, hotkey_id: int, callback: Callable[[], None]):
        super().__init__()
        self._id = hotkey_id
        self._callback = callback

    def nativeEventFilter(self, event_type, message):  # noqa: N802
        if event_type == b"windows_generic_MSG":
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == _WM_HOTKEY and msg.wParam == self._id:
                try:
                    self._callback()
                except Exception:  # a UI callback must never crash the filter
                    pass
        return False, 0


class GlobalHotkey(QObject):
    """Registers Ctrl+Alt+Space to summon the palette (Windows). No-op elsewhere.

    We use a single, unambiguous chord rather than the double-tap in config
    because ``RegisterHotKey`` cannot express double-taps; the chord is the honest,
    reliable primitive. The config's double-tap remains the aspirational default
    for a future low-level keyboard hook.
    """

    HOTKEY_ID = 0xB0B  # arbitrary, unique within this process

    def __init__(self, callback: Callable[[], None], parent=None):
        super().__init__(parent)
        self._callback = callback
        self._filter: _HotkeyFilter | None = None
        self._registered = False

    def install(self, app) -> bool:
        if sys.platform != "win32":
            return False
        try:
            ok = ctypes.windll.user32.RegisterHotKey(
                None, self.HOTKEY_ID,
                _MOD_CONTROL | _MOD_ALT | _MOD_NOREPEAT, _VK_SPACE)
            if not ok:
                return False
            self._filter = _HotkeyFilter(self.HOTKEY_ID, self._callback)
            app.installNativeEventFilter(self._filter)
            self._registered = True
            return True
        except Exception:  # noqa: BLE001
            return False

    def uninstall(self) -> None:
        if self._registered and sys.platform == "win32":
            try:
                ctypes.windll.user32.UnregisterHotKey(None, self.HOTKEY_ID)
            except Exception:  # noqa: BLE001
                pass
            self._registered = False

    @property
    def chord(self) -> str:
        return "Ctrl+Alt+Space"
