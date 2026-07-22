"""Offline chart rendering — bar, line, and pie charts for AI-written documents.

Local models describe a chart as a tiny JSON spec; this module turns it into a
reportlab :class:`Drawing`. PDFs embed the drawing directly (true vector art);
Word documents get a crisp PNG rasterized through PyMuPDF. Both paths use only
libraries BastionBox already ships — no matplotlib, no new attack surface.

The spec is deliberately forgiving because small models are messy::

    {"type": "bar" | "line" | "pie",
     "title": "Power draw by mode",
     "labels": ["Idle", "Cruise", "Peak"],
     "series": [{"name": "Unit A", "values": [4.2, 18, 45]},
                {"name": "Unit B", "values": [3.9, 17, 44]}]}

``series`` may also be a flat list of numbers (one unnamed series) or a
``{name: values}`` mapping. Values arrive as strings half the time; they are
coerced. Anything unrecoverable raises :class:`ChartError` with a message the
agent can read and fix.
"""
from __future__ import annotations

import io
import json
from typing import Any

#: Series colors: the brand sage first, then muted companions that hold up
#: in both print and the app's light/dark cards.
SERIES_COLORS = ("#54806C", "#5B7A99", "#C2A878", "#A96A5B", "#8FB6A5", "#3E5F52")
_TEXT = "#22312B"
_TEXT_DIM = "#5C6B63"
_GRID = "#D8E2DC"

VALID_TYPES = ("bar", "line", "pie")


class ChartError(ValueError):
    """A chart spec problem, worded so the model can correct its next call."""


def normalize_spec(spec: Any) -> dict[str, Any]:
    """Validate and canonicalize a chart spec (dict or JSON string).

    Returns ``{"type", "title", "labels", "series": [{"name", "values"}, ...]}``
    with float values and labels/series padded to matching length.
    """
    if isinstance(spec, str):
        try:
            spec = json.loads(spec)
        except json.JSONDecodeError as exc:
            raise ChartError(f"chart spec is not valid JSON: {exc}") from exc
    if not isinstance(spec, dict):
        raise ChartError("chart spec must be a JSON object with "
                         "'type', 'labels' and 'series'")

    kind = str(spec.get("type", "bar")).strip().lower()
    if kind not in VALID_TYPES:
        raise ChartError(f"unknown chart type {kind!r} — use one of "
                         + ", ".join(VALID_TYPES))

    labels = [str(l) for l in spec.get("labels") or []]
    series = _normalize_series(spec.get("series"))
    if not series:
        raise ChartError("chart needs at least one series of numeric values")

    # Pad the short side so axes and slices always line up.
    width = max(len(labels), max(len(s["values"]) for s in series))
    labels += [f"#{i + 1}" for i in range(len(labels), width)]
    for s in series:
        s["values"] += [0.0] * (width - len(s["values"]))
    return {"type": kind, "title": str(spec.get("title", "") or ""),
            "labels": labels, "series": series}


