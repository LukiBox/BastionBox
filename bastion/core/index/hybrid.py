"""Hybrid local retrieval — BM25 + vectors, fused, so an 8B model can answer.

A small model cannot hold a 500k-line codebase in context, so BastionBox retrieves
tightly and cites exactly. This index combines two complementary signals and
fuses them, because hybrid beats either alone on code:

* **BM25** over SQLite **FTS5** — exact lexical match. Unbeatable when the user
  knows a symbol name (``validate_token``), and it needs no model at all.
* **Vector cosine** over local embeddings (via the same :class:`Engine`) — catches
  semantic paraphrase ("where do we check credentials?").

Fusion is **Reciprocal Rank Fusion** (RRF): rank-based, scale-free, and robust
when the two score distributions are nothing alike — ideal when the embedding
model is small or, in tests, a deterministic stand-in.

Everything is one SQLite file (no server, FAISS optional later), scoped by
workspace key so two workspaces never share retrieval. Re-indexing is
incremental: a file whose mtime is unchanged is skipped; a changed or deleted
file has its old chunks dropped first.
"""
from __future__ import annotations

import math
import re
import sqlite3
import struct
import threading
from dataclasses import dataclass
from pathlib import Path

from ..security.jail import PathJail, Workspace
from .chunker import Chunk, chunk_file

# Directories never worth indexing (noise / huge / vendored).
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
              ".mypy_cache", ".pytest_cache", "dist", "build", "graphify-out",
              ".idea", ".vscode"}
_TEXT_SUFFIXES = {".py", ".md", ".markdown", ".rst", ".txt", ".js", ".ts",
                  ".tsx", ".jsx", ".c", ".h", ".cpp", ".hpp", ".java", ".go",
                  ".rs", ".rb", ".php", ".cs", ".json", ".toml", ".yaml", ".yml",
                  ".sql", ".sh", ".ps1"}
_MAX_FILE_BYTES = 1_000_000


@dataclass
class Hit:
    chunk: Chunk
    score: float
    lexical_rank: int | None = None
    vector_rank: int | None = None

    @property
    def citation(self) -> str:
        return self.chunk.citation


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"{len(blob) // 4}f", blob))


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _fts_query(text: str) -> str:
    """Turn free text into a safe FTS5 OR-query of quoted terms."""
    terms = re.findall(r"[A-Za-z0-9_]+", text)
    return " OR ".join(f'"{t}"' for t in terms) if terms else '""'


