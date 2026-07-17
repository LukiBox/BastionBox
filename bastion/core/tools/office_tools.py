"""Office tools — read datasheets, write Word/Excel/PDF, all jailed and approved.

This is the heart of the office workflow: the agent can **read** a long PDF/DOCX/
XLSX and **write** a real .docx, .xlsx, or .pdf back into the workspace. Reads are
size-capped and (for PDFs) page-aware so a small model can work through a big
datasheet; writes show the human-readable content as an approval preview and only
commit through the path jail once the user approves.

The write tools take *model-friendly* inputs — markdown-ish text for documents,
CSV-or-JSON for spreadsheets — because a 7-14B local model emits those far more
reliably than a nested block schema.
"""
from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any

from ..agent.diffing import Diff
from ..docs import extract as _extract
from ..docs import templater as _templater
from ..docs import writer as _writer
from ..security.jail import JailViolation
from .base import Tool, ToolContext, ToolResult

_READ_CAP = 60_000  # chars returned to the model for a single read_document call


def resolve_readable(ctx: ToolContext, path_arg: str):
    """Resolve *path_arg* for READING: workspace first, then the read-only
    reference library (when attached). Write paths never come through here, so
    the library stays read-only by construction."""
    try:
        return ctx.jail.resolve(path_arg, ctx.workspace, must_exist=True)
    except JailViolation:
        if ctx.library is not None:
            return ctx.jail.resolve(path_arg, ctx.library, must_exist=True)
        raise


# ---------------------------------------------------------------------------
# input parsing helpers (kept tolerant — small models are messy)
# ---------------------------------------------------------------------------
_IMAGE_LINE = re.compile(r"^!\[(?P<caption>[^\]]*)\]\((?P<path>[^)]+)\)\s*$")
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp"}


def markdown_to_blocks(text: str) -> list[dict[str, Any]]:
    """Parse light markdown into the writer's block schema.

    `# / ## / ###` → headings, `- ` / `* ` → bullets, `a | b | c` runs → tables,
    `![caption](photos/rig.png)` on its own line → an embedded image, a fenced
    ```chart block holding a JSON spec → a rendered chart, and blank-line-
    separated text → paragraphs. Good enough for reports and summaries.
    """
    blocks: list[dict[str, Any]] = []
    table: list[list[str]] = []
    chart_lines: list[str] | None = None   # inside a ```chart fence when a list

    def flush_table():
        nonlocal table
        if table:
            blocks.append({"type": "table", "rows": table})
            table = []

    for line in text.splitlines():
        s = line.rstrip()
        if chart_lines is not None:                     # collecting a chart fence
            if s.strip().startswith("```"):
                blocks.append({"type": "chart",
                               "spec": "\n".join(chart_lines).strip()})
                chart_lines = None
            else:
                chart_lines.append(line)
            continue
        if s.strip().lower().startswith("```chart"):
            flush_table()
            chart_lines = []
            continue
        img = _IMAGE_LINE.match(s.strip())
        if img:
            flush_table()
            blocks.append({"type": "image", "path": img.group("path").strip(),
                           "caption": img.group("caption").strip()})
            continue
        if "|" in s and s.strip().strip("|").strip():
            cells = [c.strip() for c in s.strip().strip("|").split("|")]
            if set("".join(cells)) <= set("-: "):  # markdown separator row
                continue
            table.append(cells)
            continue
        flush_table()
        if not s.strip():
            continue
        heading = re.match(r"(#{1,6})\s+(.*)", s)
        numbered = re.match(r"\s*\d{1,3}[.)]\s+(.*)", s)
        if heading:
            blocks.append({"type": "heading",
                           "level": min(3, len(heading.group(1))),
                           "text": heading.group(2)})
        elif s.lstrip().startswith(("- ", "* ", "• ")):
            blocks.append({"type": "bullet", "text": s.lstrip()[2:].lstrip()})
        elif numbered:
            blocks.append({"type": "bullet", "text": numbered.group(1)})
        else:
            blocks.append({"type": "paragraph", "text": s})
    flush_table()
    if chart_lines is not None:   # unterminated fence — still try to render it
        blocks.append({"type": "chart", "spec": "\n".join(chart_lines).strip()})
    return blocks


def parse_rows(data: Any) -> list[list[Any]]:
    """Turn a model's tabular input into rows. Accepts a JSON 2-D array, a JSON
    array of objects, or CSV/TSV text."""
    if isinstance(data, list):
        return _rows_from_list(data)
    text = str(data).strip()
    if text.startswith("[") or text.startswith("{"):
        try:
            return _rows_from_list(json.loads(text))
        except json.JSONDecodeError:
            pass
    if not text:
        return []
    # CSV/TSV via the csv module so quoted fields ("Smith, John") survive.
    sep = "\t" if "\t" in text.splitlines()[0] else ","
    rows = []
    for record in csv.reader(io.StringIO(text), delimiter=sep):
        if any(c.strip() for c in record):
            rows.append([c.strip() for c in record])
    return rows


