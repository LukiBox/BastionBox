"""Embedded llama.cpp backend — the air-gap-capable primary path.

Loads any GGUF straight off disk via ``llama-cpp-python``. This is the backend
that makes true air-gap possible: no server, no download, the model is a file.

``llama-cpp-python`` is an *optional* dependency: importing this module never
requires it. The import is deferred to :meth:`load`, so the app starts, the UI
renders, and the FakeEngine works even on a machine where llama.cpp was never
installed — the user gets a clear, actionable message instead of an ImportError
traceback at startup.
"""
from __future__ import annotations

from typing import Iterator, Sequence

from .engine import (Capability, Engine, GenerationConfig, Message, ModelInfo)
from .registry import RegisteredModel


class LlamaBackend(Engine):
    """A GGUF loaded in-process (or, ideally, in the isolated inference process).

    Parameters map onto the offload plan from the Hardware Optimizer: ``n_gpu_layers``
    and ``n_ctx`` come straight from :class:`~bastion.core.llm.hardware.OffloadPlan`.
    """

    def __init__(self, model: RegisteredModel, *, n_ctx: int = 8192,
                 n_gpu_layers: int = 0, n_batch: int = 256, n_threads: int | None = None):
        self.model = model
        self.n_ctx = n_ctx
        self.n_gpu_layers = n_gpu_layers
        self.n_batch = n_batch
        self.n_threads = n_threads
        self._llm = None
        self._cancel = False

    def load(self) -> ModelInfo:
        try:
            from llama_cpp import Llama  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "The embedded llama.cpp backend needs 'llama-cpp-python'. Install "
                "it (pip install llama-cpp-python) or switch the engine to Ollama "
                "in Settings. On air-gapped sites, install the prebuilt wheel from "
                "your offline mirror.") from exc
        self._llm = Llama(
            model_path=self.model.path,
            n_ctx=self.n_ctx,
            n_gpu_layers=self.n_gpu_layers,
            n_batch=self.n_batch,
            n_threads=self.n_threads,
            embedding=self.model.is_embedding,
            verbose=False,
        )
        self.info = ModelInfo(
            name=self.model.name, family=self.model.family,
            context_length=self.n_ctx, quantization=self.model.quantization,
            tool_capable=self.model.tool_capable,
            is_embedding=self.model.is_embedding, path=self.model.path)
        return self.info

    def stream(self, messages: Sequence[Message],
               config: GenerationConfig) -> Iterator[str]:
        if self._llm is None:
            self.load()
        self._cancel = False
        # llama-cpp-python applies the GGUF's own chat template when we pass
        # messages to create_chat_completion — the correct-by-construction path.
        kwargs = dict(
            messages=[m.as_dict() for m in messages],
            temperature=config.temperature, top_p=config.top_p,
            max_tokens=config.max_tokens, stream=True,
            stop=list(config.stop) or None,
        )
        if config.grammar:
            from llama_cpp import LlamaGrammar  # type: ignore
            kwargs["grammar"] = LlamaGrammar.from_string(config.grammar)
        if config.seed is not None:
            kwargs["seed"] = config.seed
        for chunk in self._llm.create_chat_completion(**kwargs):  # type: ignore
            if self._cancel:
                break
            delta = chunk["choices"][0].get("delta", {})
            piece = delta.get("content")
            if piece:
                yield piece

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if self._llm is None:
            self.load()
        out = []
        for t in texts:
            res = self._llm.create_embedding(t)  # type: ignore
            out.append(res["data"][0]["embedding"])
        return out

    def cancel(self) -> None:
        self._cancel = True

    def supports(self, cap: Capability) -> bool:
        base = {Capability.STREAMING, Capability.GRAMMAR}
        if self.model.is_embedding:
            base.add(Capability.EMBEDDING)
        return cap in base

    def unload(self) -> None:
        self._llm = None