class HybridIndex:
    def __init__(self, db_path: str | Path = ":memory:"):
        # The agent loop runs on a worker thread while the UI may query the index
        # from the GUI thread, so the connection must not be thread-affine.
        # check_same_thread=False + a lock serializing every access is the safe,
        # dependency-free way to share one SQLite connection across threads.
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._migrate()

    def _migrate(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ws TEXT NOT NULL,
                path TEXT NOT NULL,
                start_line INTEGER, end_line INTEGER,
                kind TEXT, name TEXT, text TEXT,
                embedding BLOB
            );
            CREATE TABLE IF NOT EXISTS files (
                ws TEXT NOT NULL, path TEXT NOT NULL, mtime REAL,
                PRIMARY KEY (ws, path)
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
                USING fts5(text, content='chunks', content_rowid='id');
            CREATE INDEX IF NOT EXISTS idx_chunks_ws ON chunks(ws);
            """
        )
        self._db.commit()

    # -- indexing -----------------------------------------------------------
    def index_workspace(self, jail: PathJail, ws: Workspace, engine=None,
                        force: bool = False) -> dict:
        """(Re)index every text file in *ws*. Returns a small stats dict.

        Incremental by mtime; pass ``force=True`` to rebuild. Every path is
        resolved through the jail even here — the indexer has no privileged file
        access the agent lacks.
        """
        with self._lock:
            return self._index_workspace_locked(jail, ws, engine, force)

    def _index_workspace_locked(self, jail, ws, engine, force) -> dict:
        indexed = skipped = removed = 0
        seen: set[str] = set()
        known = {r["path"]: r["mtime"] for r in self._db.execute(
            "SELECT path, mtime FROM files WHERE ws=?", (ws.key,))}

        for file in self._walk(ws.root):
            rel = file.relative_to(ws.root).as_posix()
            seen.add(rel)
            try:
                jail.resolve(rel, ws)  # containment is enforced, always
                mtime = file.stat().st_mtime
            except Exception:  # noqa: BLE001
                continue
            if not force and known.get(rel) == mtime:
                skipped += 1
                continue
            try:
                text = file.read_text("utf-8", errors="ignore")
            except OSError:
                continue
            self._drop_file(ws.key, rel)
            chunks = chunk_file(rel, text)
            self._add_chunks(ws.key, chunks, engine)
            self._db.execute(
                "INSERT INTO files(ws,path,mtime) VALUES(?,?,?) "
                "ON CONFLICT(ws,path) DO UPDATE SET mtime=excluded.mtime",
                (ws.key, rel, mtime))
            indexed += 1

        # Drop files that vanished since last index.
        for gone in set(known) - seen:
            self._drop_file(ws.key, gone)
            self._db.execute("DELETE FROM files WHERE ws=? AND path=?",
                            (ws.key, gone))
            removed += 1
        self._db.commit()
        return {"indexed": indexed, "skipped": skipped, "removed": removed,
                "chunks": self.count(ws.key)}

    def _walk(self, root: Path):
        for p in root.rglob("*"):
            if p.is_dir():
                continue
            if any(part in _SKIP_DIRS for part in p.relative_to(root).parts):
                continue
            if p.suffix.lower() not in _TEXT_SUFFIXES:
                continue
            try:
                if p.stat().st_size > _MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield p

    def _drop_file(self, ws: str, rel: str) -> None:
        ids = [r["id"] for r in self._db.execute(
            "SELECT id FROM chunks WHERE ws=? AND path=?", (ws, rel))]
        for cid in ids:
            self._db.execute("DELETE FROM chunks_fts WHERE rowid=?", (cid,))
        self._db.execute("DELETE FROM chunks WHERE ws=? AND path=?", (ws, rel))

    def _add_chunks(self, ws: str, chunks: list[Chunk], engine) -> None:
        vectors = None
        if engine is not None and chunks:
            try:
                vectors = engine.embed([c.text for c in chunks])
            except Exception:  # noqa: BLE001 - embedding is best-effort
                vectors = None
        for i, c in enumerate(chunks):
            emb = _pack(vectors[i]) if vectors else None
            cur = self._db.execute(
                "INSERT INTO chunks(ws,path,start_line,end_line,kind,name,text,"
                "embedding) VALUES(?,?,?,?,?,?,?,?)",
                (ws, c.path, c.start_line, c.end_line, c.kind, c.name, c.text, emb))
            self._db.execute("INSERT INTO chunks_fts(rowid,text) VALUES(?,?)",
                            (cur.lastrowid, c.text))

    # -- search -------------------------------------------------------------
    def search(self, query: str, ws_key: str, engine=None, top_k: int = 6,
               rrf_k: int = 60) -> list[Hit]:
        """Rank-fuse BM25 and vector similarity; return the top *top_k* hits."""
        with self._lock:
            lexical = self._bm25(query, ws_key, limit=max(top_k * 4, 20))
            vector = self._vector(query, ws_key, engine, limit=max(top_k * 4, 20))
            return self._fuse(lexical, vector, top_k, rrf_k)

    def _fuse(self, lexical, vector, top_k, rrf_k) -> list[Hit]:
        scores: dict[int, float] = {}
        lex_rank: dict[int, int] = {}
        vec_rank: dict[int, int] = {}
        for rank, cid in enumerate(lexical, 1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (rrf_k + rank)
            lex_rank[cid] = rank
        for rank, cid in enumerate(vector, 1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (rrf_k + rank)
            vec_rank[cid] = rank

        top = sorted(scores, key=lambda c: scores[c], reverse=True)[:top_k]
        return [Hit(self._chunk(cid), scores[cid],
                    lex_rank.get(cid), vec_rank.get(cid)) for cid in top]

    def _bm25(self, query: str, ws: str, limit: int) -> list[int]:
        try:
            rows = self._db.execute(
                "SELECT c.id FROM chunks_fts f JOIN chunks c ON c.id=f.rowid "
                "WHERE c.ws=? AND chunks_fts MATCH ? ORDER BY bm25(chunks_fts) "
                "LIMIT ?", (ws, _fts_query(query), limit)).fetchall()
            return [r["id"] for r in rows]
        except sqlite3.OperationalError:
            return []

    def _vector(self, query: str, ws: str, engine, limit: int) -> list[int]:
        if engine is None:
            return []
        try:
            qv = engine.embed([query])[0]
        except Exception:  # noqa: BLE001
            return []
        scored = []
        for r in self._db.execute(
                "SELECT id, embedding FROM chunks WHERE ws=? AND embedding IS NOT NULL",
                (ws,)):
            scored.append((r["id"], _cosine(qv, _unpack(r["embedding"]))))
        scored.sort(key=lambda t: t[1], reverse=True)
        return [cid for cid, _ in scored[:limit]]

    def _chunk(self, cid: int) -> Chunk:
        r = self._db.execute("SELECT * FROM chunks WHERE id=?", (cid,)).fetchone()
        return Chunk(r["path"], r["start_line"], r["end_line"], r["kind"],
                     r["name"], r["text"])

    def count(self, ws_key: str) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) n FROM chunks WHERE ws=?",
                                    (ws_key,)).fetchone()["n"]

    def clear_workspace(self, ws_key: str) -> None:
        """Panic/secure-delete support: drop a workspace's entire index."""
        with self._lock:
            for r in self._db.execute("SELECT id FROM chunks WHERE ws=?", (ws_key,)):
                self._db.execute("DELETE FROM chunks_fts WHERE rowid=?", (r["id"],))
            self._db.execute("DELETE FROM chunks WHERE ws=?", (ws_key,))
            self._db.execute("DELETE FROM files WHERE ws=?", (ws_key,))
            self._db.commit()

    def close(self) -> None:
        self._db.close()
