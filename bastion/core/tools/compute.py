"""Deterministic computation tools — exact math and file fingerprinting.

A local model must never do arithmetic "in its head": a 30B model asked for
``rho = p / (287.05 * T)`` will often be off in the third digit, which is fatal
for lab reports and financial statements. ``calculate`` evaluates the math
exactly, in a whitelisted AST sandbox that can express formulas but *cannot*
touch names, attributes, imports, or I/O — pure math, no wall risk.

``find_duplicates`` does the whole duplicate-detection job (hashing, size and
normalized-text comparison, grouping) inside the tool and hands the model
finished groups. Pushing the comparison into deterministic code instead of the
context window is what makes "scan my folder for duplicates" reliable.
"""
from __future__ import annotations

import ast
import hashlib
import math
import re
from typing import Any

from ..security.jail import JailViolation
from .base import Tool, ToolContext, ToolResult

# -- calculate ---------------------------------------------------------------

_ALLOWED_FUNCS: dict[str, Any] = {
    "sqrt": math.sqrt, "exp": math.exp, "log": math.log, "log10": math.log10,
    "log2": math.log2, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "atan2": math.atan2, "degrees": math.degrees, "radians": math.radians,
    "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
}
_ALLOWED_CONSTS: dict[str, float] = {"pi": math.pi, "e": math.e}

_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
                   ast.Mod, ast.Pow)
_ALLOWED_UNARY = (ast.UAdd, ast.USub)

_MAX_STATEMENTS = 50
_MAX_ABS = 1e150          # refuse results/operands beyond this magnitude
_MAX_POW_EXP = 512


class _CalcError(ValueError):
    pass


def _eval_node(node: ast.AST, names: dict[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, names)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise _CalcError(f"only numbers are allowed, not {node.value!r}")
        return node.value
    if isinstance(node, ast.Name):
        if node.id in names:
            return names[node.id]
        if node.id in _ALLOWED_CONSTS:
            return _ALLOWED_CONSTS[node.id]
        raise _CalcError(f"unknown variable {node.id!r} — assign it first, "
                         f"e.g. '{node.id} = 1.5'")
    if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_BINOPS):
        left = _eval_node(node.left, names)
        right = _eval_node(node.right, names)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_POW_EXP:
            raise _CalcError(f"exponent {right} too large")
        if isinstance(node.op, (ast.Div, ast.Mod, ast.FloorDiv)) and right == 0:
            raise _CalcError("division by zero")
        result = {
            ast.Add: lambda: left + right, ast.Sub: lambda: left - right,
            ast.Mult: lambda: left * right, ast.Div: lambda: left / right,
            ast.FloorDiv: lambda: left // right, ast.Mod: lambda: left % right,
            ast.Pow: lambda: left ** right,
        }[type(node.op)]()
        if isinstance(result, complex) or not math.isfinite(result) \
                or abs(result) > _MAX_ABS:
            raise _CalcError("result out of range")
        return result
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, _ALLOWED_UNARY):
        val = _eval_node(node.operand, names)
        return val if isinstance(node.op, ast.UAdd) else -val
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
            raise _CalcError("only these functions are allowed: "
                             + ", ".join(sorted(_ALLOWED_FUNCS)))
        if node.keywords:
            raise _CalcError("keyword arguments are not supported")
        args = [_eval_node(a, names) for a in node.args]
        result = _ALLOWED_FUNCS[node.func.id](*args)
        if not isinstance(result, (int, float)) or not math.isfinite(result):
            raise _CalcError("result out of range")
        return result
    raise _CalcError(f"unsupported syntax: {type(node).__name__} — use plain "
                     f"arithmetic, assignments, and math functions")


def _fmt_num(v: float) -> str:
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        return str(int(v))
    return f"{v:.10g}"


