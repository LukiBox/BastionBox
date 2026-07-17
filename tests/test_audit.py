"""Audit-chain suite — the chain verifies, and any single-byte mutation is caught.

Mirrors the acceptance walkthrough: build a log, verify it as valid, then flip a
byte and confirm the verifier fingers the exact entry — plus reordering,
insertion, and mid-file truncation.
"""
from __future__ import annotations

import json

import pytest

from bastion.core.security.audit import AuditLog


@pytest.mark.parametrize("secret", [None, b"unit-test-key"])
def test_chain_valid_after_many_records(tmp_path, secret):
    log = AuditLog(tmp_path / "audit.jsonl", secret=secret)
    for i in range(50):
        log.record("event", i=i, note=f"entry {i}")
    result = log.verify()
    assert result.ok
    assert result.entries == 50
    assert result.first_bad_seq is None


def test_single_byte_mutation_detected(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    for i in range(20):
        log.record("event", i=i)
    lines = path.read_text(encoding="utf-8").splitlines()
    # Corrupt the payload of entry #8 (0-based index 7).
    entry = json.loads(lines[7])
    entry["data"]["i"] = 999
    lines[7] = json.dumps(entry, ensure_ascii=False)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = AuditLog(path).verify()
    assert not result.ok
    assert result.first_bad_seq == 8


def test_reordering_detected(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    for i in range(6):
        log.record("event", i=i)
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[2], lines[3] = lines[3], lines[2]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert not AuditLog(path).verify().ok


def test_mid_file_truncation_detected(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    for i in range(10):
        log.record("event", i=i)
    lines = path.read_text(encoding="utf-8").splitlines()
    del lines[4]  # remove a middle entry -> seq/prev break
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = AuditLog(path).verify()
    assert not result.ok


def test_forged_entry_without_key_still_breaks_hmac_chain(tmp_path):
    """With a keyed (HMAC) chain, recomputing plain hashes cannot forge entries."""
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path, secret=b"k")
    for i in range(5):
        log.record("event", i=i)
    lines = path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[2])
    entry["data"]["i"] = 42
    # Attacker recomputes a *plain* sha256 chain hash (no key) — will not match.
    import hashlib
    body = json.dumps({k: entry[k] for k in ("seq", "ts", "kind", "prev", "data")},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    entry["hash"] = hashlib.sha256(entry["prev"].encode() + body.encode()).hexdigest()
    lines[2] = json.dumps(entry, ensure_ascii=False)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert not AuditLog(path, secret=b"k").verify().ok


def test_reopened_log_continues_chain(tmp_path):
    path = tmp_path / "audit.jsonl"
    AuditLog(path).record("event", i=0)
    AuditLog(path).record("event", i=1)  # reopened instance
    result = AuditLog(path).verify()
    assert result.ok and result.entries == 2


def test_convenience_recorders(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    log.log_prompt("conv1", "what is the capital of France?")
    log.log_tool_call("read_file", {"path": "src/a.py"})
    log.log_file_write("src/a.py", 120, "deadbeef")
    log.log_command("pytest -q", "/ws", 0)
    log.log_decision("write src/a.py", approved=True, actor="user")
    log.log_network_block("example.com", 443, "connect")
    result = log.verify()
    assert result.ok and result.entries == 6
    # Prompt plaintext is never stored — only its fingerprint.
    raw = (tmp_path / "a.jsonl").read_text(encoding="utf-8")
    assert "capital of France" not in raw
    assert "prompt_sha256" in raw
