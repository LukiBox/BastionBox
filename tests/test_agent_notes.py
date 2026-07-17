"""The reliability bundle — notepad, ask_user, stall guard, graceful wrap-up.

These prove the eigent-inspired upgrades with the same deterministic harness as
test_agent_loop: a scripted FakeEngine, a real jail, no threads. The load-bearing
claims: notes written in one step are *injected* into the next step's prompt (the
model never has to remember to read them), the notepad survives history trimming,
ask_user degrades safely headless and respects its budget, a looping model gets
nudged then wrapped up, and the iteration cap ends in a usable summary.
"""
from __future__ import annotations

import json

import pytest

from bastion.core.agent.loop import AgentLoop, EventKind
from bastion.core.agent.permissions import Decision, PolicyBroker
from bastion.core.agent.schemas import build_system_prompt, default_toolbox
from bastion.core.llm.engine import FakeEngine, GenerationConfig, Message
from bastion.core.security.audit import AuditLog
from bastion.core.security.jail import PathJail, Permission
from bastion.core.tools.base import NoteStore, ToolContext


def _call(tool, **args):
    return json.dumps({"tool": tool, "args": args})


def _final(content):
    return json.dumps({"tool": "final", "args": {"content": content}})


class CapturingEngine(FakeEngine):
    """FakeEngine that also records every prompt the loop sends (the loop
    streams each step, so the capture hooks stream())."""

    def __init__(self, script):
        super().__init__(script)
        self.prompts: list[list[Message]] = []

    def stream(self, messages, config: GenerationConfig):
        self.prompts.append(list(messages))
        yield from super().stream(messages, config)


@pytest.fixture()
def env(tmp_path):
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    (ws_dir / "a.txt").write_text("hello", encoding="utf-8")
    jail = PathJail()
    ws = jail.mount(ws_dir, Permission.ASK, label="ws")
    audit = AuditLog(tmp_path / "audit.jsonl")
    return jail, ws, audit, ws_dir


def _ctx(env, broker=None, **kw):
    jail, ws, audit, _ = env
    return ToolContext(jail=jail, workspace=ws, broker=broker or PolicyBroker(),
                       audit=audit, **kw)


# -- NoteStore ---------------------------------------------------------------
def test_notestore_caps_and_render_clipping():
    ns = NoteStore()
    ns.write("plan", "x" * 20_000)                    # over the per-note cap
    assert len(ns.read("plan")) == NoteStore.MAX_NOTE_CHARS
    ns.append("plan", "tail")
    assert len(ns.read("plan")) == NoteStore.MAX_NOTE_CHARS  # still capped
    view = ns.render(cap=500)
    assert len(view) < 700 and "read_note" in view    # clipped with the hint
    assert "### plan" in view
    assert ns.names() == ["plan"]
    assert not NoteStore()                            # empty store is falsy


# -- notepad injection + trim survival ----------------------------------------
def test_note_written_in_step_one_is_visible_in_step_two(env):
    engine = CapturingEngine([
        _call("write_note", name="plan",
              content="- [ ] read a.txt\n- [ ] answer"),
        _call("read_file", path="a.txt"),
        _final("done"),
    ])
    loop = AgentLoop(engine, _ctx(env))
    events = list(loop.run("do the task"))
    assert events[-1].kind is EventKind.FINAL
    # Step 1's prompt has no notepad; steps 2 and 3 must carry it, injected.
    assert not any("<notepad>" in m.content for m in engine.prompts[0])
    for prompt in engine.prompts[1:]:
        joined = "\n".join(m.content for m in prompt)
        assert "<notepad>" in joined and "- [ ] read a.txt" in joined


