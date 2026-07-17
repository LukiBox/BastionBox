"""Ollama backend — optional convenience for machines that already run it.

Strictly loopback. On construction we parse the host and **hard-refuse any
non-loopback address**: BastionBox will not be tricked into talking to a remote
"Ollama" that is really an exfiltration endpoint. Combined with the in-process
network guard (which only whitelists loopback), this backend can reach a local
Ollama and nothing else. The Air-Gap build does not ship it at all.
"""
from __future__ import annotations

import ipaddress
from typing import Iterator, Sequence
from urllib.parse import urlparse

from .engine import (Capability, Engine, GenerationConfig, Message, ModelInfo)


def _assert_loopback(host_url: str) -> None:
    parsed = urlparse(host_url)
    host = (parsed.hostname or "").lower()
    if host in {"localhost", "localhost.localdomain"}:
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise ValueError(
        f"Ollama host {host_url!r} is not loopback. BastionBox only permits a "
        f"local Ollama (127.0.0.1 / ::1 / localhost) — never a remote server.")


class OllamaBackend(Engine):
    def __init__(self, model_name: str, host: str = "http://127.0.0.1:11434",
                 keep_alive: str = "30m", n_ctx: int = 16384):
        _assert_loopback(host)
        self.model_name = model_name
        self.host = host
        self.keep_alive = keep_alive
        #: requested context window. Ollama's server default (often 4096) would
        #: silently TRUNCATE our carefully budgeted prompts — we must ask for
        #: the window the agent loop is budgeting against, on every request.
        self.n_ctx = int(n_ctx)
        self._client = None
        self._cancel = False

    def load(self) -> ModelInfo:
        try:
            import ollama  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "The Ollama backend needs the 'ollama' package and a running "
                "local Ollama server. Install it, or use the embedded llama.cpp "
                "backend for a fully self-contained setup.") from exc
        self._client = ollama.Client(host=self.host)
        family = "qwen" if "qwen" in self.model_name.lower() else "unknown"
        self.info = ModelInfo(name=self.model_name, family=family,
                              context_length=self.n_ctx,
                              path=f"ollama://{self.model_name}")
        return self.info

    def stream(self, messages: Sequence[Message],
               config: GenerationConfig) -> Iterator[str]:
        if self._client is None:
            self.load()
        self._cancel = False
        options = {"temperature": config.temperature, "top_p": config.top_p,
                   "num_predict": config.max_tokens, "num_ctx": self.n_ctx}
        if config.seed is not None:
            options["seed"] = config.seed
        # Ollama cannot enforce GBNF, but when the caller asked for a grammar
        # (i.e. structured tool-call output) we at least turn on Ollama's JSON
        # mode so the reply is guaranteed to be a parseable JSON value. The
        # agent loop's defensive parser handles the rest.
        kwargs = {}
        if config.grammar:
            kwargs["format"] = "json"
        for chunk in self._client.chat(  # type: ignore
                model=self.model_name,
                messages=[m.as_dict() for m in messages],
                stream=True, options=options, keep_alive=self.keep_alive,
                **kwargs):
            if self._cancel:
                break
            piece = chunk.get("message", {}).get("content", "")
            if piece:
                yield piece

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if self._client is None:
            self.load()
        out = []
        for t in texts:
            res = self._client.embeddings(model=self.model_name, prompt=t)  # type: ignore
            out.append(res["embedding"])
        return out

    def cancel(self) -> None:
        self._cancel = True

    def supports(self, cap: Capability) -> bool:
        return cap in {Capability.STREAMING, Capability.EMBEDDING}
