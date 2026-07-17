"""Detailed tutorial — the optional, step-by-step guide.

Reached from a button in the short onboarding (or Settings). Unlike the three-card
tour, this is a scrollable manual covering the things a new operator actually has
to do: load a GGUF model, mount a workspace and run the agent, and use the file /
office editing flow (read a datasheet, write a Word/Excel/PDF report). Plain,
numbered steps — no fluff.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from .theme import Palette
from .widgets.tactical import Card, StatusPill

_SECTIONS = [
    ("1 · LOAD A MODEL (GGUF)", "MODELS TAB", "armed", [
        "Open the Models tab. BastionBox reads any GGUF file straight off disk — "
        "models arrive by USB/media, never a download.",
        "Click IMPORT GGUF… and pick your file (e.g. qwen2.5-14b-instruct-q4.gguf).",
        "Paste the SHA-256 you were given out-of-band. A green check means the file "
        "is authentic; a red flag means DO NOT load it.",
        "The Hardware Optimizer shows the offload plan and the math — how many "
        "layers fit on your GPU and the context length that fits.",
        "Prefer a 7–14B Q4 model for an 8 GB GPU; CPU-only works with a 3–8B Q4.",
    ]),
    ("2 · MOUNT A WORKSPACE & RUN THE AGENT", "WORKSPACES TAB", "secure", [
        "Open Workspaces and click the permission chip to pick a tier: Read-only, "
        "Ask per write (recommended), or Auto-approve.",
        "Click MOUNT WORKSPACE… and choose a folder. The agent is confined to that "
        "folder by the path jail and can touch nothing outside it.",
        "You are dropped into Chat in agent mode. Ask it to do real work: "
        "\"rename check_tok to validate_token everywhere and update the docstring\".",
        "The agent inspects first (grep/read), then proposes edits. Each write "
        "shows a DIFF — Approve, or Reject with a note it will adapt to.",
        "Ask it to run a check (e.g. \"run pytest -q\"); allowlisted commands run "
        "jailed, output captured in the transcript.",
    ]),
    ("3 · FILE EDITING & OFFICE DOCS", "THE CORE FLOW", "secure", [
        "Drop a datasheet (.pdf), report (.docx) or sheet (.xlsx) into the mounted "
        "workspace folder.",
        "Ask: \"read the datasheet spec.pdf and summarize the electrical ratings "
        "into a Word report\". The agent calls read_document (page-aware for long "
        "PDFs) then write_document.",
        "For tables/data, ask for Excel: \"extract the pin table from spec.pdf into "
        "pins.xlsx\" — it writes a real .xlsx with a styled header.",
        "For code, ask it to create or edit files directly (write_file / edit_file) "
        "— basic scripts, configs, and docs, always behind a diff you approve.",
        "Every written file lands inside the workspace, is shown for approval "
        "first, and is recorded in the tamper-evident audit log.",
    ]),
    ("4 · TEMPLATES & THE REFERENCE LIBRARY", "EA WORKFLOW", "armed", [
        "Attach a big folder of datasheets/norms in Knowledge → Reference Library. "
        "It is READ-ONLY: the agent can search and read there, never write.",
        "Ask: \"find the vibration section of MIL-STD-810 in the library and "
        "quote the procedure\" — the agent calls search_library with keywords, "
        "then read_document on the hits.",
        "Put your company .docx template (logo, formatting) in the workspace or "
        "library, with placeholders: {{TITLE}}, {{SUMMARY}}, {{IMG:photo1}}, and "
        "a table row containing {{TABLE:results}}.",
        "Ask: \"fill template company.docx with the climatic test results into "
        "report.docx\" — fill_template keeps your branding and swaps in text, "
        "photos, and test-data rows. Unfilled placeholders are reported, never "
        "silently dropped.",
        "Pick the EA Test-Case Writer persona for MIL-STD-810-style requirements "
        "(REQ-ENV-001, −51 °C to +71 °C) and numbered Step 1./Step 2. procedures.",
        "Reports can carry real charts and photos: the agent embeds workspace "
        "images with ![caption](photos/rig.png) and renders bar/line/pie charts "
        "from data it read — vector art in PDFs, crisp images in Word. "
        "write_spreadsheet can add a native, still-editable Excel chart.",
    ]),
    ("GOOD TO KNOW", "SECURITY", "secure", [
        "Nothing leaves the machine — the network guard blocks every outbound "
        "connection; the Security tab's blocked counter should read 0 forever.",
        "Everything is encrypted at rest; use Panic Controls to secure-delete a "
        "workspace's entire footprint or lock the key from memory.",
        "Switch tone with the persona dropdown — or create your own persona with "
        "a custom system prompt in Settings → Assistant Personas.",
        "The whole interface speaks English and Polish — switch live in "
        "Settings → Appearance & Language; the choice persists across launches.",
        "Free context with COMPACT; start fresh with NEW. Summon quick-ask "
        "anywhere with Ctrl+Alt+Space.",
    ]),
]


class Tutorial(QDialog):
    def __init__(self, palette: Palette, parent=None):
        super().__init__(parent)
        self.setWindowTitle("BastionBox — Detailed Tutorial")
        self.setMinimumSize(720, 620)
        self._palette = palette

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(14)
        title = QLabel("HOW TO USE BASTIONBOX")
        title.setProperty("role", "h1")
        v.addWidget(title)
        sub = QLabel("Load a model · mount a workspace · read datasheets and write "
                     "Word/Excel/PDF — all fully offline.")
        sub.setProperty("role", "readout")
        sub.setWordWrap(True)
        v.addWidget(sub)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(2, 2, 8, 2)
        col.setSpacing(14)
        for headline, pill, status, steps in _SECTIONS:
            col.addWidget(self._section(headline, pill, status, steps))
        col.addStretch(1)
        scroll.setWidget(body)
        v.addWidget(scroll, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton("CLOSE")
        close.setProperty("variant", "primary")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        v.addLayout(row)

    def _section(self, headline: str, pill: str, status: str, steps) -> Card:
        card = Card(headline)
        card.add_header_widget(StatusPill(pill, status))
        for i, step in enumerate(steps, 1):
            row = QHBoxLayout()
            num = QLabel(f"{i:02d}")
            num.setStyleSheet(f"color:{self._palette.brand_hi};font-family:monospace;"
                              f"font-weight:700;")
            num.setFixedWidth(26)
            num.setAlignment(Qt.AlignTop)
            text = QLabel(step)
            text.setProperty("role", "readout")
            text.setWordWrap(True)
            row.addWidget(num)
            row.addWidget(text, 1)
            card.body().addLayout(row)
        return card
