"""In-process network guard — the technical proof that *nothing leaves the box*.

BastionBox's central promise is that no byte of a user's documents or code ever
reaches the network. Firewall rules and an unplugged cable are good defense in
depth, but they live *outside* the process and cannot be shown inside the app.
This guard lives *inside* the Python process, installs **before any other import
that might open a socket**, and turns every outbound connection attempt into a
hard, audited failure — except an explicit loopback allowance for a local Ollama
server, which itself can be compiled out of the Air-Gap build.

Why in-process
--------------
A sloppy or malicious *dependency* is the realistic leak, not our own code. By
monkeypatching the ``socket`` primitives that every networking library
ultimately funnels through (``connect``, ``connect_ex``, ``create_connection``,
``getaddrinfo`` for name resolution, and the connectionless ``sendto`` /
``sendmsg`` — a UDP datagram needs no ``connect()``, so leaving those unpatched
would be an open exfiltration path), we catch third-party code we never wrote.
AF_UNIX sockets are exempt: they are filesystem-local IPC by definition and
cannot carry a byte off the machine. The guard cannot make the OS airtight — a native extension calling the
Win32 socket API directly bypasses Python — and the docs say so plainly
(:doc:`docs/security`). What it *does* give is a single, observable, always-on
tripwire whose blocked-attempt counter must read **0 forever** in normal use.

The guard is deliberately fail-closed: an unexpected error while deciding
whether to allow a connection blocks the connection.
"""
from __future__ import annotations

import ipaddress
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

__all__ = ["NetworkBlocked", "NetworkGuard", "guard"]


class NetworkBlocked(OSError):
    """Raised (and audited) when outbound network access is blocked.

    Subclasses :class:`OSError` so libraries that expect a socket error handle it
    on their normal error path instead of crashing — the connection simply never
    succeeds, exactly as if the network were unplugged.
    """


@dataclass
class BlockedAttempt:
    """A single blocked connection, kept for the Security panel's live readout."""

    ts: float
    host: str
    port: int | None
    api: str  # which primitive tripped: "connect", "getaddrinfo", ...


def _loopback(host: str | None) -> bool:
    """True if *host* is a loopback literal or a local hostname we permit.

    Only literal loopback IPs and the ``localhost`` names pass. A public hostname
    never passes here — resolving it is itself treated as an attempt to leave.
    """
    if host is None:
        return True  # AF_UNIX / empty address family targets are process-local
    h = host.strip().strip("[]").lower()
    if h in {"", "localhost", "localhost.localdomain", "ip6-localhost"}:
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


