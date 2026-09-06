"""Applying and reverting patches inside a workspace.

A patch carries the full content of every file both before and after, so
applying it is a write and reverting it is another write. There is no partial
application to recover from: after a revert the workspace is byte-for-byte what
it was, which is what lets the proof step run the same suite against the patched
and unpatched trees in one session.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from mender.models import Patch


class WorkspaceError(RuntimeError):
    """Raised when a patch cannot be written to a workspace safely."""


def resolve_within(workspace: Path, relative: str) -> Path:
    """Resolve a repository-relative path, refusing anything that escapes.

    ``FileEdit`` already rejects absolute paths and ``..`` segments. This is the
    second half of the check: a symlink inside the repository could still point
    outside it, and only resolving the real path catches that.

    Args:
        workspace: The repository root.
        relative: A repository-relative POSIX path.

    Returns:
        The absolute path to write.

    Raises:
        WorkspaceError: If the resolved path lies outside the workspace.
    """
    root = workspace.resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise WorkspaceError(f"Refusing to write {relative!r}: it resolves outside the workspace.")
    return target


def apply_patch(workspace: Path, patch: Patch) -> None:
    """Write a patch's after-state into a workspace.

    Args:
        workspace: The repository root.
        patch: The change to write.

    Raises:
        WorkspaceError: If any path escapes the workspace.
    """
    for edit in patch.effective_edits:
        target = resolve_within(workspace, edit.path)
        if edit.after is None:
            target.unlink(missing_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(edit.after, encoding="utf-8")


def revert_patch(workspace: Path, patch: Patch) -> None:
    """Restore a workspace to a patch's before-state.

    Args:
        workspace: The repository root.
        patch: The change to undo.

    Raises:
        WorkspaceError: If any path escapes the workspace.
    """
    for edit in patch.effective_edits:
        target = resolve_within(workspace, edit.path)
        if edit.before is None:
            target.unlink(missing_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(edit.before, encoding="utf-8")


@contextmanager
def applied(workspace: Path, patch: Patch) -> Iterator[None]:
    """Apply a patch for the duration of the block, then put it back.

    The revert runs even when the body raises, so a crashed proof run never
    leaves a half-patched workspace behind for the next step to measure.
    """
    apply_patch(workspace, patch)
    try:
        yield
    finally:
        revert_patch(workspace, patch)
