"""Diff-approval dialog — no edit reaches disk without passing through this.

Shows the proposed change as a colorized unified diff with a +added/−removed
badge and Approve / Reject (with a note) / Approve-all-this-session. Returns a
:class:`~bastion.core.agent.permissions.Decision`. Wired into a UI permission
broker so the agent's ``write_file``/``edit_file`` calls surface here.
"""
from __future__ import annotations

from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QTextEdit, QVBoxLayout)

from ...core.agent.diffing import Diff
from ...core.agent.permissions import Decision
from ...core.i18n import t
from ..theme import Palette


def _colorize(diff_text: str, p: Palette) -> str:
    """Render a unified diff as HTML with add/remove line coloring."""
    rows = []
    for line in diff_text.splitlines():
        safe = (line.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;") or "&nbsp;")
        if line.startswith("+") and not line.startswith("+++"):
            color, bg = p.secure, "rgba(63,185,79,0.10)"
        elif line.startswith("-") and not line.startswith("---"):
            color, bg = p.danger, "rgba(229,72,77,0.10)"
        elif line.startswith("@@"):
            color, bg = p.info, "transparent"
        else:
            color, bg = p.text_dim, "transparent"
        rows.append(
            f'<div style="color:{color};background:{bg};white-space:pre;">{safe}</div>')
    return "".join(rows)


class DiffDialog(QDialog):
    def __init__(self, diff: Diff, palette: Palette, workspace_name: str = "",
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("diff.title").upper())
        self.setMinimumSize(720, 520)
        self._decision = Decision(False, "dialog closed")

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(12)

        added, removed = diff.stats
        kind = t("diff.new_file") if diff.is_new_file else t("diff.edit")
        head = QLabel(f"{kind.upper()}  ·  {diff.path}   (+{added} −{removed})")
        head.setProperty("role", "h1")
        v.addWidget(head)
        sub = QLabel(t("diff.workspace_line", name=workspace_name))
        sub.setProperty("role", "readout")
        v.addWidget(sub)

        view = QTextEdit()
        view.setObjectName("DiffView")
        view.setReadOnly(True)
        view.setHtml(_colorize(diff.unified, palette))
        v.addWidget(view, 1)

        self._note = QLineEdit()
        self._note.setPlaceholderText(t("diff.note_placeholder"))
        v.addWidget(self._note)

        row = QHBoxLayout()
        reject = QPushButton(t("agent.reject").upper())
        reject.setProperty("variant", "danger")
        reject.clicked.connect(self._reject)
        approve_all = QPushButton(t("agent.approve_all").upper())
        approve_all.clicked.connect(self._approve_all)
        approve = QPushButton(t("agent.approve").upper())
        approve.setProperty("variant", "primary")
        approve.clicked.connect(self._approve)
        row.addWidget(reject)
        row.addStretch(1)
        row.addWidget(approve_all)
        row.addWidget(approve)
        v.addLayout(row)

    def _approve(self) -> None:
        self._decision = Decision(True, "approved")
        self.accept()

    def _approve_all(self) -> None:
        self._decision = Decision(True, "approved", remember_session=True)
        self.accept()

    def _reject(self) -> None:
        self._decision = Decision(False, self._note.text().strip() or "rejected by user")
        self.reject()

    def decision(self) -> Decision:
        return self._decision

    @staticmethod
    def ask(diff: Diff, palette: Palette, workspace_name: str = "",
            parent=None) -> Decision:
        dlg = DiffDialog(diff, palette, workspace_name, parent)
        dlg.exec()
        return dlg.decision()
