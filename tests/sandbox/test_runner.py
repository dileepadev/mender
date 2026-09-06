"""Tests for the local runner, including its timeout behaviour."""

from __future__ import annotations

from pathlib import Path

from mender.sandbox.runner import MAX_CAPTURED_CHARS, LocalRunner, Runner


def test_local_runner_satisfies_the_runner_protocol() -> None:
    assert isinstance(LocalRunner(), Runner)


def test_a_successful_command_reports_ok(tmp_path: Path) -> None:
    result = LocalRunner().run("echo hello", workspace=tmp_path, timeout_seconds=30)

    assert result.ok
    assert "hello" in result.stdout
    assert result.output.strip() == "hello"


def test_a_failing_command_reports_its_exit_code(tmp_path: Path) -> None:
    result = LocalRunner().run("exit 3", workspace=tmp_path, timeout_seconds=30)

    assert not result.ok
    assert result.exit_code == 3


def test_the_command_runs_in_the_workspace(tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("here", encoding="utf-8")

    result = LocalRunner().run("cat marker.txt", workspace=tmp_path, timeout_seconds=30)

    assert result.stdout.strip() == "here"


def test_extra_environment_variables_reach_the_command(tmp_path: Path) -> None:
    result = LocalRunner().run(
        "echo $MENDER_TEST", workspace=tmp_path, timeout_seconds=30, env={"MENDER_TEST": "set"}
    )

    assert result.stdout.strip() == "set"


def test_a_command_that_overruns_is_killed(tmp_path: Path) -> None:
    result = LocalRunner().run("sleep 30", workspace=tmp_path, timeout_seconds=1)

    assert result.timed_out
    assert not result.ok
    assert result.exit_code == 124


def test_a_child_process_does_not_outlive_a_timeout(tmp_path: Path) -> None:
    """The whole process group has to die, not just the shell."""
    marker = tmp_path / "survived.txt"
    command = f"(sleep 2; touch {marker}) & wait"

    LocalRunner().run(command, workspace=tmp_path, timeout_seconds=1)
    LocalRunner().run("sleep 3", workspace=tmp_path, timeout_seconds=4)

    assert not marker.exists()


def test_enormous_output_is_truncated(tmp_path: Path) -> None:
    result = LocalRunner().run(
        f"head -c {MAX_CAPTURED_CHARS * 2} /dev/zero | tr '\\0' 'x'",
        workspace=tmp_path,
        timeout_seconds=60,
    )

    assert len(result.stdout) < MAX_CAPTURED_CHARS * 1.1
    assert "characters truncated" in result.stdout
