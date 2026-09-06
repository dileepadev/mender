"""Tests for step 3: making the failure happen again, on purpose."""

from __future__ import annotations

from pathlib import Path

from tests.helpers import FakeRunner, result

from mender.config import MenderConfig
from mender.sandbox.reproduce import reproduce


def test_a_failure_that_happens_again_is_reproduced(config: MenderConfig, tmp_path: Path) -> None:
    runner = FakeRunner(lambda command, _: result(command, exit_code=1, stdout="boom"))

    outcome = reproduce(runner, config, tmp_path)

    assert outcome.reproduced
    assert not outcome.flaky
    assert outcome.attempts == 1
    assert outcome.failure_rate == 1.0
    assert "Reproduced" in outcome.summary


def test_a_failure_that_does_not_happen_again_is_rerun(
    config: MenderConfig, tmp_path: Path
) -> None:
    runner = FakeRunner(lambda command, _: result(command, exit_code=0))

    outcome = reproduce(runner, config, tmp_path)

    assert not outcome.reproduced
    assert not outcome.flaky
    assert outcome.attempts == 1 + config.sandbox.flaky_reruns
    assert "appears resolved" in outcome.summary


def test_an_intermittent_failure_is_reported_as_flaky(config: MenderConfig, tmp_path: Path) -> None:
    outcomes = iter([0, 1, 0])
    runner = FakeRunner(lambda command, _: result(command, exit_code=next(outcomes)))

    outcome = reproduce(runner, config, tmp_path)

    assert not outcome.reproduced
    assert outcome.flaky
    assert outcome.failures == 1
    assert "flaky" in outcome.summary


def test_the_configured_test_command_is_used_by_default(
    config: MenderConfig, tmp_path: Path
) -> None:
    runner = FakeRunner(lambda command, _: result(command, exit_code=1))

    reproduce(runner, config, tmp_path)

    assert runner.calls == ["run-tests"]


def test_an_explicit_command_overrides_the_test_command(
    config: MenderConfig, tmp_path: Path
) -> None:
    runner = FakeRunner(lambda command, _: result(command, exit_code=1))

    reproduce(runner, config, tmp_path, command="run-lint")

    assert runner.calls == ["run-lint"]


def test_a_timeout_counts_as_a_failure(config: MenderConfig, tmp_path: Path) -> None:
    runner = FakeRunner(
        lambda command, _: result(command, exit_code=124).model_copy(update={"timed_out": True})
    )

    assert reproduce(runner, config, tmp_path).reproduced


def test_the_first_run_is_the_one_worth_diagnosing(config: MenderConfig, tmp_path: Path) -> None:
    runner = FakeRunner(lambda command, _: result(command, exit_code=1, stdout="first"))

    assert reproduce(runner, config, tmp_path).first_run.stdout == "first"
