"""M6 polish coverage — personas, context compaction, onboarding, audit export.

Headless (offscreen for the Qt bits). These assert the behaviors a user relies on:
a persona keeps the safety footer, compaction produces a *marked* summary and
shrinks history, onboarding shows once, and export copies the exact log file.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from bastion.core.agent import personas
from bastion.core.agent.compaction import compact
from bastion.core.llm.engine import FakeEngine, Message, Role, ScriptedTurn


# -- personas ---------------------------------------------------------------
def test_personas_carry_safety_footer():
    for name, p in personas.PERSONAS.items():
        assert "locally" in p.full_prompt      # the non-negotiable footer
        assert p.prompt in p.full_prompt
    assert personas.get("nonexistent").name == personas.DEFAULT_PERSONA


# -- compaction -------------------------------------------------------------
def test_compaction_marks_summary_and_shrinks_history():
    history = []
    for i in range(8):
        history.append(Message(Role.USER, f"question {i}"))
        history.append(Message(Role.ASSISTANT, f"answer {i}"))
    engine = FakeEngine([ScriptedTurn("SUMMARY: discussed questions 0-5.")])
    summary, kept = compact(history, engine, keep_recent=4)
    assert summary.role is Role.SYSTEM
    assert "summarized" in summary.content.lower()
    assert "SUMMARY" in summary.content
    assert len(kept) == 4
    assert kept[-1].content == "answer 7"


def test_compaction_noop_when_too_short():
    history = [Message(Role.USER, "hi"), Message(Role.ASSISTANT, "hello")]
    summary, kept = compact(history, FakeEngine(["x"]), keep_recent=4)
    assert summary.content == ""
    assert kept == history


# -- onboarding + export (Qt) ----------------------------------------------
@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_onboarding_shows_once(qapp, tmp_path, monkeypatch):
    from bastion.ui.onboarding import Onboarding
    from bastion.ui.theme import THEMES
    from bastion.core.store.db import Store
    store = Store(tmp_path / "s.db", cipher=None)
    shown = {"n": 0}
    monkeypatch.setattr(Onboarding, "exec", lambda self: shown.__setitem__("n", shown["n"] + 1))
    Onboarding.maybe_show(THEMES["dark"], store)   # first run → shows
    Onboarding.maybe_show(THEMES["dark"], store)   # second run → suppressed
    assert shown["n"] == 1
    assert store.get_setting("__global__", "onboarded") == "1"


def test_audit_export_copies_file(qapp, tmp_path, monkeypatch):
    from bastion.ui.widgets.audit_browser import AuditBrowser
    from bastion.core.security.audit import AuditLog
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    log = AuditLog(tmp_path / "audit.jsonl")
    for i in range(5):
        log.record("event", i=i)
    browser = AuditBrowser(log)
    dest = tmp_path / "exported.jsonl"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(dest), "")))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    browser._export()
    assert dest.exists()
    assert dest.read_text(encoding="utf-8") == (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert AuditLog(dest).verify().ok  # the copy verifies independently
