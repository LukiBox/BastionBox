"""Crypto/store suite — key derivation is stable and AES round-trips are lossless.

Tests that require the optional ``cryptography``/``argon2`` packages skip cleanly
when they are absent, so the suite is green on a bare interpreter while still
exercising real encryption wherever the packages exist.
"""
from __future__ import annotations

import sys

import pytest

from bastion.core.security import crypto


def test_derive_key_is_deterministic():
    params = crypto.KdfParams(algo="pbkdf2-sha256", salt=b"0123456789abcdef",
                              iterations=50_000)
    k1 = crypto.derive_key("correct horse battery staple", params)
    k2 = crypto.derive_key("correct horse battery staple", params)
    assert k1 == k2 and len(k1) == 32


def test_derive_key_differs_by_passphrase_and_salt():
    p1 = crypto.KdfParams(algo="pbkdf2-sha256", salt=b"0" * 16, iterations=50_000)
    p2 = crypto.KdfParams(algo="pbkdf2-sha256", salt=b"1" * 16, iterations=50_000)
    assert crypto.derive_key("pw", p1) != crypto.derive_key("pw", p2)   # salt matters
    assert crypto.derive_key("pw-a", p1) != crypto.derive_key("pw-b", p1)  # pw matters


def test_kdf_params_public_roundtrip():
    p = crypto.new_kdf_params()
    back = crypto.KdfParams.from_public(p.to_public())
    assert back.salt == p.salt and back.algo == p.algo


@pytest.mark.skipif(not crypto.encryption_available(),
                    reason="cryptography package not installed")
def test_aes_gcm_roundtrip():
    key = crypto.derive_key(
        "pw", crypto.KdfParams("pbkdf2-sha256", b"salt-salt-salt16", 50_000))
    c = crypto.Cipher(key)
    blob = c.encrypt(b"classified conversation text", aad=b"workspace:secret")
    assert c.decrypt(blob, aad=b"workspace:secret") == b"classified conversation text"


@pytest.mark.skipif(not crypto.encryption_available(),
                    reason="cryptography package not installed")
def test_aes_gcm_detects_tampering():
    key = crypto.derive_key(
        "pw", crypto.KdfParams("pbkdf2-sha256", b"salt-salt-salt16", 50_000))
    c = crypto.Cipher(key)
    blob = bytearray(c.encrypt(b"secret"))
    blob[-1] ^= 0x01  # flip a bit in the GCM tag
    with pytest.raises(Exception):
        c.decrypt(bytes(blob))


@pytest.mark.skipif(not crypto.encryption_available(),
                    reason="cryptography package not installed")
def test_aes_gcm_aad_binding():
    key = crypto.derive_key(
        "pw", crypto.KdfParams("pbkdf2-sha256", b"salt-salt-salt16", 50_000))
    c = crypto.Cipher(key)
    blob = c.encrypt(b"secret", aad=b"workspace:A")
    with pytest.raises(Exception):
        c.decrypt(blob, aad=b"workspace:B")  # wrong scope must fail


def test_bad_key_length_rejected():
    if not crypto.encryption_available():
        pytest.skip("cryptography package not installed")
    with pytest.raises(ValueError):
        crypto.Cipher(b"too-short")


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_dpapi_roundtrip():
    blob = crypto.dpapi_protect(b"machine-bound secret")
    assert blob != b"machine-bound secret"
    assert crypto.dpapi_unprotect(blob) == b"machine-bound secret"


@pytest.mark.skipif(not crypto.encryption_available(),
                    reason="cryptography package not installed")
def test_store_key_passphrase_is_stable_per_install(tmp_path):
    """Same passphrase + same install → same key; the salt is random but persisted."""
    k1 = crypto.load_or_create_store_key(tmp_path, "hunter2")
    k2 = crypto.load_or_create_store_key(tmp_path, "hunter2")
    assert k1 == k2 and len(k1) == 32
    assert crypto.load_or_create_store_key(tmp_path, "different") != k1
    # A fresh install (different salt) must derive a different key.
    other = tmp_path / "other"
    assert crypto.load_or_create_store_key(other, "hunter2") != k1
    # And no hardcoded salt anywhere: the persisted params carry a random one.
    import json
    salt = json.loads((tmp_path / "kdf.json").read_text())["salt"]
    assert salt != json.loads((other / "kdf.json").read_text())["salt"]


@pytest.mark.skipif(sys.platform != "win32" or not crypto.encryption_available(),
                    reason="DPAPI default key is Windows-only")
def test_store_key_dpapi_default_is_stable(tmp_path):
    """No passphrase on Windows → a DPAPI-wrapped random key, stable across opens."""
    k1 = crypto.load_or_create_store_key(tmp_path, None)
    k2 = crypto.load_or_create_store_key(tmp_path, None)
    assert k1 is not None and k1 == k2 and len(k1) == 32
    # The on-disk blob is wrapped, not the raw key.
    assert (tmp_path / "store.key.dpapi").read_bytes() != k1
