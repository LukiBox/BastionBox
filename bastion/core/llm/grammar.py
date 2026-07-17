"""GBNF grammar generation — force tool calls into valid JSON at the sampler.

The single biggest reliability lever for a small local agent is to stop *hoping*
the model emits valid JSON and instead **constrain the sampler** so it cannot do
otherwise. llama.cpp speaks GBNF (a BNF dialect); this module builds a grammar
from the registered tool schemas so every tool call the model produces parses as
valid JSON with a known tool name and only the fields that tool declares.

We keep the generated grammar small and permissive on *values* (any JSON string
/ number / bool) but strict on *shape* (object with a ``tool`` enum and an
``args`` object). Even when a backend cannot enforce grammar, the agent loop's
JSON parser is written to never crash on malformed input — grammar makes bad
output nearly impossible; defensive parsing handles the "nearly".
"""
from __future__ import annotations

from typing import Sequence


# A compact, reusable JSON value grammar. This is standard GBNF understood by
# llama.cpp's grammar sampler.
_JSON_PRIMITIVES = r"""
value   ::= object | array | string | number | boolean | null
object  ::= "{" ws (pair (ws "," ws pair)*)? ws "}"
pair    ::= string ws ":" ws value
array   ::= "[" ws (value (ws "," ws value)*)? ws "]"
string  ::= "\"" char* "\""
char    ::= [^"\\] | "\\" (["\\/bfnrt] | "u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F])
number  ::= "-"? ("0" | [1-9] [0-9]*) ("." [0-9]+)? ([eE] [-+]? [0-9]+)?
boolean ::= "true" | "false"
null    ::= "null"
ws      ::= [ \t\n]*
""".strip()


def tool_call_grammar(tool_names: Sequence[str]) -> str:
    """Return a GBNF grammar constraining output to a single tool-call object.

    Shape enforced::

        { "tool": <one-of tool_names>, "args": { ... } }

    plus an escape hatch ``{"tool":"final","args":{"content":"..."}}`` for the
    model to end the loop with a natural-language answer.
    """
    names = list(dict.fromkeys([*tool_names, "final"]))  # dedupe, keep order
    # GBNF alternation of quoted literals for the enum.
    tool_enum = " | ".join(f'"\\"{n}\\""' for n in names)
    root = (
        'root    ::= ws "{" ws "\\"tool\\"" ws ":" ws toolname ws "," ws '
        '"\\"args\\"" ws ":" ws object ws "}" ws\n'
        f"toolname ::= {tool_enum}\n"
    )
    return root + _JSON_PRIMITIVES


def json_object_grammar() -> str:
    """Grammar that forces *any* single JSON object (used for structured outputs
    like the sample-table generator, where the shape is validated afterwards)."""
    return 'root ::= ws object ws\n' + _JSON_PRIMITIVES
