"""Cross-thread approval bridge — the diff dialog lives on the GUI thread, the
agent loop lives on a worker thread, and this marshals safely between them.

The agent loop runs off the UI thread so the window never freezes mid-task. But
a tool's ``request_write`` must show a *modal* dialog, which Qt only allows on
the GUI thread. The bridge closes that gap: the worker calls :meth:`ask_write`,
which emits a queued signal to the GUI thread and then blocks on a
:class:`threading.Event` until the user's decision comes back. No polling, no
races — the worker is parked, the UI is live, and approval is synchronous with
the step exactly as the user experiences it.

Wire ``ask_write`` / ``ask_command`` into a
:class:`~bastion.core.agent.permissions.PolicyBroker` so tier policy
(read-only / auto-approve) still applies before anything reaches a dialog.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Qt, Signal

from ...core.agent.diffing import Diff
from ...core.agent.permissions import Decision
from ...core.security.jail import Workspace
from ..theme import Palette


@dataclass
class _WriteRequest:
    ws: Workspace
    diff: Diff
    event: threading.Event = field(default_factory=threading.Event)
    decision: Decision = field(default_factory=lambda: Decision(False, "no response"))


@dataclass
class _CommandRequest:
    ws: Workspace
    command: str
    event: threading.Event = field(default_factory=threading.Event)
    decision: Decision = field(default_factory=lambda: Decision(False, "no response"))


@dataclass
class _QuestionRequest:
    question: str
    event: threading.Event = field(default_factory=threading.Event)
    answer: str = ""   # empty = the user skipped


class ApprovalBridge(QObject):
    """Marshals write/command approvals from a worker thread to the GUI thread."""

    _write_requested = Signal(object)
    _command_requested = Signal(object)
    _question_requested = Signal(object)

    def __init__(self, palette: Palette, parent=None):
        super().__init__(parent)
        self._palette = palette
        # QueuedConnection guarantees the slot runs on the thread that owns this
        # QObject (the GUI thread), regardless of who emits the signal.
        self._write_requested.connect(self._show_write, Qt.QueuedConnection)
        self._command_requested.connect(self._show_command, Qt.QueuedConnection)
        self._question_requested.connect(self._show_question, Qt.QueuedConnection)

    # -- called ON THE WORKER THREAD ---------------------------------------
    def ask_write(self, ws: Workspace, diff: Diff) -> Decision:
        req = _WriteRequest(ws, diff)
        self._write_requested.emit(req)
        req.event.wait()  # park the worker until the GUI thread answers
        return req.decision

    def ask_command(self, ws: Workspace, command: str) -> Decision:
        req = _CommandRequest(ws, command)
        self._command_requested.emit(req)
        req.event.wait()
        return req.decision

    def ask_question(self, question: str) -> str:
        """The agent's ask_user tool: pose *question* to the user and block for
        the answer. Empty string means the user skipped."""
        req = _QuestionRequest(question)
        self._question_requested.emit(req)
        req.event.wait()
        return req.answer

    # -- run ON THE GUI THREAD (queued) ------------------------------------
    def _show_write(self, req: _WriteRequest) -> None:
        from .diff_dialog import DiffDialog  # local import: keeps QWidget off the
        from ..theme import current_palette  # worker thread's import path
        try:  # colorize with the palette the app is showing *right now*
            req.decision = DiffDialog.ask(
                req.diff, current_palette(), req.ws.display_name)
        finally:
            req.event.set()

    def _show_command(self, req: _CommandRequest) -> None:
        from PySide6.QtWidgets import QMessageBox
        try:
            box = QMessageBox()
            box.setWindowTitle("RUN COMMAND — approval required")
            box.setText(f"The agent wants to run, jailed to the workspace:\n\n"
                        f"    {req.command}\n\nOutput is captured and logged.")
            box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
            box.setDefaultButton(QMessageBox.Cancel)
            approved = box.exec() == QMessageBox.Ok
            req.decision = Decision(approved,
                                    "approved" if approved else "rejected by user")
        finally:
            req.event.set()

    def _show_question(self, req: _QuestionRequest) -> None:
        # Modal on purpose: the worker is parked on the Event, and modality
        # means Stop can't be clicked mid-question — no leaked parked threads.
        from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel,
                                       QPlainTextEdit, QVBoxLayout)
        from ...core.i18n import t
        try:
            dlg = QDialog()
            dlg.setWindowTitle(t("chat.agent_question_title"))
            dlg.setMinimumWidth(460)
            lay = QVBoxLayout(dlg)
            q = QLabel(req.question)
            q.setWordWrap(True)
            lay.addWidget(q)
            hint = QLabel(t("chat.agent_question_hint"))
            hint.setWordWrap(True)
            hint.setObjectName("dim")   # picks up the theme's muted style
            lay.addWidget(hint)
            answer = QPlainTextEdit()
            answer.setFixedHeight(90)
            lay.addWidget(answer)
            buttons = QDialogButtonBox()
            ok = buttons.addButton(t("chat.agent_answer"),
                                   QDialogButtonBox.AcceptRole)
            buttons.addButton(t("chat.agent_skip"), QDialogButtonBox.RejectRole)
            buttons.accepted.connect(dlg.accept)
            buttons.rejected.connect(dlg.reject)
            ok.setDefault(True)
            lay.addWidget(buttons)
            answer.setFocus()
            req.answer = (answer.toPlainText().strip()
                          if dlg.exec() == QDialog.Accepted else "")
        finally:
            req.event.set()
