"""Chat attachments — a dropped file becomes model-readable text, locally.

Dragging a file into the chat is an explicit user action, so it is the one way
content from *outside* a mounted workspace may enter a conversation: the user
is the wall. Extraction reuses the local document readers (PDF/Word/Excel/text
— nothing leaves the machine), every attachment is SHA-256 fingerprinted for
the audit log, and rendering fits the whole batch inside a character budget so
a big drop can never blow out the context window.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .extract import (DOCX_SUFFIXES, PDF_SUFFIXES, TEXT_SUFFIXES,
                      XLSX_SUFFIXES, extract)

# A file larger than this is refused outright: the right tool for big inputs is
# a workspace or the read-only library, where the agent reads within a budget.
MAX_FILE_BYTES = 50 * 1024 * 1024
# Per-attachment stored text cap — bounds memory before the send-time budget.
MAX_CHARS = 200_000
# How many raw bytes to sniff when deciding text vs. binary for unknown types.
_SNIFF_BYTES = 4096


class AttachmentError(Exception):
    """Base for attachment failures the UI turns into a translated message."""


class TooLarge(AttachmentError):
    def __init__(self, size_mb: float):
        super().__init__(f"file is {size_mb:.1f} MB")
        self.size_mb = round(size_mb, 1)


class Unsupported(AttachmentError):
    """Binary or unreadable content we can't turn into text."""


@dataclass
class Attachment:
    name: str
    path: str
    kind: str          # "pdf" | "docx" | "xlsx" | "text"
    text: str          # extracted text, capped at MAX_CHARS
    chars: int         # original extracted length, before any capping
    sha256: str        # fingerprint of the raw file, for the audit log
    truncated: bool = False


def load_attachment(path: str | Path) -> Attachment:
    """Turn *path* into an :class:`Attachment`, entirely offline.

    Raises :class:`TooLarge` / :class:`Unsupported` for the refusal cases and
    plain :class:`AttachmentError` when a document library is missing.
    """
    p = Path(path)
    size = p.stat().st_size
    if size > MAX_FILE_BYTES:
        raise TooLarge(size / (1024 * 1024))
    raw = p.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()

    suffix = p.suffix.lower()
    known = (PDF_SUFFIXES | DOCX_SUFFIXES | XLSX_SUFFIXES | TEXT_SUFFIXES)
    if suffix in known:
        try:
            doc = extract(p)
        except Exception as exc:   # ExtractionUnavailable or a corrupt file
            raise AttachmentError(str(exc)) from exc
        text, kind = doc.text, doc.kind
    else:
        # Unknown suffix: attach it as text if it plausibly *is* text.
        if b"\x00" in raw[:_SNIFF_BYTES]:
            raise Unsupported(p.name)
        text, kind = raw[:2_000_000].decode("utf-8", errors="replace"), "text"

    chars = len(text)
    truncated = chars > MAX_CHARS
    return Attachment(p.name, str(p), kind, text[:MAX_CHARS], chars, sha,
                      truncated)


def render_attachments(attachments: list[Attachment], char_budget: int) -> str:
    """Render the batch as tagged blocks that together fit *char_budget*.

    Files that fit keep their full text; the oversized ones share what budget
    remains equally, each ending in a visible truncation marker so the model
    (and the user reading the transcript) knows the file continues.
    """
    if not attachments:
        return ""
    budget = max(1_000, int(char_budget))
    # First pass: everything under a fair share keeps its full text.
    share = budget // len(attachments)
    small = [a for a in attachments if len(a.text) <= share]
    spent = sum(len(a.text) for a in small)
    big = [a for a in attachments if len(a.text) > share]
    per_big = max(500, (budget - spent) // len(big)) if big else 0

    blocks = []
    for i, a in enumerate(attachments, 1):
        body = a.text if a in small else a.text[:per_big]
        cut = a.truncated or len(body) < len(a.text)
        marker = "\n[… truncated — the full file is longer]" if cut else ""
        blocks.append(
            f'<attachment index="{i}" name="{a.name}" kind="{a.kind}" '
            f'path="{a.path}" chars="{a.chars}">\n{body}{marker}\n'
            f'</attachment>')
    return "\n\n".join(blocks)
