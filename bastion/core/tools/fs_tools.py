"""Filesystem tools — read/write/edit/list/glob/grep, every one through the jail.

These are the hands of the agent. Each resolves its path argument through
``ctx.jail.resolve`` (so an escape is impossible), routes writes through the
permission broker with a mandatory diff preview, and records what it did in the
audit log. A tool never raises at the model: jail violations, rejections, and
errors all come back as :class:`ToolResult` observations the loop can adapt to.
"""
from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..agent.diffing import Diff
from ..security.jail import JailViolation
from .base import Tool, ToolContext, ToolResult

_MAX_READ_BYTES = 200_000

#: Document formats read_file must NEVER decode as text: raw .docx/.pdf bytes in
#: the context window are pure garbage — and prefilled through a big local model
#: on CPU they turn one step into many minutes. Redirect to read_document.
_DOCUMENT_SUFFIXES = {".docx", ".doc", ".pdf", ".xlsx", ".xlsm", ".xls",
                      ".pptx", ".ppt", ".odt", ".ods", ".epub"}


def _not_found_hint(exc: JailViolation) -> str:
    """Path-not-found errors get a nudge — the model often guesses the
    workspace's display name as a folder; '.' is where it already is."""
    msg = str(exc)
    if "not exist" in msg:
        return (f"{msg} (you are already inside the workspace — use "
                f"list_dir with path '.' to see its files)")
    return msg


class ReadFile(Tool):
    name = "read_file"
    description = ("Read a plain-text/code file inside the workspace. For "
                   "documents (.docx/.pdf/.xlsx/...) use read_document instead.")
    args = {"path": "workspace-relative path to the file"}

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        try:
            real = ctx.jail.resolve(args.get("path", ""), ctx.workspace,
                                    must_exist=True)
        except JailViolation as exc:
            return ToolResult.error(_not_found_hint(exc))
        if real.is_dir():
            return ToolResult.error(f"{args['path']} is a directory; use list_dir")
        suffix = real.suffix.lower()
        if suffix in _DOCUMENT_SUFFIXES:
            return ToolResult.error(
                f"{args['path']} is a {suffix} document — read_file only reads "
                f"plain text. Call read_document with the same path instead.")
        data = real.read_bytes()[:_MAX_READ_BYTES]
        if b"\x00" in data[:512]:
            return ToolResult.error(
                f"{args['path']} is a binary file — read_file only reads plain "
                f"text. If it is a document, try read_document.")
        # Respect the context budget exactly like read_document does: one read
        # must never flood the window, whatever the file size.
        cap = min(_MAX_READ_BYTES,
                  getattr(ctx, "read_char_cap", _MAX_READ_BYTES) or _MAX_READ_BYTES)
        text = data.decode("utf-8", errors="replace")
        truncated = ""
        if len(text) > cap:
            text = text[:cap]
            truncated = (f"\n\n[truncated at {cap:,} chars to fit the context "
                         f"window — summarize this portion first]")
        ctx.audit.log_tool_call(self.name, {"path": args.get("path")})
        return ToolResult(True, f"{args['path']}:\n{text}{truncated}",
                          meta={"path": str(real)})


class WriteFile(Tool):
    name = "write_file"
    description = ("Create or overwrite a text file. Shows a diff and requires "
                   "approval before anything is written.")
    args = {"path": "workspace-relative path", "content": "full new file content"}

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        try:
            real = ctx.jail.resolve(args.get("path", ""), ctx.workspace)
        except JailViolation as exc:
            return ToolResult.error(str(exc))
        new_content = args.get("content", "")
        before = real.read_text("utf-8", errors="replace") if real.exists() else ""
        diff = Diff(path=args["path"], before=before, after=new_content,
                    is_new_file=not real.exists())
        decision = ctx.broker.request_write(ctx.workspace, diff)
        ctx.audit.log_decision(f"write {args['path']}", decision.approved,
                               actor="user", note=decision.note)
        if not decision.approved:
            return ToolResult.rejected(decision.note or "write not approved")
        real.parent.mkdir(parents=True, exist_ok=True)
        real.write_text(new_content, encoding="utf-8")
        ctx.audit.log_file_write(str(real), len(new_content.encode()), diff.sha256)
        added, removed = diff.stats
        return ToolResult(True, f"wrote {args['path']} (+{added} −{removed})",
                          meta={"diff": diff.unified})