def _rows_from_list(data: list) -> list[list[Any]]:
    if data and isinstance(data[0], dict):
        headers = list(data[0].keys())
        return [headers] + [[row.get(h, "") for h in headers] for row in data]
    return [list(r) if isinstance(r, (list, tuple)) else [r] for r in data]


# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------
class ReadDocument(Tool):
    name = "read_document"
    description = ("Extract text from a PDF, Word (.docx), or Excel (.xlsx) file in "
                   "the workspace — e.g. read a long datasheet. Returns text, "
                   "page-aware for PDFs. Use before writing a summary.")
    args = {"path": "workspace-relative path to the document",
            "pages": "optional PDF page range like '1-5' (default: all, capped)"}

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        try:
            real = resolve_readable(ctx, args.get("path", ""))
        except JailViolation as exc:
            return ToolResult.error(str(exc))
        if not _extract.supported(real):
            return ToolResult.error(f"unsupported document type: {real.suffix}")
        try:
            doc = _extract.extract(real)
        except _extract.ExtractionUnavailable as exc:
            return ToolResult.error(str(exc))
        except Exception as exc:  # noqa: BLE001 - corrupt file etc.
            return ToolResult.error(f"could not read {args['path']}: {exc}")
        ctx.audit.log_tool_call(self.name, {"path": args.get("path"),
                                            "kind": doc.kind, "pages": doc.page_count})
        text = self._select_pages(doc, args.get("pages"))
        if text is None:   # page range entirely out of bounds — say so plainly
            return ToolResult.error(
                f"page range {args.get('pages')!r} is out of bounds — "
                f"{args['path']} has {doc.page_count} page(s)")
        header = (f"{args['path']} [{doc.kind}"
                  + (f", {doc.page_count} pages" if doc.page_count else "") + "]")
        # Cap the returned text to what fits the loaded model's context (leaving
        # room for the system prompt and the reply). A full datasheet dumped raw
        # used to overflow the window and crash the turn; now it truncates and
        # tells the model how to read the rest.
        cap = getattr(ctx, "read_char_cap", _READ_CAP) or _READ_CAP
        truncated = ""
        if len(text) > cap:
            text = text[:cap]
            hint = ("request specific pages with the 'pages' argument (e.g. "
                    "'1-3', then '4-6')" if doc.page_count else
                    "summarize this portion, then read on if the file has more")
            truncated = (f"\n\n[truncated at {cap:,} chars to fit the context "
                         f"window — {hint} to read further; summarize as you go]")
        return ToolResult(True, f"{header}:\n{text}{truncated}",
                          meta={"kind": doc.kind, "pages": doc.page_count})

    @staticmethod
    def _select_pages(doc, pages: str | None) -> str | None:
        """Return the requested pages' text; ``None`` if the range misses the
        document entirely (so the model is told instead of seeing silence)."""
        if not pages or not doc.pages:
            return doc.text
        try:
            a, _, b = pages.partition("-")
            start = max(1, int(a))
            end = int(b) if b else start
            selected = doc.pages[start - 1:end]
            if not selected:
                return None
            return "\n".join(f"[page {start + i}]\n{p}"
                             for i, p in enumerate(selected))
        except (ValueError, IndexError):
            return doc.text


class _BinaryWriteTool(Tool):
    """Shared machinery for write_document / write_spreadsheet: preview → approve
    → render bytes → commit through the jail → audit."""

    def _commit(self, ctx: ToolContext, path_arg: str, preview: str,
                render, kind: str) -> ToolResult:
        try:
            real = ctx.jail.resolve(path_arg, ctx.workspace)
        except JailViolation as exc:
            return ToolResult.error(str(exc))
        # Show the human-readable content as the approval preview (binary files
        # have no meaningful text diff; the source content is what matters).
        diff = Diff(path=path_arg, before="", after=preview,
                    is_new_file=not real.exists())
        decision = ctx.broker.request_write(ctx.workspace, diff)
        ctx.audit.log_decision(f"write {path_arg}", decision.approved,
                               actor="user", note=decision.note)
        if not decision.approved:
            return ToolResult.rejected(decision.note or f"{kind} write not approved")
        try:
            data = render()
        except _extract.ExtractionUnavailable as exc:
            return ToolResult.error(str(exc))
        except Exception as exc:  # noqa: BLE001 - a bad block must not kill the loop
            return ToolResult.error(
                f"could not render {kind}: {type(exc).__name__}: {exc}")
        real.parent.mkdir(parents=True, exist_ok=True)
        real.write_bytes(data)
        ctx.audit.log_file_write(str(real), len(data), diff.sha256)
        return ToolResult(True, f"wrote {kind} {path_arg} ({len(data):,} bytes)",
                          meta={"path": str(real)})


