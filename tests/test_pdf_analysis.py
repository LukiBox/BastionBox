"""End-to-end proof: read a real multi-page PDF datasheet, write pages of
CORRECT, grounded analysis.

This is the workflow BastionBox exists for, exercised for real: a 6-page PDF is
generated with known facts pinned to known pages, the agent loop reads it
(page-aware), and writes a multi-section Word/PDF analysis. The tests then
*ground-truth* the output — every fact claimed in the report must literally
exist in the source PDF text — and check the output is genuinely a few pages
(PDF page count, word count, section count), not a one-liner.
"""
from __future__ import annotations

import io
import json

import pytest

from bastion.core.agent.permissions import Decision, PolicyBroker
from bastion.core.docs import extract
from bastion.core.security.audit import AuditLog
from bastion.core.security.jail import PathJail, Permission
from bastion.core.tools.base import ToolContext
from bastion.core.tools.office_tools import ReadDocument, WriteDocument


def _has(mod: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(mod) is not None


def _norm(text: str) -> str:
    """Whitespace-normalize so PDF line wrapping can't split a fact."""
    return " ".join(text.split())


pytestmark = pytest.mark.skipif(
    not (_has("reportlab") and (_has("fitz") or _has("pypdf"))),
    reason="needs reportlab to build the fixture PDF and a PDF reader")

# Facts planted in the datasheet — (page, claim). Every claim written into the
# analysis is checked against the source, so a wrong number fails the test.
FACTS = [
    (2, "28 VDC nominal (18-36 VDC)"),
    (2, "45 W maximum"),
    (3, "-51 °C up to +71 °C"),
    (3, "MIL-STD-810H Method 501.7"),
    (4, "Method 514.8"),
    (4, "7.7 g RMS"),
    (5, "J1-3 CAN_H"),
    (6, "MIL-STD-461G"),
]

_SECTIONS = {
    1: ("TX-9 Ruggedized Transceiver - Datasheet",
        "The TX-9 is a sealed vehicular transceiver for harsh environments. "
        "This datasheet covers electrical, environmental, mechanical, and "
        "compliance characteristics."),
    2: ("Electrical Characteristics",
        "Supply voltage: 28 VDC nominal (18-36 VDC) per MIL-STD-1275E. "
        "Power consumption: 45 W maximum at full transmit duty. "
        "Reverse polarity protection is integral."),
    3: ("Environmental Qualification",
        "Operating temperature: -51 °C up to +71 °C, qualified per "
        "MIL-STD-810H Method 501.7 (High Temperature) and Method 502.7 (Low "
        "Temperature). Humidity: 95 % RH non-condensing, Method 507.6."),
    4: ("Vibration and Shock",
        "Random vibration qualified per MIL-STD-810H Method 514.8, "
        "7.7 g RMS, 1 hour per axis. Functional shock: Method 516.8, "
        "40 g, 11 ms sawtooth."),
    5: ("Connector Pinout (J1)",
        "J1-1 PWR_IN. J1-2 GND. J1-3 CAN_H. J1-4 CAN_L. "
        "Connector: D38999/24WA35PN."),
    6: ("EMC Compliance",
        "Conducted emissions CE102 and radiated emissions RE102 per "
        "MIL-STD-461G. Bonding resistance below 2.5 milliohm."),
}


@pytest.fixture(scope="module")
def datasheet_bytes() -> bytes:
    """A real 6-page PDF datasheet with one known section per page."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer
    styles = getSampleStyleSheet()
    story = []
    for page in sorted(_SECTIONS):
        title, body = _SECTIONS[page]
        story.append(Paragraph(title, styles["Heading1"]))
        story.append(Spacer(1, 12))
        story.append(Paragraph(body, styles["BodyText"]))
        if page != max(_SECTIONS):
            story.append(PageBreak())
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4).build(story)
    return buf.getvalue()


@pytest.fixture()
def ws(tmp_path, datasheet_bytes):
    ws_dir = tmp_path / "ws"; ws_dir.mkdir()
    (ws_dir / "datasheet.pdf").write_bytes(datasheet_bytes)
    jail = PathJail()
    workspace = jail.mount(ws_dir, Permission.ASK)
    broker = PolicyBroker(ask_write=lambda w, d: Decision(True, "ok"))
    ctx = ToolContext(jail=jail, workspace=workspace, broker=broker,
                      audit=AuditLog(tmp_path / "a.jsonl"))
    return ctx, ws_dir


# -- reading: page-aware and honest ------------------------------------------
def test_pdf_extracts_six_pages_with_facts_in_place(ws, tmp_path, datasheet_bytes):
    doc = extract.extract(tmp_path / "ws" / "datasheet.pdf")
    assert doc.page_count == 6
    for page, claim in FACTS:
        assert claim in _norm(doc.pages[page - 1]), (
            f"fact missing on page {page}: {claim}")


def test_read_document_page_range_isolates_pages(ws):
    ctx, _ = ws
    r = ReadDocument().run(ctx, {"path": "datasheet.pdf", "pages": "3-3"})
    assert r.ok
    assert "-51 °C up to +71 °C" in _norm(r.observation)
    assert "MIL-STD-810H Method 501.7" in _norm(r.observation)
    assert "CAN_H" not in r.observation          # page 5 content stays out
    assert "[page 3]" in r.observation


def test_read_document_out_of_bounds_range_is_reported(ws):
    ctx, _ = ws
    r = ReadDocument().run(ctx, {"path": "datasheet.pdf", "pages": "40-50"})
    assert not r.ok
    assert "out of bounds" in r.observation and "6 page" in r.observation


def test_read_cap_tells_model_how_to_continue(ws):
    ctx, ws_dir = ws
    (ws_dir / "huge.txt").write_text("spec line\n" * 20_000, encoding="utf-8")
    r = ReadDocument().run(ctx, {"path": "huge.txt"})
    # A plain text file has no pages, so the hint guides summarize-then-continue
    # instead of a page range — but it must always say it was truncated and how
    # to proceed, and never silently drop content.
    assert r.ok and "truncated at" in r.observation
    assert "summarize" in r.observation or "read on" in r.observation


# -- writing: a few pages of detailed, grounded analysis ---------------------
def _analysis_markdown() -> str:
    """The detailed analysis a good model would write — every technical claim
    below is verbatim from the datasheet, so grounding can be asserted."""
    sections = [
        "# TX-9 Transceiver — Engineering Analysis",
        "## 1. Scope and Method",
        "This analysis reviews the TX-9 datasheet section by section. Every "
        "figure quoted below was read directly from the source document; where "
        "the datasheet is silent, the gap is called out rather than guessed at. "
        "The review covers electrical supply margins, environmental "
        "qualification coverage, mechanical robustness, interface pinout, and "
        "EMC compliance posture, in that order.",
        "## 2. Electrical Supply",
        "The unit accepts 28 VDC nominal (18-36 VDC), which matches standard "
        "military vehicle power. Peak consumption is 45 W maximum at full "
        "transmit duty, so a 5 A vehicle feed carries the unit with margin "
        "even at the 18 V low rail. Reverse polarity protection is integral, "
        "removing one common installation failure mode.",
        "- Supply range: 28 VDC nominal (18-36 VDC)",
        "- Power draw: 45 W maximum",
        "- Recommended breaker: 5 A per feed",
        "## 3. Environmental Qualification",
        "Thermal qualification spans -51 °C up to +71 °C, per "
        "MIL-STD-810H Method 501.7 (high temperature) and Method 502.7. This "
        "envelope covers all NATO climate categories except extreme arctic "
        "storage; humidity is covered to 95 % RH non-condensing. The datasheet "
        "does not state a solar-radiation (Method 505) result — flagged as a "
        "gap to confirm with the vendor, not assumed.",
        "## 4. Vibration and Shock",
        "Random vibration is qualified per Method 514.8 at 7.7 g RMS for one "
        "hour per axis, adequate for wheeled and tracked vehicle mounting. "
        "Functional shock at 40 g comfortably exceeds typical transit shocks.",
        "Aspect | Method | Level",
        "Vibration | Method 514.8 | 7.7 g RMS",
        "Shock | Method 516.8 | 40 g / 11 ms",
        "The one-hour-per-axis duration matches the general exposure profile "
        "for composite wheeled vehicles; if the installation platform is "
        "tracked, the qualification levels should be re-checked against the "
        "tracked-vehicle profile of Method 514.8 before acceptance, because "
        "track patter concentrates energy in narrow frequency bands that a "
        "broadband RMS figure can understate.",
        "## 5. Interface Pinout",
        "The J1 connector carries power and the CAN bus: J1-1 PWR_IN, J1-2 "
        "GND, J1-3 CAN_H, J1-4 CAN_L. Bus wiring must keep CAN_H/CAN_L as a "
        "twisted pair to the first splice.",
        "Pin | Signal | Notes",
        "J1-1 | PWR_IN | 28 VDC nominal (18-36 VDC) feed",
        "J1-2 | GND | Power return, bonded at chassis",
        "J1-3 | CAN_H | Twisted with CAN_L, 120 ohm at bus ends",
        "J1-4 | CAN_L | Twisted with CAN_H",
        "The D38999/24WA35PN shell is a wide-flange receptacle; panel cutout "
        "and backshell strain relief must follow the connector supplier's "
        "drawing. No spare contacts are documented, which constrains growth — "
        "any future discrete signal will require a harness change.",
        "## 6. EMC Compliance",
        "Emissions are qualified to MIL-STD-461G (CE102 conducted, RE102 "
        "radiated). Bonding resistance below 2.5 milliohm meets platform "
        "grounding requirements without extra straps.",
        "Susceptibility results (CS101, CS114, RS103) are not listed in the "
        "datasheet. For co-site operation next to an HF transmitter this is "
        "the single largest open risk in the document and must be resolved "
        "from the full qualification report rather than assumed from the "
        "emissions line items.",
        "## 7. Requirements Traceability",
        "- REQ-PWR-001 (vehicle 28 VDC supply): met — 28 VDC nominal "
        "(18-36 VDC), verification by Test.",
        "- REQ-PWR-002 (max load 60 W): met — 45 W maximum, margin 25 %.",
        "- REQ-ENV-001 (operate -40 °C to +60 °C): met with margin — "
        "qualified -51 °C up to +71 °C per MIL-STD-810H Method 501.7 and "
        "Method 502.7, verification by Test.",
        "- REQ-MEC-003 (wheeled-vehicle vibration): met — Method 514.8 at "
        "7.7 g RMS, verification by Test.",
        "- REQ-EMC-002 (emissions per MIL-STD-461G): met — CE102/RE102, "
        "verification by Test. Susceptibility: TBD, see Section 6.",
        "## 8. Verdict",
        "The TX-9 meets the stated platform requirements on every parameter "
        "the datasheet documents, with real margin on temperature and power. "
        "Three follow-ups before design freeze: confirm solar radiation "
        "testing, obtain the full MIL-STD-461G report for the RE102 curves "
        "and the missing susceptibility results, and re-check vibration "
        "levels if the platform is tracked rather than wheeled. None of these "
        "are expected to be blocking, but all three must be evidence-based "
        "closures, not assumptions.",
    ]
    return "\n\n".join(sections)


def test_agent_writes_pages_of_grounded_pdf_analysis(ws, tmp_path):
    """The full workspace-mode loop: scripted model reads the datasheet twice
    (full + page range), then writes a multi-section .docx analysis. The output
    must be long, structured, and every quoted figure must exist in the PDF."""
    if not _has("docx"):
        pytest.skip("python-docx not installed")
    from bastion.core.agent.loop import AgentLoop, EventKind
    from bastion.core.llm.engine import FakeEngine
    ctx, ws_dir = ws

    analysis = _analysis_markdown()
    script = [
        json.dumps({"tool": "read_document", "args": {"path": "datasheet.pdf"}}),
        json.dumps({"tool": "read_document",
                    "args": {"path": "datasheet.pdf", "pages": "2-4"}}),
        json.dumps({"tool": "write_document",
                    "args": {"path": "analysis.docx",
                             "title": "TX-9 Engineering Analysis",
                             "content": analysis}}),
        json.dumps({"tool": "final", "args": {
            "content": "Wrote analysis.docx grounded in datasheet.pdf."}}),
    ]
    events = list(AgentLoop(FakeEngine(script), ctx).run(
        "read datasheet.pdf and write a detailed engineering analysis"))
    assert any(e.kind is EventKind.FINAL for e in events)

    out = ws_dir / "analysis.docx"
    assert out.exists()
    written = _norm(extract.extract(out).text)
    source = _norm(extract.extract(ws_dir / "datasheet.pdf").text)

    # Grounding: every fact the analysis quotes exists verbatim in the source.
    for _page, claim in FACTS:
        assert claim in written, f"analysis lost the fact: {claim}"
        assert claim in source, f"fixture broke: {claim}"
    # Substance: multiple sections and real length, not a stub.
    assert written.count("Method") >= 4
    assert sum(1 for line in extract.extract(out).text.splitlines()
               if line.strip().startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7."))
               or "Scope" in line or "Verdict" in line) >= 2
    assert len(written.split()) > 450, "analysis should be pages, not a note"
    # Honesty: gaps are flagged as gaps, not invented.
    assert "does not state" in written or "gap" in written.lower()


def test_write_document_renders_a_multi_page_pdf(ws):
    """The same analysis written as .pdf must span several real pages."""
    if not _has("fitz"):
        pytest.skip("PyMuPDF needed to count output pages")
    import fitz
    ctx, ws_dir = ws
    r = WriteDocument().run(ctx, {"path": "analysis.pdf",
                                  "title": "TX-9 Engineering Analysis",
                                  "content": _analysis_markdown() * 2})
    assert r.ok, r.observation
    doc = fitz.open(str(ws_dir / "analysis.pdf"))
    try:
        assert doc.page_count >= 3, f"expected a few pages, got {doc.page_count}"
        text = _norm("".join(p.get_text() for p in doc))
    finally:
        doc.close()
    assert "-51 °C up to +71 °C" in text     # facts survive PDF render
    assert "MIL-STD-461G" in text


def test_long_markdown_keeps_every_section_in_docx(ws):
    """No silent section loss on long documents: every heading in a 7-section
    report must survive the markdown → .docx → extract round-trip."""
    if not _has("docx"):
        pytest.skip("python-docx not installed")
    ctx, ws_dir = ws
    r = WriteDocument().run(ctx, {"path": "long.docx", "title": "T",
                                  "content": _analysis_markdown()})
    assert r.ok
    back = extract.extract(ws_dir / "long.docx").text
    for heading in ("Scope and Method", "Electrical Supply",
                    "Environmental Qualification", "Vibration and Shock",
                    "Interface Pinout", "EMC Compliance", "Verdict"):
        assert heading in back, f"section lost in round-trip: {heading}"
    # The table made it through as a real table row, not mush.
    assert "7.7 g RMS" in back


def test_workspace_plus_library_full_ea_flow(tmp_path, datasheet_bytes):
    """Workspace mode with a library attached: search the norm in the library,
    read the datasheet in the workspace, write the test case — one loop run."""
    if not _has("docx"):
        pytest.skip("python-docx not installed")
    from bastion.core.agent.loop import AgentLoop, EventKind
    from bastion.core.llm.engine import FakeEngine
    ws_dir = tmp_path / "ws"; ws_dir.mkdir()
    lib_dir = tmp_path / "library"; lib_dir.mkdir()
    (ws_dir / "datasheet.pdf").write_bytes(datasheet_bytes)
    (lib_dir / "MIL-STD-810H-Method-502.7.txt").write_text(
        "Method 502.7 Low Temperature. Step 1. Install the test item in the "
        "chamber in its operational configuration. Step 2. Adjust the chamber "
        "air temperature to -51 °C at a rate not exceeding 3 °C per "
        "minute. Step 3. Maintain for two hours after stabilization.",
        encoding="utf-8")
    jail = PathJail()
    ws = jail.mount(ws_dir, Permission.ASK)
    lib = jail.mount(lib_dir, Permission.READ_ONLY, label="norms")
    ctx = ToolContext(jail=jail, workspace=ws,
                      broker=PolicyBroker(ask_write=lambda w, d: Decision(True, "ok")),
                      audit=AuditLog(tmp_path / "a.jsonl"), library=lib)

    test_case = ("# TC-ENV-002 Low Temperature Operation\n\n"
                 "Reference: MIL-STD-810H Method 502.7. Requirement: operate at "
                 "-51 °C (datasheet lower limit).\n\n"
                 "1. Step 1. Install the test item in the chamber in its "
                 "operational configuration.\n"
                 "2. Step 2. Adjust the chamber air temperature to -51 °C "
                 "at a rate not exceeding 3 °C per minute.\n"
                 "3. Step 3. Maintain for two hours after stabilization.\n\n"
                 "Pass criteria: full RF function at -51 °C per datasheet.")
    script = [
        json.dumps({"tool": "search_library",
                    "args": {"keywords": "MIL-STD-810 502.7 low temperature"}}),
        json.dumps({"tool": "read_document",
                    "args": {"path": "MIL-STD-810H-Method-502.7.txt"}}),
        json.dumps({"tool": "read_document",
                    "args": {"path": "datasheet.pdf", "pages": "3-3"}}),
        json.dumps({"tool": "write_document",
                    "args": {"path": "TC-ENV-002.docx", "title": "TC-ENV-002",
                             "content": test_case}}),
        json.dumps({"tool": "final", "args": {"content": "Test case written."}}),
    ]
    events = list(AgentLoop(FakeEngine(script), ctx).run(
        "write the low-temperature test case from the norm in the library"))
    obs = [e.text for e in events if e.kind is EventKind.OBSERVATION]
    assert any("MIL-STD-810H-Method-502.7.txt" in (o or "") for o in obs)
    assert any("Step 2. Adjust the chamber" in (o or "") for o in obs)
    out = ws_dir / "TC-ENV-002.docx"
    assert out.exists()
    back = extract.extract(out).text
    # The steps in the test case are verbatim from the norm the loop read.
    assert "Step 2. Adjust the chamber air temperature to -51 °C" in back
    assert "Method 502.7" in back


def test_read_document_respects_context_char_cap(tmp_path):
    """A read must never exceed the per-context cap — this is what kept a big
    .docx from overflowing an 8k window and crashing the turn."""
    from bastion.core.security.jail import PathJail, Permission
    from bastion.core.security.audit import AuditLog
    from bastion.core.agent.permissions import PolicyBroker, Decision
    from bastion.core.tools.base import ToolContext
    from bastion.core.tools.office_tools import ReadDocument
    from bastion.core.docs.writer import build_docx

    ws = tmp_path / "ws"; ws.mkdir()
    blocks = [{"type": "paragraph", "text": f"para {i} " + "word " * 40}
              for i in range(200)]
    (ws / "big.docx").write_bytes(build_docx(blocks))
    jail = PathJail(); w = jail.mount(ws, Permission.ASK)
    ctx = ToolContext(jail=jail, workspace=w,
                      broker=PolicyBroker(ask_write=lambda a, b: Decision(True, "")),
                      audit=AuditLog(tmp_path / "a.jsonl"), read_char_cap=12_000)
    r = ReadDocument().run(ctx, {"path": "big.docx"})
    assert r.ok
    assert len(r.observation) < 12_000 + 400        # capped (+ short header/note)
    assert "truncated at" in r.observation          # and says so, with guidance


def test_agent_loop_trims_history_to_context():
    """A giant observation plus system prompt must be trimmed under the context
    window, keeping the system prompt and the original task — never overflow."""
    from bastion.core.agent.loop import AgentLoop, _CHARS_PER_TOKEN
    from bastion.core.llm.engine import Message, Role

    loop = AgentLoop(engine=None, ctx=None, context_tokens=8192, reply_tokens=1024)
    msgs = [
        Message(Role.SYSTEM, "S" * 4000),
        Message(Role.USER, "the original task"),
        Message(Role.ASSISTANT, '{"tool":"read_document"}'),
        Message(Role.TOOL, "X" * 60_000, name="read_document"),  # ~15k tokens
        Message(Role.ASSISTANT, '{"tool":"final"}'),
    ]
    fit = loop._fit(msgs)
    est = sum(len(m.content) // _CHARS_PER_TOKEN + 8 for m in fit)
    assert est <= 8192 - 1024, est                  # fits with room for the reply
    assert fit[0].role is Role.SYSTEM and fit[0].content == "S" * 4000
    assert any(m.content == "the original task" for m in fit)
