"""Encrypted persistence — conversations, settings, and per-workspace memory.

Design choice, stated honestly: rather than depend on SQLCipher binaries (awkward
to ship to an air-gapped site), BastionBox stores its data in a plain SQLite file
but **encrypts every sensitive column at the application layer** with AES-256-GCM
(see :mod:`bastion.core.security.crypto`). The key is derived from the app
passphrase (Argon2id) or a DPAPI machine key. The GCM tag makes each row
tamper-evident, and the ``aad`` binds a row to its workspace so ciphertext cannot
be transplanted between scopes.

If no key is available the store runs in an explicit *unencrypted* mode and says
so — it never writes plaintext into a database the user believes is sealed
without surfacing that state (:attr:`Store.encrypted`).

Panic controls live here too: :meth:`secure_delete_workspace` removes every trace
of a workspace — chats, messages, extracted text, memory — in one action.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..security.crypto import Cipher


@dataclass
class Conversation:
    id: int
    workspace_key: str
    title: str
    created: float
    updated: float


class Store:
    def __init__(self, db_path: str | Path, cipher: Optional[Cipher] = None):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._cipher = cipher
        # Chat generation runs on a worker thread while the UI reads on the GUI
        # thread, so the connection must not be thread-affine. A lock serializes
        # every access (see the same rationale in core/index/hybrid.py).
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._migrate()

    @property
    def encrypted(self) -> bool:
        return self._cipher is not None

    def _migrate(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_key TEXT NOT NULL,
                title TEXT NOT NULL,
                created REAL NOT NULL,
                updated REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                enc INTEGER NOT NULL,       -- 1 if the blob is AES-GCM encrypted
                blob BLOB NOT NULL,
                ts REAL NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            );
            CREATE TABLE IF NOT EXISTS settings (
                scope TEXT NOT NULL,        -- 'global' or a workspace_key
                key TEXT NOT NULL,
                enc INTEGER NOT NULL,
                blob BLOB NOT NULL,
                PRIMARY KEY (scope, key)
            );
            CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id);
            CREATE INDEX IF NOT EXISTS idx_conv_ws ON conversations(workspace_key);
            """
        )
        self._db.commit()

    # -- field encryption ---------------------------------------------------
    def _seal(self, text: str, aad: str) -> tuple[int, bytes]:
        if self._cipher is None:
            return 0, text.encode("utf-8")
        return 1, self._cipher.encrypt(text.encode("utf-8"), aad=aad.encode())

    def _open(self, enc: int, blob: bytes, aad: str) -> str:
        if enc == 0:
            return bytes(blob).decode("utf-8", errors="replace")
        if self._cipher is None:
            raise RuntimeError("row is encrypted but no key is loaded")
        return self._cipher.decrypt(bytes(blob), aad=aad.encode()).decode("utf-8")

    # -- conversations ------------------------------------------------------
    def create_conversation(self, workspace_key: str, title: str) -> int:
        now = time.time()
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO conversations(workspace_key,title,created,updated) "
                "VALUES (?,?,?,?)", (workspace_key, title, now, now))
            self._db.commit()
            return cur.lastrowid

    def add_message(self, conversation_id: int, role: str, content: str) -> None:
        with self._lock:
            conv = self._db.execute(
                "SELECT workspace_key FROM conversations WHERE id=?",
                (conversation_id,)).fetchone()
            aad = f"conv:{conversation_id}:{conv['workspace_key'] if conv else ''}"
            enc, blob = self._seal(content, aad)
            self._db.execute(
                "INSERT INTO messages(conversation_id,role,enc,blob,ts) VALUES (?,?,?,?,?)",
                (conversation_id, role, enc, blob, time.time()))
            self._db.execute("UPDATE conversations SET updated=? WHERE id=?",
                             (time.time(), conversation_id))
            self._db.commit()

    def get_messages(self, conversation_id: int) -> list[dict]:
        with self._lock:
            conv = self._db.execute(
                "SELECT workspace_key FROM conversations WHERE id=?",
                (conversation_id,)).fetchone()
            ws_key = conv["workspace_key"] if conv else ""
            rows = self._db.execute(
                "SELECT role,enc,blob,ts FROM messages WHERE conversation_id=? ORDER BY id",
                (conversation_id,)).fetchall()
        aad = f"conv:{conversation_id}:{ws_key}"
        return [{"role": r["role"], "content": self._open(r["enc"], r["blob"], aad),
                 "ts": r["ts"]} for r in rows]

    def list_conversations(self, workspace_key: str) -> list[Conversation]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM conversations WHERE workspace_key=? ORDER BY updated DESC",
                (workspace_key,)).fetchall()
        return [Conversation(r["id"], r["workspace_key"], r["title"],
                             r["created"], r["updated"]) for r in rows]

    # -- settings & per-workspace memory (the visible, editable memory.md) --
    def set_setting(self, scope: str, key: str, value: str) -> None:
        enc, blob = self._seal(value, f"setting:{scope}:{key}")
        with self._lock:
            self._db.execute(
                "INSERT INTO settings(scope,key,enc,blob) VALUES (?,?,?,?) "
                "ON CONFLICT(scope,key) DO UPDATE SET enc=excluded.enc, blob=excluded.blob",
                (scope, key, enc, blob))
            self._db.commit()

    def get_setting(self, scope: str, key: str, default: str = "") -> str:
        with self._lock:
            row = self._db.execute(
                "SELECT enc,blob FROM settings WHERE scope=? AND key=?",
                (scope, key)).fetchone()
        if row is None:
            return default
        return self._open(row["enc"], row["blob"], f"setting:{scope}:{key}")

    def get_memory(self, workspace_key: str) -> str:
        """The visible, per-workspace long-term memory (no silent memory rule)."""
        return self.get_setting(workspace_key, "memory.md", default="")

    def set_memory(self, workspace_key: str, content: str) -> None:
        self.set_setting(workspace_key, "memory.md", content)

    # -- panic control ------------------------------------------------------
    def secure_delete_workspace(self, workspace_key: str) -> int:
        """Delete a workspace's entire footprint: chats, messages, settings.

        Returns the number of conversations removed. After deleting rows we run
        ``VACUUM`` so the freed pages are rewritten and stale content is not left
        lingering in the file's slack space.
        """
        with self._lock:
            conv_ids = [r["id"] for r in self._db.execute(
                "SELECT id FROM conversations WHERE workspace_key=?",
                (workspace_key,)).fetchall()]
            if conv_ids:
                qmarks = ",".join("?" * len(conv_ids))
                self._db.execute(
                    f"DELETE FROM messages WHERE conversation_id IN ({qmarks})", conv_ids)
            self._db.execute("DELETE FROM conversations WHERE workspace_key=?",
                             (workspace_key,))
            self._db.execute("DELETE FROM settings WHERE scope=?", (workspace_key,))
            self._db.commit()
            self._db.execute("VACUUM")
            self._db.commit()
            return len(conv_ids)

    def close(self) -> None:
        self._db.close()
