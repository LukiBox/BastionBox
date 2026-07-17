"""Notepad and human-in-the-loop tools — the agent's working memory and its
one sanctioned way to ask the user something mid-task.

The notepad (:class:`~bastion.core.tools.base.NoteStore`) is where the agent
keeps its plan and findings. The loop injects a compact view of every note into
each prompt automatically, so the model never has to *remember* to consult its
notes — they are simply always in front of it, and they survive the history
trimming that protects the context window. ``read_note`` exists only to fetch a
note in full when the injected view was clipped.

``ask_user`` routes a free-form clarifying question to the user through the same
worker-parks-until-the-GUI-answers bridge as diff approvals. A per-task budget
(``ctx.ask_budget``) keeps a lazy model from outsourcing its thinking; with no
UI wired (headless, tests) the tool degrades to "proceed with your best
judgment" so runs stay deterministic.
"""
from __future__ import annotations

from typing import Any

from .base import Tool, ToolContext, ToolResult


class WriteNote(Tool):
    name = "write_note"
    description = ("Create or overwrite a named note in your notepad. Notes are "
                   "shown to you automatically every turn and survive even when "
                   "older steps are trimmed. Keep your plan in a note named "
                   "'plan' as a markdown checklist and update it as you finish "
                   "steps.")
    args = {"name": "note name, e.g. 'plan' or 'findings'",
            "content": "full new note content (markdown)"}

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        name = str(args.get("name", "")).strip()
        content = str(args.get("content", ""))
        if not name:
            return ToolResult.error("note needs a name, e.g. 'plan'")
        ctx.notes.write(name, content)
        ctx.audit.log_tool_call(self.name, {"name": name, "chars": len(content)})
        return ToolResult(True, f"note '{name}' saved ({len(content)} chars); "
                                f"it will stay visible to you every turn")


class AppendNote(Tool):
    name = "append_note"
    description = ("Append a line/paragraph to a named note (creates it if "
                   "missing). Use it to log findings as you work, e.g. "
                   "append_note('findings', '- power draw peaks at 45 W').")
    args = {"name": "note name", "content": "text to append"}

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        name = str(args.get("name", "")).strip()
        content = str(args.get("content", ""))
        if not name:
            return ToolResult.error("note needs a name, e.g. 'findings'")
        ctx.notes.append(name, content)
        ctx.audit.log_tool_call(self.name, {"name": name, "chars": len(content)})
        return ToolResult(True, f"appended to note '{name}'")


class ReadNote(Tool):
    name = "read_note"
    description = ("Read one note in full. Only needed when the notepad view "
                   "shown to you was clipped — normally your notes are already "
                   "visible every turn.")
    args = {"name": "note name"}

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        name = str(args.get("name", "")).strip()
        body = ctx.notes.read(name)
        ctx.audit.log_tool_call(self.name, {"name": name})
        if body is None:
            have = ", ".join(ctx.notes.names()) or "none"
            return ToolResult.error(f"no note named '{name}' (existing: {have})")
        return ToolResult(True, f"note '{name}':\n{body}")


class AskUser(Tool):
    name = "ask_user"
    description = ("Ask the user ONE clarifying question and wait for their "
                   "answer. Use only when genuinely blocked by missing "
                   "information you cannot find in the workspace or library — "
                   "never to ask permission to proceed (the approval system "
                   "handles that). You have a small budget of questions per "
                   "task; spend it wisely.")
    args = {"question": "the single, specific question to ask the user"}

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        question = str(args.get("question", "")).strip()
        if not question:
            return ToolResult.error("empty question")
        ctx.audit.log_tool_call(self.name, {"question": question[:200]})
        if ctx.ask_user is None:
            return ToolResult(True, "no user is available to answer; proceed "
                                    "with your best judgment and state the "
                                    "assumption you made in your final answer")
        if ctx.ask_budget <= 0:
            return ToolResult(True, "question budget exhausted for this task; "
                                    "proceed with your best judgment and state "
                                    "your assumptions in your final answer")
        ctx.ask_budget -= 1
        answer = (ctx.ask_user(question) or "").strip()
        ctx.audit.log_decision(f"ask_user: {question[:120]}", bool(answer),
                               actor="user",
                               note="answered" if answer else "skipped")
        if not answer:
            return ToolResult(True, "the user skipped the question; proceed "
                                    "with your best judgment and state your "
                                    "assumptions in your final answer")
        return ToolResult(True, f"the user answered: {answer}")


#: Notepad + human-in-the-loop toolbox, keyed by name.
NOTES_TOOLS: dict[str, Tool] = {
    t.name: t for t in (WriteNote(), AppendNote(), ReadNote(), AskUser())
}
