"""The command sandbox — one-shot, jailed, captured, logged, honestly bounded.

``run_command`` executes in a restricted subprocess: working directory jailed to
the workspace, a stripped environment, a wall-clock timeout, and an output size
cap. Commands are one-shot and captured — interactive shells are out of scope.

Honesty about limits (the product's rule): we do *not* claim a perfect OS
sandbox from Python. What we provide is real and useful — a locked cwd, a minimal
env, resource bounds, an approval gate, and a full audit entry — and we document
the ceiling: a determined native payload can still do what the user's own account
can. Hard network isolation for children is an OS concern (Windows Job Objects /
firewall rules, documented in ``docs/security.md``); the in-process guard does
not extend into a child process, and we say so rather than pretending.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from typing import Any

from .base import Tool, ToolContext, ToolResult

# Environment variables safe to keep so common tools (git, python) still work.
_ENV_KEEP = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE",
             "LANG", "LC_ALL", "PYTHONIOENCODING", "COMSPEC")


def _clean_env() -> dict[str, str]:
    env = {k: os.environ[k] for k in _ENV_KEEP if k in os.environ}
    # Signal to child processes that they are inside BastionBox's sandbox.
    env["BASTIONBOX_SANDBOX"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


class RunCommand(Tool):
    name = "run_command"
    description = ("Run a one-shot shell command in the workspace. Always asks for "
                   "approval unless the exact command is on the allowlist. Output "
                   "is captured and size-capped; there is no interactive input.")
    args = {"command": "the exact command line to run"}

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        command = (args.get("command") or "").strip()
        if not command:
            return ToolResult.error("empty command")

        allowlisted = command in ctx.command_allowlist
        decision = ctx.broker.request_command(ctx.workspace, command, allowlisted)
        ctx.audit.log_decision(f"run: {command}", decision.approved,
                               actor="user", note=decision.note)
        if not decision.approved:
            return ToolResult.rejected(decision.note or "command not approved")

        try:
            argv = self._argv(command)
            proc = subprocess.run(
                argv,
                cwd=str(ctx.workspace.root),   # jailed working directory
                env=_clean_env(),              # stripped environment
                capture_output=True, text=True,
                timeout=ctx.command_timeout_s,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            ctx.audit.log_command(command, str(ctx.workspace.root), None)
            return ToolResult.error(
                f"command timed out after {ctx.command_timeout_s:.0f}s")
        except FileNotFoundError:
            return ToolResult.error(f"command not found: {command.split()[0]}")

        ctx.audit.log_command(command, str(ctx.workspace.root), proc.returncode)
        out = (proc.stdout + (("\n[stderr]\n" + proc.stderr) if proc.stderr else ""))
        if len(out) > ctx.command_output_cap:
            out = out[:ctx.command_output_cap] + "\n[output truncated]"
        status = "ok" if proc.returncode == 0 else f"exit {proc.returncode}"
        return ToolResult(proc.returncode == 0,
                          f"$ {command}\n[{status}]\n{out}".rstrip(),
                          meta={"exit_code": proc.returncode})

    @staticmethod
    def _argv(command: str) -> list[str]:
        """Split a command line without invoking a shell (no shell=True).

        Avoiding a shell removes an entire class of injection/globbing surprises.
        On Windows we still split posix-style, which handles the allowlisted
        cases (pytest, git status) cleanly.
        """
        return shlex.split(command, posix=(sys.platform != "win32")) or [command]


COMMAND_TOOLS: dict[str, Tool] = {RunCommand().name: RunCommand()}
