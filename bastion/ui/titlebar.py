"""Custom title bar for the frameless main window.

The native caption is gone (``Qt.FramelessWindowHint``); this bar replaces it:
app mark on the left, the centered "BastionBox — The AI that never phones home."
title, and custom minimize / maximize-restore / close buttons on the right —
all palette-driven, so the chrome finally belongs to the design instead of the
OS.

Dragging is real window movement: the bar calls
``windowHandle().startSystemMove()`` on press, which hands the drag to the OS —
Aero Snap by dragging to screen edges keeps working. Double-click toggles
maximize/restore. Edge *resizing* is not this widget's job; the main window
answers ``WM_NCHITTEST`` for that (see MainWindow.nativeEvent).
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from ..core.i18n import t
from .icons import icon, pixmap
from .theme import current_palette


class TitleBar(QWidget):
    HEIGHT = 42

    def __init__(self, title: str, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.setFixedHeight(self.HEIGHT)
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 4, 8, 4)
        h.setSpacing(2)

        self._mark = QLabel()
        self._mark.setFixedSize(22, 22)
        self._mark.setAlignment(Qt.AlignCenter)
        h.addWidget(self._mark)
        # Balance the three buttons on the right so the title sits centered.
        balance = QWidget()
        balance.setFixedWidth(3 * 38 - 22 - 6)
        balance.setAttribute(Qt.WA_TransparentForMouseEvents)
        h.addWidget(balance)

        h.addStretch(1)
        self._title = QLabel(title)
        self._title.setObjectName("TitleText")
        self._title.setAlignment(Qt.AlignCenter)
        h.addWidget(self._title)
        h.addStretch(1)

        self._min = self._button(t("titlebar.minimize"))
        self._min.clicked.connect(lambda: self.window().showMinimized())
        self._max = self._button(t("titlebar.maximize"))
        self._max.clicked.connect(self.toggle_max)
        self._close = self._button(t("titlebar.close"), close=True)
        self._close.clicked.connect(lambda: self.window().close())
        for b in (self._min, self._max, self._close):
            h.addWidget(b)
        self.refresh_icons()

    def set_title(self, title: str) -> None:
        self._title.setText(title)

    def retranslate(self) -> None:
        """Re-read the button tooltips in the newly selected language."""
        for btn, key in ((self._min, "titlebar.minimize"),
                         (self._close, "titlebar.close")):
            btn.setToolTip(t(key))
            btn.setAccessibleName(t(key))
        self.sync_max_icon(self.window().isMaximized() if self.window() else False)

    @staticmethod
    def _button(tip: str, close: bool = False) -> QPushButton:
        b = QPushButton("")
        b.setObjectName("WinBtnClose" if close else "WinBtn")
        b.setFixedSize(38, 30)
        b.setIconSize(QSize(14, 14))
        b.setToolTip(tip)
        b.setAccessibleName(tip)
        b.setCursor(Qt.PointingHandCursor)
        b.setFocusPolicy(Qt.NoFocus)
        return b

    def refresh_icons(self) -> None:
        pal = current_palette()
        self._mark.setPixmap(pixmap("box", pal.brand, 16))
        self._min.setIcon(icon("minus", pal.text_dim, 14))
        self.sync_max_icon(self.window().isMaximized() if self.window() else False)
        # Close: dim normally, white when hovered (QIcon.Active) over the red.
        close = QIcon()
        close.addPixmap(pixmap("x", pal.text_dim, 14), QIcon.Normal)
        close.addPixmap(pixmap("x", pal.on_accent, 14), QIcon.Active)
        self._close.setIcon(close)

    def sync_max_icon(self, maximized: bool) -> None:
        pal = current_palette()
        self._max.setIcon(icon("restore" if maximized else "square",
                               pal.text_dim, 14))
        tip = t("titlebar.restore") if maximized else t("titlebar.maximize")
        self._max.setToolTip(tip)
        self._max.setAccessibleName(tip)

    def toggle_max(self) -> None:
        w = self.window()
        if w.isMaximized():
            w.showNormal()
        else:
            w.showMaximized()

    # -- dragging -------------------------------------------------------------
    def mousePressEvent(self, event):  # noqa: N802 (Qt override)
        if (event.button() == Qt.LeftButton
                and not isinstance(self.childAt(event.position().toPoint()),
                                   QPushButton)
                and not self.window().isMaximized()):
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802 (Qt override)
        if (event.button() == Qt.LeftButton
                and not isinstance(self.childAt(event.position().toPoint()),
                                   QPushButton)):
            self.toggle_max()
            return
        super().mouseDoubleClickEvent(event)
