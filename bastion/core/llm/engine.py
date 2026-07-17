"""Inference engine abstraction — one interface, swappable local backends.

The rest of BastionBox never imports ``llama_cpp`` or ``ollama`` directly; it
talks to an :class:`Engine`. That indirection buys three things that matter for
this product:

* **Air-gap first.** The primary backend is embedded llama.cpp loading a GGUF
  straight off disk — models arrive by sneakernet, never a download. Ollama is
  an *optional* convenience for machines that already run it, loopback-only.
* **Testability.** :class:`FakeEngine` implements the same interface with
  scripted output, so the agent loop, grammar handling, and UI can be exercised
  deterministically on CI with no model, no GPU, and no network.
* **Crash isolation (see the process host).** A backend can run in a separate
  process; the UI only ever holds an :class:`Engine` handle and a token queue, so
  a bad GGUF cannot take the window down with it.

Everything here is plain dataclasses and an abstract base — cheap to read, cheap
to audit, and importable without any heavy optional dependency installed.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator, Sequence


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class Message:
    role: Role
    content: str
    #: Optional name for tool results (which tool produced this observation).
    name: str | None = None

    def as_dict(self) -> dict:
        d = {"role": self.role.value, "content": self.content}
        if self.name:
            d["name"] = self.name
        return d


@dataclass
class GenerationConfig:
    """Sampling knobs plus the optional grammar that forces structured output."""

    temperature: float = 0.7
    top_p: float = 0.95
    max_tokens: int = 2048
    stop: Sequence[str] = field(default_factory=tuple)
    #: A GBNF grammar string. When set, llama.cpp *constrains the sampler* so the
    #: output is guaranteed to match — the single biggest reliability lever for
    #: small local models doing tool calls. Backends that cannot enforce it must
    #: say so rather than silently ignoring it (see :meth:`Engine.supports`).
    grammar: str | None = None
    seed: int | None = None


@dataclass
class ModelInfo:
    """What the UI shows about the currently loaded model."""

    name: str
    family: str = "unknown"          # llama3 / qwen / mistral / …
    context_length: int = 8192
    quantization: str = ""           # Q4_K_M, Q8_0, …
    tool_capable: bool = True
    is_embedding: bool = False
    path: str = ""


class Capability(str, Enum):
    GRAMMAR = "grammar"              # can constrain output with GBNF
    STREAMING = "streaming"
    EMBEDDING = "embedding"
    MULTIMODAL = "multimodal"


class Engine(abc.ABC):
    """A loaded local model behind a uniform, streaming, tool-aware interface."""

    #: Populated by :meth:`load`.
    info: ModelInfo | None = None

    @abc.abstractmethod
    def load(self) -> ModelInfo:
        """Bring the model into memory and return its :class:`ModelInfo`."""

    @abc.abstractmethod
    def stream(self, messages: Sequence[Message],
               config: GenerationConfig) -> Iterator[str]:
        """Yield generated text token-by-token. Must be promptly interruptible.

        Callers stop generation simply by ceasing to consume the iterator and
        calling :meth:`cancel`; a good backend checks a cancel flag between
        tokens so the UI's Stop button aborts *now*, not at the next full reply.
        """

    def generate(self, messages: Sequence[Message],
                 config: GenerationConfig) -> str:
        """Convenience: run :meth:`stream` to completion and join the text."""
        return "".join(self.stream(messages, config))

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return an embedding vector per input (embedding models only)."""
        raise NotImplementedError("this engine is not an embedding model")

    def cancel(self) -> None:
        """Request that an in-flight :meth:`stream` stop as soon as possible."""

    def supports(self, cap: Capability) -> bool:
        return False

    def unload(self) -> None:
        """Free model memory. Safe to call more than once."""


# ---------------------------------------------------------------------------
# FakeEngine — the deterministic stand-in that makes the whole app testable
# ---------------------------------------------------------------------------
@dataclass
class ScriptedTurn:
    """One scripted model reply. Either free text, or a raw string that already
    contains the grammar-shaped JSON the agent loop expects for a tool call."""

    text: str
    chunk_size: int = 8   # how finely to slice it when streaming, for realism


