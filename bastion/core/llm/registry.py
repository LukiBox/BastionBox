"""Model registry — import GGUFs by sneakernet, verify their hash, remember them.

On an air-gapped site models arrive on a USB stick, not from a download. Supply-
chain hygiene therefore matters: before BastionBox will register a model it can
verify the file's SHA-256 against a hash the operator supplies out-of-band, so a
swapped or corrupted GGUF is caught at import, green-check or red-flag, rather
than discovered at inference time.

The registry itself is a small JSON file (no server, no network) recording each
model's metadata: family, quant, context, whether it is tool-capable, and
whether it is an embedding model. It is intentionally boring and inspectable.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict, field
from pathlib import Path


@dataclass
class RegisteredModel:
    name: str
    path: str
    sha256: str
    family: str = "unknown"
    quantization: str = ""
    context_length: int = 8192
    tool_capable: bool = True
    is_embedding: bool = False
    size_bytes: int = 0
    #: Per-model tuned profile from the Hardware Optimizer benchmark, if run.
    tuned: dict = field(default_factory=dict)

    @property
    def size_gb(self) -> float:
        return round(self.size_bytes / 1024**3, 2)


# Chat-template family is inferred from the filename as a convenience; the user
# can always correct it. We never hardcode a single template for everything —
# using the wrong template is a top cause of "the local model seems dumb".
_FAMILY_HINTS = {
    "llama-3": "llama3", "llama3": "llama3", "meta-llama": "llama3",
    "qwen2": "qwen", "qwen3": "qwen", "qwen": "qwen",
    "mistral": "mistral", "mixtral": "mistral",
    "phi-3": "phi3", "phi3": "phi3", "gemma": "gemma",
    "nomic-embed": "embed", "bge": "embed", "e5": "embed",
}
_QUANT_HINTS = ("Q2_K", "Q3_K", "Q4_K_M", "Q4_K_S", "Q4_0", "Q5_K_M", "Q5_0",
                "Q6_K", "Q8_0", "F16", "BF16")


def infer_family(filename: str) -> str:
    low = filename.lower()
    for needle, fam in _FAMILY_HINTS.items():
        if needle in low:
            return fam
    return "unknown"


def infer_quant(filename: str) -> str:
    up = filename.upper()
    for q in _QUANT_HINTS:
        if q in up:
            return q
    return ""


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    """Streaming SHA-256 so hashing a multi-GB GGUF never loads it into RAM."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


@dataclass
class VerifyResult:
    ok: bool
    computed: str
    expected: str | None
    message: str


class ModelRegistry:
    def __init__(self, registry_path: Path):
        self.path = Path(registry_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.models: dict[str, RegisteredModel] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.models = {m["name"]: RegisteredModel(**m)
                           for m in data.get("models", [])}

    def _save(self) -> None:
        self.path.write_text(
            json.dumps({"models": [asdict(m) for m in self.models.values()]},
                       indent=2),
            encoding="utf-8")

    def verify(self, gguf_path: str | Path,
               expected_sha256: str | None) -> VerifyResult:
        """Hash the file and compare to *expected_sha256* (case-insensitive).

        If no expected hash is supplied we still compute and record one so the
        model can be re-verified later against this first-seen baseline.
        """
        p = Path(gguf_path)
        if not p.is_file():
            return VerifyResult(False, "", expected_sha256, f"not a file: {p}")
        computed = sha256_file(p)
        if expected_sha256:
            ok = computed.lower() == expected_sha256.strip().lower()
            return VerifyResult(
                ok, computed, expected_sha256,
                "SHA-256 verified" if ok else
                "HASH MISMATCH — do not load this model")
        return VerifyResult(True, computed, None,
                            "no expected hash provided; recorded first-seen hash")

    def register(self, gguf_path: str | Path, *, name: str | None = None,
                 expected_sha256: str | None = None,
                 context_length: int = 8192,
                 is_embedding: bool = False) -> tuple[RegisteredModel, VerifyResult]:
        """Verify and add a model. Raises on hash mismatch — fail closed."""
        p = Path(gguf_path)
        result = self.verify(p, expected_sha256)
        if not result.ok:
            raise ValueError(result.message)
        fam = infer_family(p.name)
        model = RegisteredModel(
            name=name or p.stem, path=str(p), sha256=result.computed,
            family=fam, quantization=infer_quant(p.name),
            context_length=context_length,
            tool_capable=fam not in {"embed"},
            is_embedding=is_embedding or fam == "embed",
            size_bytes=p.stat().st_size)
        self.models[model.name] = model
        self._save()
        return model, result

    def remove(self, name: str) -> None:
        if self.models.pop(name, None) is not None:
            self._save()

    def get(self, name: str) -> RegisteredModel | None:
        return self.models.get(name)

    def list_chat_models(self) -> list[RegisteredModel]:
        return [m for m in self.models.values() if not m.is_embedding]

    def list_embedding_models(self) -> list[RegisteredModel]:
        return [m for m in self.models.values() if m.is_embedding]
