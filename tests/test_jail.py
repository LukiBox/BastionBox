"""Path-jail escape suite — these tests gate the milestone; if they fail, ship nothing.

Each test encodes one attack from the threat model in
:mod:`bastion.core.security.jail`. A green run is the technical claim that a weak
or compromised model cannot reach a byte outside a mounted workspace.
"""
from __future__ import annotations

import os
import sys

import pytest

from bastion.core.security.jail import JailViolation, PathJail, Permission


@pytest.fixture()
def jail(tmp_path):
    """A jail with a single mounted workspace plus a sibling 'outside' folder."""
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()
    (ws_dir / "src").mkdir()
    (ws_dir / "src" / "auth.py").write_text("token = 1\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("classified\n", encoding="utf-8")
    j = PathJail()
    ws = j.mount(ws_dir, Permission.ASK, label="Workspace")
    return j, ws, ws_dir, outside


def test_relative_inside_resolves(jail):
    j, ws, ws_dir, _ = jail
    real = j.resolve("src/auth.py", ws, must_exist=True)
    assert real == (ws_dir / "src" / "auth.py").resolve()


def test_mixed_separators_stay_contained(jail):
    j, ws, ws_dir, _ = jail
    real = j.resolve("src\\auth.py" if sys.platform != "win32" else "src/auth.py", ws)
    assert j._within(real, ws.root)


def test_new_file_inside_is_allowed(jail):
    j, ws, ws_dir, _ = jail
    real = j.resolve("src/new_file.py", ws, must_exist=False)
    assert real.parent == (ws_dir / "src").resolve()


def test_dotdot_traversal_rejected(jail):
    j, ws, _, _ = jail
    with pytest.raises(JailViolation):
        j.resolve("../outside/secret.txt", ws)
    with pytest.raises(JailViolation):
        j.resolve("src/../../outside/secret.txt", ws)


def test_absolute_outside_rejected(jail):
    j, ws, _, outside = jail
    with pytest.raises(JailViolation):
        j.resolve(str(outside / "secret.txt"), ws)


def test_absolute_inside_allowed(jail):
    j, ws, ws_dir, _ = jail
    real = j.resolve(str(ws_dir / "src" / "auth.py"), ws)
    assert j._within(real, ws.root)


def test_nul_byte_rejected(jail):
    j, ws, _, _ = jail
    with pytest.raises(JailViolation):
        j.resolve("src/auth\x00.py", ws)


def test_empty_path_rejected(jail):
    j, ws, _, _ = jail
    with pytest.raises(JailViolation):
        j.resolve("   ", ws)


def test_unc_path_rejected(jail):
    j, ws, _, _ = jail
    with pytest.raises(JailViolation):
        j.resolve(r"\\server\share\file", ws)
    with pytest.raises(JailViolation):
        j.resolve("//server/share/file", ws)


def test_device_namespace_paths_rejected(jail):
    j, ws, _, _ = jail
    for bad in (r"\\?\C:\Windows\System32", r"\\.\PhysicalDrive0"):
        with pytest.raises(JailViolation):
            j.resolve(bad, ws)


@pytest.mark.skipif(sys.platform != "win32", reason="drive-relative is Windows-only")
def test_drive_relative_rejected(jail):
    j, ws, _, _ = jail
    with pytest.raises(JailViolation):
        j.resolve("C:secret", ws)


def test_unmounted_workspace_rejected(tmp_path):
    j = PathJail()
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    ws = j.mount(ws_dir)
    j.unmount(ws)
    with pytest.raises(JailViolation):
        j.resolve("anything", ws)


def test_symlink_escape_rejected(jail):
    """A symlink *inside* the workspace pointing *outside* must not be a door.

    resolve() follows the link to its real target, which lands outside the root,
    so containment fails. Skips cleanly where symlink creation needs privilege.
    """
    j, ws, ws_dir, outside = jail
    link = ws_dir / "escape_link"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted in this environment")
    with pytest.raises(JailViolation):
        j.resolve("escape_link/secret.txt", ws)


def test_resolve_any_finds_containing_workspace(tmp_path):
    a = tmp_path / "a"; a.mkdir(); (a / "f.txt").write_text("x")
    b = tmp_path / "b"; b.mkdir()
    j = PathJail()
    j.mount(a); j.mount(b)
    real, ws = j.resolve_any(str(a / "f.txt"))
    assert ws.root == a.resolve()
    with pytest.raises(JailViolation):
        j.resolve_any(str(tmp_path / "elsewhere.txt"))
