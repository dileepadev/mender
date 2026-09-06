"""Tests for the shared domain models and their path safety invariant."""

from __future__ import annotations

import pytest
from tests.helpers import edit, patch_of

from mender.models import FailedRun, FileEdit, Patch, PathError, normalise_repo_path


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("src/app.py", "src/app.py"),
        ("./src/app.py", "src/app.py"),
        ("src\\app.py", "src/app.py"),
        ("  src/app.py  ", "src/app.py"),
    ],
)
def test_repo_paths_are_normalised(given: str, expected: str) -> None:
    assert normalise_repo_path(given) == expected


@pytest.mark.parametrize(
    "given",
    ["", "   ", "/etc/passwd", "../outside.py", "src/../../outside.py", "."],
)
def test_paths_that_escape_the_repository_are_rejected(given: str) -> None:
    with pytest.raises(PathError):
        normalise_repo_path(given)


def test_file_edit_rejects_a_traversal_path() -> None:
    with pytest.raises(ValueError, match="escapes the repository root"):
        FileEdit(path="../../.ssh/authorized_keys", before=None, after="key")


def test_creation_and_deletion_are_distinguished() -> None:
    created = edit("a.py", None, "x = 1\n")
    deleted = edit("b.py", "x = 1\n", None)

    assert created.is_creation
    assert deleted.is_deletion
    assert not created.is_deletion


def test_unified_diff_marks_a_creation_against_dev_null() -> None:
    diff = edit("a.py", None, "x = 1\n").unified_diff()

    assert "--- /dev/null" in diff
    assert "+++ b/a.py" in diff


def test_line_count_ignores_the_diff_header() -> None:
    counted = edit("a.py", "one\ntwo\n", "one\nTWO\n").line_count()

    assert counted == 2


def test_patch_counts_only_edits_that_change_something() -> None:
    patch = patch_of(
        edit("a.py", "same\n", "same\n"),
        edit("b.py", "one\n", "two\n"),
    )

    assert patch.files_changed == 1
    assert patch.paths == ["b.py"]
    assert not patch.is_empty


def test_an_all_no_op_patch_is_empty() -> None:
    assert patch_of(edit("a.py", "same\n", "same\n")).is_empty


def test_without_and_only_select_subsets() -> None:
    patch = patch_of(edit("a.py", "1\n", "2\n"), edit("tests/t.py", None, "x\n"))

    assert patch.without("tests/t.py").paths == ["a.py"]
    assert patch.only("tests/t.py").paths == ["tests/t.py"]


def test_edit_for_finds_an_edit_by_path() -> None:
    patch = patch_of(edit("src/a.py", "1\n", "2\n"))

    assert patch.edit_for("./src/a.py") is not None
    assert patch.edit_for("src/b.py") is None


def test_failed_run_shortens_its_commit() -> None:
    run = FailedRun(repository="owner/repo", commit="a1b2c3d4e5f6")

    assert run.short_commit == "a1b2c3d"


def test_patch_diff_concatenates_every_changed_file() -> None:
    diff = Patch(edits=[edit("a.py", "1\n", "2\n"), edit("b.py", "3\n", "4\n")]).unified_diff()

    assert "a/a.py" in diff
    assert "a/b.py" in diff
