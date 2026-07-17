"""Offline-guard suite — proves a real outbound socket attempt is blocked & audited.

We install a private :class:`NetworkGuard` (never the module-global one, so tests
stay isolated), attempt genuine network calls through the standard library, and
assert they fail closed and increment the blocked counter — the number the
Security panel promises reads 0 forever.
"""
from __future__ import annotations

import socket

import pytest

from bastion.core.security.netguard import NetworkBlocked, NetworkGuard


@pytest.fixture()
def guard():
    g = NetworkGuard(allow_loopback=True).install()
    try:
        yield g
    finally:
        g.uninstall()


def test_outbound_connect_blocked(guard):
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("example.com", 80), timeout=1)
    assert guard.blocked_count >= 1


def test_raw_socket_connect_blocked(guard):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(NetworkBlocked):
            s.connect(("93.184.216.34", 443))  # a public IP literal
    finally:
        s.close()


def test_dns_resolution_of_public_host_blocked(guard):
    with pytest.raises(NetworkBlocked):
        socket.getaddrinfo("example.com", 443)


def test_udp_sendto_blocked(guard):
    """UDP needs no connect() — sendto must be guarded or it's an open door."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(NetworkBlocked):
            s.sendto(b"exfil", ("8.8.8.8", 53))
    finally:
        s.close()
    assert guard.status()["recent"][0]["api"] == "sendto"


def test_udp_sendto_loopback_allowed(guard):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.sendto(b"ping", ("127.0.0.1", 9))  # fire-and-forget; no listener needed
    finally:
        s.close()


def test_connect_ex_returns_error_not_success(guard):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        rc = s.connect_ex(("example.com", 80))
        assert rc != 0  # non-zero == failed, as if unplugged
    finally:
        s.close()


def test_loopback_allowed_when_permitted(guard):
    """Loopback is *permitted* (for Ollama); it should not be a guard block.

    We connect to a closed loopback port: the OS refuses it, which is a normal
    ConnectionRefusedError — crucially *not* a NetworkBlocked from our guard.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", 1))  # port 1: essentially always closed
    except NetworkBlocked:
        pytest.fail("loopback must not be blocked when allow_loopback=True")
    except OSError:
        pass  # refused/unreachable is the expected, acceptable outcome
    finally:
        s.close()


def test_airgap_blocks_even_loopback():
    g = NetworkGuard(allow_loopback=False).install()
    try:
        with pytest.raises(NetworkBlocked):
            socket.create_connection(("127.0.0.1", 11434), timeout=1)
    finally:
        g.uninstall()


def test_on_block_callback_fires(guard):
    seen = []
    guard.on_block = lambda host, port, api: seen.append((host, port, api))
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("example.com", 80), timeout=1)
    assert seen and seen[0][0] == "example.com"


def test_status_reports_blocks(guard):
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("example.com", 80), timeout=1)
    st = guard.status()
    assert st["installed"] is True
    assert st["blocked_count"] >= 1
    assert st["recent"][0]["host"] == "example.com"
