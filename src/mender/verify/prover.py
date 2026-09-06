"""Step 6 of the loop: prove it, or abstain.

Three things have to hold, and all three are demonstrated by running code rather
than asserted by a model:

1. The check that was failing now passes.
2. A test genuinely catches this bug — it fails against the unpatched code and
   passes against the patched code. A test that passes either way proves
   nothing.
3. Nothing else broke, measured against a pre-patch baseline of the full suite.

If any of them does not hold, the loop routes to abstention: an issue containing
the diagnosis rather than a pull request containing a guess.
"""

from __future__ import annotations

import shlex
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from mender.classify import extract_failing_tests
from mender.config import MenderConfig
from mender.diagnose.agent import RegressionTest
from mender.models import Patch
from mender.patch.workspace import applied
from mender.sandbox.runner import CommandResult, Runner

FAILING_CHECK_PASSES = "the failing check now passes"
REGRESSION_CATCHES_BUG = "the regression test catches the bug"
NOTHING_ELSE_BROKE = "nothing else broke"


class Check(BaseModel):
    """One of the three things the proof step demonstrates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    passed: bool
    detail: str


class Proof(BaseModel):
    """The result of the proof step."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proven: bool
    checks: list[Check] = Field(default_factory=list)
    before: CommandResult | None = None
    after: CommandResult | None = None
    baseline_failures: list[str] = Field(default_factory=list)
    remaining_failures: list[str] = Field(default_factory=list)
    new_failures: list[str] = Field(default_factory=list)

    @property
    def failed_checks(self) -> list[Check]:
        """The checks that did not hold."""
        return [check for check in self.checks if not check.passed]

    @property
    def reason(self) -> str:
        """A one-line summary, naming the first check that did not hold."""
        if self.proven:
            return "Proven: the failing check passes, a test catches the bug, nothing regressed."
        failed = self.failed_checks
        if not failed:  # pragma: no cover - defensive
            return "Not proven."
        return f"Not proven — {failed[0].name}: {failed[0].detail}"


class Prover:
    """Runs the three proof checks against a workspace."""

    def __init__(self, runner: Runner, config: MenderConfig) -> None:
        """Store the sandbox and configuration the checks run under.

        Args:
            runner: The sandbox backend. Everything here runs through it.
            config: The repository's validated configuration.
        """
        self.runner = runner
        self.config = config

    def prove(
        self,
        workspace: Path,
        patch: Patch,
        *,
        failing_command: str,
        baseline_suite: CommandResult,
        regression: RegressionTest | None = None,
    ) -> Proof:
        """Demonstrate that a patch fixes the failure and breaks nothing.

        Args:
            workspace: The repository at the failing commit, unpatched.
            patch: The approved patch, including any regression test.
            failing_command: The command that was failing — the test command for
                a test failure, the lint or type-check command otherwise.
            baseline_suite: A pre-patch run of the full test command, used as
                the regression baseline.
            regression: The test the agent authored, if it authored one.

        Returns:
            The proof, with every check's outcome and the before and after runs.
        """
        checks: list[Check] = []
        timeout = self.config.sandbox.timeout_seconds
        baseline_failures = extract_failing_tests(baseline_suite.output)

        without_fix: CommandResult | None = None
        if regression is not None:
            single = self._single_test_command(regression.test_id)
            with applied(workspace, patch.only(regression.path)):
                without_fix = self.runner.run(single, workspace=workspace, timeout_seconds=timeout)

        with applied(workspace, patch):
            suite = self.runner.run(
                self.config.test_command, workspace=workspace, timeout_seconds=timeout
            )
            failing_check = (
                suite
                if failing_command == self.config.test_command
                else self.runner.run(failing_command, workspace=workspace, timeout_seconds=timeout)
            )
            with_fix = (
                self.runner.run(
                    self._single_test_command(regression.test_id),
                    workspace=workspace,
                    timeout_seconds=timeout,
                )
                if regression is not None
                else None
            )

        # 1. The failing check now passes.
        checks.append(
            Check(
                name=FAILING_CHECK_PASSES,
                passed=failing_check.ok,
                detail=(
                    f"`{failing_command}` exited {failing_check.exit_code}."
                    + (" It was expected to exit 0." if not failing_check.ok else "")
                ),
            )
        )

        # 2. A test genuinely catches this bug.
        checks.append(self._regression_check(regression, without_fix, with_fix, failing_command))

        # 3. Nothing else broke.
        remaining = extract_failing_tests(suite.output)
        new_failures = [test for test in remaining if test not in baseline_failures]
        checks.append(self._regression_free_check(suite, baseline_failures, new_failures))

        return Proof(
            proven=all(check.passed for check in checks),
            checks=checks,
            before=baseline_suite,
            after=suite,
            baseline_failures=baseline_failures,
            remaining_failures=remaining,
            new_failures=new_failures,
        )

    def _single_test_command(self, test_id: str) -> str:
        """Build the command that runs exactly one test."""
        return f"{self.config.test_command} {shlex.quote(test_id)}"

    def _regression_check(
        self,
        regression: RegressionTest | None,
        without_fix: CommandResult | None,
        with_fix: CommandResult | None,
        failing_command: str,
    ) -> Check:
        """Judge whether a test demonstrably catches this bug.

        When the agent authored a regression test, it has to fail without the
        fix and pass with it. When it did not, the check that was already
        failing has to be one that plays the same role — a linter or a type
        checker, which fails on the unpatched code by construction.
        """
        if regression is None:
            return Check(
                name=REGRESSION_CATCHES_BUG,
                passed=True,
                detail=(
                    f"No new test was authored. `{failing_command}` is itself the "
                    f"check that fails on the unpatched code and passes on the "
                    f"patched code."
                ),
            )
        if without_fix is None or with_fix is None:  # pragma: no cover - defensive
            return Check(
                name=REGRESSION_CATCHES_BUG,
                passed=False,
                detail="The regression test could not be run.",
            )
        if without_fix.ok:
            return Check(
                name=REGRESSION_CATCHES_BUG,
                passed=False,
                detail=(
                    f"{regression.test_id} passes against the unpatched code, so it "
                    f"does not catch this bug. A test that passes either way proves "
                    f"nothing."
                ),
            )
        if not with_fix.ok:
            return Check(
                name=REGRESSION_CATCHES_BUG,
                passed=False,
                detail=(
                    f"{regression.test_id} still fails with the patch applied "
                    f"(exit {with_fix.exit_code})."
                ),
            )
        return Check(
            name=REGRESSION_CATCHES_BUG,
            passed=True,
            detail=(
                f"{regression.test_id} fails without the patch "
                f"(exit {without_fix.exit_code}) and passes with it."
            ),
        )

    def _regression_free_check(
        self,
        suite: CommandResult,
        baseline_failures: list[str],
        new_failures: list[str],
    ) -> Check:
        """Judge whether the patch broke anything that was previously fine."""
        if new_failures:
            return Check(
                name=NOTHING_ELSE_BROKE,
                passed=False,
                detail=f"New failures introduced: {', '.join(new_failures)}.",
            )
        if not suite.ok:
            return Check(
                name=NOTHING_ELSE_BROKE,
                passed=False,
                detail=(
                    f"The suite still fails (exit {suite.exit_code}) for a reason "
                    f"Mender could not attribute to a named test."
                ),
            )
        return Check(
            name=NOTHING_ELSE_BROKE,
            passed=True,
            detail=(
                f"The full suite passes. Baseline had {len(baseline_failures)} failing test(s)."
            ),
        )
