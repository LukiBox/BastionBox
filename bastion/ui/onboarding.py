"""First-run onboarding — a short, honest tour of the security model.

Not a marketing carousel: three plain cards that tell a new operator what
BastionBox guarantees, what it does not, and how the mount → approve → audit loop
works. Shown once (a flag is stored in the encrypted settings), re-openable from
Settings. The copy is calm and specific — this app's user may be audited.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from .theme import Palette
from .widgets.tactical import Card, HudFrame, StatusPill, StencilLabel

_STEPS = [
    ("NOTHING LEAVES",
     "BastionBox runs entirely on this machine. An in-process network guard is "
     "armed before anything else loads and blocks every outbound connection — "
     "including a sloppy dependency's. The Security tab shows a blocked-attempt "
     "counter that reads 0 in normal use.",
     "OFFLINE · SEALED", "secure"),
    ("YOU APPROVE EVERY WRITE",
     "Mount a folder as a workspace and the agent can read and edit inside it — "
     "and nowhere else, enforced by the path jail. Every write is shown to you as "
     "a diff to Approve or Reject before it touches disk. A rejection is fed back "
     "to the model so it adapts.",
     "ASK PER WRITE", "armed"),
    ("EVERYTHING IS PROVABLE",
     "Every prompt, tool call, file path, diff, and command is recorded in a "
     "hash-chained audit log. One click re-verifies the whole chain and flags any "
     "tampering. Data at rest is AES-256-GCM encrypted; secure-delete wipes a "
     "workspace's entire footprint.",
     "AUDIT · VERIFIABLE", "secure"),
]


class Onboarding(QDialog):
    def __init__(self, palette: Palette, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to BastionBox")
        self.setMinimumSize(640, 460)
        self._palette = palette

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 20)
        v.setSpacing(14)

        title = QLabel("BASTIONBOX")
        title.setProperty("role", "h1")
        v.addWidget(title)
        tag = QLabel("The AI that never phones home.")
        tag.setProperty("role", "readout")
        v.addWidget(tag)

        self._stack = QStackedWidget()
        for headline, body, pill_text, status in _STEPS:
            self._stack.addWidget(self._step(headline, body, pill_text, status))
        v.addWidget(self._stack, 1)

        # Controls row: don't-show-again + detailed tutorial + nav.
        opts = QHBoxLayout()
        self._show_again = QCheckBox("Show this tour next launch")
        self._show_again.setChecked(False)  # default: don't nag on 2nd open
        opts.addWidget(self._show_again)
        opts.addStretch(1)
        tut = QPushButton("DETAILED TUTORIAL")
        tut.setToolTip("Step-by-step: load a GGUF, run the agent, edit files & docs")
        tut.clicked.connect(self._open_tutorial)
        opts.addWidget(tut)
        v.addLayout(opts)

        row = QHBoxLayout()
        self._dots = QLabel()
        self._dots.setProperty("role", "readout")
        row.addWidget(self._dots)
        row.addStretch(1)
        self._back = QPushButton("BACK")
        self._back.clicked.connect(self._prev)
        self._next = QPushButton("NEXT")
        self._next.setProperty("variant", "primary")
        self._next.clicked.connect(self._advance)
        row.addWidget(self._back)
        row.addWidget(self._next)
        v.addLayout(row)
        self._sync()

    def _open_tutorial(self) -> None:
        from .tutorial import Tutorial
        Tutorial(self._palette, self).exec()

    @property
    def show_again(self) -> bool:
        return self._show_again.isChecked()

    def _step(self, headline: str, body: str, pill_text: str, status: str) -> QWidget:
        frame = HudFrame(self._palette.brand)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(22, 22, 22, 22)
        lay.setSpacing(12)
        lay.addWidget(StatusPill(pill_text, status))
        h = QLabel(headline)
        h.setProperty("role", "h1")
        lay.addWidget(h)
        b = QLabel(body)
        b.setProperty("role", "readout")
        b.setWordWrap(True)
        lay.addWidget(b)
        lay.addStretch(1)
        return frame

    def _advance(self) -> None:
        i = self._stack.currentIndex()
        if i >= self._stack.count() - 1:
            self.accept()
            return
        self._stack.setCurrentIndex(i + 1)
        self._sync()

    def _prev(self) -> None:
        self._stack.setCurrentIndex(max(0, self._stack.currentIndex() - 1))
        self._sync()

    def _sync(self) -> None:
        i = self._stack.currentIndex()
        last = i == self._stack.count() - 1
        self._back.setEnabled(i > 0)
        self._next.setText("ENTER BASTIONBOX" if last else "NEXT")
        self._dots.setText("  ".join("●" if j == i else "○"
                                     for j in range(self._stack.count())))

    @staticmethod
    def maybe_show(palette: Palette, store, parent=None) -> None:
        """Show unless the user has opted out; the flag lives in encrypted settings.

        Shown on first run. On the last card the user chooses whether to see it
        again next launch (default: no), so it never nags on the second open of
        the .exe unless the user asks for it.
        """
        seen = store.get_setting("__global__", "onboarded", "") if store else "1"
        if seen == "1":
            return
        dlg = Onboarding(palette, parent)
        dlg.exec()
        if store is not None:
            # "onboarded=1" suppresses future auto-shows unless they ticked to keep it.
            store.set_setting("__global__", "onboarded",
                              "0" if dlg.show_again else "1")
