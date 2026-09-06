"""Tests for the proof step.

The runner in these tests reads the workspace, so the patch really is applied
and reverted around each run. That matters: the whole point of the proof step is
that it measures the code as it actually is at that moment.
"""

from __future__ import annotations

from pathlib import Path

from tests.helpers import FakeRunner, edit, patch_of, result

from mender.config import MenderConfig
from mender.diagnose.agent import RegressionTest
from mender.models import Patch
from mender.sandbox.runner import CommandResult
from mender.verify import (
    FAILING_CHECK_PASSES,
    NOTHING_ELSE_BROKE,
    REGRESSION_CATCHES_BUG,
    Check,
    Proof,
)
from mender.verify.prover import Prover

FIXED = "def total(a: int, b: int) -> int:\n    return a + b\n"
BROKEN = "def total(a: int, b: int) -> int:\n    return a - b\n"
REGRESSION = RegressionTest(
    path="tests/test_regression.py",
    content="from pkg.money import total\n\n\ndef test_total():\n    assert total(1, 1) == 2\n",
    test_id="tests/test_regression.py::test_total",
    rationale="fails on the broken code",
)


def fix_patch(workspace: Path, *, with_regression: bool = True) -> Patch:
    """A patch that repairs the source and adds a regression test."""
    edits = [edit("src/pkg/money.py", BROKEN, FIXED)]
    if with_regression:
        edits.append(edit(REGRESSION.path, None, REGRESSION.content))
    (workspace / "src" / "pkg" / "money.py").write_text(BROKEN, encoding="utf-8")
    return Patch(edits=edits)


def source_aware_runner(workspace: Path) -> FakeRunner:
    """A runner whose results depend on whether the fix is currently applied."""

    def handle(command: str, _: Path) -> str:
        fixed = (workspace / "src" / "pkg" / "money.py").read_text() == FIXED
        return "" if fixed else "FAILED tests/test_money.py::test_total - boom\n"

    return FakeRunner(
        lambda command, ws: result(
            command, exit_code=0 if not handle(command, ws) else 1, stdout=handle(command, ws)
        )
    )


def check(proof: Proof, name: str) -> Check:
    """Find a named check on a proof."""
    return next(item for item in proof.checks if item.name == name)


def prover_for(workspace: Path, config: MenderConfig) -> tuple[Prover, FakeRunner]:
    """Build a prover over a source-aware runner."""
    runner = source_aware_runner(workspace)
    return Prover(runner, config), runner


def test_a_real_fix_is_proven(workspace: Path, config: MenderConfig) -> None:
    patch = fix_patch(workspace)
    prover, _ = prover_for(workspace, config)
    baseline = result("run-tests", exit_code=1, stdout="FAILED tests/test_money.py::test_total\n")

    proof = prover.prove(
        workspace,
        patch,
        failing_command="run-tests",
        baseline_suite=baseline,
        regression=REGRESSION,
    )

    assert proof.proven
    assert all(item.passed for item in proof.checks)
    assert "Proven" in proof.reason


def test_the_workspace_is_left_unpatched_afterwards(workspace: Path, config: MenderConfig) -> None:
    patch = fix_patch(workspace)
    prover, _ = prover_for(workspace, config)

    prover.prove(
        workspace,
        patch,
        failing_command="run-tests",
        baseline_suite=result("run-tests", exit_code=1),
        regression=REGRESSION,
    )

    assert (workspace / "src" / "pkg" / "money.py").read_text() == BROKEN
    assert not (workspace / REGRESSION.path).exists()


def test_a_regression_test_that_passes_either_way_proves_nothing(
    workspace: Path, config: MenderConfig
) -> None:
    """The test never fails, so it does not catch the bug."""
    patch = fix_patch(workspace)
    runner = FakeRunner(lambda command, _: result(command, exit_code=0))
    prover = Prover(runner, config)

    proof = prover.prove(
        workspace,
        patch,
        failing_command="run-tests",
        baseline_suite=result("run-tests", exit_code=1),
        regression=REGRESSION,
    )

    assert not proof.proven
    assert not check(proof, REGRESSION_CATCHES_BUG).passed
    assert "does not catch this bug" in check(proof, REGRESSION_CATCHES_BUG).detail


def test_a_regression_test_that_still_fails_is_not_a_proof(
    workspace: Path, config: MenderConfig
) -> None:
    patch = fix_patch(workspace)
    runner = FakeRunner(lambda command, _: result(command, exit_code=1))
    prover = Prover(runner, config)

    proof = prover.prove(
        workspace,
        patch,
        failing_command="run-tests",
        baseline_suite=result("run-tests", exit_code=1),
        regression=REGRESSION,
    )

    assert not proof.proven
    assert "still fails with the patch applied" in check(proof, REGRESSION_CATCHES_BUG).detail


