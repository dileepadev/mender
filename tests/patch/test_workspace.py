"""Tests for applying and reverting patches."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.helpers import edit, patch_of

from mender.models import FileEdit, Patch
from mender.patch import WorkspaceError, applied, apply_patch, resolve_within, revert_patch


def test_applying_a_patch_writes_the_after_state(workspace: Path) -> None:
    patch = patch_of(edit("src/pkg/money.py", None, "new content\n"))

    apply_patch(workspace, patch)

    assert (workspace / "src/pkg/money.py").read_text() == "new content\n"


def test_applying_a_patch_creates_missing_directories(workspace: Path) -> None:
    apply_patch(workspace, patch_of(edit("tests/deep/test_new.py", None, "x = 1\n")))

    assert (workspace / "tests/deep/test_new.py").is_file()


def test_a_deletion_removes_the_file(workspace: Path) -> None:
    original = (workspace / "src/pkg/money.py").read_text()

    apply_patch(workspace, patch_of(edit("src/pkg/money.py", original, None)))

    assert not (workspace / "src/pkg/money.py").exists()


def test_reverting_restores_the_original_bytes(workspace: Path) -> None:
    target = workspace / "src/pkg/money.py"
    original = target.read_text()
    patch = patch_of(edit("src/pkg/money.py", original, "changed\n"))

    apply_patch(workspace, patch)
    revert_patch(workspace, patch)

    assert target.read_text() == original


def test_reverting_removes_a_file_the_patch_created(workspace: Path) -> None:
    patch = patch_of(edit("tests/test_new.py", None, "x = 1\n"))

    apply_patch(workspace, patch)
    revert_patch(workspace, patch)

    assert not (workspace / "tests/test_new.py").exists()


def test_the_context_manager_reverts_even_when_the_body_raises(workspace: Path) -> None:
    target = workspace / "src/pkg/money.py"
    original = target.read_text()
    patch = patch_of(edit("src/pkg/money.py", original, "changed\n"))

    with pytest.raises(RuntimeError), applied(workspace, patch):
        assert target.read_text() == "changed\n"
        raise RuntimeError("proof step exploded")

    assert target.read_text() == original


def test_a_symlink_that_points_outside_the_workspace_is_refused(
    workspace: Path, tmp_path: Path
) -> None:
    """FileEdit blocks `..`; only resolving the real path catches a symlink."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "src" / "escape").symlink_to(outside)

    with pytest.raises(WorkspaceError, match="outside the workspace"):
        apply_patch(workspace, patch_of(edit("src/escape/pwned.txt", None, "x")))


def test_resolve_within_returns_an_absolute_path(workspace: Path) -> None:
    assert resolve_within(workspace, "src/pkg/money.py").is_absolute()


def test_a_no_op_edit_is_not_written(workspace: Path) -> None:
    target = workspace / "src/pkg/money.py"
    original = target.read_text()

    apply_patch(
        workspace, Patch(edits=[FileEdit(path="src/pkg/money.py", before=original, after=original)])
    )

    assert target.read_text() == original