class WriteDocument(_BinaryWriteTool):
    name = "write_document"
    description = ("Create a Word (.docx), PDF, or self-contained HTML report "
                   "from markdown-style content "
                   "(# headings, - bullets, 'a | b' tables). Embed a workspace/"
                   "library photo with ![caption](photos/rig.png) on its own line. "
                   "Render a chart from a fenced block: ```chart {\"type\": "
                   "\"bar|line|pie\", \"title\": \"...\", \"labels\": [...], "
                   "\"series\": [{\"name\": \"...\", \"values\": [...]}]} ``` . "
                   "Extension picks the format (.html embeds charts/photos as "
                   "base64 — one portable file). Shows the content for approval "
                   "before writing.")
    args = {"path": "workspace-relative .docx, .pdf, or .html path",
            "title": "document title",
            "content": ("markdown-style body text; may include ![caption](img) "
                        "lines and ```chart JSON fences")}

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        path = args.get("path", "")
        title = args.get("title", "")
        content = args.get("content", "")
        if not path:
            return ToolResult.error("empty path")
        # Backstop against the "plan pasted as content" failure: a short body
        # that is mostly unchecked checklist lines is the agent's own notepad
        # leaking out, not a document anyone asked for. Reject with guidance —
        # a real report is never a bare '- [ ]' list.
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        boxes = sum(1 for ln in lines if ln.startswith("- [ ]"))
        if boxes >= 2 and len(content.strip()) < 500:
            return ToolResult.error(
                "the content looks like your plan checklist, not a document. "
                "Write the actual substance (the facts, findings, and numbers "
                "from the files you read), then call write_document again.")
        blocks = markdown_to_blocks(content)
        problem = self._prepare_media(ctx, blocks)
        if problem is not None:
            return problem
        preview = (f"# {title}\n\n{content}" if title else content)
        suffix = Path(path).suffix.lower()
        if suffix == ".pdf":
            render = lambda: _writer.build_pdf(blocks, title=title)
            kind = "PDF"
        elif suffix == ".docx":
            head = [{"type": "heading", "level": 1, "text": title}] if title else []
            render = lambda: _writer.build_docx(head + blocks)
            kind = "Word document"
        elif suffix in (".html", ".htm"):
            render = lambda: _writer.build_html(blocks, title=title)
            kind = "HTML report"
        else:
            return ToolResult.error("path must end in .docx, .pdf, or .html")
        return self._commit(ctx, path, preview, render, kind)

    @staticmethod
    def _prepare_media(ctx: ToolContext, blocks: list[dict[str, Any]]) -> ToolResult | None:
        """Resolve embedded photos through the jail and validate chart specs
        up front — a bad reference becomes a clear observation the model can
        fix, never a render crash after the user already approved."""
        from ..docs import charts as _charts
        for b in blocks:
            if b.get("type") == "image":
                try:
                    real = resolve_readable(ctx, b["path"])
                except JailViolation as exc:
                    return ToolResult.error(f"image {b['path']!r}: {exc}")
                if real.suffix.lower() not in _IMAGE_SUFFIXES:
                    return ToolResult.error(
                        f"image {b['path']!r}: unsupported type {real.suffix!r} "
                        f"— use png/jpg/jpeg/gif/bmp")
                b["data"] = real.read_bytes()
            elif b.get("type") == "chart":
                try:
                    b["spec"] = _charts.normalize_spec(b.get("spec"))
                except _charts.ChartError as exc:
                    return ToolResult.error(f"chart block: {exc}")
        return None