@dataclass
class NetworkGuard:
    """Monkeypatches ``socket`` to block every non-loopback connection.

    Install once, at the very top of ``app.py``, before importing anything that
    might touch the network. ``allow_loopback`` gates the single legitimate local
    endpoint (Ollama); the Air-Gap build constructs the guard with it ``False``
    so even that door is welded shut.
    """

    allow_loopback: bool = True
    installed: bool = False
    blocked_count: int = 0
    recent: list[BlockedAttempt] = field(default_factory=list)
    #: called with (host, port, api) on every block; wired to the audit log so a
    #: violation is permanently recorded. Set by the app after the log exists.
    on_block: Callable[[str, int | None, str], None] | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _orig: dict[str, Callable] = field(default_factory=dict, repr=False)

    # -- policy -------------------------------------------------------------
    def _permit(self, host: str | None) -> bool:
        return self.allow_loopback and _loopback(host)

    def _deny(self, host: str, port: int | None, api: str) -> "NetworkBlocked":
        with self._lock:
            self.blocked_count += 1
            self.recent.append(BlockedAttempt(time.time(), host, port, api))
            del self.recent[:-50]  # keep only the last 50 for the UI
        if self.on_block is not None:
            try:
                self.on_block(host, port, api)
            except Exception:  # auditing must never crash the guard
                pass
        return NetworkBlocked(
            f"BastionBox network guard blocked an outbound connection to "
            f"{host}:{port} via {api}(). Nothing leaves this machine."
        )

    # -- install / remove ---------------------------------------------------
    def install(self) -> "NetworkGuard":
        """Patch the socket primitives. Idempotent."""
        if self.installed:
            return self
        self._orig["connect"] = socket.socket.connect
        self._orig["connect_ex"] = socket.socket.connect_ex
        self._orig["sendto"] = socket.socket.sendto
        self._orig["create_connection"] = socket.create_connection
        self._orig["getaddrinfo"] = socket.getaddrinfo
        if hasattr(socket.socket, "sendmsg"):  # not available on Windows
            self._orig["sendmsg"] = socket.socket.sendmsg

        guard = self

        def _addr_host_port(address) -> tuple[str, int | None]:
            if isinstance(address, (tuple, list)) and address:
                host = str(address[0])
                port = address[1] if len(address) > 1 else None
                return host, (int(port) if isinstance(port, int) else None)
            return str(address), None  # AF_UNIX path or opaque

        def _is_unix(sock) -> bool:
            # Filesystem-local IPC; physically cannot leave the machine.
            af_unix = getattr(socket, "AF_UNIX", None)
            return af_unix is not None and sock.family == af_unix

        def connect(self, address):  # type: ignore[no-redef]
            if _is_unix(self):
                return guard._orig["connect"](self, address)
            host, port = _addr_host_port(address)
            if not guard._permit(host):
                raise guard._deny(host, port, "connect")
            return guard._orig["connect"](self, address)

        def connect_ex(self, address):  # type: ignore[no-redef]
            if _is_unix(self):
                return guard._orig["connect_ex"](self, address)
            host, port = _addr_host_port(address)
            if not guard._permit(host):
                # connect_ex returns an errno rather than raising; still audit it.
                guard._deny(host, port, "connect_ex")
                return 13  # EACCES
            return guard._orig["connect_ex"](self, address)

        def sendto(self, data, *args):  # type: ignore[no-redef]
            # sendto(bytes, address) or sendto(bytes, flags, address) — the
            # address is always last. UDP needs no connect(), so this is the
            # primitive a DNS-tunnel-style exfiltration would reach for.
            if _is_unix(self) or not args:
                return guard._orig["sendto"](self, data, *args)
            host, port = _addr_host_port(args[-1])
            if not guard._permit(host):
                raise guard._deny(host, port, "sendto")
            return guard._orig["sendto"](self, data, *args)

        def sendmsg(self, buffers, *args):  # type: ignore[no-redef]
            # sendmsg(buffers[, ancdata[, flags[, address]]]) — address is 4th.
            address = args[2] if len(args) >= 3 else None
            if _is_unix(self) or address is None:
                return guard._orig["sendmsg"](self, buffers, *args)
            host, port = _addr_host_port(address)
            if not guard._permit(host):
                raise guard._deny(host, port, "sendmsg")
            return guard._orig["sendmsg"](self, buffers, *args)

        def create_connection(address, *args, **kwargs):  # type: ignore[no-redef]
            host, port = _addr_host_port(address)
            if not guard._permit(host):
                raise guard._deny(host, port, "create_connection")
            return guard._orig["create_connection"](address, *args, **kwargs)

        def getaddrinfo(host, *args, **kwargs):  # type: ignore[no-redef]
            # Name resolution of a public host is itself a leak signal; block it.
            if not guard._permit(host if isinstance(host, str) else None):
                raise guard._deny(str(host), None, "getaddrinfo")
            return guard._orig["getaddrinfo"](host, *args, **kwargs)

        socket.socket.connect = connect          # type: ignore[assignment]
        socket.socket.connect_ex = connect_ex    # type: ignore[assignment]
        socket.socket.sendto = sendto            # type: ignore[assignment]
        socket.create_connection = create_connection  # type: ignore[assignment]
        socket.getaddrinfo = getaddrinfo         # type: ignore[assignment]
        if "sendmsg" in self._orig:
            socket.socket.sendmsg = sendmsg      # type: ignore[assignment]
        self.installed = True
        return self

    def uninstall(self) -> None:
        """Restore the original socket primitives (used only by the test suite)."""
        if not self.installed:
            return
        socket.socket.connect = self._orig["connect"]              # type: ignore[assignment]
        socket.socket.connect_ex = self._orig["connect_ex"]        # type: ignore[assignment]
        socket.socket.sendto = self._orig["sendto"]                # type: ignore[assignment]
        socket.create_connection = self._orig["create_connection"]  # type: ignore[assignment]
        socket.getaddrinfo = self._orig["getaddrinfo"]            # type: ignore[assignment]
        if "sendmsg" in self._orig:
            socket.socket.sendmsg = self._orig["sendmsg"]          # type: ignore[assignment]
        self.installed = False

    # -- readout for the Security panel ------------------------------------
    def status(self) -> dict:
        with self._lock:
            return {
                "installed": self.installed,
                "allow_loopback": self.allow_loopback,
                "allowed_endpoints": ["127.0.0.0/8", "::1", "localhost"]
                if self.allow_loopback
                else [],
                "blocked_count": self.blocked_count,
                "recent": [
                    {"ts": a.ts, "host": a.host, "port": a.port, "api": a.api}
                    for a in reversed(self.recent)
                ],
            }


#: The process-wide guard. ``app.py`` calls ``guard.install()`` before anything
#: else. Tests construct their own instances to avoid touching global state.
guard = NetworkGuard()
