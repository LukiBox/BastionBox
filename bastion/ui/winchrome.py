"""Native window chrome that follows the theme (Windows).

Qt styles the *inside* of a window; the title bar belongs to the OS. On a
Windows machine set to dark mode, a light-themed BastionBox used to get a harsh
black title bar bolted on top — the "black box". This module talks to DWM
directly so the caption matches the palette:

* ``DWMWA_USE_IMMERSIVE_DARK_MODE`` (20) flips the caption's base mode,
* ``DWMWA_CAPTION_COLOR`` (35) / ``DWMWA_TEXT_COLOR`` (36) — Windows 11 —
  paint the caption in the exact surface/text colors of the palette.

Every call is best-effort: on Windows 10 the color attributes just return an
error we ignore, and on non-Windows everything is a no-op. A single
:class:`TitlebarStyler` event filter watches for top-level windows being shown
(dialogs included) and styles each one, so no widget needs to know about DWM.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QWidget

from .theme import Palette, current_palette

_IS_WINDOWS = sys.platform == "win32"

_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19   # pre-20H1 builds used 19
_DWMWA_WINDOW_CORNER_PREFERENCE = 33      # Windows 11
_DWMWCP_ROUND = 2
_DWMWA_CAPTION_COLOR = 35
_DWMWA_TEXT_COLOR = 36


def _colorref(hex_color: str) -> int:
    """``#RRGGBB`` → Win32 COLORREF (0x00BBGGRR)."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b << 16) | (g << 8) | r


def style_titlebar(widget: QWidget, palette: Palette | None = None) -> None:
    """Match *widget*'s native title bar to the palette. Best-effort, silent."""
    if not _IS_WINDOWS:
        return
    pal = palette or current_palette()
    try:
        import ctypes
        hwnd = int(widget.winId())
        dwm = ctypes.windll.dwmapi

        def _set(attr: int, value: int) -> int:
            v = ctypes.c_int(value)
            return dwm.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd), ctypes.c_uint(attr),
                ctypes.byref(v), ctypes.sizeof(v))

        dark = 1 if pal.name == "dark" else 0
        if _set(_DWMWA_USE_IMMERSIVE_DARK_MODE, dark) != 0:
            _set(_DWMWA_USE_IMMERSIVE_DARK_MODE_OLD, dark)
        # Frameless windows lose the OS rounding; ask Windows 11 to round the
        # corners (and paint its standard soft shadow). No-op on Windows 10.
        _set(_DWMWA_WINDOW_CORNER_PREFERENCE, _DWMWCP_ROUND)
        # Windows 11: paint the caption in the app's own surface color so the
        # chrome and the canvas read as one piece. Fails harmlessly on Win10.
        _set(_DWMWA_CAPTION_COLOR, _colorref(pal.surface))
        _set(_DWMWA_TEXT_COLOR, _colorref(pal.text))
    except Exception:  # noqa: BLE001 - chrome is cosmetic, never fatal
        pass


def restyle_all_windows(palette: Palette | None = None) -> None:
    """Re-apply the caption style to every open top-level window (theme switch)."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return
    for w in app.topLevelWidgets():
        if w.isWindow() and w.windowHandle() is not None:
            style_titlebar(w, palette)


class TitlebarStyler(QObject):
    """App-level event filter: styles every top-level window as it appears."""

    def eventFilter(self, obj, event):  # noqa: N802 (Qt override)
        if event.type() == QEvent.Show and isinstance(obj, QWidget) and obj.isWindow():
            style_titlebar(obj)
        return False


def install(app) -> TitlebarStyler:
    styler = TitlebarStyler(app)
    app.installEventFilter(styler)
    return styler
