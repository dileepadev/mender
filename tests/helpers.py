"""Shared test doubles and builders.

Imported as ``tests.helpers`` — ``pythonpath = ["."]`` in the pytest
configuration puts the repository root on ``sys.path``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from mender.models import FileEdit, Patch
from mender.sandbox.runner import CommandResult


def result(command: str, exit_code: int = 0, stdout: str = "", stderr: str = "") -> CommandResult:
    """Build a command result without running anything."""
    return CommandResult(command=command, exit_code=exit_code, stdout=stdout, stderr=stderr)


class FakeRunner:
    """A runner that answers from a handler and records what it was asked."""

    name = "fake"

    def __init__(self, handler: Callable[[str, Path], CommandResult]) -> None:
        self.handler = handler
        self.calls: list[str] = []

    def run(
        self,
        command: str,
        *,
        workspace: Path,
        timeout_seconds: int,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        """Record the command and return whatever the handler decides."""
        del timeout_seconds, env
        self.calls.append(command)
        return self.handler(command, workspace)


def edit(path: str, before: str | None, after: str | None) -> FileEdit:
    """Build a single file edit."""
    return FileEdit(path=path, before=before, after=after)


def patch_of(*edits: FileEdit, summary: str = "test patch") -> Patch:
    """Build a patch from edits."""
    return Patch(edits=list(edits), summary=summary)
