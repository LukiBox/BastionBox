"""The permission system — the heart of the product.

A workspace carries a permission tier (:class:`~bastion.core.security.jail.Permission`).
This module turns that tier into concrete answers to two questions the agent asks
constantly: *may I write this?* and *may I run this command?* — and routes the
answer through a broker so the UI can show a diff and Approve/Reject, tests can
script decisions deterministically, and every decision is auditable.

Rejection is *feedback*, not death: a rejected action returns to the model as an
observation ("user rejected: wrong file"), so the loop adapts instead of dying.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Callable

from ..security.jail import Permission, Workspace
from .diffing import Diff


@dataclass
class Decision:
    approved: bool
    note: str = ""
    #: Set true when the user chose "auto-approve writes for this session"; the
    #: broker upgrades the workspace tier in-memory (never persisted silently).
    remember_session: bool = False


class PermissionBroker(abc.ABC):
    """Decides whether a proposed write/command may proceed."""

    @abc.abstractmethod
    def request_write(self, ws: Workspace, diff: Diff) -> Decision: ...

    @abc.abstractmethod
    def request_command(self, ws: Workspace, command: str,
                        allowlisted: bool) -> Decision: ...


class PolicyBroker(PermissionBroker):
    """Applies the tier policy, delegating the "ask" case to a UI/test callback.

    * READ_ONLY  → every write auto-*rejected* (fail closed).
    * ASK        → each write calls ``ask_write`` (the UI shows the diff).
    * AUTO_WRITE → writes auto-approved (the UI shows a loud session indicator).

    Commands always ask unless the exact command string is on the allowlist.
    ``ask_*`` callbacks default to *reject*, so a broker wired to nothing can
    never silently approve anything.
    """

    def __init__(
        self,
        ask_write: Callable[[Workspace, Diff], Decision] | None = None,
        ask_command: Callable[[Workspace, str], Decision] | None = None,
        session_auto: dict[str, bool] | None = None,
    ):
        self._ask_write = ask_write or (lambda ws, d: Decision(False, "no approver wired"))
        self._ask_command = ask_command or (lambda ws, c: Decision(False, "no approver wired"))
        #: workspace.key -> whether the user granted session auto-approve.
        self._session_auto = session_auto if session_auto is not None else {}

    def request_write(self, ws: Workspace, diff: Diff) -> Decision:
        if ws.permission is Permission.READ_ONLY:
            return Decision(False, "workspace is read-only")
        if ws.permission is Permission.AUTO_WRITE or self._session_auto.get(ws.key):
            return Decision(True, "auto-approved (session)")
        decision = self._ask_write(ws, diff)
        if decision.approved and decision.remember_session:
            self._session_auto[ws.key] = True
        return decision

    def request_command(self, ws: Workspace, command: str,
                        allowlisted: bool) -> Decision:
        if ws.permission is Permission.READ_ONLY:
            return Decision(False, "workspace is read-only; commands not permitted")
        if allowlisted:
            return Decision(True, "command on allowlist")
        return self._ask_command(ws, command)


class AutoApproveBroker(PermissionBroker):
    """Approves everything — for headless agent-harness tests only, never the UI."""

    def request_write(self, ws, diff):  # noqa: D401
        return Decision(True, "auto (test)")

    def request_command(self, ws, command, allowlisted):
        return Decision(True, "auto (test)")
