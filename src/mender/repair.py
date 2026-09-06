"""The loop, wired end to end.

Watch, classify, reproduce, diagnose, fix, prove, ship — with an exit at every
stage. Most of this module is those exits. Mender is designed to stop more often
than it ships, so the paths that decline to act are the ones worth reading.
"""

from __future__ import annotations

import time
from pathlib import Path

from mender.classify import Classification, FailureClass, Support, classify
from mender.config import MenderConfig
from mender.diagnose.agent import Diagnosis, DiagnosisAgent
from mender.diagnose.context import build_request
from mender.models import FailedRun, Patch, PathError
from mender.policy.engine import PolicyDecision, PolicyEngine
from mender.report import Outcome, RepairReport, Stage
from mender.sandbox.reproduce import Reproduction, reproduce
from mender.sandbox.runner import CommandResult, Runner
from mender.ship.evidence import render
from mender.ship.publish import Publisher, ShipError
from mender.verify.prover import Proof, Prover

_COMMAND_BY_CLASS: dict[FailureClass, str] = {
    FailureClass.LINT: "lint_command",
    FailureClass.FORMAT: "lint_command",
    FailureClass.TYPE_ERROR: "type_check_command",
}


def command_for(classification: Classification, config: MenderConfig) -> str:
    """Choose the command that reproduces a given failure class.

    A lint failure does not reproduce by running the tests. The class decides
    which of the repository's configured commands is the one that was red.

    Args:
        classification: What the classifier concluded.
        config: The repository's validated configuration.

    Returns:
        The command to run, falling back to the test command when the class has
        no dedicated one or the repository did not configure it.
    """
    attribute = _COMMAND_BY_CLASS.get(classification.failure_class)
    if attribute is None:
        return config.test_command
    command: str | None = getattr(config, attribute)
    return command or config.test_command


