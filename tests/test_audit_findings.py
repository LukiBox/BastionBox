"""Regression tests for the external technical-audit findings (W1, W3, K1, J1).

Each test pins a confirmed weakness so it cannot silently return:
  * W1 — the fallback grep must not read files that escape the path jail.
  * W3 — verify() must catch truncation of the newest audit entries.
  * K1 — the default command allowlist must be empty (no silent code exec).
  * J1 — an HTML/Office report must still write when the chart engine is absent.
(W2 lives with the rest of the network-guard suite in test_netguard.py.)
"""
from __future__ import annotations

import os

import pytest

from bastion.core.security.audit import AuditLog


# -- W1: fallback grep must honour the jail ----------------------------------

def _make_reparse_dir(target, link):
    """Create a directory reparse point *link* -> *target*, skipping if neither
    a symlink (needs privilege) nor a junction (Windows) can be made."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except (OSError, NotImplementedError, AttributeError):
        pass
    if os.name == "nt":  # a junction needs no elevation on Windows
        import subprocess
        rc = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if rc.returncode == 0 and os.path.exists(link):
            return
    pytest.skip("symlink/junction creation not permitted here")


def _grep_ctx(tmp_path):
    from bastion.core.security.jail import PathJail, Permission
    from bastion.core.tools.base import ToolContext
    from bastion.core.agent.permissions import AutoApproveBroker
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    jail = PathJail()
    ws = jail.mount(ws_dir, Permission.ASK, label="ws")
    audit = AuditLog(tmp_path / "audit.jsonl")
    ctx = ToolContext(jail=jail, workspace=ws, broker=AutoApproveBroker(),
                      audit=audit)
    return ctx, ws_dir


def test_fallback_grep_does_not_leak_across_symlink(tmp_path, monkeypatch):
    """A symlink/junction inside the workspace pointing outside must not let the
    pure-Python grep read the outside file into the model's context (finding W1).
    """
    from bastion.core.tools import fs_tools
    ctx, ws_dir = _grep_ctx(tmp_path)

    outside = tmp_path / "secret"
    outside.mkdir()
    (outside / "classified.txt").write_text("TOP_SECRET_LEAK code=1234\n",
                                             encoding="utf-8")
    (ws_dir / "inside.txt").write_text("INSIDE_SECRET_OK here\n", encoding="utf-8")
    _make_reparse_dir(outside, ws_dir / "leak")

    # Force the pure-Python fallback path (as on an air-gapped box without rg).
    monkeypatch.setattr(fs_tools.shutil, "which", lambda _name: None)
    result = fs_tools.Grep().run(ctx, {"query": "SECRET"})

    assert "INSIDE_SECRET_OK" in result.observation     # in-jail match still found
    assert "TOP_SECRET_LEAK" not in result.observation  # escaped file NOT read
    assert "1234" not in result.observation


# -- W3: audit tail-truncation is detected -----------------------------------

def test_audit_tail_truncation_detected(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    for i in range(5):
        log.record("event", i=i)
    assert log.verify().ok

    # Attacker lops off the two newest entries; the remaining 1..3 chain is
    # internally valid, so chain-only verification would give a false OK.
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:3]) + "\n", encoding="utf-8")

    result = AuditLog(path).verify()
    assert not result.ok
    assert "truncat" in result.detail.lower() or "removed" in result.detail.lower()


def test_audit_wholesale_deletion_detected(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    for i in range(4):
        log.record("event", i=i)
    path.unlink()  # delete the log entirely, leave the checkpoint
    result = AuditLog(path).verify()
    assert not result.ok


def test_audit_forged_checkpoint_detected(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path, secret=b"anchor-key")
    for i in range(3):
        log.record("event", i=i)
    # Tamper the checkpoint's count without the key: the MAC no longer matches.
    import json
    cp = json.loads(log.checkpoint_path.read_text(encoding="utf-8"))
    cp["count"] = 99
    log.checkpoint_path.write_text(json.dumps(cp), encoding="utf-8")
    assert not AuditLog(path, secret=b"anchor-key").verify().ok


def test_audit_untampered_log_still_verifies(tmp_path):
    """The anchor must not create false positives on an honest log."""
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path, secret=b"k")
    for i in range(10):
        log.record("event", i=i)
    result = AuditLog(path, secret=b"k").verify()
    assert result.ok and result.entries == 10


# -- K1: the default command allowlist is empty ------------------------------

def test_default_command_allowlist_is_empty(monkeypatch):
    monkeypatch.delenv("BASTION_CMD_ALLOWLIST", raising=False)
    import importlib
    from bastion.core import config as _config
    importlib.reload(_config)
    try:
        assert _config.COMMAND_ALLOWLIST == ()
        assert _config.RuntimeConfig().command_allowlist == ()
    finally:
        importlib.reload(_config)   # restore for any later importer


# -- J1: reports degrade gracefully without a chart engine -------------------

def test_html_report_degrades_chart_without_engine(monkeypatch):
    """When chart rendering is unavailable the HTML report still writes, with the
    chart's data preserved as a table (finding J1)."""
    from bastion.core.docs import charts as _charts
    from bastion.core.docs.writer import build_html

    def _boom(*_a, **_k):
        raise RuntimeError("no render engine")

    monkeypatch.setattr(_charts, "chart_png", _boom)
    blocks = [
        {"type": "heading", "text": "Q2"},
        {"type": "chart", "spec": {"type": "bar", "labels": ["Cloud", "Office"],
                                   "series": [{"name": "EUR",
                                               "values": [2550, 800]}]}},
    ]
    page = build_html(blocks, title="Q2 Report").decode("utf-8")
    assert "<!DOCTYPE html>" in page          # the report was produced
    assert "data:image/png" not in page       # no chart image (engine gone)
    assert "2550" in page and "800" in page    # numbers survive as a table
    assert "<table>" in page
