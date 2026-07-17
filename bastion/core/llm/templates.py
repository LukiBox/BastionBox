"""Chat-template handling per model family — never hardcode one template.

Rendering the conversation with the *wrong* special tokens is one of the top
reasons a capable local model "seems dumb". Each family (Llama 3.x, Qwen 2.5/3,
Mistral, Phi-3, Gemma) has its own turn delimiters. When a backend can apply the
GGUF's own embedded chat template we prefer that; this module is the fallback
(and the reference the tests check against) for families we know.
"""
from __future__ import annotations

from typing import Sequence

from .engine import Message, Role

__all__ = ["render", "KNOWN_FAMILIES"]

KNOWN_FAMILIES = ("llama3", "qwen", "mistral", "phi3", "gemma")


def _llama3(messages: Sequence[Message]) -> str:
    out = ["<|begin_of_text|>"]
    for m in messages:
        # Llama 3 was trained with tool results under the "ipython" header,
        # not "tool" — the wrong header makes the model ignore observations.
        role = "ipython" if m.role is Role.TOOL else m.role.value
        out.append(f"<|start_header_id|>{role}<|end_header_id|>\n\n"
                   f"{m.content}<|eot_id|>")
    out.append("<|start_header_id|>assistant<|end_header_id|>\n\n")
    return "".join(out)


def _qwen(messages: Sequence[Message]) -> str:
    out = []
    for m in messages:
        out.append(f"<|im_start|>{m.role.value}\n{m.content}<|im_end|>\n")
    out.append("<|im_start|>assistant\n")
    return "".join(out)


def _mistral(messages: Sequence[Message]) -> str:
    # Mistral uses [INST]…[/INST]; system is folded into the first instruction.
    sys_txt = " ".join(m.content for m in messages if m.role is Role.SYSTEM)
    out = []
    for m in messages:
        if m.role is Role.SYSTEM:
            continue
        if m.role is Role.USER:
            prefix = f"{sys_txt}\n\n" if sys_txt and not out else ""
            out.append(f"[INST] {prefix}{m.content} [/INST]")
        elif m.role is Role.ASSISTANT:
            out.append(f" {m.content}</s>")
        elif m.role is Role.TOOL:
            out.append(f"[INST] (tool result) {m.content} [/INST]")
    return "".join(out)


def _phi3(messages: Sequence[Message]) -> str:
    out = []
    for m in messages:
        out.append(f"<|{m.role.value}|>\n{m.content}<|end|>\n")
    out.append("<|assistant|>\n")
    return "".join(out)


def _gemma(messages: Sequence[Message]) -> str:
    # Gemma has no system role; fold it into the first user turn.
    out = ["<bos>"]
    sys_txt = " ".join(m.content for m in messages if m.role is Role.SYSTEM)
    injected = False
    for m in messages:
        if m.role is Role.SYSTEM:
            continue
        role = "model" if m.role is Role.ASSISTANT else "user"
        content = m.content
        if role == "user" and sys_txt and not injected:
            content = f"{sys_txt}\n\n{content}"
            injected = True
        out.append(f"<start_of_turn>{role}\n{content}<end_of_turn>\n")
    out.append("<start_of_turn>model\n")
    return "".join(out)


_RENDERERS = {
    "llama3": _llama3, "qwen": _qwen, "mistral": _mistral,
    "phi3": _phi3, "gemma": _gemma,
}


def render(messages: Sequence[Message], family: str) -> str:
    """Render *messages* to a prompt string for *family*.

    Unknown families fall back to the widely-compatible ChatML (Qwen) format
    rather than guessing wrong with special tokens the model never saw.
    """
    return _RENDERERS.get(family, _qwen)(messages)