class WriteSpreadsheet(_BinaryWriteTool):
    name = "write_spreadsheet"
    description = ("Create an Excel (.xlsx) file from tabular data — CSV/TSV text "
                   "or a JSON array (of arrays, or of objects). First row is the "
                   "header. Optional chart arg adds a native Excel chart of the "
                   "data (first column = categories). Shows the data for approval "
                   "before writing.")
    args = {"path": "workspace-relative .xlsx path",
            "data": "CSV/TSV text or JSON rows", "sheet": "optional sheet name",
            "chart": ("optional JSON {\"type\": \"bar|line|pie\", "
                      "\"title\": \"...\"} to chart the data")}

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        path = args.get("path", "")
        if not path or Path(path).suffix.lower() not in (".xlsx", ".xlsm"):
            return ToolResult.error("path must end in .xlsx")
        rows = parse_rows(args.get("data", ""))
        if not rows:
            return ToolResult.error("no rows parsed from data")
        chart = FillTemplate._as_dict(args.get("chart"))
        if chart is None:
            return ToolResult.error(
                "chart must be a JSON object like {\"type\": \"bar\", "
                "\"title\": \"...\"}")
        kind = str(chart.get("type", "bar")).strip().lower() if chart else "bar"
        if chart and kind not in ("bar", "line", "pie"):
            return ToolResult.error(
                f"unknown chart type {kind!r} — use bar, line, or pie")
        preview = "\n".join(" | ".join(str(c) for c in r) for r in rows[:30])
        if chart:
            preview += f"\n[+ native {kind} chart: {chart.get('title', '')}]"
        sheet = {"name": args.get("sheet", "Sheet1"), "rows": rows,
                 "chart": chart or None}
        return self._commit(ctx, path, preview,
                            lambda: _writer.build_xlsx([sheet]), "spreadsheet")


class FillTemplate(_BinaryWriteTool):
    name = "fill_template"
    description = ("Fill a business .docx TEMPLATE (company logo/formatting kept "
                   "intact): replaces {{KEY}} text placeholders, {{IMG:name}} "
                   "photo placeholders, and {{TABLE:name}} data-table rows. "
                   "Template may live in the workspace or the reference library. "
                   "Values: fields is a JSON object of placeholder→text; a value "
                   "that is a 2-D array fills the matching {{TABLE:...}}; images "
                   "maps name→image path. Shows the mapping for approval.")
    args = {"template": "path to the .docx template (workspace or library)",
            "path": "workspace-relative output .docx path",
            "fields": "JSON object: {\"TITLE\": \"...\", \"results\": [[...],...]}",
            "images": "optional JSON object: {\"photo1\": \"photos/rig.png\"}"}

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        out_path = args.get("path", "")
        if not out_path or Path(out_path).suffix.lower() != ".docx":
            return ToolResult.error("output path must end in .docx")
        try:
            template = resolve_readable(ctx, args.get("template", ""))
        except JailViolation as exc:
            return ToolResult.error(str(exc))
        if template.suffix.lower() != ".docx":
            return ToolResult.error("template must be a .docx file")

        raw_fields = self._as_dict(args.get("fields"))
        if raw_fields is None:
            return ToolResult.error("fields must be a JSON object of "
                                    "placeholder → value")
        raw_images = self._as_dict(args.get("images")) or {}
        # Split table values (2-D arrays) out of the plain text fields.
        fields: dict[str, Any] = {}
        tables: dict[str, list] = {}
        for k, v in raw_fields.items():
            if isinstance(v, list) and v and all(isinstance(r, (list, tuple))
                                                 for r in v):
                tables[str(k)] = [list(r) for r in v]
            else:
                fields[str(k)] = v
        # Resolve image paths through the jail (workspace or library, read side).
        images: dict[str, Path] = {}
        for name, p in raw_images.items():
            try:
                images[str(name)] = resolve_readable(ctx, str(p))
            except JailViolation as exc:
                return ToolResult.error(f"image {name!r}: {exc}")

        preview_lines = [f"TEMPLATE: {args.get('template')}"]
        preview_lines += [f"{{{{{k}}}}} ← {str(v)[:120]}" for k, v in fields.items()]
        preview_lines += [f"{{{{TABLE:{k}}}}} ← {len(v)} data row(s)"
                          for k, v in tables.items()]
        preview_lines += [f"{{{{IMG:{k}}}}} ← {p}" for k, p in raw_images.items()]
        preview = "\n".join(preview_lines)

        result: dict[str, Any] = {}

        def render() -> bytes:
            data, leftover = _templater.fill_docx_template(
                template, fields=fields, images=images, tables=tables)
            result["leftover"] = leftover
            return data

        outcome = self._commit(ctx, out_path, preview, render, "filled template")
        if outcome.ok and result.get("leftover"):
            outcome.observation += ("\nWARNING — unfilled placeholders left in "
                                    "the document: "
                                    + ", ".join(result["leftover"])
                                    + ". Call fill_template again with values "
                                      "for them if they matter.")
        return outcome

    @staticmethod
    def _as_dict(value: Any) -> dict | None:
        if isinstance(value, dict):
            return value
        if value is None or (isinstance(value, str) and not value.strip()):
            return {}
        try:
            parsed = json.loads(str(value))
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None


OFFICE_TOOLS: dict[str, Tool] = {
    t.name: t for t in (ReadDocument(), WriteDocument(), WriteSpreadsheet(),
                        FillTemplate())
}
