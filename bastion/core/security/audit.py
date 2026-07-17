"""Tamper-evident audit log — the record that answers *what did the AI touch?*

The product's whole loop is: mount → ask → approve diffs → **the audit trail
proves what happened**. If a user cannot answer "what did the assistant do last
Tuesday, and did anyone alter the record?" in ten seconds, the product has failed
its mission. This module is that record.

Design
------
* **Append-only JSONL.** One JSON object per line, opened in append mode and
  ``fsync``-ed, so a crash can lose at most the last unfinished line.
* **Hash-chained.** Every entry carries ``prev`` — the hash of the entry before
  it — and its own ``hash`` covers ``prev`` plus the canonical serialization of
  the entry's content. Changing, reordering, or deleting any entry breaks the
  chain from that point on, and truncation is caught because the sequence numbers
  must be contiguous and the final hash is known.
* **Optional keyed integrity.** With a secret key the chain uses HMAC-SHA256, so
  an attacker who can rewrite the file *and* recompute plain SHA-256 hashes still
  cannot forge a valid chain without the key. Without a key it falls back to a
  plain SHA-256 chain (still detects accidental corruption and naive edits).

What we log — and what we deliberately do not
---------------------------------------------
We record *that* a prompt happened and its SHA-256, never its plaintext; the
same for file contents (we log paths, sizes, and diff hashes). The audit log is
a proof of activity, not a second copy of the user's secrets.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

__all__ = ["AuditLog", "AuditResult", "sha256_hex"]

_GENESIS = "0" * 64


def sha256_hex(data: str | bytes) -> str:
    """Hex SHA-256 of *data* — used for prompt/content fingerprints in entries."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _canonical(obj: dict[str, Any]) -> bytes:
    """Deterministic JSON bytes for hashing (sorted keys, no incidental spaces)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


@dataclass
class AuditResult:
    """Outcome of :meth:`AuditLog.verify`."""

    ok: bool
    entries: int
    #: 1-based sequence number of the first bad/mismatched entry, else ``None``.
    first_bad_seq: int | None = None
    detail: str = ""


class AuditLog:
    """Append-only, hash-chained JSONL audit log.

    Thread-safe: a single lock serializes appends and the read-side verification,
    which is enough because the file is only ever written by this process.
    """

    def __init__(self, path: str | os.PathLike[str], secret: bytes | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._secret = secret
        self._lock = threading.Lock()
        # Recover chain state ONCE at open; record() then appends in O(1) rather
        # than re-reading the file per entry (a busy agent session writes
        # thousands of entries — rescanning each time would be O(n²)).
        self._last_hash, self._seq = self._recover_state()

    # -- chaining primitives ------------------------------------------------
    def _digest(self, prev: str, body: bytes) -> str:
        if self._secret is not None:
            return hmac.new(self._secret, prev.encode() + body,
                            hashlib.sha256).hexdigest()
        h = hashlib.sha256()
        h.update(prev.encode())
        h.update(body)
        return h.hexdigest()

    def _recover_state(self) -> tuple[str, int]:
        """Read the last entry's hash + count so a reopened log continues its chain."""
        if not self.path.exists():
            return _GENESIS, 0
        last, count = _GENESIS, 0
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                count += 1
                try:
                    last = json.loads(line)["hash"]
                except (json.JSONDecodeError, KeyError):
                    break  # a truncated/garbled tail; verify() will flag it
        return last, count

    # -- writing ------------------------------------------------------------
    def record(self, kind: str, **payload: Any) -> dict[str, Any]:
        """Append an entry of type *kind* with arbitrary JSON-able *payload*.

        Returns the full written entry (including seq and hash) for callers that
        want to reference it immediately (e.g. surface the seq in the UI).
        """
        with self._lock:
            seq = self._seq + 1
            entry = {
                "seq": seq,
                "ts": round(time.time(), 3),
                "kind": kind,
                "prev": self._last_hash,
                "data": payload,
            }
            entry["hash"] = self._digest(self._last_hash, _canonical(
                {k: entry[k] for k in ("seq", "ts", "kind", "prev", "data")}))
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            self._last_hash = entry["hash"]
            self._seq = seq
            return entry

    # -- convenience recorders (what the agent actually logs) ---------------
    def log_prompt(self, conversation_id: str, prompt: str) -> None:
        self.record("prompt", conversation=conversation_id,
                    prompt_sha256=sha256_hex(prompt), chars=len(prompt))

    def log_tool_call(self, tool: str, args: dict[str, Any]) -> None:
        self.record("tool_call", tool=tool, args=args)

    def log_file_write(self, path: str, size: int, diff_sha256: str) -> None:
        self.record("file_write", path=path, size=size, diff_sha256=diff_sha256)

    def log_command(self, command: str, cwd: str, exit_code: int | None) -> None:
        self.record("command", command=command, cwd=cwd, exit_code=exit_code)

    def log_decision(self, action: str, approved: bool, actor: str, note: str = "") -> None:
        self.record("decision", action=action, approved=approved,
                    actor=actor, note=note)

    def log_network_block(self, host: str, port: int | None, api: str) -> None:
        self.record("network_block", host=host, port=port, api=api)

    # -- reading / verifying ------------------------------------------------
    def __iter__(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)

    def verify(self) -> AuditResult:
        """Recompute the whole chain and report the first tampered entry, if any.

        Detects content mutation, hash forgery (without the key), reordering,
        insertion, and truncation (via contiguous sequence numbers).
        """
        prev = _GENESIS
        count = 0
        expected_seq = 1
        if not self.path.exists():
            return AuditResult(ok=True, entries=0, detail="no log yet")
        with self.path.open("r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    return AuditResult(False, count, count + 1,
                                       f"line {lineno}: not valid JSON (truncated?)")
                count += 1
                if entry.get("seq") != expected_seq:
                    return AuditResult(False, count, expected_seq,
                                       f"sequence break at entry {count}: "
                                       f"expected seq {expected_seq}, "
                                       f"got {entry.get('seq')}")
                if entry.get("prev") != prev:
                    return AuditResult(False, count, expected_seq,
                                       f"entry {expected_seq}: prev-hash does not "
                                       f"match previous entry (chain cut/reordered)")
                body = _canonical({k: entry.get(k)
                                   for k in ("seq", "ts", "kind", "prev", "data")})
                if self._digest(prev, body) != entry.get("hash"):
                    return AuditResult(False, count, expected_seq,
                                       f"entry {expected_seq}: content does not "
                                       f"match its hash (tampered)")
                prev = entry["hash"]
                expected_seq += 1
        return AuditResult(ok=True, entries=count,
                           detail=f"chain valid, {count} entries")