def evaluate(expression: str) -> list[tuple[str, float]]:
    """Evaluate ``a = ...; b = ...; final_expr`` and return (name, value) pairs.

    Statements are separated by ';' or newlines. Assignments bind variables for
    later statements; a bare expression's value is reported as ``result``.
    Raises :class:`_CalcError` with a model-actionable message on any problem.
    """
    statements = [s.strip() for s in re.split(r"[;\n]+", expression) if s.strip()]
    if not statements:
        raise _CalcError("empty expression")
    if len(statements) > _MAX_STATEMENTS:
        raise _CalcError(f"too many statements (max {_MAX_STATEMENTS})")
    names: dict[str, float] = {}
    out: list[tuple[str, float]] = []
    for stmt in statements:
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?!=)(.+)$", stmt)
        try:
            if m and m.group(1) not in _ALLOWED_FUNCS \
                    and m.group(1) not in _ALLOWED_CONSTS:
                tree = ast.parse(m.group(2), mode="eval")
                val = _eval_node(tree, names)
                names[m.group(1)] = val
                out.append((m.group(1), val))
            else:
                tree = ast.parse(stmt, mode="eval")
                val = _eval_node(tree, names)
                out.append(("result", val))
        except SyntaxError as exc:
            raise _CalcError(f"syntax error in {stmt!r}: {exc.msg}") from exc
    return out


class Calculate(Tool):
    name = "calculate"
    description = ("Evaluate math EXACTLY. Use this for ALL arithmetic — sums, "
                   "unit conversions, physics/finance formulas — never compute "
                   "numbers in your head. Separate steps with ';': "
                   "'p = 751 * 133.322; rho = p / (287.05 * 299.65); rho'. "
                   "Assignments carry forward within the call; the last bare "
                   "expression is the result. Functions: sqrt, exp, log, log10, "
                   "sin/cos/tan(radians), atan2, degrees, radians, abs, round, "
                   "min, max; constants pi, e.")
    args = {"expression": "math statements separated by ';' (or newlines)"}

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        expression = str(args.get("expression", ""))
        ctx.audit.log_tool_call(self.name, {"expression": expression[:300]})
        try:
            pairs = evaluate(expression)
        except _CalcError as exc:
            return ToolResult.error(str(exc))
        lines = [f"{name} = {_fmt_num(val)}" for name, val in pairs]
        return ToolResult(True, "\n".join(lines),
                          meta={"result": pairs[-1][1]})


# -- find_duplicates ----------------------------------------------------------

_SCAN_FILE_CAP = 2_000            # max files examined per scan
_FULL_HASH_CAP = 64 * 1024 * 1024  # full-content hash up to 64 MB
_PARTIAL_CHUNK = 4 * 1024 * 1024   # bigger files: hash first 4 MB + size
_TEXT_NORM_CAP = 2 * 1024 * 1024   # normalized text hash for files up to 2 MB

_KIND_MAGIC: list[tuple[bytes, str]] = [
    (b"%PDF", "pdf"), (b"\x89PNG", "png"), (b"\xff\xd8", "jpeg"),
    (b"GIF8", "gif"), (b"PK\x03\x04", "zip-container (docx/xlsx/pptx/zip)"),
    (b"BM", "bmp"), (b"\x7fELF", "elf"), (b"MZ", "exe/dll"),
]


def _sniff_kind(head: bytes) -> str:
    for magic, kind in _KIND_MAGIC:
        if head.startswith(magic):
            return kind
    sample = head[:512]
    if sample and (b"\x00" not in sample):
        return "text"
    return "binary"


