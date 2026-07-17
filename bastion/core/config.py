"""Central configuration for BastionBox — one screen to understand the whole app.

Every tunable lives here and almost all of it can be overridden with a
``BASTION_*`` environment variable, so an operator can retune the app for a
different machine, model, or security posture *without editing code* — which
matters on locked-down, air-gapped sites where editing source may be controlled.

Security-relevant defaults are chosen to fail *safe*: encryption on, offline
guard armed, workspaces mounted "ask before every write". Loosening any of them
is a deliberate, visible choice (an env var or a toggle in the UI), never an
accident of a missing setting.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Identity & data home
# ---------------------------------------------------------------------------
APP_NAME = "BastionBox"
APP_TAGLINE = "The AI that never phones home."
VERSION = "0.1.0"

HOME = Path.home()
#: All persistent state (encrypted stores, audit log, model registry, indexes)
#: lives under one root so "where is my data?" has a single, auditable answer.
DATA_DIR = Path(os.environ.get("BASTION_DATA_DIR", str(HOME / ".bastionbox")))
MODELS_DIR = Path(os.environ.get("BASTION_MODELS_DIR", str(DATA_DIR / "models")))
AUDIT_PATH = Path(os.environ.get("BASTION_AUDIT_PATH", str(DATA_DIR / "audit.jsonl")))
STORE_PATH = Path(os.environ.get("BASTION_STORE_PATH", str(DATA_DIR / "store.db")))


# ---------------------------------------------------------------------------
# Build flavor — is this the Air-Gap build?
# ---------------------------------------------------------------------------
# In the Air-Gap PyInstaller flavor the model downloader and every networking
# convenience is *compiled out*; the capability is absent, not merely disabled.
# At dev time the flag is env-driven so the same tree can be exercised both ways.
AIR_GAP_BUILD = _env_bool("BASTION_AIR_GAP", False)

# Whether the in-process network guard permits a loopback Ollama connection.
# Forced off in Air-Gap builds — even the local door is welded shut there.
ALLOW_LOOPBACK_OLLAMA = (not AIR_GAP_BUILD) and _env_bool(
    "BASTION_ALLOW_OLLAMA", True)


# ---------------------------------------------------------------------------
# Inference engine
# ---------------------------------------------------------------------------
# "llama" (embedded llama.cpp, the air-gap-capable primary) or "ollama".
ENGINE_BACKEND = os.environ.get("BASTION_ENGINE", "llama").lower()
OLLAMA_HOST = os.environ.get("BASTION_OLLAMA_HOST", "http://127.0.0.1:11434")

# Default generation controls (advanced flyout overrides per conversation).
DEFAULT_TEMPERATURE = _env_float("BASTION_TEMPERATURE", 0.7)
DEFAULT_TOP_P = _env_float("BASTION_TOP_P", 0.95)
DEFAULT_MAX_TOKENS = _env_int("BASTION_MAX_TOKENS", 2048)
DEFAULT_CONTEXT = _env_int("BASTION_CONTEXT", 8192)
# Context window a loaded GGUF is opened with. Bigger than DEFAULT_CONTEXT so a
# whole business document can be read and summarized without overflowing (an 8k
# window is destroyed by nearly any real .docx). Modern local models (Qwen3,
# Llama-3.1) support this comfortably; grouped-query attention keeps the KV
# cache small. Lower it with BASTION_MODEL_CTX on a RAM-constrained machine.
MODEL_CONTEXT = _env_int("BASTION_MODEL_CTX", 16384)

# The inference process is isolated from the UI so a bad GGUF can't crash the app.
INFERENCE_ISOLATED_PROCESS = _env_bool("BASTION_ISOLATED_INFERENCE", True)


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------
AGENT_MAX_ITERATIONS = _env_int("BASTION_AGENT_MAX_ITERS", 12)
# Commands that may run without a per-call approval prompt (exact-match allowlist).
COMMAND_ALLOWLIST = tuple(
    c.strip() for c in os.environ.get(
        "BASTION_CMD_ALLOWLIST", "pytest -q,git status,git diff,ls,dir").split(",")
    if c.strip()
)
COMMAND_TIMEOUT_S = _env_float("BASTION_CMD_TIMEOUT", 60.0)
COMMAND_OUTPUT_CAP = _env_int("BASTION_CMD_OUTPUT_CAP", 100_000)  # bytes


# ---------------------------------------------------------------------------
# Knowledge / RAG index
# ---------------------------------------------------------------------------
EMBEDDING_MODEL = os.environ.get("BASTION_EMBED_MODEL", "nomic-embed-text")
INDEX_CHUNK_MAX_TOKENS = _env_int("BASTION_CHUNK_TOKENS", 512)
INDEX_TOP_K = _env_int("BASTION_TOP_K", 6)
INDEX_RESPECT_GITIGNORE = _env_bool("BASTION_RESPECT_GITIGNORE", True)
# Grounded mode: answer strictly from retrieved passages or say "not found".
GROUNDED_MODE_DEFAULT = _env_bool("BASTION_GROUNDED", False)


# ---------------------------------------------------------------------------
# Security posture
# ---------------------------------------------------------------------------
NETGUARD_ENABLED = _env_bool("BASTION_NETGUARD", True)
ENCRYPT_AT_REST = _env_bool("BASTION_ENCRYPT", True)
AUDIT_ENABLED = _env_bool("BASTION_AUDIT", True)
# If a passphrase env var is present we derive the store key from it; otherwise
# the app either prompts, or falls back to a DPAPI machine key on Windows.
STORE_PASSPHRASE_ENV = "BASTION_PASSPHRASE"


# ---------------------------------------------------------------------------
# UI / appearance / language
# ---------------------------------------------------------------------------
THEME_DEFAULT = os.environ.get("BASTION_THEME", "dark")   # "dark" or "light"
LANGUAGE_DEFAULT = os.environ.get("BASTION_LANG", "en")   # "en" or "pl"
REDUCED_MOTION = _env_bool("BASTION_REDUCED_MOTION", False)
GLOBAL_HOTKEY = os.environ.get("BASTION_HOTKEY", "ctrl+space,ctrl+space")


@dataclass
class RuntimeConfig:
    """A snapshot of live settings the UI can mutate and persist per session.

    The module-level constants above are *defaults*; this object is what the
    running app reads and writes so a user's in-app changes take effect without
    a restart and can be saved to the encrypted store.
    """

    theme: str = THEME_DEFAULT
    language: str = LANGUAGE_DEFAULT
    reduced_motion: bool = REDUCED_MOTION
    engine_backend: str = ENGINE_BACKEND
    temperature: float = DEFAULT_TEMPERATURE
    top_p: float = DEFAULT_TOP_P
    max_tokens: int = DEFAULT_MAX_TOKENS
    context_window: int = DEFAULT_CONTEXT
    grounded_mode: bool = GROUNDED_MODE_DEFAULT
    netguard_enabled: bool = NETGUARD_ENABLED
    encrypt_at_rest: bool = ENCRYPT_AT_REST
    audit_enabled: bool = AUDIT_ENABLED
    air_gap: bool = AIR_GAP_BUILD
    command_allowlist: tuple[str, ...] = COMMAND_ALLOWLIST
    agent_max_iterations: int = AGENT_MAX_ITERATIONS
    extra: dict = field(default_factory=dict)


def ensure_data_dirs() -> None:
    """Create the data home and subfolders on first run (idempotent)."""
    for p in (DATA_DIR, MODELS_DIR, AUDIT_PATH.parent, STORE_PATH.parent):
        p.mkdir(parents=True, exist_ok=True)


def store_passphrase() -> str | None:
    """The store passphrase from the environment, if the operator set one."""
    return os.environ.get(STORE_PASSPHRASE_ENV) or None


def resource_path(*parts: str) -> Path:
    """Locate a bundled resource in both source and PyInstaller-frozen runs.

    Under a frozen build PyInstaller unpacks data to ``sys._MEIPASS``; in a source
    checkout the resources live at ``bastion/resources``. This resolves either so
    the app finds its fonts and stylesheets whether run from source or the .exe.
    """
    import sys
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "bastion" / "resources" / Path(*parts)
    return Path(__file__).resolve().parent.parent / "resources" / Path(*parts)