class FakeEngine(Engine):
    """An :class:`Engine` that replays a fixed script — no model, no GPU, no net.

    Used by the test suite (deterministic agent-loop runs) and by the app's
    "no model loaded yet" state so the UI is never a dead screen. If the script
    is exhausted it returns a polite, honest placeholder rather than inventing
    capability it does not have.
    """

    def __init__(self, script: Sequence[ScriptedTurn | str] | None = None,
                 name: str = "fake-deterministic"):
        self._script: list[ScriptedTurn] = [
            t if isinstance(t, ScriptedTurn) else ScriptedTurn(t)
            for t in (script or [])
        ]
        self._cursor = 0
        self._cancel = False
        self._name = name

    def load(self) -> ModelInfo:
        self.info = ModelInfo(name=self._name, family="fake", context_length=8192,
                              quantization="none", tool_capable=True)
        return self.info

    def stream(self, messages, config) -> Iterator[str]:
        self._cancel = False
        turn = (self._script[self._cursor] if self._cursor < len(self._script)
                else ScriptedTurn("[no scripted reply — FakeEngine is a stub]"))
        self._cursor += 1
        text = turn.text
        for i in range(0, len(text), turn.chunk_size):
            if self._cancel:
                return
            yield text[i:i + turn.chunk_size]

    def embed(self, texts):
        # A cheap, deterministic pseudo-embedding: hashed byte histogram. Not
        # semantically meaningful, but stable and dependency-free for index tests.
        import hashlib
        out = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            out.append([b / 255.0 for b in h])  # 32-dim unit-ish vector
        return out

    def cancel(self) -> None:
        self._cancel = True

    def supports(self, cap: Capability) -> bool:
        return cap in {Capability.STREAMING, Capability.GRAMMAR, Capability.EMBEDDING}


class DemoEngine(Engine):
    """A canned, on-brand engine for the offline UI demo (no GGUF required).

    It streams a short, honest reply derived from the user's last message so the
    chat window is a live, satisfying experience out of the box — while making
    clear that a real model must be loaded for real answers. Not for tests; the
    deterministic :class:`FakeEngine` is used there.
    """

    def __init__(self) -> None:
        self._cancel = False

    def load(self) -> ModelInfo:
        self.info = ModelInfo(name="demo-offline", family="demo",
                              context_length=8192, quantization="none")
        return self.info

    def stream(self, messages: Sequence[Message],
               config: GenerationConfig) -> Iterator[str]:
        self._cancel = False
        last_user = next((m.content for m in reversed(messages)
                          if m.role is Role.USER), "")
        reply = (
            f"Received: “{last_user.strip()[:160]}”.\n\n"
            "This is the offline demo engine — proof the interface streams with "
            "zero network. Load a GGUF in Models (or point BastionBox at a local "
            "Ollama) and I'll answer for real, still without a byte leaving this "
            "machine. Mount a workspace and I can read and edit files, showing "
            "you a diff to approve before anything is written."
        )
        import time as _t
        for word in reply.split(" "):
            if self._cancel:
                return
            yield word + " "
            _t.sleep(0.012)  # a gentle typewriter cadence for the demo

    def cancel(self) -> None:
        self._cancel = True

    def supports(self, cap: Capability) -> bool:
        return cap is Capability.STREAMING


def demo_agent_script() -> list[str]:
    """A canned tool-call sequence for the offline agent demo (no model needed).

    Drives the real :class:`~bastion.core.agent.loop.AgentLoop` through an
    inspect → propose-write → finish cycle so a user with no GGUF loaded still
    sees the whole permissioned flow — including the mandatory diff-approval
    dialog on the ``write_file`` step. Fed to a :class:`FakeEngine` in the UI.
    """
    import json
    note = ("# Reviewed by BastionBox\n\n"
            "- Inspected this workspace **locally**.\n"
            "- No byte left the machine.\n"
            "- Every write, including this one, was shown to you as a diff.\n")
    return [
        json.dumps({"tool": "search_codebase", "args": {"query": "token"}}),
        json.dumps({"tool": "list_dir", "args": {"path": "."}}),
        json.dumps({"tool": "write_file",
                    "args": {"path": "BASTIONBOX_REVIEW.md", "content": note}}),
        json.dumps({"tool": "final", "args": {"content":
                    "I searched the index, listed the workspace, and proposed a "
                    "short review note — shown to you as a diff to approve. "
                    "Nothing left this machine."}}),
    ]
