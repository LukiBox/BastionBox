"""Knowledge index suite (§8) — chunk boundaries, hybrid recall, incremental refresh.

The chunker respects function/class boundaries with line spans; hybrid search
returns the known-relevant chunk in the top results on a seeded corpus;
re-indexing picks up edits and drops deleted files; and every hit carries a
`file:line` citation.
"""
from __future__ import annotations

import pytest

from bastion.core.agent.permissions import PolicyBroker
from bastion.core.index.chunker import chunk_file
from bastion.core.index.hybrid import HybridIndex
from bastion.core.llm.engine import FakeEngine
from bastion.core.security.audit import AuditLog
from bastion.core.security.jail import PathJail, Permission
from bastion.core.tools.base import ToolContext
from bastion.core.tools.search_tools import SearchCodebase


_SRC = '''\
"""Module docstring."""
import os

TOKEN_TTL = 3600


def helper(x):
    return x + 1


class AuthValidator:
    """Validates auth tokens."""

    def validate_token(self, token):
        # the real token check lives here
        return token == "ok"

    def refresh(self, token):
        return token
'''


def test_chunker_respects_python_boundaries():
    chunks = chunk_file("auth/validator.py", _SRC)
    kinds = {(c.kind, c.name) for c in chunks}
    assert ("function", "helper") in kinds
    assert ("class", "AuthValidator") in kinds
    assert ("method", "AuthValidator.validate_token") in kinds
    # The method chunk's span actually contains its body line.
    m = next(c for c in chunks if c.name == "AuthValidator.validate_token")
    assert "return token ==" in m.text
    assert m.start_line <= m.end_line
    assert m.citation.startswith("auth/validator.py:")


def test_chunker_markdown_by_heading():
    md = "# Title\nintro\n\n## Section A\nbody a\n\n## Section B\nbody b\n"
    chunks = chunk_file("doc.md", md)
    names = [c.name for c in chunks]
    assert "Section A" in names and "Section B" in names


def _seed(tmp_path):
    ws_dir = tmp_path / "code"
    (ws_dir / "auth").mkdir(parents=True)
    (ws_dir / "auth" / "validator.py").write_text(_SRC, encoding="utf-8")
    (ws_dir / "util.py").write_text(
        "def unrelated():\n    return 'nothing to do with tokens'\n", encoding="utf-8")
    (ws_dir / "README.md").write_text(
        "# Project\nGeneral notes about deployment.\n", encoding="utf-8")
    jail = PathJail()
    ws = jail.mount(ws_dir, Permission.ASK)
    return jail, ws, ws_dir


def test_hybrid_search_finds_relevant_chunk_top_k(tmp_path):
    jail, ws, _ = _seed(tmp_path)
    idx = HybridIndex()
    stats = idx.index_workspace(jail, ws, engine=FakeEngine())
    assert stats["indexed"] == 3 and stats["chunks"] > 0

    hits = idx.search("validate_token", ws.key, engine=FakeEngine(), top_k=3)
    assert hits, "expected at least one hit"
    top_citations = [h.citation for h in hits]
    assert any(c.startswith("auth/validator.py") for c in top_citations)
    # The most relevant hit is the method that defines/uses the symbol.
    assert "validator.py" in hits[0].citation


def test_incremental_reindex_picks_up_edits_and_deletes(tmp_path):
    jail, ws, ws_dir = _seed(tmp_path)
    idx = HybridIndex()
    idx.index_workspace(jail, ws, engine=FakeEngine())

    # Second pass with no changes indexes nothing new.
    again = idx.index_workspace(jail, ws, engine=FakeEngine())
    assert again["indexed"] == 0 and again["skipped"] >= 3

    # Edit a file -> it (and only it) is re-indexed; new content is searchable.
    import os, time
    target = ws_dir / "util.py"
    target.write_text("def brand_new_symbol():\n    return 42\n", encoding="utf-8")
    os.utime(target, (time.time() + 2, time.time() + 2))  # bump mtime deterministically
    delta = idx.index_workspace(jail, ws, engine=FakeEngine())
    assert delta["indexed"] == 1
    hits = idx.search("brand_new_symbol", ws.key, engine=FakeEngine())
    assert any("util.py" in h.citation for h in hits)

    # Delete a file -> its chunks are removed on next index.
    (ws_dir / "auth" / "validator.py").unlink()
    after = idx.index_workspace(jail, ws, engine=FakeEngine())
    assert after["removed"] == 1
    assert not any("validator.py" in h.citation
                   for h in idx.search("validate_token", ws.key, engine=FakeEngine()))


def test_search_codebase_tool_returns_citations(tmp_path):
    jail, ws, _ = _seed(tmp_path)
    idx = HybridIndex()
    idx.index_workspace(jail, ws, engine=FakeEngine())
    ctx = ToolContext(jail=jail, workspace=ws, broker=PolicyBroker(),
                      audit=AuditLog(tmp_path / "a.jsonl"),
                      index=idx, embed_engine=FakeEngine())
    result = SearchCodebase().run(ctx, {"query": "validate_token"})
    assert result.ok
    assert any(c.startswith("auth/validator.py") for c in result.meta["citations"])


def test_search_without_index_is_honest(tmp_path):
    jail, ws, _ = _seed(tmp_path)
    ctx = ToolContext(jail=jail, workspace=ws, broker=PolicyBroker(),
                      audit=AuditLog(tmp_path / "a.jsonl"))
    result = SearchCodebase().run(ctx, {"query": "anything"})
    assert not result.ok and "no index" in result.observation


def test_index_is_usable_across_threads(tmp_path):
    """The index is built on one thread and queried from another (the agent
    runs on a worker thread) — this must not raise a SQLite thread error."""
    import threading
    jail, ws, _ = _seed(tmp_path)
    idx = HybridIndex()  # created on the main thread
    idx.index_workspace(jail, ws, engine=FakeEngine())

    result = {}
    def worker():
        try:
            result["hits"] = idx.search("validate_token", ws.key, engine=FakeEngine())
        except Exception as exc:  # noqa: BLE001
            result["error"] = exc
    t = threading.Thread(target=worker)
    t.start(); t.join()
    assert "error" not in result, f"cross-thread search raised {result.get('error')}"
    assert result["hits"]


def test_grounded_miss_says_not_found(tmp_path):
    jail, ws, _ = _seed(tmp_path)
    idx = HybridIndex()
    idx.index_workspace(jail, ws, engine=None)  # lexical-only index
    hits = idx.search("quantum chromodynamics zzzzz", ws.key)
    assert hits == []  # nothing matched — the UI/model must say "not found"
