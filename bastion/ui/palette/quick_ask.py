"""Quick-ask palette — a Spotlight-style floating console, summoned and gone.

A frameless, always-on-top panel: ask, read the streamed answer, ``Esc``, gone.
It is a *stateless* one-shot (no conversation history) so it stays instant and
leaks no prior context, and it can optionally fold the clipboard in as context —
the "explain / review / fix this snippet I just copied" flow — without ever
sending a byte anywhere. Generation runs on the same worker thread as the main
chat, so the palette never blocks.

Summoned by the global hotkey (see :mod:`bastion.integrations.hotkey`) or the
tray menu; dismissed by ``Esc`` or losing focus.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QTextEdit, QVBoxLayout, QWidget)

from ...core.llm.engine import Engine, GenerationConfig, Message, Role
from ..chat.chat_view import GenerationWorker
from ..theme import Palette
from ..widgets.tactical import StatusPill, StencilLabel


class QuickAskPalette(QWidget):
    def __init__(self, engine: Engine, palette: Palette, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.Tool)
        self.setObjectName("Root")
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setFixedWidth(720)
        self._engine = engine
        self._palette = palette
        self._worker: GenerationWorker | None = None

        shell = QFrame(self)
        shell.setProperty("role", "card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(shell)

        v = QVBoxLayout(shell)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)

        header = QHBoxLayout()
        header.addWidget(StencilLabel("Quick Ask"))
        header.addStretch(1)
        header.addWidget(StatusPill("OFFLINE · SEALED", "secure"))
        v.addLayout(header)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Ask anything — Esc to dismiss. Nothing leaves this machine.")
        self._input.returnPressed.connect(self._ask)
        v.addWidget(self._input)

        row = QHBoxLayout()
        self._clip = QCheckBox("Use clipboard as context")
        row.addWidget(self._clip)
        row.addStretch(1)
        self._hint = QLabel("↩ ask   ·   Esc close")
        self._hint.setProperty("role", "readout")
        row.addWidget(self._hint)
        v.addLayout(row)

        self._answer = QTextEdit()
        self._answer.setObjectName("Mono")
        self._answer.setReadOnly(True)
        self._answer.setFixedHeight(220)
        self._answer.hide()
        v.addWidget(self._answer)

        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self.hide)

    # -- behavior -----------------------------------------------------------
    def summon(self) -> None:
        """Center on the active screen, clear, and focus the input."""
        self._input.clear()
        self._answer.clear()
        self._answer.hide()
        self.adjustSize()
        screen = QGuiApplication.screenAt(self.cursor().pos()) or \
            QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        self.move(geo.center().x() - self.width() // 2, geo.top() + geo.height() // 5)
        self.show()
        self.raise_()
        self.activateWindow()
        self._input.setFocus()

    def _ask(self) -> None:
        text = self._input.text().strip()
        if not text or self._worker is not None:
            return
        if self._clip.isChecked():
            clip = QGuiApplication.clipboard().text().strip()
            if clip:
                text = f"{text}\n\n--- clipboard ---\n{clip[:4000]}"
        self._answer.show()
        self._acc = ""
        self._answer.setPlainText("")
        self.adjustSize()
        messages = [
            Message(Role.SYSTEM, "You are BastionBox quick-ask: answer concisely, "
                                 "fully offline."),
            Message(Role.USER, text),
        ]
        self._worker = GenerationWorker(self._engine, messages,
                                        GenerationConfig(temperature=0.5, max_tokens=512))
        self._worker.chunk.connect(self._on_chunk)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_chunk(self, piece: str) -> None:
        self._acc += piece
        self._answer.setPlainText(self._acc)

    def _on_done(self) -> None:
        self._worker = None

    def focusOutEvent(self, event):  # noqa: N802 (Qt override)
        # Dismiss when focus leaves — Spotlight behavior. Skip while generating.
        if self._worker is None:
            self.hide()
        super().focusOutEvent(event)