class FindDuplicates(Tool):
    name = "find_duplicates"
    description = ("Scan a folder (recursively) for duplicate files and return "
                   "them GROUPED: exact duplicates (identical content even if "
                   "names/extensions differ), near-duplicates (same text after "
                   "normalizing whitespace/case), and same-size candidates. "
                   "Report the returned groups to the user — the comparison "
                   "itself is already done.")
    args = {"path": "workspace-relative folder to scan (default: whole workspace)"}

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        try:
            root = ctx.jail.resolve(args.get("path", ".") or ".", ctx.workspace,
                                    must_exist=True)
        except JailViolation as exc:
            return ToolResult.error(str(exc))
        if not root.is_dir():
            return ToolResult.error(f"{args.get('path')} is not a directory")
        ctx.audit.log_tool_call(self.name, {"path": args.get("path", ".")})

        infos: list[dict[str, Any]] = []
        capped = False
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            if len(infos) >= _SCAN_FILE_CAP:
                capped = True
                break
            try:
                size = p.stat().st_size
                with open(p, "rb") as fh:
                    if size <= _FULL_HASH_CAP:
                        data = fh.read()
                        digest = hashlib.sha256(data).hexdigest()
                        partial = False
                    else:
                        data = fh.read(_PARTIAL_CHUNK)
                        digest = hashlib.sha256(data).hexdigest() + f"+{size}"
                        partial = True
            except OSError:
                continue
            head = data[:512]
            kind = _sniff_kind(head)
            norm = None
            if kind == "text" and size <= _TEXT_NORM_CAP:
                text = data.decode("utf-8", errors="replace")
                norm = hashlib.sha256(
                    re.sub(r"\s+", " ", text).strip().lower().encode()).hexdigest()
            infos.append({"rel": p.relative_to(root).as_posix(), "size": size,
                          "sha": digest, "kind": kind, "norm": norm,
                          "partial": partial})

        if not infos:
            return ToolResult(True, "no files found to compare")

        by_sha: dict[str, list[dict]] = {}
        for i in infos:
            by_sha.setdefault(i["sha"], []).append(i)
        exact = [g for g in by_sha.values() if len(g) > 1]
        in_exact = {i["rel"] for g in exact for i in g}

        # Near-duplicates: same normalized text across ≥2 *different* contents.
        # Exact-group members stay eligible — an exact copy of A can still be a
        # near-duplicate of B, and hiding that would under-report.
        by_norm: dict[str, list[dict]] = {}
        for i in infos:
            if i["norm"]:
                by_norm.setdefault(i["norm"], []).append(i)
        near = [g for g in by_norm.values()
                if len({i["sha"] for i in g}) > 1]
        in_near = {i["rel"] for g in near for i in g}

        by_size: dict[int, list[dict]] = {}
        for i in infos:
            if i["rel"] not in in_exact and i["rel"] not in in_near:
                by_size.setdefault(i["size"], []).append(i)
        same_size = [g for g in by_size.values() if len(g) > 1]

        def _kb(n: int) -> str:
            return f"{n/1024:.1f} KB" if n >= 1024 else f"{n} B"

        lines = [f"scanned {len(infos)} file(s) under {args.get('path', '.') or '.'}"
                 + (" [scan capped — results may be incomplete]" if capped else "")]
        if exact:
            lines.append(f"\nEXACT DUPLICATES ({len(exact)} group(s), "
                         f"identical content):")
            for n, g in enumerate(exact, 1):
                mark = " [first 4MB compared]" if g[0]["partial"] else ""
                lines.append(f"  group {n} — {_kb(g[0]['size'])}, "
                             f"{g[0]['kind']}{mark}:")
                lines += [f"    - {i['rel']}" for i in g]
        if near:
            lines.append(f"\nNEAR-DUPLICATES ({len(near)} group(s), same text "
                         f"after normalizing whitespace/case):")
            for n, g in enumerate(near, 1):
                lines.append(f"  group {n}:")
                lines += [f"    - {i['rel']} ({_kb(i['size'])})" for i in g]
        if same_size:
            lines.append(f"\nSAME SIZE, different content ({len(same_size)} "
                         f"group(s) — possible related versions):")
            for n, g in enumerate(same_size, 1):
                lines.append(f"  group {n} — {_kb(g[0]['size'])}:")
                lines += [f"    - {i['rel']} ({i['kind']})" for i in g]
        if not (exact or near or same_size):
            lines.append("no duplicates found — every file is unique in "
                         "content, normalized text, and size.")
        body = "\n".join(lines)
        if len(body) > 12_000:
            body = body[:12_000] + "\n[…output clipped — narrow the scan to a subfolder…]"
        return ToolResult(True, body,
                          meta={"files": len(infos), "exact_groups": len(exact),
                                "near_groups": len(near)})


#: Deterministic-computation toolbox, keyed by name.
COMPUTE_TOOLS: dict[str, Tool] = {
    t.name: t for t in (Calculate(), FindDuplicates())
}
