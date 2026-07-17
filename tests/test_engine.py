"""Engine / index / store bucket — the non-security invariants from §8.

Chat templates match per family, the grammar names every tool, the hardware
planner never crashes (0 GB → CPU plan), the registry verifies SHA-256 and
refuses a mismatch, and the encrypted store round-trips losslessly and truly
wipes on secure-delete.
"""
from __future__ import annotations

import pytest

from bastion.core.llm import hardware, templates
from bastion.core.llm.engine import Capability, FakeEngine, Message, Role, GenerationConfig
from bastion.core.llm.grammar import tool_call_grammar
from bastion.core.llm.registry import ModelRegistry
from bastion.core.security import crypto
from bastion.core.store.db import Store


# -- engine -----------------------------------------------------------------
def test_fake_engine_streams_and_generates():
    eng = FakeEngine(["hello world from a local model"])
    eng.load()
    chunks = list(eng.stream([Message(Role.USER, "hi")], GenerationConfig()))
    assert "".join(chunks) == "hello world from a local model"
    assert eng.supports(Capability.GRAMMAR)


def test_fake_engine_cancel_stops_stream():
    eng = FakeEngine(["a" * 400])
    out = []
    for i, piece in enumerate(eng.stream([Message(Role.USER, "x")], GenerationConfig())):
        out.append(piece)
        if i == 1:
            eng.cancel()
    assert len("".join(out)) < 400  # aborted early


def test_fake_engine_embeddings_are_stable():
    eng = FakeEngine()
    a = eng.embed(["same text"])[0]
    b = eng.embed(["same text"])[0]
    assert a == b and len(a) == 32


# -- templates --------------------------------------------------------------
@pytest.mark.parametrize("family,needle", [
    ("llama3", "<|start_header_id|>"),
    ("qwen", "<|im_start|>"),
    ("mistral", "[INST]"),
    ("phi3", "<|user|>"),
    ("gemma", "<start_of_turn>"),
])
def test_templates_use_family_delimiters(family, needle):
    msgs = [Message(Role.SYSTEM, "sys"), Message(Role.USER, "hello")]
    rendered = templates.render(msgs, family)
    assert needle in rendered


def test_unknown_family_falls_back_to_chatml():
    rendered = templates.render([Message(Role.USER, "hi")], "does-not-exist")
    assert "<|im_start|>" in rendered  # ChatML fallback, not a crash


# -- grammar ----------------------------------------------------------------
def test_grammar_names_every_tool_and_final():
    g = tool_call_grammar(["read_file", "write_file"])
    assert "read_file" in g and "write_file" in g and "final" in g
    assert "root" in g and "object" in g  # well-formed GBNF skeleton


# -- hardware planner -------------------------------------------------------
def test_plan_cpu_only_when_no_gpu():
    prof = hardware.HardwareProfile(cpu_cores=8, ram_gb=16, vram_gb=0)
    plan = hardware.plan(prof, model_size_gb=4.0, n_layers=32)
    assert plan.cpu_only and plan.gpu_layers == 0
    assert "GB weights" in plan.explain()


def test_plan_full_offload_on_big_gpu():
    prof = hardware.HardwareProfile(cpu_cores=16, ram_gb=64,
                                    vram_gb=24, gpu_name="RTX", gpu_backend="cuda")
    plan = hardware.plan(prof, model_size_gb=8.0, n_layers=48)
    assert plan.gpu_layers > 0 and plan.tier in {"workstation", "server"}


def test_plan_never_crashes_on_zero_everything():
    plan = hardware.plan(hardware.HardwareProfile(), model_size_gb=0.0)
    assert plan.total_layers > 0  # returns a valid plan, not an exception


# -- registry ---------------------------------------------------------------
def test_registry_verifies_and_rejects_mismatch(tmp_path):
    gguf = tmp_path / "qwen2.5-7b-instruct-Q4_K_M.gguf"
    gguf.write_bytes(b"not a real gguf but hashable")
    reg = ModelRegistry(tmp_path / "registry.json")
    from bastion.core.llm.registry import sha256_file
    good = sha256_file(gguf)
    model, result = reg.register(gguf, expected_sha256=good, context_length=4096)
    assert result.ok and model.family == "qwen" and model.quantization == "Q4_K_M"
    with pytest.raises(ValueError):
        reg.register(gguf, expected_sha256="0" * 64)  # wrong hash -> fail closed


# -- encrypted store --------------------------------------------------------
def _cipher():
    key = crypto.derive_key("pw", crypto.KdfParams("pbkdf2-sha256", b"salt" * 4, 50_000))
    return crypto.Cipher(key)


@pytest.mark.skipif(not crypto.encryption_available(), reason="no cryptography")
def test_store_roundtrip_encrypted(tmp_path):
    store = Store(tmp_path / "s.db", cipher=_cipher())
    assert store.encrypted
    cid = store.create_conversation("wsA", "secret chat")
    store.add_message(cid, "user", "where do we validate tokens?")
    store.add_message(cid, "assistant", "in auth/validator.py:112")
    msgs = store.get_messages(cid)
    assert [m["content"] for m in msgs] == [
        "where do we validate tokens?", "in auth/validator.py:112"]
    # Ciphertext on disk must not contain the plaintext.
    raw = (tmp_path / "s.db").read_bytes()
    assert b"validate tokens" not in raw


@pytest.mark.skipif(not crypto.encryption_available(), reason="no cryptography")
def test_secure_delete_wipes_workspace(tmp_path):
    store = Store(tmp_path / "s.db", cipher=_cipher())
    cid = store.create_conversation("wsA", "chat")
    store.add_message(cid, "user", "classified payload string")
    store.set_memory("wsA", "remember: project X")
    removed = store.secure_delete_workspace("wsA")
    assert removed == 1
    assert store.list_conversations("wsA") == []
    assert store.get_memory("wsA") == ""
    raw = (tmp_path / "s.db").read_bytes()
    assert b"classified payload" not in raw  # VACUUM rewrote the freed pages


def test_store_plaintext_mode_is_explicit(tmp_path):
    store = Store(tmp_path / "s.db", cipher=None)
    assert store.encrypted is False
    cid = store.create_conversation("ws", "c")
    store.add_message(cid, "user", "hello")
    assert store.get_messages(cid)[0]["content"] == "hello"
