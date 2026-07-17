"""Context compaction — summarize older turns, and say so in the transcript.

When a conversation approaches the context window, BastionBox can fold the older
turns into a compact summary produced by the utility model, freeing room while
keeping the thread coherent. The cardinal rule (mirrored in the UI): **never
silently lie about what the model can see.** The summary is inserted as a clearly
marked block in the transcript, and the recent turns are kept verbatim, so the
user always knows exactly what context is live.
"""
from __future__ import annotations

from typing import Sequence

from ..llm.engine import Engine, GenerationConfig, Message, Role

_SUMMARY_SYSTEM = (
    "You compress a conversation for context management. Produce a tight, factual "
    "summary of the exchange so it can stand in for the original turns: preserve "
    "decisions, facts, file names, and open threads; drop pleasantries. Plain "
    "prose, no preamble, under 200 words.")


def compact(messages: Sequence[Message], engine: Engine, *,
            keep_recent: int = 4) -> tuple[Message, list[Message]]:
    """Summarize all but the last *keep_recent* messages.

    Returns ``(summary_message, kept_messages)``. The summary is a SYSTEM message
    tagged so the UI and any downstream prompt render it as an explicit
    "earlier conversation summarized" block rather than passing it off as a real
    turn. If there is too little to compact, returns an empty summary and the
    messages unchanged.
    """
    older = list(messages[:-keep_recent]) if keep_recent else list(messages)
    kept = list(messages[-keep_recent:]) if keep_recent else []
    older = [m for m in older if m.role in (Role.USER, Role.ASSISTANT)]
    if len(older) < 2:
        return Message(Role.SYSTEM, ""), list(messages)

    transcript = "\n".join(f"{m.role.value.upper()}: {m.content}" for m in older)
    summary = engine.generate(
        [Message(Role.SYSTEM, _SUMMARY_SYSTEM), Message(Role.USER, transcript)],
        GenerationConfig(temperature=0.2, max_tokens=400)).strip()
    marked = Message(
        Role.SYSTEM,
        f"[Earlier conversation, summarized for context]\n{summary}")
    return marked, kept
