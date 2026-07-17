"""Startup theme picker — choose Dark or Light the instant the app opens.

A small, fast dialog shown at launch (until the user ticks "don't ask again").
Selecting a theme previews it *live* on the whole app, so the choice is a
one-click, see-it-immediately decision. The pick is persisted in the encrypted
settings and can always be changed later from Settings.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget, QDialog)

from .theme import THEMES, Palette
from .widgets.tactical import StencilLabel


def _swatch_row(pal: Palette) -> QWidget:
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    for color in (pal.bg, pal.surface, pal.brand, pal.secure, pal.amber, pal.danger):
        chip = QFrame()
        chip.setFixedSize(26, 26)
        chip.setStyleSheet(
            f"background:{color};border:1px solid {pal.border_strong};border-radius:4px;")
        lay.addWidget(chip)
    lay.addStretch(1)
    return row


class _ThemeCard(QFrame):
    """A selectable preview card for one theme."""

    def __init__(self, pal: Palette, title: str, on_pick: Callable[[str], None]):
        super().__init__()
        self._name = pal.name
        self._on_pick = on_pick
        self.setProperty("role", "card")
        self.setCursor(Qt.PointingHandCursor)
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 16)
        v.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(StencilLabel(title))
        head.addStretch(1)
        self._check = QLabel("○")
        self._check.setStyleSheet(f"color:{pal.brand};font-size:18px;")
        head.addWidget(self._check)
        v.addLayout(head)
        v.addWidget(_swatch_row(pal))
        sub = QLabel("Deep forest + sage teal" if pal.name == "dark"
                     else "Soft sage + floating white")
        sub.setProperty("role", "readout")
        v.addWidget(sub)

    def mousePressEvent(self, event):  # noqa: N802
        self._on_pick(self._name)

    def set_selected(self, selected: bool) -> None:
        self._check.setText("●" if selected else "○")
        self.setStyleSheet("QFrame{border:2px solid %s;}" % THEMES[self._name].brand
                           if selected else "")


class ThemePicker(QDialog):
    def __init__(self, apply_live: Callable[[str], None], current: str = "dark",
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose your display")
        self.setMinimumWidth(560)
        self._apply_live = apply_live
        self._chosen = current if current in THEMES else "dark"
        self.dont_ask = False

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 20)
        v.setSpacing(16)
        title = QLabel("DISPLAY THEME")
        title.setProperty("role", "h1")
        v.addWidget(title)
        hint = QLabel("Pick a look — it applies instantly. You can change it any "
                      "time in Settings.")
        hint.setProperty("role", "readout")
        hint.setWordWrap(True)
        v.addWidget(hint)

        cards = QHBoxLayout()
        cards.setSpacing(16)
        self._cards = {
            "dark": _ThemeCard(THEMES["dark"], "BASTION DARK", self._pick),
            "light": _ThemeCard(THEMES["light"], "BASTION LIGHT", self._pick),
        }
        cards.addWidget(self._cards["dark"])
        cards.addWidget(self._cards["light"])
        v.addLayout(cards)

        self._remember = QCheckBox("Use this and don't ask at launch again")
        v.addWidget(self._remember)

        row = QHBoxLayout()
        row.addStretch(1)
        confirm = QPushButton("CONFIRM")
        confirm.setProperty("variant", "primary")
        confirm.clicked.connect(self._confirm)
        row.addWidget(confirm)
        v.addLayout(row)

        self._pick(self._chosen)

    def _pick(self, name: str) -> None:
        self._chosen = name
        for key, card in self._cards.items():
            card.set_selected(key == name)
        self._apply_live(name)   # live preview across the whole app

    def _confirm(self) -> None:
        self.dont_ask = self._remember.isChecked()
        self.accept()

    @property
    def chosen(self) -> str:
        return self._chosen

    @staticmethod
    def run_if_needed(store, apply_live: Callable[[str], None],
                      current: str, parent=None) -> str:
        """Show the picker unless the user chose to stop being asked.

        Returns the theme to use. Persists both the chosen theme and the
        "ask at launch" preference to the encrypted settings.
        """
        ask = (store.get_setting("__global__", "theme_ask", "1") if store else "1")
        saved = (store.get_setting("__global__", "theme", current) if store else current)
        if ask != "1":
            apply_live(saved or current)
            return saved or current
        dlg = ThemePicker(apply_live, saved or current, parent)
        dlg.exec()
        if store is not None:
            store.set_setting("__global__", "theme", dlg.chosen)
            store.set_setting("__global__", "theme_ask", "0" if dlg.dont_ask else "1")
        return dlg.chosen