class EditFile(Tool):
    name = "edit_file"
    description = ("Replace an exact substring in a file (search/replace). Shows a "
                   "diff and requires approval. The search text must be unique.")
    args = {"path": "workspace-relative path", "search": "exact text to find",
            "replace": "text to replace it with"}

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        try:
            real = ctx.jail.resolve(args.get("path", ""), ctx.workspace,
                                    must_exist=True)
        except JailViolation as exc:
            return ToolResult.error(str(exc))
        before = real.read_text("utf-8", errors="replace")
        search, replace = args.get("search", ""), args.get("replace", "")
        count = before.count(search)
        if not search:
            return ToolResult.error("empty search text")
        if count == 0:
            return ToolResult.error(f"search text not found in {args['path']}")
        if count > 1:
            return ToolResult.error(
                f"search text appears {count} times in {args['path']}; make it "
                f"unique (include surrounding lines)")
        after = before.replace(search, replace, 1)
        diff = Diff(path=args["path"], before=before, after=after)
        decision = ctx.broker.request_write(ctx.workspace, diff)
        ctx.audit.log_decision(f"edit {args['path']}", decision.approved,
                               actor="user", note=decision.note)
        if not decision.approved:
            return ToolResult.rejected(decision.note or "edit not approved")
        real.write_text(after, encoding="utf-8")
        ctx.audit.log_file_write(str(real), len(after.encode()), diff.sha256)
        added, removed = diff.stats
        return ToolResult(True, f"edited {args['path']} (+{added} −{removed})",
                          meta={"diff": diff.unified})


class ListDir(Tool):
    name = "list_dir"
    description = "List the entries of a directory inside the workspace."
    args = {"path": "workspace-relative directory (default: workspace root)"}

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        try:
            real = ctx.jail.resolve(args.get("path", ".") or ".", ctx.workspace,
                                    must_exist=True)
        except JailViolation as exc:
            return ToolResult.error(_not_found_hint(exc))
        if not real.is_dir():
            return ToolResult.error(f"{args.get('path')} is not a directory")
        entries = []
        for child in sorted(real.iterdir()):
            tag = "/" if child.is_dir() else ""
            entries.append(f"{child.name}{tag}")
        ctx.audit.log_tool_call(self.name, {"path": args.get("path")})
        rel = os.path.relpath(real, ctx.workspace.root)
        return ToolResult(True, f"{rel}:\n" + "\n".join(entries) if entries
                          else f"{rel}: (empty)")


class Glob(Tool):
    name = "glob"
    description = "Find files matching a glob pattern (e.g. **/*.py) in the workspace."
    args = {"pattern": "glob pattern, workspace-relative"}

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        pattern = args.get("pattern", "")
        if not pattern:
            return ToolResult.error("empty pattern")
        matches: list[str] = []
        root = ctx.workspace.root
        for path in root.rglob("*"):
            if len(matches) >= 500:
                break
            rel = path.relative_to(root).as_posix()
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(path.name, pattern):
                try:  # never surface anything outside the jail, even here
                    ctx.jail.resolve(rel, ctx.workspace)
                except JailViolation:
                    continue
                matches.append(rel)
        ctx.audit.log_tool_call(self.name, {"pattern": pattern})
        body = "\n".join(sorted(matches)) or "(no matches)"
        return ToolResult(True, body)


class Grep(Tool):
    name = "grep"
    description = ("Search file contents for a regex/string. Uses ripgrep when "
                   "available (fast), falling back to a pure-Python scan.")
    args = {"query": "text or regex to search for",
            "glob": "optional file glob to restrict the search"}

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        query = args.get("query", "")
        if not query:
            return ToolResult.error("empty query")
        ctx.audit.log_tool_call(self.name, {"query": query, "glob": args.get("glob")})
        rg = shutil.which("rg")
        root = str(ctx.workspace.root)
        if rg:
            cmd = [rg, "--line-number", "--no-heading", "--color", "never",
                   "--max-count", "50"]
            if args.get("glob"):
                cmd += ["--glob", args["glob"]]
            cmd += [query, root]
            try:
                out = subprocess.run(cmd, capture_output=True, text=True,
                                     timeout=20, cwd=root)
                lines = out.stdout.splitlines()[:200]
                # Make paths workspace-relative for clean citations.
                rel = [ln.replace(root + os.sep, "").replace(root + "/", "")
                       for ln in lines]
                return ToolResult(True, "\n".join(rel) or "(no matches)")
            except Exception:  # noqa: BLE001 - fall through to python scan
                pass
        return self._python_grep(ctx, query, args.get("glob"))

    def _python_grep(self, ctx: ToolContext, query: str, glob: str | None) -> ToolResult:
        import re
        try:
            rx = re.compile(query)
        except re.error:
            rx = re.compile(re.escape(query))
        hits: list[str] = []
        root = ctx.workspace.root
        for path in root.rglob("*"):
            if len(hits) >= 200 or not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if glob and not fnmatch.fnmatch(rel, glob):
                continue
            try:
                text = path.read_text("utf-8", errors="ignore")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{rel}:{i}:{line.strip()[:200]}")
                    if len(hits) >= 200:
                        break
        return ToolResult(True, "\n".join(hits) or "(no matches)")


#: The default filesystem toolbox, keyed by name.
FS_TOOLS: dict[str, Tool] = {
    t.name: t for t in (ReadFile(), WriteFile(), EditFile(), ListDir(), Glob(), Grep())
}
