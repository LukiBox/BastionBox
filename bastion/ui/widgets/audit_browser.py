"""Audit browser — read the tamper-evident log, and verify it, from the UI.

Answers the product's north-star question — "what did the AI touch last Tuesday?"
— in a scrollable, filterable table, with a one-click chain verification banner.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ...core.security.audit import AuditLog
from .tactical import StatusPill


_COLS = ("SEQ", "TIME", "KIND", "DETAIL")


class AuditBrowser(QWidget):
    def __init__(self, audit: AuditLog, parent=None):
        super().__init__(parent)
        self._audit = audit
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("AUDIT TRAIL")
        title.setProperty("role", "h1")
        header.addWidget(title)
        header.addStretch(1)
        self._status = StatusPill("NOT VERIFIED", "offline")
        header.addWidget(self._status)
        verify = QPushButton("VERIFY")
        verify.setProperty("variant", "secure")
        verify.clicked.connect(self._verify)
        header.addWidget(verify)
        export = QPushButton("EXPORT")
        export.setToolTip("Export the audit log for off-box review (copies the JSONL)")
        export.clicked.connect(self._export)
        header.addWidget(export)
        reload_btn = QPushButton("RELOAD")
        reload_btn.clicked.connect(self.reload)
        header.addWidget(reload_btn)
        root.addLayout(header)

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter by kind or detail (e.g. file_write, command)…")
        self._filter.textChanged.connect(self._apply_filter)
        root.addWidget(self._filter)

        self._table = QTableWidget(0, len(_COLS))
        self._table.setHorizontalHeaderLabels(_COLS)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        root.addWidget(self._table)

        self.reload()

    def reload(self) -> None:
        self._entries = list(self._audit)
        self._render(self._entries)

    def _render(self, entries) -> None:
        self._table.setRowCount(0)
        for e in entries:
            row = self._table.rowCount()
            self._table.insertRow(row)
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e.get("ts", 0)))
            detail = self._summarize(e)
            for col, val in enumerate((str(e.get("seq", "")), ts,
                                       e.get("kind", ""), detail)):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                self._table.setItem(row, col, item)

    @staticmethod
    def _summarize(entry: dict) -> str:
        data = entry.get("data", {})
        kind = entry.get("kind")
        if kind == "tool_call":
            return f"{data.get('tool')} {data.get('args', {})}"
        if kind == "file_write":
            return f"{data.get('path')}  ({data.get('size')} bytes)"
        if kind == "command":
            return f"{data.get('command')}  → exit {data.get('exit_code')}"
        if kind == "decision":
            verdict = "APPROVED" if data.get("approved") else "REJECTED"
            return f"[{verdict}] {data.get('action')}  {data.get('note','')}"
        if kind == "network_block":
            return f"BLOCKED {data.get('host')}:{data.get('port')} via {data.get('api')}"
        if kind == "prompt":
            return f"prompt sha256={data.get('prompt_sha256','')[:16]}… ({data.get('chars')} chars)"
        return str(data)

    def _apply_filter(self, text: str) -> None:
        text = text.lower().strip()
        if not text:
            self._render(self._entries)
            return
        self._render([e for e in self._entries
                      if text in e.get("kind", "").lower()
                      or text in self._summarize(e).lower()])

    def _verify(self) -> None:
        result = self._audit.verify()
        if result.ok:
            self._status.set_status(f"VALID · {result.entries}", "secure")
        else:
            self._status.set_status(f"TAMPERED · #{result.first_bad_seq}", "blocked")

    def _export(self) -> None:
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        import shutil
        if not self._audit.path.exists():
            QMessageBox.information(self, "Nothing to export", "The audit log is empty.")
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, "Export audit log", "bastionbox-audit.jsonl", "JSONL (*.jsonl)")
        if not dest:
            return
        shutil.copyfile(self._audit.path, dest)
        result = self._audit.verify()
        QMessageBox.information(
            self, "Audit exported",
            f"Copied {result.entries} entries to:\n{dest}\n\nChain status at export: "
            + ("VALID — verify it again off-box with the same tool." if result.ok
               else f"TAMPERED at entry {result.first_bad_seq}."))
