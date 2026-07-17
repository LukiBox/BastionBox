"""The agent loop — plan → act → observe, engineered for a small local model.

A hard iteration cap, grammar-forced JSON tool calls, a visible thinking trace,
and rejection-as-feedback. The loop emits a stream of :class:`AgentEvent`s that
both the UI (collapsible trace, diff dialogs) and the test harness consume the
same way — so what CI proves is exactly what the user sees.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterator, Sequence

from ..llm.engine import Engine, GenerationConfig, Message, Role
from ..llm.grammar import tool_call_grammar
from ..tools.base import Tool, ToolContext, ToolResult
from .schemas import build_system_prompt, default_toolbox


class EventKind(str, Enum):
    THINKING = "thinking"     # raw model output for this step (trace)
    TOOL_CALL = "tool_call"   # a parsed tool invocation
    OBSERVATION = "observation"  # a tool's result fed back to the model
    FINAL = "final"           # the agent's final answer
    ERROR = "error"           # loop-level problem (cap hit, unparseable, …)
    PROGRESS = "progress"     # live liveness ping while the model works
    # (meta: step, chars generated so far — 0 = still reading the context).
    # A local model can take minutes on one step; without these the trace
    # freezes and the user reads "broken" where the truth is "thinking".


@dataclass
class AgentEvent:
    kind: EventKind
    text: str = ""
    tool: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


def _extract_json_object(text: str) -> dict | None:
    """Parse the first balanced JSON object in *text*, defensively.

    Grammar makes the whole output a clean JSON object, but this must never crash
    on malformed input (the parser is the backstop for the "nearly" in "grammar
    makes bad output nearly impossible"). Returns None if nothing parses.
    """
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back to scanning for the first balanced {...} span.
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start != -1:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


#: rough chars-per-token for budget estimates (English + code averages ~4).
_CHARS_PER_TOKEN = 4


@dataclass
class AgentLoop:
    engine: Engine
    ctx: ToolContext
    toolbox: dict[str, Tool] = field(default_factory=default_toolbox)
    #: generous enough for many-file jobs (e.g. reading a folder of invoices);
    #: the stall guard + graceful wrap-up keep a high cap safe.
    max_iterations: int = 24
    temperature: float = 0.2   # agents want low temperature / determinism
    #: the loaded model's context window (tokens). The message history is kept
    #: under this so a big tool observation can never overflow it and crash the
    #: turn (llama.cpp raises when the prompt exceeds n_ctx).
    context_tokens: int = 8192
    #: tokens reserved for the model's reply on each step.
    reply_tokens: int = 1024
    #: the active persona's prompt, injected as the <role> section of the
    #: system prompt — steers voice and domain focus, never the safety rules.
    role_prompt: str = ""
    #: consecutive identical tool calls tolerated before the loop wraps up.
    max_stalls: int = 3

    def _notepad_message(self) -> Message | None:
        """The agent's notes, rendered fresh for this turn (never persisted in
        the history, so no stale copies accumulate). Pinned through trimming —
        the plan survives even when the steps that produced it are gone."""
        if not self.ctx.notes:
            return None
        return Message(Role.USER,
                       "<notepad>\nYour saved notes (always current):\n\n"
                       + self.ctx.notes.render() + "\n</notepad>")

    def _fit(self, messages: list[Message],
             extra_pinned: list[Message] | None = None) -> list[Message]:
        """Trim history so the prompt fits the context, newest-first.

        Always keeps the system prompt (index 0), the original task (the first
        user message), and any ``extra_pinned`` messages (the notepad), then
        keeps as many of the most-recent turns as fit. Older tool observations
        are dropped with a short marker so the model knows earlier context
        existed — better a truncated history than a crash.
        """
        budget = max(512, self.context_tokens - self.reply_tokens - 256)

        def est(m: Message) -> int:
            return len(m.content) // _CHARS_PER_TOKEN + 8

        if not messages:
            return messages
        head = [messages[0]]                       # system prompt
        rest = messages[1:]
        # Keep the first user message (the task) pinned at the front of `rest`.
        pinned: list[Message] = []
        if rest and rest[0].role is Role.USER:
            pinned = [rest[0]]
            rest = rest[1:]
        if extra_pinned:
            pinned = pinned + list(extra_pinned)
        used = sum(est(m) for m in head + pinned)
        kept_tail: list[Message] = []
        for m in reversed(rest):                   # newest-first
            c = est(m)
            if used + c > budget and kept_tail:
                break
            # A single observation larger than the whole budget gets truncated
            # rather than dropped, so the latest read still informs the reply.
            if used + c > budget:
                keep_chars = max(0, (budget - used - 8) * _CHARS_PER_TOKEN)
                m = Message(m.role, m.content[:keep_chars]
                            + "\n[…truncated to fit the context window…]",
                            name=m.name)
                c = est(m)
            used += c
            kept_tail.append(m)
        dropped = len(rest) - len(kept_tail)
        note: list[Message] = []
        if dropped > 0:
            note = [Message(Role.USER,
                            f"[{dropped} earlier step(s) were trimmed to fit the "
                            f"context window. Rely on your notes and the recent "
                            f"observations below.]")]
        return head + pinned + note + list(reversed(kept_tail))

    def run(self, user_message: str,
            history: Sequence[Message] | None = None) -> Iterator[AgentEvent]:
        """Drive the loop, yielding events until a final answer or the cap.

        Callers (UI or tests) iterate this generator; the UI renders each event
        live and, crucially, the diff-approval dialogs happen *inside* the tool
        run via the permission broker, so approval is synchronous with the step.
        """
        self.ctx.audit.log_prompt("agent", user_message)
        system = build_system_prompt(
            self.toolbox, self.ctx.workspace.display_name,
            self.ctx.workspace.permission.value,
            library_name=(self.ctx.library.display_name
                          if self.ctx.library is not None else None),
            role_prompt=self.role_prompt)
        messages: list[Message] = [Message(Role.SYSTEM, system)]
        messages.extend(history or [])
        messages.append(Message(Role.USER, user_message))

        grammar = tool_call_grammar(list(self.toolbox.keys()))
        cfg = GenerationConfig(temperature=self.temperature,
                               max_tokens=self.reply_tokens, grammar=grammar)

        last_call: tuple[str, str] | None = None   # (tool, canonical args)
        stalls = 0
        for step in range(1, self.max_iterations + 1):
            notepad = self._notepad_message()
            prompt = self._fit(messages, [notepad] if notepad else None)
            # Stream the step so the UI can show life: chars=0 means the model
            # is still prefilling the context (the silent, slow part on CPU);
            # afterwards a ping lands roughly every 200 generated chars. A
            # backend failure (Ollama died, OOM, …) must never kill the trace
            # silently — it becomes an ERROR plus a graceful wrap-up.
            yield AgentEvent(EventKind.PROGRESS, meta={"step": step, "chars": 0})
            parts: list[str] = []
            total, next_tick = 0, 200
            try:
                for piece in self.engine.stream(prompt, cfg):
                    parts.append(piece)
                    total += len(piece)
                    if total >= next_tick:
                        next_tick = total + 200
                        yield AgentEvent(EventKind.PROGRESS,
                                         meta={"step": step, "chars": total})
            except Exception as exc:  # noqa: BLE001 - engine death → honest stop
                yield AgentEvent(
                    EventKind.ERROR,
                    text=f"model backend failed: {type(exc).__name__}: {exc}")
                yield from self._wrap_up(messages, cfg,
                                         reason="the model backend failed")
                return
            raw = "".join(parts)
            yield AgentEvent(EventKind.THINKING, text=raw, meta={"step": step})

            parsed = _extract_json_object(raw)
            if parsed is None:
                # Grammar should prevent this; recover by asking for valid JSON.
                messages.append(Message(Role.ASSISTANT, raw))
                messages.append(Message(
                    Role.USER, "That was not a single valid JSON tool object. "
                               "Reply with exactly one JSON object."))
                yield AgentEvent(EventKind.ERROR, text="unparseable step; retrying")
                continue

            tool_name = parsed.get("tool", "final")
            args = parsed.get("args", {}) or {}

            if tool_name == "final":
                answer = args.get("content", "") if isinstance(args, dict) else str(args)
                yield AgentEvent(EventKind.FINAL, text=answer)
                return

            tool = self.toolbox.get(tool_name)
            yield AgentEvent(EventKind.TOOL_CALL, tool=tool_name, args=args)

            # Stall guard: the exact same call twice in a row means the model is
            # looping — nothing changed in a jailed offline workspace between two
            # back-to-back identical calls, so re-running it can't help. Nudge
            # instead of executing; too many stalls and we wrap up gracefully.
            this_call = (tool_name, json.dumps(args, sort_keys=True, default=str))
            if this_call == last_call:
                stalls += 1
                if stalls >= self.max_stalls:
                    yield from self._wrap_up(
                        messages, cfg,
                        reason="the loop kept repeating the same call")
                    return
                result = ToolResult(False,
                                    "you just made this exact call and already "
                                    "have its result above. Do something "
                                    "different: check your plan note, advance "
                                    "to the next step, or give your final "
                                    "answer.")
            elif tool is None:
                result = ToolResult.error(f"unknown tool {tool_name!r}")
            else:
                stalls = 0
                try:
                    result = tool.run(self.ctx, args)
                except Exception as exc:  # a tool bug must not kill the loop
                    result = ToolResult.error(f"{type(exc).__name__}: {exc}")
            last_call = this_call

            yield AgentEvent(EventKind.OBSERVATION, tool=tool_name,
                             text=result.observation, meta=result.meta)
            # Feed the step and its observation back for the next turn.
            messages.append(Message(Role.ASSISTANT, raw))
            messages.append(Message(Role.TOOL, result.observation, name=tool_name))

        yield from self._wrap_up(
            messages, cfg,
            reason=f"reached the {self.max_iterations}-step limit")

    def _wrap_up(self, messages: list[Message], cfg: GenerationConfig,
                 reason: str) -> Iterator[AgentEvent]:
        """One last plain-text generation so a capped run still ends usefully.

        Hitting the iteration cap (or the stall limit) used to end in a bare
        error; now the model is asked — without the tool grammar — to summarize
        what it did, found, and what remains, so the user gets a real answer
        with honest 'unfinished' framing instead of a dead end.
        """
        yield AgentEvent(EventKind.ERROR,
                         text=f"{reason}; asking the model to summarize progress")
        wrap_cfg = GenerationConfig(temperature=self.temperature,
                                    max_tokens=self.reply_tokens)
        ask = Message(Role.USER,
                      "Stop working now. In plain text (no JSON, no tool "
                      "calls): summarize what you did and found, what remains "
                      "unfinished, and any assumptions you made.")
        try:
            notepad = self._notepad_message()
            summary = self.engine.generate(
                self._fit(messages + [ask], [notepad] if notepad else None),
                wrap_cfg).strip()
        except Exception as exc:  # noqa: BLE001 - summary is best-effort
            summary = ""
            self.ctx.audit.log_tool_call("wrap_up_failed",
                                         {"error": f"{type(exc).__name__}"})
        if not summary:
            summary = (f"Stopped: {reason}. No summary could be generated — "
                       f"see the agent trace above for what was done.")
        yield AgentEvent(EventKind.FINAL, text=summary,
                         meta={"partial": True, "reason": reason})
