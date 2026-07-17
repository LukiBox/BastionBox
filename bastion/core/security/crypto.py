"""Encryption at rest and key handling — honest about what it does and doesn't do.

BastionBox stores conversations, indexes, extracted document text, and settings.
On a machine that may be audited or physically seized, those must be unreadable
without the user's key. This module provides:

* **Key derivation** from an optional app passphrase — Argon2id when the
  ``argon2-cffi`` package is present (memory-hard, the modern default), otherwise
  a high-iteration PBKDF2-HMAC-SHA256 fallback that ships with the standard
  library so encryption never silently degrades to *nothing*.
* **A DPAPI machine-key mode on Windows** (``CryptProtectData`` via ``ctypes``,
  zero third-party code) for users who want "unreadable off this machine / this
  account" without memorizing a passphrase.
* **AES-256-GCM** authenticated encryption via the ``cryptography`` package for
  the actual data. GCM gives us confidentiality *and* tamper detection on each
  blob.

Honesty rule (mirrors the product's docs): if neither ``cryptography`` nor a
platform crypto provider is available we **raise** rather than pretend — we never
write plaintext to a file the user believes is encrypted. Callers check
:func:`encryption_available` and surface the real state in the Security panel.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "derive_key", "KdfParams", "Cipher", "encryption_available",
    "dpapi_protect", "dpapi_unprotect", "EncryptionUnavailable",
    "load_or_create_store_key",
]

_IS_WINDOWS = sys.platform == "win32"

# Optional strong deps, imported lazily so the security tests run dependency-free.
try:  # pragma: no cover - presence depends on the environment
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore
    _HAVE_AESGCM = True
except Exception:  # noqa: BLE001
    _HAVE_AESGCM = False

try:  # pragma: no cover
    from argon2.low_level import hash_secret_raw, Type as _Argon2Type  # type: ignore
    _HAVE_ARGON2 = True
except Exception:  # noqa: BLE001
    _HAVE_ARGON2 = False


class EncryptionUnavailable(RuntimeError):
    """Raised when strong encryption is requested but no provider is installed."""


def encryption_available() -> bool:
    """True if we can actually AES-encrypt data (never fake it if we can't)."""
    return _HAVE_AESGCM


@dataclass(frozen=True)
class KdfParams:
    """Parameters recorded alongside a derived key so it can be reproduced.

    Stored (non-secret) so the same passphrase yields the same key next launch.
    """

    algo: str          # "argon2id" or "pbkdf2-sha256"
    salt: bytes
    iterations: int = 600_000       # pbkdf2 rounds (OWASP-class default)
    memory_kib: int = 262_144       # argon2 memory cost (256 MiB)
    parallelism: int = 4            # argon2 lanes
    length: int = 32                # 256-bit key

    def to_public(self) -> dict:
        return {
            "algo": self.algo, "salt": self.salt.hex(),
            "iterations": self.iterations, "memory_kib": self.memory_kib,
            "parallelism": self.parallelism, "length": self.length,
        }

    @classmethod
    def from_public(cls, d: dict) -> "KdfParams":
        return cls(algo=d["algo"], salt=bytes.fromhex(d["salt"]),
                   iterations=d.get("iterations", 600_000),
                   memory_kib=d.get("memory_kib", 262_144),
                   parallelism=d.get("parallelism", 4),
                   length=d.get("length", 32))


def new_kdf_params() -> KdfParams:
    """Fresh KDF parameters with a random salt, preferring Argon2id if available."""
    algo = "argon2id" if _HAVE_ARGON2 else "pbkdf2-sha256"
    return KdfParams(algo=algo, salt=secrets.token_bytes(16))


def derive_key(passphrase: str, params: KdfParams) -> bytes:
    """Derive a 32-byte key from *passphrase* using *params*.

    Deterministic for a given passphrase + params (same salt → same key), which
    is what lets a returning user unlock last session's databases.
    """
    pw = passphrase.encode("utf-8")
    if params.algo == "argon2id":
        if not _HAVE_ARGON2:  # params say argon2 but lib is gone -> be explicit
            raise EncryptionUnavailable(
                "database was sealed with Argon2id but argon2-cffi is not installed")
        return hash_secret_raw(
            secret=pw, salt=params.salt, time_cost=3,
            memory_cost=params.memory_kib, parallelism=params.parallelism,
            hash_len=params.length, type=_Argon2Type.ID)
    # PBKDF2 fallback — always available (stdlib).
    return hashlib.pbkdf2_hmac("sha256", pw, params.salt,
                               params.iterations, dklen=params.length)


class Cipher:
    """AES-256-GCM authenticated encryption around a 32-byte key.

    Wire format per blob: ``nonce(12) || ciphertext || tag`` (the tag is appended
    by AESGCM). ``aad`` (additional authenticated data) binds a blob to context —
    e.g. a workspace key — so a ciphertext cannot be transplanted between scopes.
    """

    def __init__(self, key: bytes):
        if len(key) != 32:
            raise ValueError("Cipher key must be 32 bytes (256-bit)")
        if not _HAVE_AESGCM:
            raise EncryptionUnavailable(
                "AES-256-GCM requires the 'cryptography' package. Install it, or "
                "run BastionBox in unencrypted-store mode explicitly.")
        self._aead = AESGCM(key)

    def encrypt(self, plaintext: bytes, aad: bytes | None = None) -> bytes:
        nonce = secrets.token_bytes(12)
        return nonce + self._aead.encrypt(nonce, plaintext, aad)

    def decrypt(self, blob: bytes, aad: bytes | None = None) -> bytes:
        if len(blob) < 12:
            raise ValueError("ciphertext too short to contain a nonce")
        nonce, body = blob[:12], blob[12:]
        return self._aead.decrypt(nonce, body, aad)


# ---------------------------------------------------------------------------
# Windows DPAPI machine/user key (no third-party dependency)
# ---------------------------------------------------------------------------
def dpapi_protect(data: bytes, entropy: bytes = b"BastionBox") -> bytes:
    """Encrypt *data* with the current Windows user's DPAPI key.

    Usable as a passphrase-free "unreadable off this account" mode: the blob can
    only be decrypted by the same Windows user on the same machine.
    """
    if not _IS_WINDOWS:
        raise EncryptionUnavailable("DPAPI is only available on Windows")
    return _dpapi(data, entropy, protect=True)


def dpapi_unprotect(blob: bytes, entropy: bytes = b"BastionBox") -> bytes:
    if not _IS_WINDOWS:
        raise EncryptionUnavailable("DPAPI is only available on Windows")
    return _dpapi(blob, entropy, protect=False)


def _dpapi(data: bytes, entropy: bytes, protect: bool) -> bytes:  # pragma: no cover
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _blob(b: bytes) -> DATA_BLOB:
        buf = ctypes.create_string_buffer(b, len(b))
        return DATA_BLOB(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    in_blob, ent_blob, out_blob = _blob(data), _blob(entropy), DATA_BLOB()
    # 0x1 = CRYPTPROTECT_UI_FORBIDDEN (never pop a dialog).
    if not fn(ctypes.byref(in_blob), None, ctypes.byref(ent_blob),
              None, None, 0x1, ctypes.byref(out_blob)):
        raise OSError("DPAPI operation failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def constant_time_equals(a: bytes, b: bytes) -> bool:
    """Timing-safe comparison for verifying MACs / key checks."""
    return hmac.compare_digest(a, b)


# ---------------------------------------------------------------------------
# Store-key resolution — encryption ON by default, never a hardcoded salt
# ---------------------------------------------------------------------------
def load_or_create_store_key(data_dir: Path, passphrase: str | None) -> bytes | None:
    """Resolve the 32-byte store key for this installation, creating it if new.

    Resolution order:

    1. **Passphrase** (if given): derived via Argon2id/PBKDF2 with a *random,
       per-install salt* persisted in ``data_dir/kdf.json`` — the same
       passphrase unlocks the same store next launch, and no two installs share
       a salt. (A fixed salt would let one precomputed table attack every
       BastionBox install; that is why none is hardcoded anywhere.)
    2. **DPAPI machine key** (Windows, no passphrase): a random 32-byte key is
       generated once, wrapped with the current user's DPAPI key, and stored as
       ``data_dir/store.key.dpapi``. The store is then unreadable off this
       machine/account without the user memorizing anything.
    3. **None** — no encryption provider or no key source. The caller must
       surface this honestly (the Security panel shows UNSEALED); we never
       pretend.

    The KDF parameter file and the DPAPI blob are not secrets themselves: the
    salt is public by design, and the DPAPI blob is useless off this account.
    """
    if not encryption_available():
        return None
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    if passphrase:
        params_path = data_dir / "kdf.json"
        if params_path.exists():
            params = KdfParams.from_public(
                json.loads(params_path.read_text(encoding="utf-8")))
        else:
            params = new_kdf_params()
            params_path.write_text(json.dumps(params.to_public(), indent=2),
                                   encoding="utf-8")
        try:
            return derive_key(passphrase, params)
        except EncryptionUnavailable:
            return None

    if _IS_WINDOWS:
        key_path = data_dir / "store.key.dpapi"
        if key_path.exists():
            try:
                key = dpapi_unprotect(key_path.read_bytes())
                return key if len(key) == 32 else None
            except OSError:
                return None  # wrong user/machine — fail closed to UNSEALED
        key = secrets.token_bytes(32)
        key_path.write_bytes(dpapi_protect(key))
        return key

    return None
