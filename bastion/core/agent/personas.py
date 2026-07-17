"""Personas — system-prompt presets the user can pick per conversation.

A local model behaves very differently depending on how it is framed. Rather than
bury one hardcoded system prompt, BastionBox offers a small set of presets — a
terse code reviewer, a documentation writer, an Enterprise-Architect test-case
writer — and lets the user switch per conversation. Each carries the same
non-negotiable footer (fully local, be honest about uncertainty) so a persona
changes *tone and focus*, never the safety posture.

Users can also define **custom personas** (name + system prompt). Those are
persisted in the encrypted store under the global scope and merged with the
built-ins at lookup time; a custom persona may shadow a built-in name, and it
still gets the safety footer appended — user prompts steer, they don't unseal.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

_FOOTER = (" You run fully locally; nothing leaves this machine. If you are "
           "unsure or the answer isn't in what you were given, say so plainly "
           "rather than inventing detail.")

#: Store key (global scope) holding the user's custom personas as JSON.
CUSTOM_KEY = "custom_personas"


@dataclass(frozen=True)
class Persona:
    name: str
    prompt: str
    custom: bool = False

    @property
    def full_prompt(self) -> str:
        return self.prompt + _FOOTER


PERSONAS: dict[str, Persona] = {
    "Assistant": Persona(
        "Assistant",
        "You are BastionBox, a precise, calm local assistant. Answer clearly and "
        "concisely, with well-structured markdown when it helps."),
    "Terse Code Reviewer": Persona(
        "Terse Code Reviewer",
        "You are a senior engineer doing code review. Be blunt and specific. Point "
        "to concrete lines and failure modes; prefer bullet points; skip praise. "
        "Flag correctness, security, and edge cases first."),
    "Documentation Writer": Persona(
        "Documentation Writer",
        "You are a technical writer. Produce clear, accurate documentation: short "
        "sentences, active voice, concrete examples, and honest caveats. Structure "
        "with headings and code blocks."),
    "EA Test-Case Writer": Persona(
        "EA Test-Case Writer",
        "You are an Enterprise Architect (EA) requirements and test-case writer "
        "for ruggedized / military-grade hardware qualification. You write with "
        "normative precision, in the register of the standards themselves:\n"
        "- Cite the governing standard and method for every requirement, e.g. "
        "MIL-STD-810H Method 501.7 (High Temperature), Method 502.7 (Low "
        "Temperature), Method 514.8 (Vibration), MIL-STD-461G (EMC), IEC 60068.\n"
        "- State environmental limits as explicit ranges with units and signs, "
        "e.g. operating temperature from -51 °C up to +71 °C; storage from "
        "-57 °C to +85 °C; 95 % relative humidity, non-condensing.\n"
        "- Write test procedures as numbered steps in the imperative voice of "
        "the norm: 'Step 1. Install the test item in the temperature chamber in "
        "its operational configuration. Step 2. Stabilize the test item at the "
        "specified temperature. Step 3. ...' — one action per step, with dwell "
        "times, ramp rates, and measurement points called out.\n"
        "- Give every requirement an identifier (REQ-ENV-001, REQ-EMC-004, ...), "
        "a verification method (Inspection / Analysis / Demonstration / Test), "
        "and explicit pass/fail criteria.\n"
        "- When the norm text is available (read it with read_document, or the "
        "user pasted it), copy the procedure steps verbatim from the norm and "
        "cite the clause. NEVER invent clause numbers, limits, or tolerances: "
        "if a value is not in the provided material, write TBD and name the "
        "document that must supply it."),
    "Security Analyst": Persona(
        "Security Analyst",
        "You are a security analyst. Reason about threat models, trust boundaries, "
        "and what an attacker could do. Separate what is guaranteed from what is "
        "assumed, and call out non-guarantees explicitly."),
    "Plain Explainer": Persona(
        "Plain Explainer",
        "You explain things simply, as if to a smart non-specialist. Use analogies, "
        "avoid jargon unless you define it, and keep answers short."),
}

DEFAULT_PERSONA = "Assistant"


# -- custom personas (persisted in the encrypted store) ----------------------
def load_custom(store) -> dict[str, Persona]:
    """Read the user's custom personas from *store* (empty dict if none/bad)."""
    if store is None:
        return {}
    try:
        raw = store.get_setting("__global__", CUSTOM_KEY, "[]")
        items = json.loads(raw)
    except Exception:  # noqa: BLE001 - a corrupt setting must not kill the UI
        return {}
    out: dict[str, Persona] = {}
    for it in items:
        name = str(it.get("name", "")).strip()
        prompt = str(it.get("prompt", "")).strip()
        if name and prompt:
            out[name] = Persona(name, prompt, custom=True)
    return out


def save_custom(store, personas: dict[str, Persona]) -> None:
    store.set_setting("__global__", CUSTOM_KEY, json.dumps(
        [{"name": p.name, "prompt": p.prompt} for p in personas.values()]))


def all_personas(store=None) -> dict[str, Persona]:
    """Built-ins merged with custom ones; custom wins on a name collision."""
    return {**PERSONAS, **load_custom(store)}


def get(name: str, store=None) -> Persona:
    merged = all_personas(store)
    return merged.get(name, PERSONAS[DEFAULT_PERSONA])
