"""Unified-diff generation — because no edit is written without a preview.

Every write and every edit the agent proposes is shown to the user as a unified
diff *before* it touches disk. This module produces those diffs and a stable
SHA-256 of the change so the audit log can record exactly what was applied
without storing the file contents themselves.
"""
from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass


@dataclass
class Diff:
    path: str
    before: str
    after: str
    is_new_file: bool = False

    @property
    def unified(self) -> str:
        # Lines WITHOUT terminators + lineterm="" so join adds exactly one "\n"
        # per row. (Mixing keepends=True with lineterm="" doubles every newline
        # and makes the preview air-gapped from readability.)
        before_lines = self.before.splitlines()
        after_lines = self.after.splitlines()
        label = "/dev/null" if self.is_new_file else f"a/{self.path}"
        diff = difflib.unified_diff(
            before_lines, after_lines,
            fromfile=label, tofile=f"b/{self.path}", lineterm="")
        return "\n".join(diff)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.unified.encode("utf-8")).hexdigest()

    @property
    def stats(self) -> tuple[int, int]:
        """(+added, -removed) line counts, for a compact '+12 −3' badge."""
        added = removed = 0
        for line in self.unified.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed += 1
        return added, removed
