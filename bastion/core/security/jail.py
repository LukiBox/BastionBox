"""The path jail — the single chokepoint for every filesystem access.

This module is a *load-bearing wall*, not a convenience helper. Every file the
agent reads, writes, lists, or executes is first resolved through :class:`PathJail`.
There is deliberately **no second file API** in BastionBox: if a code path touches
disk without going through the jail, that is a bug to be fixed, not a shortcut.

Threat model (Windows-first, Linux-friendly)
--------------------------------------------
A weak local model — or a compromised dependency, or a malicious document that
tricks the model into emitting a path — must **never** be able to reach a byte
outside a mounted workspace. The jail defends against every escape we know:

* ``..`` traversal (lexical and post-symlink)                       → rejected
* absolute paths pointing outside every mounted root                → rejected
* symlinks / directory junctions that resolve outside a root        → rejected
* UNC network paths (``\\\\server\\share``)                         → rejected
* Win32 device / namespace paths (``\\\\?\\``, ``\\\\.\\``)         → rejected
* drive-relative paths (``C:foo`` with no separator)                → rejected
* mixed / duplicated separators, trailing dots/spaces               → normalized
* embedded NUL bytes                                                → rejected
* 8.3 short names that alias a long path outside a root             → resolved

The canonicalization strategy is *resolve-then-contain*: we canonicalize with
:func:`os.path.realpath` (which follows symlinks and junctions to their real
target) and then require the real path to sit inside a mounted root. Because
resolution happens **before** the containment check, a symlink inside a
workspace that points out of it lands outside a root and is rejected — the
attacker cannot smuggle an escape past us by hiding it behind a reparse point.

The jail never touches the network, never logs on its own (callers own the audit
trail, see :mod:`bastion.core.security.audit`), and raises :class:`JailViolation`
on any breach so the agent loop can turn the rejection into an observation.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PureWindowsPath

__all__ = ["Permission", "Workspace", "PathJail", "JailViolation"]

_IS_WINDOWS = sys.platform == "win32"


class JailViolation(PermissionError):
    """Raised when a path escapes — or tries to escape — the mounted workspaces.

    Subclasses :class:`PermissionError` so that a caller which forgets to handle
    it still fails *closed* (an unhandled permission error aborts the operation)
    rather than failing open. The message is safe to surface to the model as an
    observation; it names the offending path but never leaks a resolved system
    path outside the jail.
    """


class Permission(str, Enum):
    """How much the agent may do inside a given workspace.

    Ordered from least to most trusting. The tier is enforced at the tool layer
    (see :mod:`bastion.core.agent.permissions`); the jail itself only answers the
    prior question — *is this path even inside the workspace at all?*
    """

    READ_ONLY = "read_only"          # agent may read, never write or execute
    ASK = "ask"                      # default: every write/edit needs approval
    AUTO_WRITE = "auto_write"        # session-scoped auto-approve (loud indicator)


@dataclass(frozen=True)
class Workspace:
    """A user-mounted folder, plus the permission tier the agent has inside it.

    ``root`` is stored already canonicalized (real, absolute). Two workspaces
    never share chats, index, or audit scope — need-to-know by construction — so
    a stable ``key`` derived from the real path identifies the workspace across
    the store, the index, and the audit log.
    """

    root: Path
    permission: Permission = Permission.ASK
    label: str = ""

    @property
    def key(self) -> str:
        """Stable, case-folded identifier for scoping store/index/audit rows."""
        return os.path.normcase(str(self.root))

    @property
    def display_name(self) -> str:
        return self.label or self.root.name or str(self.root)


def _has_forbidden_prefix(raw: str) -> str | None:
    """Return a reason string if *raw* uses a forbidden Win32 namespace prefix.

    We reject these *before* resolution because they are never legitimate inside
    a user workspace and some of them (``\\\\.\\PhysicalDrive0``) name raw
    devices that must never be reachable from an AI tool call.
    """
    s = raw.replace("/", "\\")
    if s.startswith("\\\\?\\") or s.startswith("\\\\.\\"):
        return "Win32 device/namespace path (\\\\?\\ or \\\\.\\) is not permitted"
    # A leading double-backslash that is *not* a device prefix is a UNC path.
    if s.startswith("\\\\"):
        return "UNC network path (\\\\server\\share) is not permitted"
    return None


def _is_drive_relative(raw: str) -> bool:
    """True for Windows drive-relative paths like ``C:foo`` (drive, no separator).

    These are anchored to the *current directory of that drive*, which is process
    state an attacker could influence, so we refuse to guess and reject outright.
    """
    if not _IS_WINDOWS:
        return False
    p = PureWindowsPath(raw)
    # drive present ("C:") but the path is not absolute ("C:\\...") and not a bare
    # drive root — i.e. there is a relative remainder glued to the drive letter.
    return bool(p.drive) and not raw[2:3] in ("\\", "/") and len(raw) > 2


@dataclass
class PathJail:
    """Holds the mounted workspaces and canonicalizes every path against them.

    Typical use::

        jail = PathJail()
        ws = jail.mount("D:/secret-codebase", Permission.ASK, label="Secret")
        real = jail.resolve("src/auth.py", ws)     # -> D:/secret-codebase/src/auth.py
        jail.resolve("../../Windows/System32", ws) # -> raises JailViolation

    The jail is intentionally tiny and dependency-free so it can be audited by
    reading one screen of code.
    """

    workspaces: dict[str, Workspace] = field(default_factory=dict)

    # -- mounting -----------------------------------------------------------
    def mount(
        self,
        root: str | os.PathLike[str],
        permission: Permission = Permission.ASK,
        label: str = "",
    ) -> Workspace:
        """Mount *root* as a workspace and return the canonical :class:`Workspace`.

        The root itself must exist and be a directory; we canonicalize it so that
        later containment checks compare real path against real path.
        """
        reason = _has_forbidden_prefix(str(root))
        if reason:
            raise JailViolation(f"Cannot mount {root!r}: {reason}")
        real = Path(os.path.realpath(str(root)))
        if not real.is_dir():
            raise JailViolation(f"Cannot mount {root!r}: not an existing directory")
        ws = Workspace(root=real, permission=permission, label=label)
        self.workspaces[ws.key] = ws
        return ws

    def unmount(self, ws: Workspace) -> None:
        self.workspaces.pop(ws.key, None)

    def is_mounted(self, ws: Workspace) -> bool:
        return ws.key in self.workspaces

    # -- the chokepoint -----------------------------------------------------
    def resolve(
        self,
        candidate: str | os.PathLike[str],
        workspace: Workspace,
        *,
        must_exist: bool = False,
    ) -> Path:
        """Canonicalize *candidate* and prove it lives inside *workspace*.

        *candidate* may be workspace-relative (the common case for tool calls) or
        absolute. Whatever it is, the returned path is real, absolute, and
        guaranteed to be contained in the workspace root. Any failure raises
        :class:`JailViolation`; the operation must not proceed on a raised jail.
        """
        if workspace.key not in self.workspaces:
            raise JailViolation(f"Workspace {workspace.display_name!r} is not mounted")

        raw = os.fspath(candidate)
        if "\x00" in raw:
            raise JailViolation("Path contains an embedded NUL byte")
        if not raw.strip():
            raise JailViolation("Empty path")

        reason = _has_forbidden_prefix(raw)
        if reason:
            raise JailViolation(f"Rejected path {raw!r}: {reason}")
        if _is_drive_relative(raw):
            raise JailViolation(
                f"Rejected drive-relative path {raw!r}: use an absolute or "
                f"workspace-relative path"
            )

        # Anchor relative paths to the workspace root; leave absolutes as given.
        base = Path(raw)
        joined = base if base.is_absolute() else (workspace.root / base)

        # Canonicalize: realpath follows every symlink/junction to its true
        # target and collapses ``..`` — this is what defeats reparse-point escapes.
        real = Path(os.path.realpath(str(joined)))

        if not self._within(real, workspace.root):
            raise JailViolation(
                f"Path {raw!r} resolves to {real} which is outside workspace "
                f"{workspace.display_name!r}"
            )

        if must_exist and not real.exists():
            raise JailViolation(f"Path {raw!r} does not exist")
        return real

    def resolve_any(
        self, candidate: str | os.PathLike[str], *, must_exist: bool = False
    ) -> tuple[Path, Workspace]:
        """Resolve *candidate* against *whichever* mounted workspace contains it.

        Used by tools that receive an absolute path without an explicit workspace
        (e.g. a citation click). Tries each mount; the first that contains the
        path wins. Raises if no workspace contains it.
        """
        last: JailViolation | None = None
        for ws in self.workspaces.values():
            try:
                return self.resolve(candidate, ws, must_exist=must_exist), ws
            except JailViolation as exc:  # keep trying other mounts
                last = exc
        raise JailViolation(
            f"Path {os.fspath(candidate)!r} is not inside any mounted workspace"
        ) from last

    @staticmethod
    def _within(path: Path, root: Path) -> bool:
        """True iff *path* is *root* itself or a descendant, case-insensitively.

        ``Path.is_relative_to`` uses the platform path flavour, so on Windows the
        comparison is correctly case-insensitive (``D:\\Secret`` contains
        ``d:\\secret\\x``). We normalize both to realpaths before calling.
        """
        try:
            return path == root or path.is_relative_to(root)
        except ValueError:
            # Different drives on Windows raise ValueError from is_relative_to.
            return False
