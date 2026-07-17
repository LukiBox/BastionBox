"""Semantic + lexical codebase search, with mandatory citations.

``search_codebase`` is how the agent finds *where* something is without reading
whole files into a small model's context. It queries the hybrid index and returns
ranked passages, each labelled with a `path:start-end` citation the UI turns into
a clickable jump to the file. If retrieval finds nothing, it says so — the model
is expected to relay "not found" rather than invent an answer (grounded mode).
"""
from __future__ import annotations

from typing import Any

from .base import Tool, ToolContext, ToolResult


class SearchCodebase(Tool):
    name = "search_codebase"
    description = ("Find relevant code/doc passages by meaning or keyword. Returns "
                   "ranked snippets, each with a file:line citation. Use this "
                   "before reading whole files.")
    args = {"query": "what you are looking for (symbol, concept, or question)"}

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        query = (args.get("query") or "").strip()
        if not query:
            return ToolResult.error("empty query")
        if ctx.index is None:
            return ToolResult.error(
                "no index has been built for this workspace yet — build the index "
                "in the Knowledge tab first")
        ctx.audit.log_tool_call(self.name, {"query": query})
        hits = ctx.index.search(query, ctx.workspace.key,
                                engine=ctx.embed_engine, top_k=6)
        if not hits:
            return ToolResult(True, f"No passages matched “{query}”. "
                                    f"Not found in the indexed workspace.")
        lines = [f"{len(hits)} passage(s) for “{query}”:"]
        for h in hits:
            snippet = h.chunk.text.strip().splitlines()
            preview = "\n    ".join(snippet[:6])
            lines.append(f"\n[{h.citation}]  ({h.chunk.kind} {h.chunk.name})\n"
                         f"    {preview}")
        return ToolResult(True, "\n".join(lines),
                          meta={"citations": [h.citation for h in hits]})


SEARCH_TOOLS: dict[str, Tool] = {SearchCodebase().name: SearchCodebase()}
