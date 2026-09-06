"""Tests for the Mender command-line interface."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mender import __version__
from mender.cli import app

runner = CliRunner()
CORPUS = Path(__file__).resolve().parents[1] / "evals" / "corpus"


@pytest.fixture
def rename_case(tmp_path: Path) -> tuple[Path, Path]:
    """A copy of the incomplete-rename fixture, and its log file."""
    workspace = tmp_path / "repo"
    shutil.copytree(CORPUS / "incomplete-rename" / "repo", workspace)
    return workspace, CORPUS / "incomplete-rename" / "logs.txt"


# --- version and validate -----------------------------------------------------


def test_version_reports_the_package_version() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert __version__ in result.output


def test_no_arguments_shows_help() -> None:
    result = runner.invoke(app, [])

    assert result.exit_code != 0
    assert "Usage" in result.output


def test_validate_accepts_a_valid_config(tmp_path: Path) -> None:
    config = tmp_path / "mender.yaml"
    config.write_text("test_command: pytest\n", encoding="utf-8")

    result = runner.invoke(app, ["validate", "--config", str(config)])

    assert result.exit_code == 0
    assert "is valid" in result.output


def test_validate_rejects_an_invalid_config(tmp_path: Path) -> None:
    config = tmp_path / "mender.yaml"
    config.write_text("test_command: pytest\nbogus_key: 1\n", encoding="utf-8")

    result = runner.invoke(app, ["validate", "--config", str(config)])

    assert result.exit_code == 1


def test_validate_reports_a_missing_config(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate", "--config", str(tmp_path / "absent.yaml")])

    assert result.exit_code == 1


def test_repository_own_config_is_valid() -> None:
    repo_config = Path(__file__).resolve().parent.parent / "mender.yaml"

    result = runner.invoke(app, ["validate", "--config", str(repo_config)])

    assert result.exit_code == 0, result.output


# --- classify -----------------------------------------------------------------


def test_classify_explains_what_it_found(rename_case: tuple[Path, Path]) -> None:
    workspace, logs = rename_case

    result = runner.invoke(app, ["classify", str(logs), "--config", str(workspace / "mender.yaml")])

    assert result.exit_code == 0
    assert "import_error" in result.output
    assert "import-name-missing" in result.output


def test_classify_says_which_command_would_run(rename_case: tuple[Path, Path]) -> None:
    workspace, logs = rename_case

    result = runner.invoke(app, ["classify", str(logs), "--config", str(workspace / "mender.yaml")])

    assert "python -m pytest -q" in result.output


def test_classify_warns_when_confidence_is_below_the_threshold(tmp_path: Path) -> None:
    config = tmp_path / "mender.yaml"
    config.write_text(
        "test_command: pytest\ndiagnose:\n  confidence_threshold: 0.99\n", encoding="utf-8"
    )
    logs = tmp_path / "logs.txt"
    logs.write_text("E   AssertionError\n", encoding="utf-8")

    result = runner.invoke(app, ["classify", str(logs), "--config", str(config)])

    assert "Mender would stop here" in result.output


def test_classify_reports_an_unreadable_log(tmp_path: Path) -> None:
    config = tmp_path / "mender.yaml"
    config.write_text("test_command: pytest\n", encoding="utf-8")

    result = runner.invoke(app, ["classify", str(tmp_path / "absent.txt"), "--config", str(config)])

    assert result.exit_code == 1
    assert "Could not read" in result.output


# --- reproduce ----------------------------------------------------------------


def test_reproduce_confirms_a_real_failure(rename_case: tuple[Path, Path]) -> None:
    workspace, logs = rename_case

    result = runner.invoke(
        app,
        [
            "reproduce",
            str(logs),
            "--workspace",
            str(workspace),
            "--config",
            str(workspace / "mender.yaml"),
            "--runner",
            "local",
        ],
    )

    assert result.exit_code == 0
    assert "Reproduced" in result.output


def test_reproduce_exits_non_zero_when_the_failure_will_not_happen_again(
    rename_case: tuple[Path, Path],
) -> None:
    workspace, logs = rename_case
    (workspace / "app" / "checkout.py").write_text(
        "from app.utils import format_currency\n\n\ndef checkout(total):\n"
        "    return format_currency(total)\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "reproduce",
            str(logs),
            "--workspace",
            str(workspace),
            "--config",
            str(workspace / "mender.yaml"),
            "--runner",
            "local",
        ],
    )

    assert result.exit_code == 2
    assert "Did not reproduce" in result.output


def test_the_local_runner_warns_about_what_it_gives_up(rename_case: tuple[Path, Path]) -> None:
    workspace, logs = rename_case

    result = runner.invoke(
        app,
        [
            "reproduce",
            str(logs),
            "--workspace",
            str(workspace),
            "--config",
            str(workspace / "mender.yaml"),
            "--runner",
            "local",
        ],
    )

    assert "no container, no network isolation" in result.output


# --- repair -------------------------------------------------------------------


def test_repair_runs_the_whole_loop_and_writes_the_evidence(
    rename_case: tuple[Path, Path], tmp_path: Path
) -> None:
    workspace, logs = rename_case
    output = tmp_path / "out"

    result = runner.invoke(
        app,
        [
            "repair",
            str(logs),
            "--workspace",
            str(workspace),
            "--config",
            str(workspace / "mender.yaml"),
            "--runner",
            "local",
            "--commit",
            "a1b2c3d",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "shipped at ship" in result.output
    assert (output / "pull-request-a1b2c3d.md").is_file()


def test_repair_reports_an_abstention_without_failing(
    rename_case: tuple[Path, Path], tmp_path: Path
) -> None:
    workspace, _ = rename_case
    assertion_logs = tmp_path / "assertion.txt"
    assertion_logs.write_text("E   AssertionError\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "repair",
            str(assertion_logs),
            "--workspace",
            str(workspace),
            "--config",
            str(workspace / "mender.yaml"),
            "--runner",
            "local",
            "--output",
            str(tmp_path / "out"),
        ],
    )

    assert result.exit_code == 0
    assert "reported at classify" in result.output


# --- eval ---------------------------------------------------------------------


def test_eval_runs_the_corpus_and_publishes_the_numbers() -> None:
    result = runner.invoke(app, ["eval", "--corpus", str(CORPUS)])

    assert result.exit_code == 0, result.output
    assert "false-fix rate   0%" in result.output
    assert "abstention rate" in result.output


def test_eval_reports_a_missing_corpus(tmp_path: Path) -> None:
    result = runner.invoke(app, ["eval", "--corpus", str(tmp_path / "absent")])

    assert result.exit_code == 1
    assert "No corpus" in result.output
