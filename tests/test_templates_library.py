"""Template filling + reference library + custom personas — the LukiBox batch.

Covers the three features added for real EA work:
* fill_docx_template / fill_template: business template in, branded report out —
  {{KEY}} text (across runs), {{IMG:x}} photos, {{TABLE:x}} data rows, leftovers
  reported, formatting of the first run preserved.
* search_library + resolve_readable: a read-only datasheet library the agent can
  keyword-search and read — but never write into.
* custom personas: persisted in the store, merged with built-ins, EA persona pins.
"""
from __future__ import annotations

import base64
import io

import pytest

from bastion.core.agent.permissions import Decision, PolicyBroker
from bastion.core.security.audit import AuditLog
from bastion.core.security.jail import JailViolation, PathJail, Permission
from bastion.core.tools.base import ToolContext


def _has(mod: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(mod) is not None


docx = pytest.importorskip("docx")

# A valid 1×1 red PNG (for image-placeholder tests).
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/"
    "q842iQAAAABJRU5ErkJggg==")


def _template(path, with_table=True):
    """Build a small 'company template': heading, placeholders, styled table."""
    d = docx.Document()
    h = d.add_paragraph()
    run = h.add_run("ACME DEFENSE — ")
    run.bold = True
    # Split the placeholder across runs, like real Word files do.
    h.add_run("{{TI")
    h.add_run("TLE}}")
    d.add_paragraph("Prepared by: {{AUTHOR}}")
    d.add_paragraph("{{SUMMARY}}")
    d.add_paragraph("{{IMG:photo}}")
    if with_table:
        t = d.add_table(rows=2, cols=3)
        t.rows[0].cells[0].text = "Step"
        t.rows[0].cells[1].text = "Condition"
        t.rows[0].cells[2].text = "Result"
        t.rows[1].cells[0].text = "{{TABLE:results}}"
    d.save(str(path))


# -- templater core ----------------------------------------------------------
def test_fill_template_text_across_runs(tmp_path):
    from bastion.core.docs.templater import fill_docx_template
    tpl = tmp_path / "tpl.docx"; _template(tpl, with_table=False)
    data, leftover = fill_docx_template(
        tpl, fields={"TITLE": "Climatic Test Report",
                     "AUTHOR": "LukiBox",
                     "SUMMARY": "Line one\nLine two"})
    d = docx.Document(io.BytesIO(data))
    text = "\n".join(p.text for p in d.paragraphs)
    assert "ACME DEFENSE — Climatic Test Report" in text
    assert "Prepared by: LukiBox" in text
    assert "{{" not in text.replace("{{IMG:photo}}", "")  # only IMG remains
    assert leftover == ["IMG:photo"]                      # honest about gaps
    # The branded first run kept its bold formatting.
    branded = next(p for p in d.paragraphs if "ACME" in p.text)
    assert branded.runs[0].bold


def test_fill_template_image_and_table(tmp_path):
    from bastion.core.docs.templater import fill_docx_template
    tpl = tmp_path / "tpl.docx"; _template(tpl)
    img = tmp_path / "rig.png"; img.write_bytes(_PNG)
    data, leftover = fill_docx_template(
        tpl,
        fields={"TITLE": "T", "AUTHOR": "A", "SUMMARY": "S"},
        images={"photo": img},
        tables={"results": [["Step 1.", "-51 °C", "PASS"],
                            ["Step 2.", "+71 °C", "PASS"]]})
    assert leftover == []
    d = docx.Document(io.BytesIO(data))
    assert len(d.inline_shapes) == 1                     # the photo landed
    table = d.tables[0]
    cells = [c.text for row in table.rows for c in row.cells]
    assert "Step 1." in cells and "+71 °C" in cells
    assert not any("{{TABLE" in c for c in cells)        # prototype row gone
    assert len(table.rows) == 3                          # header + 2 data rows


def test_find_placeholders(tmp_path):
    from bastion.core.docs.templater import find_placeholders
    tpl = tmp_path / "tpl.docx"; _template(tpl)
    keys = find_placeholders(tpl)
    assert {"TITLE", "AUTHOR", "SUMMARY", "IMG:photo", "TABLE:results"} <= set(keys)


# -- fill_template tool (jail + approval + library template) -----------------
@pytest.fixture()
def ctx2(tmp_path):
    ws_dir = tmp_path / "ws"; ws_dir.mkdir()
    lib_dir = tmp_path / "lib"; lib_dir.mkdir()
    jail = PathJail()
    ws = jail.mount(ws_dir, Permission.ASK)
    lib = jail.mount(lib_dir, Permission.READ_ONLY, label="norms")
    audit = AuditLog(tmp_path / "a.jsonl")
    broker = PolicyBroker(ask_write=lambda ws, d: Decision(True, "ok"))
    return (ToolContext(jail=jail, workspace=ws, broker=broker, audit=audit,
                        library=lib), ws_dir, lib_dir)


