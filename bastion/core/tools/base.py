"""Tool foundations — the context every tool runs in, and the result it returns.

There is exactly one file API in BastionBox and it runs through the jail. Every
tool receives a :class:`ToolContext` carrying the jail, the active workspace, the
permission broker, and the audit log, so no tool can reach disk, write, or run a
command without passing the walls and leaving a record.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Callable

from ..security.audit import AuditLog
from ..security.jail import PathJail, Workspace
from ..agent.permissions import PermissionBroker


class NoteStore:
    """The agent's scratchpad — a living plan and findings kept across one task.

    A small local model loses the thread on long, multi-step jobs: earlier tool
    observations scroll out of the context window (see :meth:`AgentLoop._fit`) and
    the model forgets what it already learned or intended to do. The notepad fixes
    that. Notes live here in memory for the run, and the loop re-injects a compact
    view of them near the top of every prompt, so the plan and key findings survive
    even after the raw steps that produced them have been trimmed away.

    This is deliberately *not* on disk: notes are working memory, not a workspace
    artefact, so they never hit the jail, never show up as a diff, and vanish when
    the task ends. Files the agent means to keep, it writes with ``write_file`` /
    ``write_document`` like anything else.
    """

    #: Hard cap on a single note, so one runaway append can't dominate the window.
    MAX_NOTE_CHARS = 8_000

    def __init__(self) -> None:
        self._notes: dict[str, str] = {}

    def write(self, name: str, content: str) -> None:
        self._notes[name] = content[: self.MAX_NOTE_CHARS]

    def append(self, name: str, content: str) -> None:
        cur = self._notes.get(name, "")
        joined = (cur + "\n" + content) if cur else content
        self._notes[name] = joined[: self.MAX_NOTE_CHARS]

    def read(self, name: str) -> str | None:
        return self._notes.get(name)

    def names(self) -> list[str]:
        return list(self._notes)

    def __bool__(self) -> bool:
        return bool(self._notes)

    def render(self, cap: int = 2_000) -> str:
        """A compact, human-readable view of all notes for prompt injection.

        Truncates the *whole* view to ``cap`` chars (newest notes such as 'plan'
        first is the caller's job — here we keep insertion order) so the injected
        block stays bounded no matter how much the agent has written; a note that
        gets clipped can still be read in full with the ``read_note`` tool.
        """
        if not self._notes:
            return ""
        out: list[str] = []
        for name, body in self._notes.items():
            out.append(f"### {name}\n{body.strip()}")
        text = "\n\n".join(out)
        if len(text) > cap:
            text = text[:cap] + "\n[…notes clipped; read a specific note in full " \
                                "with read_note…]"
        return text


@dataclass
class ToolContext:
    jail: PathJail
    workspace: Workspace
    broker: PermissionBroker
    audit: AuditLog
    #: command allowlist (exact-match) and caps, passed from config.
    command_allowlist: tuple[str, ...] = ()
    command_timeout_s: float = 60.0
    command_output_cap: int = 100_000
    #: Max characters a single read_document returns. Sized from the loaded
    #: model's context window so one document can never overflow it (leaving
    #: room for the system prompt and the reply); the agent reads further pages
    #: on demand. Default suits an ~8k window.
    read_char_cap: int = 24_000
    #: Optional hybrid index + embedding engine for the search_codebase tool.
    #: When absent, search reports "no index" instead of failing.
    index: object | None = None
    embed_engine: object | None = None
    #: Optional read-only reference library (a second jail mount): a big folder
    #: of datasheets/norms the agent may SEARCH and READ but never write to.
    #: Read tools fall back to it when a path isn't in the workspace; write
    #: tools never resolve against it — read-only by construction.
    library: Workspace | None = None
    #: The agent's scratchpad for this run (plan + findings). Its own default so
    #: a freshly-built context always has somewhere to take notes.
    notes: NoteStore = field(default_factory=NoteStore)
    #: Optional bridge to ask the user a free-form clarifying question and block
    #: for the answer. Wired to the UI on the GUI thread; ``None`` headless/in
    #: tests, where the ask_user tool degrades to "no user available, proceed".
    ask_user: Callable[[str], str] | None = None
    #: How many ask_user questions remain for this task. A tight budget keeps a
    #: lazy model from outsourcing its thinking to the user; when it hits zero
    #: the tool answers "proceed with your best judgment" instead of asking.
    ask_budget: int = 2


@dataclass
class ToolResult:
    """What a tool hands back to the loop as an *observation*.

    ``ok`` is False for rejections and errors alike — both are recoverable
    signals the model reads and adapts to, never exceptions that kill the loop.
    """

    ok: bool
    observation: str
    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def error(cls, msg: str) -> "ToolResult":
        return cls(False, f"error: {msg}")

    @classmethod
    def rejected(cls, msg: str) -> "ToolResult":
        return cls(False, f"user rejected: {msg}")


class Tool(abc.ABC):
    name: str = ""
    description: str = ""
    #: Compact JSON-schema-ish arg spec, rendered into the system prompt and the
    #: GBNF grammar. Kept small and example-rich — few tools, well described.
    args: dict[str, str] = {}

    @abc.abstractmethod
    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult: ...

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "args": self.args}