class Repairer:
    """Runs one failed CI run through the whole loop."""

    def __init__(
        self,
        config: MenderConfig,
        *,
        runner: Runner,
        agent: DiagnosisAgent,
        publisher: Publisher,
    ) -> None:
        """Assemble the loop from its four replaceable parts.

        Args:
            config: The repository's validated configuration.
            runner: The sandbox backend everything executes in.
            agent: The diagnosis agent.
            publisher: Where the evidence package goes.
        """
        self.config = config
        self.runner = runner
        self.agent = agent
        self.publisher = publisher
        self.policy = PolicyEngine(config.policy)
        self.prover = Prover(runner, config)

    def repair(self, run: FailedRun, workspace: Path) -> RepairReport:
        """Take one failed run as far through the loop as it honestly goes.

        Args:
            run: The ingested failed run, including its logs.
            workspace: A checkout of the repository at the failing commit.

        Returns:
            The report, whether it ends in a pull request or an abstention.
        """
        started = time.monotonic()
        trace: list[str] = []

        classification = classify(run.logs)
        trace.append(
            f"classify: {classification.failure_class} "
            f"({classification.confidence}, rule {classification.rule or 'none'})"
        )

        stop = self._stop_at_classify(run, classification, trace, started)
        if stop is not None:
            return self._finish(stop, workspace)

        command = command_for(classification, self.config)
        reproduction = reproduce(self.runner, self.config, workspace, command=command)
        trace.append(f"reproduce: {reproduction.summary}")

        if not reproduction.reproduced:
            return self._finish(
                self._report(
                    run,
                    Outcome.REPORTED,
                    Stage.REPRODUCE,
                    reproduction.summary
                    + (" Mender does not edit flaky tests." if reproduction.flaky else ""),
                    started,
                    trace,
                    command=command,
                    classification=classification,
                    reproduction=reproduction,
                ),
                workspace,
            )

        baseline_suite = self._baseline_suite(workspace, command, reproduction)
        return self._finish(
            self._attempt_repair(
                run=run,
                workspace=workspace,
                classification=classification,
                reproduction=reproduction,
                command=command,
                baseline_suite=baseline_suite,
                started=started,
                trace=trace,
            ),
            workspace,
        )

    # --- Stage exits ---------------------------------------------------------

    def _stop_at_classify(
        self,
        run: FailedRun,
        classification: Classification,
        trace: list[str],
        started: float,
    ) -> RepairReport | None:
        """Stop before reproduction when the class is not one Mender repairs."""
        support = classification.support
        if support is Support.UNSUPPORTED:
            reason = (
                "The failure signature is not one Mender recognises. Reporting what "
                "was seen rather than guessing."
            )
        elif support is Support.REPORT_ONLY:
            reason = (
                f"A {classification.failure_class} failure is detected and reported, "
                f"never repaired."
            )
        elif support is Support.LATER:
            reason = (
                f"A {classification.failure_class} failure is recognised but out of "
                f"scope for now — confident wrongness on subtle bugs is the fastest "
                f"way to lose trust."
            )
        elif classification.confidence < self.config.diagnose.confidence_threshold:
            reason = (
                f"Classification confidence {classification.confidence} is below the "
                f"configured threshold "
                f"{self.config.diagnose.confidence_threshold}."
            )
        else:
            return None

        return self._report(
            run,
            Outcome.REPORTED,
            Stage.CLASSIFY,
            reason,
            started,
            trace,
            classification=classification,
        )

    def _attempt_repair(
        self,
        *,
        run: FailedRun,
        workspace: Path,
        classification: Classification,
        reproduction: Reproduction,
        command: str,
        baseline_suite: CommandResult,
        started: float,
        trace: list[str],
    ) -> RepairReport:
        """Diagnose, patch, check, and prove — retrying within the configured budget."""
        request = build_request(
            classification=classification,
            failing_output=reproduction.first_run.output,
            workspace=workspace,
            config=self.config,
            commit=run.commit,
            last_green_commit=run.last_green_commit,
        )

        limits = self.config.diagnose
        spent = 0.0
        last: RepairReport | None = None

        for attempt in range(1, limits.max_attempts + 1):
            diagnosis = self.agent.diagnose(request)
            spent += diagnosis.cost_usd
            diagnosis.cost_usd = round(spent, 6)
            trace.append(
                f"diagnose (attempt {attempt}): confidence {diagnosis.confidence}, "
                f"{len(diagnosis.edits)} edit(s), ${spent:.4f} spent"
            )

            last = self._evaluate(
                run=run,
                workspace=workspace,
                classification=classification,
                reproduction=reproduction,
                diagnosis=diagnosis,
                command=command,
                baseline_suite=baseline_suite,
                started=started,
                trace=trace,
            )
            if last.outcome is Outcome.SHIPPED:
                return last
            if not self._retryable(last):
                return last
            if spent >= limits.max_cost_usd:
                last.reason += (
                    f" Stopped retrying: ${spent:.4f} spent against a "
                    f"${limits.max_cost_usd:.2f} budget."
                )
                return last
            request.previous_attempts.append(last.reason)

        if last is None:  # pragma: no cover - max_attempts is validated as >= 1
            raise RuntimeError("The diagnosis loop ran zero attempts.")
        return last

    def _evaluate(
        self,
        *,
        run: FailedRun,
        workspace: Path,
        classification: Classification,
        reproduction: Reproduction,
        diagnosis: Diagnosis,
        command: str,
        baseline_suite: CommandResult,
        started: float,
        trace: list[str],
    ) -> RepairReport:
        """Take one diagnosis through policy and proof."""

        def report(
            outcome: Outcome,
            stage: Stage,
            reason: str,
            *,
            patch: Patch | None = None,
            decision: PolicyDecision | None = None,
            proof: Proof | None = None,
        ) -> RepairReport:
            return self._report(
                run,
                outcome,
                stage,
                reason,
                started,
                trace,
                command=command,
                classification=classification,
                reproduction=reproduction,
                diagnosis=diagnosis,
                patch=patch,
                decision=decision,
                proof=proof,
            )

        if not diagnosis.has_fix:
            return report(
                Outcome.ABSTAINED,
                Stage.DIAGNOSE,
                f"The agent proposed no change. {diagnosis.root_cause}",
            )
        if diagnosis.confidence < self.config.diagnose.confidence_threshold:
            return report(
                Outcome.ABSTAINED,
                Stage.DIAGNOSE,
                f"Diagnosis confidence {diagnosis.confidence} is below the "
                f"configured threshold {self.config.diagnose.confidence_threshold}.",
            )

        try:
            patch = diagnosis.to_patch(workspace)
        except (PathError, OSError) as exc:
            return report(
                Outcome.REJECTED,
                Stage.FIX,
                f"The proposed patch could not be built: {exc}",
            )

        decision = self.policy.evaluate(patch)
        trace.append(f"policy: {decision.reason}")
        if not decision.approved:
            return report(
                Outcome.REJECTED,
                Stage.FIX,
                decision.reason,
                patch=patch,
                decision=decision,
            )

        proof = self.prover.prove(
            workspace,
            patch,
            failing_command=command,
            baseline_suite=baseline_suite,
            regression=diagnosis.regression_test,
        )
        trace.append(f"prove: {proof.reason}")
        if not proof.proven:
            return report(
                Outcome.ABSTAINED,
                Stage.PROVE,
                proof.reason,
                patch=patch,
                decision=decision,
                proof=proof,
            )

        return report(
            Outcome.SHIPPED,
            Stage.SHIP,
            proof.reason,
            patch=patch,
            decision=decision,
            proof=proof,
        )

    # --- Helpers -------------------------------------------------------------

    def _retryable(self, report: RepairReport) -> bool:
        """Whether another attempt could plausibly do better.

        A rejected or unproven patch is worth one more try with the reason fed
        back. An agent that declined to propose anything is not — asking the
        same question again is how a system talks itself into a bad answer.
        """
        if report.stopped_at is Stage.DIAGNOSE:
            return False
        return report.outcome in {Outcome.REJECTED, Outcome.ABSTAINED}

    def _baseline_suite(
        self, workspace: Path, command: str, reproduction: Reproduction
    ) -> CommandResult:
        """Get a pre-patch run of the full suite to measure regressions against."""
        if command == self.config.test_command:
            return reproduction.first_run
        return self.runner.run(
            self.config.test_command,
            workspace=workspace,
            timeout_seconds=self.config.sandbox.timeout_seconds,
        )

    def _report(
        self,
        run: FailedRun,
        outcome: Outcome,
        stage: Stage,
        reason: str,
        started: float,
        trace: list[str],
        *,
        command: str = "",
        classification: Classification | None = None,
        reproduction: Reproduction | None = None,
        diagnosis: Diagnosis | None = None,
        patch: Patch | None = None,
        decision: PolicyDecision | None = None,
        proof: Proof | None = None,
    ) -> RepairReport:
        """Build the report for however this attempt ended."""
        return RepairReport(
            run=run,
            outcome=outcome,
            stopped_at=stage,
            reason=reason,
            command=command,
            classification=classification,
            reproduction=reproduction,
            diagnosis=diagnosis,
            patch=patch,
            decision=decision,
            proof=proof,
            duration_seconds=round(time.monotonic() - started, 3),
            agent=getattr(self.agent, "name", "unknown"),
            runner=getattr(self.runner, "name", "unknown"),
            trace=list(trace),
        )

    def _finish(self, report: RepairReport, workspace: Path) -> RepairReport:
        """Publish the evidence package and record where it went.

        Every outcome except an internal error is published. An abstention that
        nobody sees is the same as no abstention at all.
        """
        if report.outcome is Outcome.ERROR:
            return report
        try:
            report.url = self.publisher.publish(report, render(report), workspace=workspace)
        except ShipError as exc:
            report.trace.append(f"ship: failed — {exc}")
        else:
            report.trace.append(f"ship: {report.url}")
        return report
