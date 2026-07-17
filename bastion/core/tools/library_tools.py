"""Reference-library search — find the needle file in a huge attached folder.

The user attaches a *reference library*: a big (possibly enormous) read-only
folder of datasheets, norms, and archives. ``search_library`` lets the agent
find candidate files by keyword — matching file names/paths always, and file
*contents* too when the library has been indexed in the Knowledge tab — and
then read the hits with ``read_document``.

The library is mounted read-only in the same path jail as workspaces, so every
access is contained; and the walk is capped so a million-file archive can't
stall the loop — ranking prefers files matching more keywords, then newer ones.
"""
from __future__ import annotations

import os
from typing import Any

from ..docs import extract as _extract
from .base import Tool, ToolContext, ToolResult

_MAX_WALK = 50_000      # directory entries examined per search, tops
_MAX_RESULTS = 20
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
              "$RECYCLE.BIN", "System Volume Information"}


def keyword_search(root, keywords: list[str], cap: int = _MAX_WALK
                   ) -> list[tuple[str, int, float]]:
    """Walk *root* matching *keywords* against relative paths.

    Returns ``(relpath, matched_kw_count, mtime)`` for files matching at least
    one keyword, best first. Bounded at *cap* entries so huge trees stay fast.
    """
    kws = [k.lower() for k in keywords if k.strip()]
    if not kws:
        return []
    hits: list[tuple[str, int, float]] = []
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in filenames:
            seen += 1
            if seen > cap:
                break
            rel = os.path.relpath(os.path.join(dirpath, fname), root)
            hay = rel.replace("\\", "/").lower()
            matched = sum(1 for k in kws if k in hay)
            if matched:
                try:
                    mtime = os.path.getmtime(os.path.join(dirpath, fname))
                except OSError:
                    mtime = 0.0
                hits.append((rel.replace("\\", "/"), matched, mtime))
        if seen > cap:
            break
    hits.sort(key=lambda h: (-h[1], -h[2]))
    return hits[:_MAX_RESULTS]


class SearchLibrary(Tool):
    name = "search_library"
    description = ("Search the attached read-only reference library (a large "
                   "folder of datasheets/norms) for files. Matches keywords "
                   "against file names/paths, and against file CONTENTS when "
                   "the library is indexed. Returns paths to pass to "
                   "read_document.")
    args = {"keywords": "space-separated keywords, e.g. 'MIL-STD-810 vibration'"}

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        if ctx.library is None:
            return ToolResult.error(
                "no reference library is attached — attach one in the "
                "Knowledge tab first")
        raw = str(args.get("keywords") or "").strip()
        if not raw:
            return ToolResult.error("empty keywords")
        keywords = raw.split()
        ctx.audit.log_tool_call(self.name, {"keywords": raw})

        name_hits = keyword_search(ctx.library.root, keywords)
        lines: list[str] = []
        if name_hits:
            lines.append(f"{len(name_hits)} file(s) matched by name:")
            for rel, matched, _ in name_hits:
                suffix = os.path.splitext(rel)[1].lower()
                readable = " (readable)" if _extract.supported(rel) else ""
                lines.append(f"  {rel}  [{suffix or 'file'}{readable}, "
                             f"{matched}/{len(keywords)} keywords]")

        # Content search rides on the hybrid index when the library was indexed.
        if ctx.index is not None:
            try:
                content = ctx.index.search(raw, ctx.library.key,
                                           engine=ctx.embed_engine, top_k=5)
            except Exception:  # noqa: BLE001 - content search is best-effort
                content = []
            if content:
                lines.append(f"{len(content)} content match(es):")
                for h in content:
                    first = h.chunk.text.strip().splitlines()
                    preview = first[0][:100] if first else ""
                    lines.append(f"  {h.citation}  «{preview}»")

        if not lines:
            return ToolResult(True, f"No library files matched “{raw}”. "
                                    f"Try fewer or different keywords.")
        lines.append("Read any hit with read_document(path).")
        return ToolResult(True, "\n".join(lines))


LIBRARY_TOOLS: dict[str, Tool] = {SearchLibrary().name: SearchLibrary()}