def _normalize_series(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if isinstance(raw, dict):                       # {name: values}
        raw = [{"name": k, "values": v} for k, v in raw.items()]
    if isinstance(raw, (int, float)):
        raw = [raw]
    if isinstance(raw, list) and raw and not isinstance(raw[0], (dict, list)):
        raw = [{"name": "", "values": raw}]         # flat list → one series
    if isinstance(raw, list) and raw and isinstance(raw[0], list):
        raw = [{"name": "", "values": r} for r in raw]
    out: list[dict[str, Any]] = []
    for i, s in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(s, dict):
            continue
        values = s.get("values", s.get("data", []))
        if isinstance(values, (int, float, str)):
            values = [values]
        out.append({"name": str(s.get("name", "") or f"Series {i + 1}"),
                    "values": [_number(v) for v in values]})
    return [s for s in out if s["values"]]


def _number(v: Any) -> float:
    try:
        return float(str(v).replace(",", ".").strip())
    except (TypeError, ValueError) as exc:
        raise ChartError(f"chart value {v!r} is not a number") from exc


def chart_table(spec: Any) -> list[list[str]]:
    """Degrade a chart spec to a plain data table (header + one row per series).

    Used when no rendering engine is available (e.g. reportlab absent on a
    partial install) so a report never hard-fails: the numbers survive even if
    the picture can't be drawn. Header is the title/label row; each series is a
    row of its values. Raises :class:`ChartError` only if the spec itself is
    unusable — callers treat that as "skip this block", not "abort the report".
    """
    spec = normalize_spec(spec)
    header = [spec["title"] or "Series", *spec["labels"]]
    rows = [header]
    for s in spec["series"]:
        rows.append([s["name"] or "", *[f"{v:g}" for v in s["values"]]])
    return rows


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------
def build_drawing(spec: dict[str, Any], width: int = 460, height: int = 250):
    """Render a normalized spec to a reportlab Drawing (a PDF flowable)."""
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.lib.colors import HexColor

    spec = normalize_spec(spec)
    d = Drawing(width, height)
    top = height
    if spec["title"]:
        top -= 18
        d.add(String(width / 2, top + 4, spec["title"],
                     fontName="Helvetica-Bold", fontSize=11,
                     fillColor=HexColor(_TEXT), textAnchor="middle"))
    if spec["type"] == "pie":
        _add_pie(d, spec, width, top)
    else:
        _add_axes_chart(d, spec, width, top)
    return d


def _add_axes_chart(d, spec, width, top) -> None:
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.charts.linecharts import HorizontalLineChart
    from reportlab.lib.colors import HexColor

    multi = len(spec["series"]) > 1
    legend_h = 16 if multi else 0
    chart = VerticalBarChart() if spec["type"] == "bar" else HorizontalLineChart()
    chart.x, chart.y = 42, 28 + legend_h
    chart.width, chart.height = width - 60, top - chart.y - 12
    chart.data = [tuple(s["values"]) for s in spec["series"]]
    chart.categoryAxis.categoryNames = spec["labels"]
    chart.categoryAxis.labels.fontName = "Helvetica"
    chart.categoryAxis.labels.fontSize = 8
    chart.categoryAxis.labels.fillColor = HexColor(_TEXT_DIM)
    chart.valueAxis.labels.fontName = "Helvetica"
    chart.valueAxis.labels.fontSize = 8
    chart.valueAxis.labels.fillColor = HexColor(_TEXT_DIM)
    chart.valueAxis.visibleGrid = 1
    chart.valueAxis.gridStrokeColor = HexColor(_GRID)
    chart.valueAxis.strokeColor = HexColor(_GRID)
    chart.categoryAxis.strokeColor = HexColor(_GRID)
    for i in range(len(spec["series"])):
        color = HexColor(SERIES_COLORS[i % len(SERIES_COLORS)])
        if spec["type"] == "bar":
            chart.bars[i].fillColor = color
            chart.bars[i].strokeColor = None
        else:
            chart.lines[i].strokeColor = color
            chart.lines[i].strokeWidth = 2
    d.add(chart)
    if multi:
        _add_legend(d, spec, width, y=10)


def _add_pie(d, spec, width, top) -> None:
    from reportlab.graphics.charts.piecharts import Pie
    from reportlab.lib.colors import HexColor

    values = spec["series"][0]["values"]
    pie = Pie()
    size = min(width - 200, top - 40)
    pie.width = pie.height = max(80, size)
    pie.x = 30
    pie.y = (top - pie.height) / 2
    pie.data = values
    total = sum(values) or 1.0
    pie.labels = None                     # a legend reads better than spokes
    pie.slices.strokeColor = HexColor("#FFFFFF")
    pie.slices.strokeWidth = 1
    for i in range(len(values)):
        pie.slices[i].fillColor = HexColor(SERIES_COLORS[i % len(SERIES_COLORS)])
    d.add(pie)
    _add_legend(d, spec, width, y=pie.y + pie.height - 10,
                x=pie.x + pie.width + 28, columns=1,
                names=[f"{lbl}  —  {v:g} ({v / total:.0%})"
                       for lbl, v in zip(spec["labels"], values)])


def _add_legend(d, spec, width, y, x=None, columns=0, names=None) -> None:
    from reportlab.graphics.charts.legends import Legend
    from reportlab.lib.colors import HexColor

    legend = Legend()
    legend.alignment = "right"
    legend.fontName = "Helvetica"
    legend.fontSize = 8
    legend.fillColor = HexColor(_TEXT)
    legend.strokeColor = None
    items = names if names is not None else [s["name"] for s in spec["series"]]
    legend.colorNamePairs = [
        (HexColor(SERIES_COLORS[i % len(SERIES_COLORS)]), n)
        for i, n in enumerate(items)]
    legend.x = x if x is not None else 42
    legend.y = y
    if columns:
        legend.columnMaximum = max(len(items) // columns + 1, 1)
        legend.deltay = 14
    else:
        legend.columnMaximum = 1
        legend.deltax = max(60, (width - 84) // max(len(items), 1))
    d.add(legend)


def chart_png(spec: dict[str, Any], scale: float = 2.0) -> bytes:
    """Rasterize a chart to PNG bytes (for .docx embedding).

    The drawing goes through a one-page in-memory PDF and PyMuPDF's renderer —
    both already bundled — so no separate raster backend is needed.
    """
    from reportlab.graphics import renderPDF

    drawing = build_drawing(spec)
    pdf = renderPDF.drawToString(drawing)
    try:
        import fitz
        with fitz.open(stream=pdf, filetype="pdf") as doc:
            pix = doc[0].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            return pix.tobytes("png")
    except ImportError:
        # Fallback raster path (PIL-based) if PyMuPDF is ever absent.
        from reportlab.graphics import renderPM
        buf = io.BytesIO()
        renderPM.drawToFile(drawing, buf, fmt="PNG", dpi=int(72 * scale))
        return buf.getvalue()
