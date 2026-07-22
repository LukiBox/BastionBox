"""Detailed tutorial — the optional, step-by-step guide.

Reached from a button in the short onboarding (or Settings). Unlike the three-card
tour, this is a scrollable manual covering the things a new operator actually has
to do: load a GGUF model, mount a workspace and run the agent, and use the file /
office editing flow (read a datasheet, write a Word/Excel/PDF report). Plain,
numbered steps — no fluff.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from .theme import Palette
from .widgets.tactical import Card, StatusPill
from ..core.i18n import t

# (headline key, pill key, pill status, step keys) — resolved at build time so
# the manual opens in whichever language the app is currently set to.
_SECTIONS = [
    ("tut.s1_head", "tut.s1_pill", "armed",
     ["tut.s1_1", "tut.s1_2", "tut.s1_3", "tut.s1_4", "tut.s1_5"]),
    ("tut.s2_head", "tut.s2_pill", "secure",
     ["tut.s2_1", "tut.s2_2", "tut.s2_3", "tut.s2_4", "tut.s2_5"]),
    ("tut.s3_head", "tut.s3_pill", "secure",
     ["tut.s3_1", "tut.s3_2", "tut.s3_3", "tut.s3_4", "tut.s3_5"]),
    ("tut.s4_head", "tut.s4_pill", "armed",
     ["tut.s4_1", "tut.s4_2", "tut.s4_3", "tut.s4_4", "tut.s4_5", "tut.s4_6"]),
    ("tut.s5_head", "tut.s5_pill", "secure",
     ["tut.s5_1", "tut.s5_2", "tut.s5_3", "tut.s5_4", "tut.s5_5"]),
]


class Tutorial(QDialog):
    def __init__(self, palette: Palette, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("tut.window"))
        self.setMinimumSize(720, 620)
        self._palette = palette

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(14)
        title = QLabel(t("tut.title"))
        title.setProperty("role", "h1")
        v.addWidget(title)
        sub = QLabel(t("tut.sub"))
        sub.setProperty("role", "readout")
        sub.setWordWrap(True)
        v.addWidget(sub)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(2, 2, 8, 2)
        col.setSpacing(14)
        for head_key, pill_key, status, step_keys in _SECTIONS:
            col.addWidget(self._section(t(head_key), t(pill_key), status,
                                        [t(k) for k in step_keys]))
        col.addStretch(1)
        scroll.setWidget(body)
        v.addWidget(scroll, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton(t("common.close").upper())
        close.setProperty("variant", "primary")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        v.addLayout(row)

    def _section(self, headline: str, pill: str, status: str, steps) -> Card:
        card = Card(headline)
        card.add_header_widget(StatusPill(pill, status))
        for i, step in enumerate(steps, 1):
            row = QHBoxLayout()
            num = QLabel(f"{i:02d}")
            num.setStyleSheet(f"color:{self._palette.brand_hi};font-family:monospace;"
                              f"font-weight:700;")
            num.setFixedWidth(26)
            num.setAlignment(Qt.AlignTop)
            text = QLabel(step)
            text.setProperty("role", "readout")
            text.setWordWrap(True)
            row.addWidget(num)
            row.addWidget(text, 1)
            card.body().addLayout(row)
        return card
