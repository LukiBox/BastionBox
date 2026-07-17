"""The Security page — the reason this app exists, made visible and checkable.

Three cards answer the three promises in one glance:
  * Network Guard — armed, whitelisted loopback only, and a blocked-attempt
    counter that must read 0 forever.
  * Encryption at rest — whether data is truly sealed, and with what.
  * Audit chain — a Verify button that re-hashes the whole log and reports VALID
    with a count, or fingers the exact tampered entry.

The panel reads live state from the guard / audit objects it is handed; it never
fabricates a reassuring number.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ...core.i18n import t
from ...core.security.audit import AuditLog
from ...core.security.netguard import NetworkGuard
from ..theme import Palette
from .tactical import Card, StatusPill, StencilLabel


class _Metric(QWidget):
    def __init__(self, label: str, value: str, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        self.value = QLabel(value)
        self.value.setProperty("role", "h1")
        self.caption = QLabel(label.upper())
        self.caption.setProperty("role", "readout")
        v.addWidget(self.value)
        v.addWidget(self.caption)


class SecurityPanel(QWidget):
    def __init__(self, guard: NetworkGuard, audit: AuditLog,
                 palette: Palette, encrypted: bool, air_gap: bool,
                 store=None, index=None, workspace_getter=None, parent=None):
        super().__init__(parent)
        self._guard = guard
        self._audit = audit
        self._palette = palette
        self._encrypted = encrypted
        self._air_gap = air_gap
        self._store = store
        self._index = index
        self._workspace_getter = workspace_getter or (lambda: None)
        self._locked = False

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        header = QHBoxLayout()
        self._title = QLabel(t("sec.title"))
        self._title.setProperty("role", "h1")
        header.addWidget(self._title)
        header.addStretch(1)
        self._overall = StatusPill(t("sec.pill_secure"), "secure")
        header.addWidget(self._overall)
        root.addLayout(header)

        grid = QGridLayout()
        grid.setSpacing(16)
        grid.addWidget(self._netguard_card(), 0, 0)
        grid.addWidget(self._encryption_card(), 0, 1)
        grid.addWidget(self._audit_card(), 1, 0, 1, 2)
        grid.addWidget(self._panic_card(), 2, 0, 1, 2)
        root.addLayout(grid)
        root.addStretch(1)

        self.refresh()

    # -- cards --------------------------------------------------------------
    def _netguard_card(self) -> Card:
        card = self._ng_card = Card(t("sec.netguard"))
        self._ng_pill = StatusPill(t("sec.pill_armed"), "secure")
        card.add_header_widget(self._ng_pill)
        self._blocked_metric = _Metric(t("sec.blocked_label"), "0")
        card.add(self._blocked_metric)
        self._endpoints = QLabel()
        self._endpoints.setProperty("role", "readout")
        self._endpoints.setWordWrap(True)
        card.add(self._endpoints)
        self._ng_note = QLabel(t("sec.netguard_note"))
        self._ng_note.setProperty("role", "readout")
        self._ng_note.setWordWrap(True)
        card.add(self._ng_note)
        return card

    def _encryption_card(self) -> Card:
        card = self._enc_card = Card(t("sec.encryption"))
        self._enc_pill = StatusPill(
            "AES-256-GCM" if self._encrypted else "PLAINTEXT",
            "secure" if self._encrypted else "blocked")
        card.add_header_widget(self._enc_pill)
        self._enc_body = QLabel(t("sec.enc_sealed") if self._encrypted
                                else t("sec.enc_unsealed"))
        self._enc_body.setProperty("role", "readout")
        self._enc_body.setWordWrap(True)
        card.add(self._enc_body)
        return card

    def _audit_card(self) -> Card:
        card = self._audit_card_ref = Card(t("sec.audit"))
        row = QHBoxLayout()
        self._verify_result = None     # last AuditLog.verify() outcome
        self._audit_status = StatusPill(t("sec.pill_not_verified"), "offline")
        self._verify_btn = QPushButton(t("sec.verify_btn"))
        self._verify_btn.setProperty("variant", "secure")
        self._verify_btn.clicked.connect(self._on_verify)
        row.addWidget(self._audit_status)
        row.addStretch(1)
        row.addWidget(self._verify_btn)
        card.body().addLayout(row)
        self._audit_detail = QLabel(t("sec.audit_note"))
        self._audit_detail.setProperty("role", "readout")
        self._audit_detail.setWordWrap(True)
        card.add(self._audit_detail)
        return card

    def _panic_card(self) -> Card:
        card = self._panic_card_ref = Card(t("sec.panic"))
        self._panic_pill = StatusPill(t("sec.panic_pill"), "armed")
        card.add_header_widget(self._panic_pill)
        self._panic_note = QLabel(t("sec.panic_note"))
        self._panic_note.setProperty("role", "readout")
        self._panic_note.setWordWrap(True)
        card.add(self._panic_note)
        row = QHBoxLayout()
        self._lock_btn = QPushButton(t("sec.lock"))
        self._lock_btn.clicked.connect(self._on_lock)
        self._wipe_btn = QPushButton(t("sec.wipe"))
        self._wipe_btn.setProperty("variant", "danger")
        self._wipe_btn.clicked.connect(self._on_secure_delete)
        row.addWidget(self._lock_btn)
        row.addStretch(1)
        row.addWidget(self._wipe_btn)
        card.body().addLayout(row)
        return card

    def retranslate(self) -> None:
        """Re-read every string in the app-wide language, keeping live state."""
        self._title.setText(t("sec.title"))
        self._ng_card.set_title(t("sec.netguard"))
        self._enc_card.set_title(t("sec.encryption"))
        self._audit_card_ref.set_title(t("sec.audit"))
        self._panic_card_ref.set_title(t("sec.panic"))
        self._blocked_metric.caption.setText(t("sec.blocked_label").upper())
        self._ng_note.setText(t("sec.netguard_note"))
        self._enc_body.setText(t("sec.enc_sealed") if self._encrypted
                               else t("sec.enc_unsealed"))
        self._verify_btn.setText(t("sec.verify_btn"))
        self._panic_pill.set_status(t("sec.panic_pill"), "armed")
        self._panic_note.setText(t("sec.panic_note"))
        self._wipe_btn.setText(t("sec.wipe"))
        if self._locked:
            self._lock_btn.setText(t("sec.locked"))
        else:
            self._lock_btn.setText(t("sec.lock"))
        self._render_verify()
        self.refresh()

    def _on_lock(self) -> None:
        # Wipe the in-memory key by dropping the store's cipher reference. The
        # store then refuses to read encrypted rows until re-unlocked.
        if self._store is not None and getattr(self._store, "_cipher", None):
            self._store._cipher = None
        self._locked = True
        self._lock_btn.setText(t("sec.locked"))
        self._lock_btn.setEnabled(False)
        self._audit.record("lock_now", actor="user")
        self._overall.set_status(t("sec.pill_locked"), "armed")

    def _on_secure_delete(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        ws = self._workspace_getter()
        if ws is None:
            QMessageBox.information(self, t("ws.no_workspace_title"),
                                    t("sec.no_ws_msg"))
            return
        confirm = QMessageBox.warning(
            self, t("sec.wipe_title"),
            t("sec.wipe_confirm", path=ws.root),
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if confirm != QMessageBox.Yes:
            return
        removed = 0
        if self._store is not None:
            removed = self._store.secure_delete_workspace(ws.key)
        if self._index is not None:
            self._index.clear_workspace(ws.key)
        self._audit.record("secure_delete", workspace=ws.key,
                           conversations_removed=removed, actor="user")
        QMessageBox.information(self, t("sec.wipe_done_title"),
                                t("sec.wipe_done", removed=removed))

    # -- behavior -----------------------------------------------------------
    def _on_verify(self) -> None:
        self._verify_result = self._audit.verify()
        self._render_verify()
        self.refresh_overall()

    def _render_verify(self) -> None:
        result = self._verify_result
        if result is None:
            self._audit_status.set_status(t("sec.pill_not_verified"), "offline")
            self._audit_detail.setText(t("sec.audit_note"))
        elif result.ok:
            self._audit_status.set_status(
                f"{t('sec.pill_valid')} · {result.entries}", "secure")
            self._audit_detail.setText(
                t("sec.chain_valid", entries=result.entries))
        else:
            self._audit_status.set_status(
                f"{t('sec.pill_tampered')} · #{result.first_bad_seq}", "blocked")
            self._audit_detail.setText(
                t("sec.tamper_detected", detail=result.detail))

    def refresh(self) -> None:
        st = self._guard.status()
        blocked = st["blocked_count"]
        self._blocked_metric.value.setText(str(blocked))
        armed = st["installed"]
        self._ng_pill.set_status(
            t("sec.pill_armed") if armed else t("sec.pill_down"),
            "secure" if armed and blocked == 0 else
            ("blocked" if blocked else "offline"))
        eps = ", ".join(st["allowed_endpoints"]) or t("sec.eps_none")
        self._endpoints.setText(t("sec.whitelisted", eps=eps)
                                + (t("sec.airgap_suffix") if self._air_gap else ""))
        self.refresh_overall()

    def refresh_overall(self) -> None:
        blocked = self._guard.status()["blocked_count"]
        if self._locked:
            self._overall.set_status(t("sec.pill_locked"), "armed")
        elif blocked:
            self._overall.set_status(t("sec.pill_breach"), "blocked")
        elif not self._encrypted:
            self._overall.set_status(t("sec.pill_unsealed"), "armed")
        else:
            self._overall.set_status(t("sec.pill_secure"), "secure")
