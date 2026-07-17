"""Code-aware chunking — split by *meaning*, not by a blind character window.

Retrieval quality on code lives or dies on chunk boundaries. A chunk that cuts a
function in half retrieves half an answer. So we chunk by structure:

* **Python** → the standard-library ``ast`` module gives exact function/class
  spans (no third-party parser, nothing to vet on an air-gapped site). Each
  top-level function, each class, and each method becomes a chunk carrying its
  file path and 1-based line span, so every retrieved passage cites `file:a-b`.
* **Markdown / text** → split on headings and blank-line paragraph boundaries.
* **Anything else** (JS, C, …) → a line-window fallback that overlaps slightly so
  a match near a boundary is still retrievable, until a real tree-sitter grammar
  is wired in (the ``index`` optional dependency).

The chunker is pure and dependency-free, so the index tests run anywhere.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Chunk:
    """One retrievable unit, with everything a citation needs."""

    path: str            # workspace-relative, forward-slash
    start_line: int      # 1-based, inclusive
    end_line: int        # 1-based, inclusive
    kind: str            # "function" | "class" | "method" | "section" | "block"
    name: str            # symbol or heading, for the citation label
    text: str

    @property
    def citation(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"


def chunk_file(path: str, text: str) -> list[Chunk]:
    """Chunk *text* (contents of *path*) by structure appropriate to its type."""
    suffix = Path(path).suffix.lower()
    rel = path.replace("\\", "/")
    if suffix == ".py":
        chunks = _chunk_python(rel, text)
        if chunks:
            return chunks
    if suffix in {".md", ".markdown", ".rst", ".txt"}:
        return _chunk_markdown(rel, text)
    return _chunk_lines(rel, text)


def _chunk_python(rel: str, text: str) -> list[Chunk]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []  # fall back to line chunking for unparseable/partial files
    lines = text.splitlines()
    chunks: list[Chunk] = []

    def span(node) -> tuple[int, int]:
        start = node.lineno
        # Include a preceding decorator line in the span if present.
        if getattr(node, "decorator_list", None):
            start = min(start, min(d.lineno for d in node.decorator_list))
        end = getattr(node, "end_lineno", start)
        return start, end

    def text_of(a: int, b: int) -> str:
        return "\n".join(lines[a - 1:b])

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a, b = span(node)
            chunks.append(Chunk(rel, a, b, "function", node.name, text_of(a, b)))
        elif isinstance(node, ast.ClassDef):
            a, b = span(node)
            # Emit the class header as its own chunk, then each method.
            methods = [n for n in node.body
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            header_end = (min(m.lineno for m in methods) - 1) if methods else b
            chunks.append(Chunk(rel, a, header_end, "class", node.name,
                                text_of(a, header_end)))
            for m in methods:
                ma, mb = span(m)
                chunks.append(Chunk(rel, ma, mb, "method",
                                    f"{node.name}.{m.name}", text_of(ma, mb)))
    # Capture module-level code outside any def/class (imports, constants) so a
    # question about a top-level symbol still retrieves something.
    covered = {ln for c in chunks for ln in range(c.start_line, c.end_line + 1)}
    leftover = [i for i in range(1, len(lines) + 1)
                if i not in covered and lines[i - 1].strip()]
    if leftover:
        chunks.append(Chunk(rel, leftover[0], leftover[-1], "block", "<module>",
                            "\n".join(lines[i - 1] for i in leftover)))
    return sorted(chunks, key=lambda c: c.start_line)


def _chunk_markdown(rel: str, text: str) -> list[Chunk]:
    lines = text.splitlines()
    chunks: list[Chunk] = []
    cur_start = 1
    cur_name = "(intro)"
    buf: list[str] = []

    def flush(end: int) -> None:
        body = "\n".join(buf).strip()
        if body:
            chunks.append(Chunk(rel, cur_start, end, "section", cur_name, body))

    for i, line in enumerate(lines, 1):
        if line.startswith("#"):
            flush(i - 1)
            cur_start = i
            cur_name = line.lstrip("#").strip() or "(section)"
            buf = [line]
        else:
            buf.append(line)
    flush(len(lines))
    return chunks or _chunk_lines(rel, text)


def _chunk_lines(rel: str, text: str, window: int = 60, overlap: int = 10) -> list[Chunk]:
    lines = text.splitlines()
    if not lines:
        return []
    chunks: list[Chunk] = []
    step = max(1, window - overlap)
    for start in range(0, len(lines), step):
        end = min(len(lines), start + window)
        body = "\n".join(lines[start:end]).strip()
        if body:
            chunks.append(Chunk(rel, start + 1, end, "block", "<block>", body))
        if end == len(lines):
            break
    return chunks
