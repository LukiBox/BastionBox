"""Regression tests for the office/LLM hardening fixes.

Each test pins one real crash or correctness bug that a 7-14B local model reliably
triggers, so the fix can't silently regress: jagged tables, PDF markup on '<'/'&',
Excel sheet-name / number coercion, quoted CSV, numbered-list markdown, the
Llama-3 tool-result role header, and the GBNF \\uXXXX escape.
"""
from __future__ import annotations

import importlib.util

import pytest

from bastion.core.docs import writer
from bastion.core.llm import templates
from bastion.core.llm.engine import Message, Role
from bastion.core.llm.grammar import tool_call_grammar
from bastion.core.tools.office_tools import markdown_to_blocks, parse_rows


def _has(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


# -- jagged tables ----------------------------------------------------------
def test_pad_rows_squares_a_jagged_table():
    padded = writer._pad_rows([["a", "b", "c"], ["1"], ["x", "y"]])
    assert all(len(r) == 3 for r in padded)


@pytest.mark.skipif(not _has("docx"), reason="python-docx not installed")
def test_docx_jagged_table_does_not_crash():
    blocks = [{"type": "table", "rows": [["h1", "h2", "h3"], ["only one"], ["a", "b"]]}]
    data = writer.build_docx(blocks)
    assert data[:2] == b"PK"  # a real .docx (zip) came back, no IndexError


@pytest.mark.skipif(not _has("docx"), reason="python-docx not installed")
def test_docx_bold_italic_rendered_not_literal():
    data = writer.build_docx([{"type": "paragraph", "text": "a **bold** and *em* word"}])
    import io, docx
    d = docx.Document(io.BytesIO(data))
    runs = d.paragraphs[0].runs
    assert any(r.bold for r in runs) and any(r.italic for r in runs)
    assert "**" not in d.paragraphs[0].text  # asterisks consumed, not literal


# -- PDF markup safety ------------------------------------------------------
@pytest.mark.skipif(not _has("reportlab"), reason="reportlab not installed")
def test_pdf_survives_angle_and_amp():
    data = writer.build_pdf(
        [{"type": "paragraph", "text": "Voltage < 5V & current > 1A"}], title="Spec")
    assert data[:4] == b"%PDF"


@pytest.mark.skipif(not _has("reportlab"), reason="reportlab not installed")
def test_pdf_jagged_table_ok():
    data = writer.build_pdf([{"type": "table", "rows": [["a", "b"], ["1"]]}])
    assert data[:4] == b"%PDF"


# -- Excel sheet names + coercion ------------------------------------------
def test_sheet_title_sanitized():
    assert writer._sheet_title("Data/2024:Q1*[draft]?", 0) == "Data 2024 Q1  draft"
    assert len(writer._sheet_title("x" * 50, 0)) <= 31
    assert writer._sheet_title("", 2) == "Sheet3"


def test_number_coercion_is_conservative():
    assert writer._coerce("42") == 42
    assert writer._coerce("3.14") == 3.14
    assert writer._coerce("007") == "007"        # ID, not the number 7
    assert writer._coerce("Smith, John") == "Smith, John"
    assert writer._coerce("nan") == "nan"         # not float('nan')


@pytest.mark.skipif(not _has("openpyxl"), reason="openpyxl not installed")
def test_xlsx_bad_name_and_numbers(tmp_path):
    data = writer.build_xlsx([{"name": "a/b:c*[d]?", "rows": [["qty"], ["5"], ["007"]]}])
    import io, openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb.active
    assert ws["A2"].value == 5 and ws["A3"].value == "007"  # coerced vs. preserved
    assert ws.freeze_panes == "A2"


# -- CSV / markdown parsing -------------------------------------------------
def test_quoted_csv_field_survives():
    rows = parse_rows('name,age\n"Smith, John",42')
    assert rows == [["name", "age"], ["Smith, John", "42"]]


def test_numbered_lists_and_deep_headings():
    blocks = markdown_to_blocks("#### Deep\n\n1. first\n2) second\n- third")
    kinds = [b["type"] for b in blocks]
    assert kinds[0] == "heading"                 # #### handled (clamped to level 3)
    assert blocks[0]["level"] == 3
    assert kinds.count("bullet") == 3            # 1. , 2) , and -


# -- LLM: Llama-3 tool role + grammar escape --------------------------------
def test_llama3_uses_ipython_role_for_tool_results():
    rendered = templates.render(
        [Message(Role.USER, "hi"), Message(Role.TOOL, "obs", name="grep")], "llama3")
    assert "ipython" in rendered
    assert "start_header_id>tool" not in rendered


def test_grammar_allows_unicode_escape():
    g = tool_call_grammar(["read_file"])
    assert '"u"' in g and "0-9a-fA-F" in g   # \\uXXXX accepted in strings
