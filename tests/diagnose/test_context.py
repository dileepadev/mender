"""Tests for assembling the packet an agent receives."""

from __future__ import annotations

import subprocess
from pathlib import Path

from mender.classify import classify
from mender.config import MenderConfig
from mender.diagnose.context import (
    MAX_CONTEXT_FILES,
    build_request,
    diff_since_last_green,
    referenced_files,
    tail,
)


def test_tail_keeps_the_end_and_says_what_it_dropped() -> None:
    trimmed = tail("abcdefghij", 4)

    assert trimmed.endswith("ghij")
    assert "6 characters truncated" in trimmed


def test_short_text_is_left_alone() -> None:
    assert tail("abc", 100) == "abc"


def test_traceback_paths_are_resolved_against_the_workspace(workspace: Path) -> None:
    log = f'File "{workspace / "src/pkg/money.py"}", line 2\n'

    assert referenced_files(log, workspace) == ["src/pkg/money.py"]


def test_diagnostic_and_node_id_paths_are_found(workspace: Path) -> None:
    log = "src/pkg/money.py:2: error: boom\nFAILED tests/test_money.py::test_total\n"

    assert set(referenced_files(log, workspace)) == {
        "src/pkg/money.py",
        "tests/test_money.py",
    }


def test_paths_outside_the_workspace_are_discarded(workspace: Path) -> None:
    assert referenced_files('File "/etc/hosts.py", line 1\n', workspace) == []


def test_paths_that_do_not_exist_are_discarded(workspace: Path) -> None:
    assert referenced_files("src/pkg/absent.py:1: error: boom\n", workspace) == []


def test_the_request_carries_the_policy_limits(workspace: Path, config: MenderConfig) -> None:
    request = build_request(
        classification=classify("E   AssertionError\n"),
        failing_output="src/pkg/money.py:2: error: boom\n",
        workspace=workspace,
        config=config,
    )

    assert request.max_files_changed == config.policy.max_files_changed
    assert ".github/workflows/**" in request.never_touch
    assert request.file_context["src/pkg/money.py"].startswith("def total")


def test_context_is_capped(workspace: Path, config: MenderConfig) -> None:
    for index in range(MAX_CONTEXT_FILES + 5):
        (workspace / "src" / "pkg" / f"m{index}.py").write_text("x = 1\n", encoding="utf-8")
    output = "".join(
        f"src/pkg/m{index}.py:1: error: boom\n" for index in range(MAX_CONTEXT_FILES + 5)
    )

    request = build_request(
        classification=classify(output),
        failing_output=output,
        workspace=workspace,
        config=config,
    )

    assert len(request.file_context) == MAX_CONTEXT_FILES


def test_the_diff_since_last_green_is_empty_when_there_is_no_last_green(workspace: Path) -> None:
    assert diff_since_last_green(workspace, "HEAD", None) == ""


def test_the_diff_is_empty_rather_than_fatal_outside_a_git_repository(workspace: Path) -> None:
    assert diff_since_last_green(workspace, "HEAD", "abc123") == ""


def test_the_diff_since_last_green_is_read_from_git(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            env={
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t",
                "HOME": str(tmp_path),
                "PATH": "/usr/bin:/bin",
            },
        )

    git("init", "--quiet")
    (repo / "a.py").write_text("one\n", encoding="utf-8")
    git("add", "a.py")
    git("commit", "--quiet", "-m", "green")
    green = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    (repo / "a.py").write_text("two\n", encoding="utf-8")
    git("add", "a.py")
    git("commit", "--quiet", "-m", "red")

    diff = diff_since_last_green(repo, "HEAD", green)

    assert "-one" in diff
    assert "+two" in diff