def test_fill_template_tool_end_to_end(ctx2):
    from bastion.core.tools.office_tools import FillTemplate
    c, ws_dir, lib_dir = ctx2
    _template(lib_dir / "company.docx", with_table=False)   # template in LIBRARY
    r = FillTemplate().run(c, {
        "template": "company.docx",
        "path": "out/report.docx",
        "fields": '{"TITLE": "EMC Report", "AUTHOR": "LukiBox", "SUMMARY": "ok"}'})
    assert r.ok, r.observation
    assert (ws_dir / "out" / "report.docx").exists()
    assert "IMG:photo" in r.observation                     # leftover warned


def test_fill_template_rejects_bad_args(ctx2):
    from bastion.core.tools.office_tools import FillTemplate
    c, _, lib_dir = ctx2
    _template(lib_dir / "t.docx", with_table=False)
    assert not FillTemplate().run(c, {"template": "t.docx", "path": "x.pdf",
                                      "fields": "{}"}).ok
    assert not FillTemplate().run(c, {"template": "t.docx", "path": "x.docx",
                                      "fields": "not json"}).ok
    assert not FillTemplate().run(c, {"template": "missing.docx",
                                      "path": "x.docx", "fields": "{}"}).ok


# -- reference library --------------------------------------------------------
def test_search_library_by_name_and_read(ctx2):
    from bastion.core.tools.library_tools import SearchLibrary
    from bastion.core.tools.office_tools import ReadDocument
    c, _, lib_dir = ctx2
    (lib_dir / "MIL-STD-810H-vibration.txt").write_text(
        "Method 514.8 Vibration. Step 1. Mount the item.", encoding="utf-8")
    (lib_dir / "unrelated.txt").write_text("nothing", encoding="utf-8")
    r = SearchLibrary().run(c, {"keywords": "MIL-STD-810 vibration"})
    assert r.ok and "MIL-STD-810H-vibration.txt" in r.observation
    assert "unrelated" not in r.observation
    # …and the hit is readable through the library fallback.
    doc = ReadDocument().run(c, {"path": "MIL-STD-810H-vibration.txt"})
    assert doc.ok and "Method 514.8" in doc.observation


def test_search_library_requires_attachment(tmp_path):
    from bastion.core.tools.library_tools import SearchLibrary
    ws_dir = tmp_path / "ws"; ws_dir.mkdir()
    jail = PathJail(); ws = jail.mount(ws_dir, Permission.ASK)
    c = ToolContext(jail=jail, workspace=ws,
                    broker=PolicyBroker(ask_write=lambda w, d: Decision(True, "")),
                    audit=AuditLog(tmp_path / "a.jsonl"))
    r = SearchLibrary().run(c, {"keywords": "anything"})
    assert not r.ok and "library" in r.observation.lower()


def test_library_is_never_writable(ctx2):
    """Write tools resolve against the WORKSPACE only — a path that exists just
    in the library must not be reachable for writing."""
    from bastion.core.tools.office_tools import WriteDocument
    c, ws_dir, lib_dir = ctx2
    r = WriteDocument().run(c, {"path": "../lib/evil.docx", "title": "x",
                                "content": "y"})
    assert not r.ok
    assert not (lib_dir / "evil.docx").exists()


def test_keyword_search_ranks_more_matches_first(tmp_path):
    from bastion.core.tools.library_tools import keyword_search
    (tmp_path / "shock-vibration-810.pdf").write_bytes(b"x")
    (tmp_path / "vibration-only.pdf").write_bytes(b"x")
    hits = keyword_search(tmp_path, ["vibration", "810"])
    assert hits[0][0] == "shock-vibration-810.pdf"
    assert hits[0][1] == 2 and hits[1][1] == 1


# -- personas -----------------------------------------------------------------
def test_ea_persona_pins():
    from bastion.core.agent.personas import PERSONAS
    ea = PERSONAS["EA Test-Case Writer"]
    p = ea.full_prompt
    assert "MIL-STD-810" in p and "-51 °C up to +71 °C" in p
    assert "Step 1." in p and "Step 2." in p
    assert "REQ-ENV-001" in p and "pass/fail" in p
    assert "TBD" in p                       # never invent missing clause values
    assert "nothing leaves this machine" in p   # safety footer survives


def test_custom_personas_roundtrip(tmp_path):
    from bastion.core.agent import personas as P
    from bastion.core.store.db import Store
    store = Store(tmp_path / "s.db", cipher=None)
    P.save_custom(store, {"ACME Reporter": P.Persona(
        "ACME Reporter", "Write ACME-style reports.", custom=True)})
    merged = P.all_personas(store)
    assert "ACME Reporter" in merged and "Assistant" in merged
    got = P.get("ACME Reporter", store)
    assert got.custom and got.full_prompt.startswith("Write ACME-style reports.")
    assert "nothing leaves this machine" in got.full_prompt
    # Unknown name falls back to the default, never crashes.
    assert P.get("nope", store).name == "Assistant"


def test_custom_persona_corrupt_setting_is_ignored(tmp_path):
    from bastion.core.agent import personas as P
    from bastion.core.store.db import Store
    store = Store(tmp_path / "s.db", cipher=None)
    store.set_setting("__global__", P.CUSTOM_KEY, "{not json!")
    assert P.load_custom(store) == {}
    assert "Assistant" in P.all_personas(store)
