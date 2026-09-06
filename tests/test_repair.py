"""Tests for the loop, end to end.

Most of these exercise the exits. Mender is designed to stop more often than it
ships, so the interesting behaviour is where it declines and what it says.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from tests.helpers import FakeRunner, result

from mender.classify import Classification, FailureClass, classify
from mender.config import MenderConfig, load_config
from mender.diagnose.agent import Diagnosis, DiagnosisRequest, ProposedEdit, RegressionTest
from mender.models import FailedRun
from mender.repair import Repairer, command_for
from mender.report import Outcome, Stage
from mender.sandbox.runner import CommandResult
from mender.ship.publish import DryRunPublisher, ShipError

IMPORT_LOG = "E   ImportError: cannot import name 'format_price' from 'pkg.money'\n"
LINT_LOG = "src/pkg/money.py:1:8: F401 [*] `os` imported but unused\n"
ASSERTION_LOG = "E   AssertionError\nFAILED tests/test_money.py::test_total\n"

FIXED = "def total(a: int, b: int) -> int:\n    return a + b\n"
BROKEN = "def total(a: int, b: int) -> int:\n    return a - b\n"


class ScriptedAgent:
    """Returns a prepared diagnosis and records what it was asked."""

    name = "scripted"

    def __init__(self, *diagnoses: Diagnosis) -> None:
        self.diagnoses = list(diagnoses)
        self.requests: list[DiagnosisRequest] = []

    def diagnose(self, request: DiagnosisRequest) -> Diagnosis:
        """Return the next scripted diagnosis, repeating the last one."""
        self.requests.append(request.model_copy(deep=True))
        index = min(len(self.requests) - 1, len(self.diagnoses) - 1)
        return self.diagnoses[index].model_copy(deep=True)


def diagnosis(
    *,
    confidence: float = 0.9,
    edits: list[ProposedEdit] | None = None,
    regression: RegressionTest | None = None,
    root_cause: str = "The fix is obvious.",
) -> Diagnosis:
    """Build a diagnosis."""
    return Diagnosis(
        root_cause=root_cause,
        confidence=confidence,
        edits=edits
        if edits is not None
        else [ProposedEdit(path="src/pkg/money.py", content=FIXED)],
        regression_test=regression,
    )


@pytest.fixture
def repo(workspace: Path) -> Path:
    """The shared workspace with the source broken."""
    (workspace / "src" / "pkg" / "money.py").write_text(BROKEN, encoding="utf-8")
    return workspace


@pytest.fixture
def failing_config(tmp_path: Path) -> MenderConfig:
    """A configuration whose allowlist covers the shared workspace."""
    path = tmp_path / "mender.yaml"
    path.write_text(
        "test_command: run-tests\nlint_command: run-lint\nsandbox:\n  flaky_reruns: 2\n",
        encoding="utf-8",
    )
    return load_config(path)


def build(
    config: MenderConfig,
    tmp_path: Path,
    *,
    agent: object,
    handler: object = None,
) -> Repairer:
    """Assemble a repairer over a fake runner and a dry-run publisher."""
    runner = FakeRunner(handler or (lambda command, _: result(command, exit_code=1)))  # type: ignore[arg-type]
    return Repairer(
        config,
        runner=runner,
        agent=agent,  # type: ignore[arg-type]
        publisher=DryRunPublisher(tmp_path / "out"),
    )


def run_for(logs: str) -> FailedRun:
    """A failed run carrying the given logs."""
    return FailedRun(repository="owner/repo", commit="a1b2c3d4", job="ci", logs=logs)


def source_aware(workspace: Path) -> Callable[[str, Path], CommandResult]:
    """A runner handler whose result depends on whether the fix is applied."""

    def handle(command: str, _: Path) -> CommandResult:
        fixed = (workspace / "src" / "pkg" / "money.py").read_text() == FIXED
        return result(command, exit_code=0 if fixed else 1, stdout="" if fixed else "boom")

    return handle


# --- The command each failure class reproduces with ---------------------------


def test_a_lint_failure_reproduces_with_the_lint_command(failing_config: MenderConfig) -> None:
    assert command_for(classify(LINT_LOG), failing_config) == "run-lint"


def test_a_test_failure_reproduces_with_the_test_command(failing_config: MenderConfig) -> None:
    assert command_for(classify(IMPORT_LOG), failing_config) == "run-tests"


def test_an_unconfigured_command_falls_back_to_the_test_command(
    failing_config: MenderConfig,
) -> None:
    unset = failing_config.model_copy(update={"lint_command": None})

    assert command_for(classify(LINT_LOG), unset) == "run-tests"


def test_a_type_error_uses_the_type_check_command(config: MenderConfig) -> None:
    typed = Classification(failure_class=FailureClass.TYPE_ERROR, confidence=0.9)

    assert command_for(typed, config) == "run-types"


# --- Stage exits --------------------------------------------------------------


def test_an_unknown_class_stops_before_anything_runs(
    failing_config: MenderConfig, repo: Path, tmp_path: Path
) -> None:
    repairer = build(failing_config, tmp_path, agent=ScriptedAgent(diagnosis()))

    report = repairer.repair(run_for("something went wrong somehow\n"), repo)

    assert report.outcome is Outcome.REPORTED
    assert report.stopped_at is Stage.CLASSIFY
    assert "not one Mender recognises" in report.reason
    assert report.reproduction is None


def test_an_infrastructure_failure_is_reported_never_repaired(
    failing_config: MenderConfig, repo: Path, tmp_path: Path
) -> None:
    repairer = build(failing_config, tmp_path, agent=ScriptedAgent(diagnosis()))

    report = repairer.repair(run_for("Connection refused\n"), repo)

    assert report.outcome is Outcome.REPORTED
    assert "detected and reported, never repaired" in report.reason


def test_an_assertion_failure_is_declared_out_of_scope(
    failing_config: MenderConfig, repo: Path, tmp_path: Path
) -> None:
    repairer = build(failing_config, tmp_path, agent=ScriptedAgent(diagnosis()))

    report = repairer.repair(run_for(ASSERTION_LOG), repo)

    assert report.outcome is Outcome.REPORTED
    assert "out of scope" in report.reason


def test_low_classification_confidence_stops_the_loop(
    failing_config: MenderConfig, repo: Path, tmp_path: Path
) -> None:
    strict = failing_config.model_copy(
        update={
            "diagnose": failing_config.diagnose.model_copy(update={"confidence_threshold": 0.99})
        }
    )
    repairer = build(strict, tmp_path, agent=ScriptedAgent(diagnosis()))

    report = repairer.repair(run_for(IMPORT_LOG), repo)

    assert report.outcome is Outcome.REPORTED
    assert "below the configured threshold" in report.reason


def test_a_failure_that_will_not_reproduce_is_never_repaired(
    failing_config: MenderConfig, repo: Path, tmp_path: Path
) -> None:
    repairer = build(
        failing_config,
        tmp_path,
        agent=ScriptedAgent(diagnosis()),
        handler=lambda command, _: result(command, exit_code=0),
    )

    report = repairer.repair(run_for(IMPORT_LOG), repo)

    assert report.outcome is Outcome.REPORTED
    assert report.stopped_at is Stage.REPRODUCE
    assert report.diagnosis is None


def test_a_flaky_failure_says_mender_does_not_edit_it(
    failing_config: MenderConfig, repo: Path, tmp_path: Path
) -> None:
    codes = iter([0, 1, 0])
    repairer = build(
        failing_config,
        tmp_path,
        agent=ScriptedAgent(diagnosis()),
        handler=lambda command, _: result(command, exit_code=next(codes)),
    )

    report = repairer.repair(run_for(IMPORT_LOG), repo)

    assert report.outcome is Outcome.REPORTED
    assert "does not edit flaky tests" in report.reason


def test_an_agent_that_proposes_nothing_abstains(
    failing_config: MenderConfig, repo: Path, tmp_path: Path
) -> None:
    repairer = build(
        failing_config, tmp_path, agent=ScriptedAgent(diagnosis(edits=[], confidence=0.0))
    )

    report = repairer.repair(run_for(IMPORT_LOG), repo)

    assert report.outcome is Outcome.ABSTAINED
    assert report.stopped_at is Stage.DIAGNOSE


def test_a_low_confidence_diagnosis_abstains(
    failing_config: MenderConfig, repo: Path, tmp_path: Path
) -> None:
    repairer = build(failing_config, tmp_path, agent=ScriptedAgent(diagnosis(confidence=0.2)))

    report = repairer.repair(run_for(IMPORT_LOG), repo)

    assert report.outcome is Outcome.ABSTAINED
    assert "confidence 0.2 is below" in report.reason


def test_an_unproven_patch_abstains_rather_than_shipping(
    failing_config: MenderConfig, repo: Path, tmp_path: Path
) -> None:
    """The patch is applied but the suite still fails, so nothing ships."""
    repairer = build(failing_config, tmp_path, agent=ScriptedAgent(diagnosis()))

    report = repairer.repair(run_for(IMPORT_LOG), repo)

    assert report.outcome is Outcome.ABSTAINED
    assert report.stopped_at is Stage.PROVE
    assert report.patch is not None


# --- The cheating agent -------------------------------------------------------


def test_a_patch_that_deletes_a_test_is_rejected_by_policy(
    failing_config: MenderConfig, repo: Path, tmp_path: Path
) -> None:
    cheat = diagnosis(
        edits=[ProposedEdit(path="tests/test_money.py", content="")],
        root_cause="Making the pipeline green.",
    )
    repairer = build(failing_config, tmp_path, agent=ScriptedAgent(cheat))

    report = repairer.repair(run_for(IMPORT_LOG), repo)

    assert report.outcome is Outcome.REJECTED
    assert report.stopped_at is Stage.FIX
    assert report.decision is not None
    assert report.decision.weakened_a_test


def test_a_patch_that_edits_a_workflow_file_is_rejected(
    failing_config: MenderConfig, repo: Path, tmp_path: Path
) -> None:
    cheat = diagnosis(edits=[ProposedEdit(path=".github/workflows/ci.yml", content="on: never\n")])
    repairer = build(failing_config, tmp_path, agent=ScriptedAgent(cheat))

    report = repairer.repair(run_for(IMPORT_LOG), repo)

    assert report.outcome is Outcome.REJECTED
    assert "never-touch" in report.reason


def test_a_patch_that_escapes_the_workspace_is_rejected(
    failing_config: MenderConfig, repo: Path, tmp_path: Path
) -> None:
    cheat = diagnosis(edits=[ProposedEdit(path="../../.ssh/authorized_keys", content="key\n")])
    repairer = build(failing_config, tmp_path, agent=ScriptedAgent(cheat))

    report = repairer.repair(run_for(IMPORT_LOG), repo)

    assert report.outcome is Outcome.REJECTED
    assert "could not be built" in report.reason


def test_a_rejection_is_fed_back_to_the_next_attempt(
    failing_config: MenderConfig, repo: Path, tmp_path: Path
) -> None:
    cheat = diagnosis(edits=[ProposedEdit(path=".github/workflows/ci.yml", content="x\n")])
    agent = ScriptedAgent(cheat)
    repairer = build(failing_config, tmp_path, agent=agent)

    repairer.repair(run_for(IMPORT_LOG), repo)

    assert len(agent.requests) == failing_config.diagnose.max_attempts
    assert "never-touch" in agent.requests[-1].previous_attempts[0]


def test_an_agent_that_declines_is_not_asked_again(
    failing_config: MenderConfig, repo: Path, tmp_path: Path
) -> None:
    """Asking the same question again is how a system talks itself into a bad answer."""
    agent = ScriptedAgent(diagnosis(edits=[], confidence=0.0))
    repairer = build(failing_config, tmp_path, agent=agent)

    repairer.repair(run_for(IMPORT_LOG), repo)

    assert len(agent.requests) == 1


# --- The happy path -----------------------------------------------------------


def test_a_proven_fix_ships_with_its_evidence(
    failing_config: MenderConfig, repo: Path, tmp_path: Path
) -> None:
    regression = RegressionTest(
        path="tests/test_regression.py",
        content="def test_regression():\n    assert True\n",
        test_id="tests/test_regression.py::test_regression",
        rationale="Fails without the fix.",
    )
    repairer = build(
        failing_config,
        tmp_path,
        agent=ScriptedAgent(diagnosis(regression=regression)),
        handler=source_aware(repo),
    )

    report = repairer.repair(run_for(IMPORT_LOG), repo)

    assert report.outcome is Outcome.SHIPPED
    assert report.shipped
    assert report.url is not None
    assert Path(report.url).is_file()
    body = Path(report.url).read_text()
    assert "## Proof" in body
    assert "the regression test catches the bug" in body


def test_the_workspace_is_left_untouched_by_a_shipped_repair(
    failing_config: MenderConfig, repo: Path, tmp_path: Path
) -> None:
    """Publishing is a separate step; the loop itself never leaves a patch behind."""
    repairer = build(
        failing_config,
        tmp_path,
        agent=ScriptedAgent(diagnosis()),
        handler=source_aware(repo),
    )

    repairer.repair(run_for(IMPORT_LOG), repo)

    assert (repo / "src" / "pkg" / "money.py").read_text() == BROKEN


def test_the_trace_records_every_stage(
    failing_config: MenderConfig, repo: Path, tmp_path: Path
) -> None:
    repairer = build(
        failing_config,
        tmp_path,
        agent=ScriptedAgent(diagnosis()),
        handler=source_aware(repo),
    )

    report = repairer.repair(run_for(IMPORT_LOG), repo)

    assert [step.split(":")[0] for step in report.trace] == [
        "classify",
        "reproduce",
        "diagnose (attempt 1)",
        "policy",
        "prove",
        "ship",
    ]


def test_abstentions_are_published_too(
    failing_config: MenderConfig, repo: Path, tmp_path: Path
) -> None:
    """An abstention nobody sees is the same as no abstention at all."""
    repairer = build(failing_config, tmp_path, agent=ScriptedAgent(diagnosis()))

    report = repairer.repair(run_for(IMPORT_LOG), repo)

    assert report.url is not None
    assert Path(report.url).name.startswith("issue-")


def test_a_publisher_failure_does_not_lose_the_report(
    failing_config: MenderConfig, repo: Path, tmp_path: Path
) -> None:
    class BrokenPublisher:
        name = "broken"

        def publish(self, report: object, evidence: object, *, workspace: Path) -> str:
            """Fail the way an unauthenticated `gh` would."""
            raise ShipError("gh is not authenticated")

    repairer = Repairer(
        failing_config,
        runner=FakeRunner(source_aware(repo)),
        agent=ScriptedAgent(diagnosis()),
        publisher=BrokenPublisher(),
    )

    report = repairer.repair(run_for(IMPORT_LOG), repo)

    assert report.outcome is Outcome.SHIPPED
    assert report.url is None
    assert "gh is not authenticated" in report.trace[-1]


def test_the_agent_receives_the_policy_limits(
    failing_config: MenderConfig, repo: Path, tmp_path: Path
) -> None:
    agent = ScriptedAgent(diagnosis(edits=[], confidence=0.0))
    repairer = build(failing_config, tmp_path, agent=agent)

    repairer.repair(run_for(IMPORT_LOG), repo)

    assert agent.requests[0].max_files_changed == failing_config.policy.max_files_changed
    assert ".github/workflows/**" in agent.requests[0].never_touch
