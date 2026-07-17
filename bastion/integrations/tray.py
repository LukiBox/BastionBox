"""System-tray residence — BastionBox lives in the tray with a status readout.

An opt-in tray icon (drawn programmatically — no external asset, air-gap-clean)
with a menu to show the window, summon quick-ask, and quit, plus a tooltip that
carries the model/status line. Everything here is local; the tray is presence,
not telephony.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..ui.theme import Palette


def _draw_icon(palette: Palette, size: int = 32) -> QIcon:
    """Draw a tactical 'shielded box' glyph so no image file is needed."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.fillRect(0, 0, size, size, QColor(palette.bg))
    pen = QPen(QColor(palette.brand))
    pen.setWidth(2)
    p.setPen(pen)
    m = 5
    # A rounded 'bastion' box with corner ticks.
    p.drawRoundedRect(m, m, size - 2 * m, size - 2 * m, 4, 4)
    p.setPen(QPen(QColor(palette.secure), 2))
    c = size // 2
    p.drawLine(c, m + 3, c, size - m - 3)          # vertical bar
    p.drawLine(m + 3, c, size - m - 3, c)          # horizontal bar
    p.end()
    return QIcon(pm)


class Tray(QSystemTrayIcon):
    def __init__(self, palette: Palette, on_show: Callable[[], None],
                 on_quick_ask: Callable[[], None], on_quit: Callable[[], None],
                 parent=None):
        super().__init__(_draw_icon(palette), parent)
        self.setToolTip("BastionBox — offline · sealed")
        menu = QMenu()
        self._status = QAction("no model loaded")
        self._status.setEnabled(False)
        menu.addAction(self._status)
        menu.addSeparator()
        act_show = QAction("Open BastionBox", menu)
        act_show.triggered.connect(on_show)
        act_ask = QAction("Quick Ask…  (Ctrl+Alt+Space)", menu)
        act_ask.triggered.connect(on_quick_ask)
        act_quit = QAction("Quit", menu)
        act_quit.triggered.connect(on_quit)
        menu.addAction(act_show)
        menu.addAction(act_ask)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)
        self._on_show = on_show

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._on_show()

    def set_status(self, text: str) -> None:
        self._status.setText(text)
        self.setToolTip(f"BastionBox — {text}")