def test_a_new_failure_elsewhere_stops_the_loop(workspace: Path, config: MenderConfig) -> None:
    patch = fix_patch(workspace, with_regression=False)
    runner = FakeRunner(
        lambda command, _: result(
            command, exit_code=1, stdout="FAILED tests/test_other.py::test_x\n"
        )
    )
    prover = Prover(runner, config)

    proof = prover.prove(
        workspace,
        patch,
        failing_command="run-tests",
        baseline_suite=result("run-tests", exit_code=1, stdout=""),
    )

    assert not proof.proven
    assert proof.new_failures == ["tests/test_other.py::test_x"]
    assert "New failures introduced" in check(proof, NOTHING_ELSE_BROKE).detail


def test_a_failure_that_was_already_failing_is_not_a_new_one(
    workspace: Path, config: MenderConfig
) -> None:
    patch = fix_patch(workspace, with_regression=False)
    output = "FAILED tests/test_other.py::test_x\n"
    runner = FakeRunner(lambda command, _: result(command, exit_code=1, stdout=output))
    prover = Prover(runner, config)

    proof = prover.prove(
        workspace,
        patch,
        failing_command="run-tests",
        baseline_suite=result("run-tests", exit_code=1, stdout=output),
    )

    assert proof.new_failures == []
    assert "could not attribute" in check(proof, NOTHING_ELSE_BROKE).detail


def test_a_lint_failure_needs_no_new_test(workspace: Path, config: MenderConfig) -> None:
    """The linter is itself the check that fails before and passes after."""
    patch = patch_of(edit("src/pkg/money.py", "import os\n", ""))
    runner = FakeRunner(lambda command, _: result(command, exit_code=0))
    prover = Prover(runner, config)

    proof = prover.prove(
        workspace,
        patch,
        failing_command="run-lint",
        baseline_suite=result("run-tests", exit_code=0),
    )

    assert proof.proven
    assert "No new test was authored" in check(proof, REGRESSION_CATCHES_BUG).detail


def test_the_failing_check_is_run_separately_when_it_is_not_the_test_command(
    workspace: Path, config: MenderConfig
) -> None:
    runner = FakeRunner(lambda command, _: result(command, exit_code=0))
    prover = Prover(runner, config)

    prover.prove(
        workspace,
        patch_of(edit("src/pkg/money.py", "a\n", "b\n")),
        failing_command="run-lint",
        baseline_suite=result("run-tests", exit_code=0),
    )

    assert "run-lint" in runner.calls
    assert "run-tests" in runner.calls


def test_the_failing_check_run_is_reused_when_it_is_the_test_command(
    workspace: Path, config: MenderConfig
) -> None:
    runner = FakeRunner(lambda command, _: result(command, exit_code=0))
    prover = Prover(runner, config)

    prover.prove(
        workspace,
        patch_of(edit("src/pkg/money.py", "a\n", "b\n")),
        failing_command="run-tests",
        baseline_suite=result("run-tests", exit_code=0),
    )

    assert runner.calls == ["run-tests"]


def test_a_failing_check_that_still_fails_is_reported(
    workspace: Path, config: MenderConfig
) -> None:
    runner = FakeRunner(lambda command, _: result(command, exit_code=2))
    prover = Prover(runner, config)

    proof = prover.prove(
        workspace,
        patch_of(edit("src/pkg/money.py", "a\n", "b\n")),
        failing_command="run-tests",
        baseline_suite=result("run-tests", exit_code=1),
    )

    assert not check(proof, FAILING_CHECK_PASSES).passed
    assert "expected to exit 0" in check(proof, FAILING_CHECK_PASSES).detail
    assert "Not proven" in proof.reason


def test_the_regression_test_is_run_by_node_id(workspace: Path, config: MenderConfig) -> None:
    patch = fix_patch(workspace)
    runner = FakeRunner(lambda command, _: result(command, exit_code=1))
    prover = Prover(runner, config)

    prover.prove(
        workspace,
        patch,
        failing_command="run-tests",
        baseline_suite=result("run-tests", exit_code=1),
        regression=REGRESSION,
    )

    assert f"run-tests {REGRESSION.test_id}" in runner.calls


def test_only_the_regression_test_is_present_when_checking_it_fails_first(
    workspace: Path, config: MenderConfig
) -> None:
    """The test must be judged against the *unpatched* source, not the fixed one."""
    patch = fix_patch(workspace)
    seen: list[str] = []

    def record(command: str, _: Path) -> CommandResult:
        seen.append((workspace / "src" / "pkg" / "money.py").read_text())
        return result(command, exit_code=1)

    runner = FakeRunner(record)
    Prover(runner, config).prove(
        workspace,
        patch,
        failing_command="run-tests",
        baseline_suite=result("run-tests", exit_code=1),
        regression=REGRESSION,
    )

    assert seen[0] == BROKEN
