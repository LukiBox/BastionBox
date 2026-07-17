"""Agent harness — a scripted fake model drives the tool loop deterministically.

No real model, no GPU, no network: :class:`FakeEngine` replays a fixed script so
the loop's behavior is reproducible on CI. We assert the things that matter for a
*permissioned* agent: edits actually land, rejections are recovered from, the
iteration cap holds, and malformed output never crashes the parser.
"""
from __future__ import annotations

import json

import pytest

from bastion.core.agent.diffing import Diff
from bastion.core.agent.loop import AgentLoop, EventKind
from bastion.core.agent.permissions import Decision, PolicyBroker
from bastion.core.llm.engine import FakeEngine, ScriptedTurn
from bastion.core.security.audit import AuditLog
from bastion.core.security.jail import PathJail, Permission
from bastion.core.tools.base import ToolContext


def _call(tool, **args):
    return json.dumps({"tool": tool, "args": args})


def _final(content):
    return json.dumps({"tool": "final", "args": {"content": content}})


@pytest.fixture()
def env(tmp_path):
    ws_dir = tmp_path / "code"
    (ws_dir / "src").mkdir(parents=True)
    (ws_dir / "src" / "auth.py").write_text(
        "def check_tok(t):\n    return t == 1\n", encoding="utf-8")
    jail = PathJail()
    ws = jail.mount(ws_dir, Permission.ASK, label="code")
    audit = AuditLog(tmp_path / "audit.jsonl")
    return jail, ws, audit, ws_dir


def _ctx(env, broker):
    jail, ws, audit, _ = env
    return ToolContext(jail=jail, workspace=ws, broker=broker, audit=audit,
                       command_allowlist=("pytest -q",))


def test_multistep_edit_and_verify(env):
    jail, ws, audit, ws_dir = env
    script = [
        _call("read_file", path="src/auth.py"),
        _call("edit_file", path="src/auth.py",
              search="check_tok", replace="validate_token"),
        _call("grep", query="validate_token"),           # verify step
        _final("Renamed check_tok to validate_token and confirmed with grep."),
    ]
    broker = PolicyBroker(ask_write=lambda ws, d: Decision(True, "ok"))
    loop = AgentLoop(FakeEngine(script), _ctx(env, broker))
    events = list(loop.run("rename check_tok to validate_token"))

    kinds = [e.kind for e in events]
    assert EventKind.FINAL in kinds
    assert (ws_dir / "src" / "auth.py").read_text().count("validate_token") == 1
    assert "check_tok" not in (ws_dir / "src" / "auth.py").read_text()
    # The audit recorded the write decision and the file write.
    assert audit.verify().ok
    kinds_logged = {e["kind"] for e in audit}
    assert "file_write" in kinds_logged and "decision" in kinds_logged


def test_rejection_is_recovered(env):
    ws_dir = env[3]
    calls = {"n": 0}

    def ask(ws, diff: Diff) -> Decision:
        calls["n"] += 1
        if calls["n"] == 1:
            return Decision(False, "wrong file — put it under src/")
        return Decision(True, "ok")

    script = [
        _call("write_file", path="notes.txt", content="scratch"),   # rejected
        _call("write_file", path="src/notes.txt", content="scratch"),  # approved
        _final("Wrote src/notes.txt after correcting the path."),
    ]
    broker = PolicyBroker(ask_write=ask)
    loop = AgentLoop(FakeEngine(script), _ctx(env, broker))
    events = list(loop.run("save a note"))

    observations = [e.text for e in events if e.kind == EventKind.OBSERVATION]
    assert any("user rejected" in o for o in observations)
    assert not (ws_dir / "notes.txt").exists()          # first write blocked
    assert (ws_dir / "src" / "notes.txt").exists()       # second write landed


def test_read_only_workspace_blocks_writes(tmp_path):
    ws_dir = tmp_path / "ro"
    ws_dir.mkdir()
    (ws_dir / "a.txt").write_text("x")
    jail = PathJail()
    ws = jail.mount(ws_dir, Permission.READ_ONLY)
    audit = AuditLog(tmp_path / "a.jsonl")
    # Broker whose approver would say yes — policy must still refuse read-only.
    broker = PolicyBroker(ask_write=lambda ws, d: Decision(True, "yes"))
    ctx = ToolContext(jail=jail, workspace=ws, broker=broker, audit=audit)
    loop = AgentLoop(FakeEngine([
        _call("write_file", path="a.txt", content="tampered"),
        _final("done"),
    ]), ctx)
    list(loop.run("overwrite a.txt"))
    assert (ws_dir / "a.txt").read_text() == "x"  # unchanged — write refused


def test_iteration_cap_stops_runaway(env):
    # A model that never finishes: always lists the directory. The stall guard
    # catches the identical repeats, and the run ends in a graceful *partial*
    # summary (FINAL with meta) rather than a bare error — but it still stops.
    broker = PolicyBroker()
    loop = AgentLoop(FakeEngine([_call("list_dir", path=".")] * 20),
                     _ctx(env, broker), max_iterations=4)
    events = list(loop.run("loop forever"))
    assert any(e.kind == EventKind.ERROR for e in events)   # stop was flagged
    assert events[-1].kind == EventKind.FINAL
    assert events[-1].meta.get("partial") is True
    # Never exceeded the cap in tool calls.
    assert sum(1 for e in events if e.kind == EventKind.TOOL_CALL) <= 4


def test_malformed_output_does_not_crash(env):
    broker = PolicyBroker()
    script = [
        ScriptedTurn("this is not json at all, just prose"),
        _final("recovered"),
    ]
    loop = AgentLoop(FakeEngine(script), _ctx(env, broker), max_iterations=5)
    events = list(loop.run("be messy"))
    assert any(e.kind == EventKind.ERROR for e in events)
    assert events[-1].kind == EventKind.FINAL and events[-1].text == "recovered"


def test_json_embedded_in_prose_is_extracted(env):
    broker = PolicyBroker(ask_write=lambda ws, d: Decision(True, "ok"))
    script = [
        ScriptedTurn('Sure! ' + _call("list_dir", path=".") + ' — running that.'),
        _final("listed"),
    ]
    loop = AgentLoop(FakeEngine(script), _ctx(env, broker))
    events = list(loop.run("list the dir"))
    tool_calls = [e.tool for e in events if e.kind == EventKind.TOOL_CALL]
    assert "list_dir" in tool_calls
