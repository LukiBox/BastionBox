"""Office pipeline — read PDF/DOCX/XLSX and write .docx/.xlsx/.pdf, all jailed.

Proves the priority workflow end-to-end: the agent can read a document and write
structured output back, with every write passing the approval broker and the path
jail. Tests skip cleanly if an optional writer/reader library is missing.
"""
from __future__ import annotations

import pytest

from bastion.core.agent.permissions import Decision, PolicyBroker
from bastion.core.docs import extract, writer
from bastion.core.security.audit import AuditLog
from bastion.core.security.jail import PathJail, Permission
from bastion.core.tools.base import ToolContext
from bastion.core.tools.office_tools import (WriteDocument, WriteSpreadsheet,
                                             ReadDocument, markdown_to_blocks,
                                             parse_rows)


def _has(mod: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(mod) is not None


@pytest.fixture()
def ctx(tmp_path):
    ws_dir = tmp_path / "ws"; ws_dir.mkdir()
    jail = PathJail(); ws = jail.mount(ws_dir, Permission.ASK)
    audit = AuditLog(tmp_path / "a.jsonl")
    broker = PolicyBroker(ask_write=lambda ws, d: Decision(True, "ok"))
    return ToolContext(jail=jail, workspace=ws, broker=broker, audit=audit), ws_dir


# -- parsing ----------------------------------------------------------------
def test_markdown_to_blocks():
    blocks = markdown_to_blocks("# Title\n\nIntro para.\n\n- a\n- b\n\nx | y\n1 | 2")
    kinds = [b["type"] for b in blocks]
    assert kinds[0] == "heading" and "bullet" in kinds and "table" in kinds
    table = next(b for b in blocks if b["type"] == "table")
    assert table["rows"] == [["x", "y"], ["1", "2"]]


def test_parse_rows_csv_and_json():
    assert parse_rows("a,b\n1,2") == [["a", "b"], ["1", "2"]]
    assert parse_rows('[{"name":"x","v":1}]') == [["name", "v"], ["x", 1]]


# -- writers produce real files, readers get the text back -----------------
@pytest.mark.skipif(not _has("docx"), reason="python-docx not installed")
def test_write_and_read_docx(ctx):
    c, ws_dir = ctx
    r = WriteDocument().run(c, {"path": "report.docx", "title": "Datasheet Summary",
                                "content": "# Overview\n\nVoltage is 3.3V.\n- pin 1\n- pin 2"})
    assert r.ok and (ws_dir / "report.docx").exists()
    back = ReadDocument().run(c, {"path": "report.docx"})
    assert back.ok and "Voltage is 3.3V" in back.observation


@pytest.mark.skipif(not _has("openpyxl"), reason="openpyxl not installed")
def test_write_and_read_xlsx(ctx):
    c, ws_dir = ctx
    r = WriteSpreadsheet().run(c, {"path": "data.xlsx",
                                   "data": "part,qty\nR1,5\nC2,10"})
    assert r.ok and (ws_dir / "data.xlsx").exists()
    back = ReadDocument().run(c, {"path": "data.xlsx"})
    assert back.ok and "R1" in back.observation and "qty" in back.observation


@pytest.mark.skipif(not _has("reportlab"), reason="reportlab not installed")
def test_write_pdf_and_read_back(ctx):
    c, ws_dir = ctx
    r = WriteDocument().run(c, {"path": "note.pdf", "title": "Note",
                                "content": "Hello from a locally generated PDF."})
    assert r.ok and (ws_dir / "note.pdf").exists()
    if _has("fitz") or _has("pypdf"):
        back = ReadDocument().run(c, {"path": "note.pdf"})
        assert back.ok and "locally generated PDF" in back.observation


def test_write_rejected_when_broker_declines(tmp_path):
    ws_dir = tmp_path / "ws"; ws_dir.mkdir()
    jail = PathJail(); ws = jail.mount(ws_dir, Permission.ASK)
    audit = AuditLog(tmp_path / "a.jsonl")
    broker = PolicyBroker(ask_write=lambda ws, d: Decision(False, "no"))
    c = ToolContext(jail=jail, workspace=ws, broker=broker, audit=audit)
    if not _has("docx"):
        pytest.skip("python-docx not installed")
    r = WriteDocument().run(c, {"path": "x.docx", "title": "t", "content": "y"})
    assert not r.ok and "rejected" in r.observation
    assert not (ws_dir / "x.docx").exists()


def test_write_document_rejects_bad_extension(ctx):
    c, _ = ctx
    r = WriteDocument().run(c, {"path": "x.txt", "title": "t", "content": "y"})
    assert not r.ok and ".docx, .pdf, or .html" in r.observation


def test_read_document_jailed(ctx):
    c, _ = ctx
    r = ReadDocument().run(c, {"path": "../../etc/passwd"})
    assert not r.ok


@pytest.mark.skipif(not _has("openpyxl"), reason="openpyxl not installed")
def test_agent_writes_spreadsheet_end_to_end(tmp_path):
    """Drive the real agent loop: scripted model calls write_spreadsheet and the
    file lands after approval — the whole office path through the grammar+loop."""
    import json
    from bastion.core.agent.loop import AgentLoop, EventKind
    from bastion.core.llm.engine import FakeEngine
    ws_dir = tmp_path / "ws"; ws_dir.mkdir()
    jail = PathJail(); ws = jail.mount(ws_dir, Permission.ASK)
    audit = AuditLog(tmp_path / "a.jsonl")
    broker = PolicyBroker(ask_write=lambda ws, d: Decision(True, "ok"))
    ctx = ToolContext(jail=jail, workspace=ws, broker=broker, audit=audit)
    script = [
        json.dumps({"tool": "write_spreadsheet",
                    "args": {"path": "out.xlsx", "data": "part,qty\nR1,5"}}),
        json.dumps({"tool": "final", "args": {"content": "Wrote out.xlsx."}}),
    ]
    events = list(AgentLoop(FakeEngine(script), ctx).run("make a spreadsheet"))
    assert any(e.kind is EventKind.FINAL for e in events)
    assert (ws_dir / "out.xlsx").exists()