def test_notepad_survives_history_trimming(env):
    # A tiny context forces heavy trimming; a huge observation would evict the
    # plan if it lived in history. It doesn't — it's pinned via injection.
    big = "B" * 30_000
    (env[3] / "big.txt").write_text(big, encoding="utf-8")
    engine = CapturingEngine([
        _call("write_note", name="plan", content="THE-PLAN-MARKER"),
        _call("read_file", path="big.txt"),
        _call("list_dir", path="."),
        _final("done"),
    ])
    loop = AgentLoop(engine, _ctx(env), context_tokens=3000, reply_tokens=256)
    events = list(loop.run("survive the flood"))
    assert events[-1].kind is EventKind.FINAL
    last_prompt = "\n".join(m.content for m in engine.prompts[-1])
    assert "THE-PLAN-MARKER" in last_prompt          # plan outlived the trim
    assert "B" * 3_000 not in last_prompt            # the flood did not
    est = sum(len(m.content) // 4 + 8 for m in engine.prompts[-1])
    assert est <= 3000                               # and the prompt still fits


# -- ask_user ------------------------------------------------------------------
def test_ask_user_headless_degrades_gracefully(env):
    engine = FakeEngine([
        _call("ask_user", question="docx or pdf?"),
        _final("assumed docx"),
    ])
    events = list(AgentLoop(engine, _ctx(env)).run("write a report"))
    obs = [e for e in events if e.kind is EventKind.OBSERVATION]
    assert "no user is available" in obs[0].text
    assert events[-1].kind is EventKind.FINAL


def test_ask_user_answer_and_budget(env):
    answers = iter(["PDF please", "should not be reached"])
    ctx = _ctx(env, ask_user=lambda q: next(answers), ask_budget=1)
    engine = FakeEngine([
        _call("ask_user", question="docx or pdf?"),
        _call("ask_user", question="what font?"),     # budget is spent now
        _final("done"),
    ])
    events = list(AgentLoop(engine, ctx).run("write a report"))
    obs = [e.text for e in events if e.kind is EventKind.OBSERVATION]
    assert "the user answered: PDF please" in obs[0]
    assert "budget exhausted" in obs[1]


def test_ask_user_skip_means_best_judgment(env):
    ctx = _ctx(env, ask_user=lambda q: "")            # user hit Skip
    engine = FakeEngine([_call("ask_user", question="which one?"),
                         _final("assumed")])
    events = list(AgentLoop(engine, ctx).run("task"))
    obs = [e.text for e in events if e.kind is EventKind.OBSERVATION]
    assert "skipped" in obs[0] and "best judgment" in obs[0]


# -- stall guard + graceful wrap-up -------------------------------------------
def test_identical_repeat_gets_nudged_not_rerun(env):
    engine = FakeEngine([
        _call("list_dir", path="."),
        _call("list_dir", path="."),                  # exact repeat → nudge
        _final("ok"),
    ])
    events = list(AgentLoop(engine, _ctx(env)).run("look around"))
    obs = [e.text for e in events if e.kind is EventKind.OBSERVATION]
    assert "exact call" in obs[1]                     # nudged, not re-executed
    assert events[-1].kind is EventKind.FINAL and events[-1].text == "ok"


def test_runaway_repeats_end_in_partial_summary(env):
    engine = FakeEngine([_call("list_dir", path=".")] * 10
                        + ["I listed the directory once; nothing else done."])
    events = list(AgentLoop(engine, _ctx(env)).run("loop forever"))
    assert any(e.kind is EventKind.ERROR and "repeating" in e.text
               for e in events)
    assert events[-1].kind is EventKind.FINAL
    assert events[-1].meta.get("partial") is True


def test_iteration_cap_ends_in_usable_summary(env):
    # Distinct calls each step (stall guard must NOT fire), never finishing.
    script = [_call("read_file", path="a.txt"),
              _call("list_dir", path="."),
              _call("glob", pattern="*.txt"),
              "Partial: inspected the workspace, ran out of steps."]
    loop = AgentLoop(FakeEngine(script), _ctx(env), max_iterations=3)
    events = list(loop.run("never finish"))
    assert any(e.kind is EventKind.ERROR and "limit" in e.text for e in events)
    assert events[-1].kind is EventKind.FINAL
    assert events[-1].meta.get("partial") is True
    assert "Partial" in events[-1].text
    assert sum(1 for e in events if e.kind is EventKind.TOOL_CALL) <= 3


# -- prompt + toolbox ----------------------------------------------------------
def test_system_prompt_sections_and_persona():
    tb = default_toolbox()
    for name in ("write_note", "append_note", "read_note", "ask_user"):
        assert name in tb
    p = build_system_prompt(tb, "wsname", "ask", library_name="lib",
                            role_prompt="You are the EA Test-Case Writer.",
                            today="2026-07-16")
    for tag in ("<role>", "<environment>", "<output>", "<planning>",
                "<rules>", "<office_work>", "<tools>"):
        assert tag in p
    assert "You are the EA Test-Case Writer." in p
    assert "wsname" in p and "lib" in p and "2026-07-16" in p
    assert "write_note" in p                     # tool docs rendered
    # No unresolved format placeholders escaped the template.
    assert "{workspace}" not in p and "{role_block}" not in p
