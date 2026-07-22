"""Drag-and-drop chat attachments — extraction, caps, rendering, and the UI flow.

The core (bastion.core.docs.attach) is pure Python: a dropped file becomes
capped text plus a SHA-256 fingerprint, and a batch renders inside a character
budget so a big drop can never blow out the context window. The UI half runs
under the Qt 'offscreen' platform and proves the whole flow: drop → attachment
bar → send folds the text into the outgoing message → the bar clears.
"""
from __future__ import annotations

import os

import pytest

from bastion.core.docs import attach as attach_mod
from bastion.core.docs.attach import (Attachment, TooLarge, Unsupported,
                                      load_attachment, render_attachments)


# -- core: load_attachment ---------------------------------------------------

def test_text_file_loads_with_fingerprint(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("line one\nline two\n", encoding="utf-8")
    att = load_attachment(p)
    assert att.kind == "text"
    assert "line two" in att.text
    assert att.chars == len(att.text)
    assert len(att.sha256) == 64
    assert not att.truncated


def test_unknown_suffix_still_attaches_as_text(tmp_path):
    p = tmp_path / "server.conf"
    p.write_text("port = 8080\n", encoding="utf-8")
    att = load_attachment(p)
    assert att.kind == "text"
    assert "8080" in att.text


def test_binary_is_refused(tmp_path):
    p = tmp_path / "blob.bin"
    p.write_bytes(b"\x00\x01\x02" * 100)
    with pytest.raises(Unsupported):
        load_attachment(p)


def test_oversized_file_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(attach_mod, "MAX_FILE_BYTES", 100)
    p = tmp_path / "big.txt"
    p.write_text("x" * 500, encoding="utf-8")
    with pytest.raises(TooLarge) as exc:
        load_attachment(p)
    assert exc.value.size_mb >= 0


def test_csv_attaches_via_extractor(tmp_path):
    p = tmp_path / "data.csv"
    p.write_text("date,amount\n2026-01-02,10.50\n", encoding="utf-8")
    att = load_attachment(p)
    assert "amount" in att.text


# -- core: render_attachments ------------------------------------------------

def _att(name: str, text: str) -> Attachment:
    return Attachment(name, f"C:/fake/{name}", "text", text, len(text), "0" * 64)


def test_render_within_budget_keeps_full_text():
    out = render_attachments([_att("a.txt", "alpha"), _att("b.txt", "beta")],
                             char_budget=10_000)
    assert '<attachment index="1" name="a.txt"' in out
    assert "alpha" in out and "beta" in out
    assert "truncated" not in out


def test_render_over_budget_truncates_visibly():
    big = _att("big.txt", "z" * 50_000)
    small = _att("small.txt", "tiny")
    out = render_attachments([small, big], char_budget=5_000)
    assert "tiny" in out                          # small file kept whole
    assert "truncated" in out                     # big one visibly cut
    assert len(out) < 12_000                      # bounded, envelope included


def test_render_empty_batch_is_empty():
    assert render_attachments([], 1000) == ""


# -- UI flow (offscreen Qt) --------------------------------------------------

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from bastion.core.llm.engine import DemoEngine  # noqa: E402
from bastion.ui.theme import THEMES, build_qss  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(build_qss(THEMES["dark"]))
    yield app


def test_drop_attach_send_clears_and_folds_text(qapp, tmp_path):
    from bastion.ui.chat.chat_view import ChatView
    p = tmp_path / "report.txt"
    p.write_text("quarterly totals: 1234\n", encoding="utf-8")

    view = ChatView(DemoEngine(), THEMES["dark"])
    view._add_attachments([str(p)])
    assert len(view._attachments) == 1
    assert not view._attach_bar.isHidden()
    assert "report.txt" in view._attach_label.text()

    view._input.setPlainText("summarize the attached file")
    view._on_send()
    # Let the worker thread run to completion.
    if view._worker is not None:
        view._worker.wait(3000)
    qapp.processEvents()

    sent = view._history[0].content
    assert "summarize the attached file" in sent
    assert '<attachment index="1" name="report.txt"' in sent
    assert "quarterly totals: 1234" in sent
    assert view._attachments == []          # consumed by the send
    assert view._attach_bar.isHidden()


def test_folder_drop_is_refused_not_attached(qapp, tmp_path):
    from bastion.ui.chat.chat_view import ChatView
    d = tmp_path / "folder"
    d.mkdir()
    view = ChatView(DemoEngine(), THEMES["dark"])
    view._add_attachments([str(d)])
    assert view._attachments == []
    assert view._attach_bar.isHidden()


def test_input_routes_file_drops_not_urls(qapp, tmp_path):
    """Dropping a file on the input attaches it instead of pasting file:///."""
    from PySide6.QtCore import QMimeData, QUrl
    from bastion.ui.chat.chat_view import ChatView
    p = tmp_path / "pins.csv"
    p.write_text("pin,net\n1,GND\n", encoding="utf-8")

    view = ChatView(DemoEngine(), THEMES["dark"])
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p))])
    view._input.insertFromMimeData(mime)
    assert len(view._attachments) == 1
    assert view._input.toPlainText() == ""   # nothing pasted into the box
