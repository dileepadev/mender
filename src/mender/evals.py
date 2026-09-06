"""The eval harness: measuring Mender against failures with known answers.

A repair rate quoted without a corpus is an anecdote. Every case here is a small
repository broken in one specific way, with the outcome Mender *should* reach
recorded alongside it — including the cases where the right answer is to decline.

Two numbers matter more than the rest. The **false-fix rate** counts cases where
Mender shipped a pull request for a failure it was supposed to decline; it is
published deliberately, because it is what makes the other numbers believable.
The **abstention rate** counts the declines, and a high one is healthy.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from mender.classify import FailureClass
from mender.config import ConfigError, load_config
from mender.diagnose.agent import DiagnosisAgent
from mender.diagnose.heuristic import HeuristicAgent
from mender.models import FailedRun
from mender.policy.globs import matches_any
from mender.repair import Repairer
from mender.report import Outcome, RepairReport
from mender.sandbox.runner import LocalRunner, Runner
from mender.ship.publish import DryRunPublisher

CASE_FILENAME = "case.yaml"
REPO_DIRNAME = "repo"
LOGS_FILENAME = "logs.txt"


class EvalCase(BaseModel):
    """One historical failure with a known correct outcome."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    description: str
    failure_class: FailureClass
    expect: Outcome
    commit: str = "0000000"
    repository: str = "mender/eval-fixture"
    notes: str = ""
    directory: Path = Field(default=Path())

    @property
    def repo_dir(self) -> Path:
        """The broken repository this case ships."""
        return self.directory / REPO_DIRNAME

    @property
    def logs(self) -> str:
        """The CI output the case starts from."""
        path = self.directory / LOGS_FILENAME
        return path.read_text(encoding="utf-8") if path.is_file() else ""


class CaseResult(BaseModel):
    """What Mender actually did with one case."""

    model_config = ConfigDict(extra="forbid")

    name: str
    failure_class: FailureClass
    expected: Outcome
    actual: Outcome
    stopped_at: str
    reason: str
    duration_seconds: float = 0.0
    cost_usd: float = 0.0
    touched_forbidden_paths: list[str] = Field(default_factory=list)

    @property
    def matched(self) -> bool:
        """Whether Mender reached the outcome the case expects."""
        return self.actual is self.expected and not self.touched_forbidden_paths

    @property
    def false_fix(self) -> bool:
        """Whether Mender shipped a fix for a case it should have declined."""
        return self.actual is Outcome.SHIPPED and self.expected is not Outcome.SHIPPED


class CorpusResult(BaseModel):
    """Aggregate results across the corpus."""

    model_config = ConfigDict(extra="forbid")

    results: list[CaseResult] = Field(default_factory=list)

    @property
    def total(self) -> int:
        """How many cases ran."""
        return len(self.results)

    @property
    def matched(self) -> int:
        """How many cases reached the expected outcome."""
        return sum(1 for result in self.results if result.matched)

    @property
    def repair_rate(self) -> float:
        """The share of repairable cases that were actually repaired."""
        repairable = [r for r in self.results if r.expected is Outcome.SHIPPED]
        if not repairable:
            return 0.0
        shipped = sum(1 for r in repairable if r.actual is Outcome.SHIPPED)
        return round(shipped / len(repairable), 3)

    @property
    def false_fix_rate(self) -> float:
        """The share of cases where Mender shipped something it should not have."""
        if not self.results:
            return 0.0
        return round(sum(1 for r in self.results if r.false_fix) / self.total, 3)

    @property
    def abstention_rate(self) -> float:
        """The share of cases where Mender declined to open a pull request."""
        if not self.results:
            return 0.0
        declined = sum(1 for r in self.results if r.actual is not Outcome.SHIPPED)
        return round(declined / self.total, 3)

    @property
    def total_cost_usd(self) -> float:
        """What running the corpus cost in agent spend."""
        return round(sum(result.cost_usd for result in self.results), 4)

    @property
    def mean_seconds(self) -> float:
        """Mean time from failure to outcome."""
        if not self.results:
            return 0.0
        return round(sum(r.duration_seconds for r in self.results) / self.total, 3)

    def by_class(self) -> dict[FailureClass, tuple[int, int]]:
        """Matched and total counts per failure class."""
        counts: dict[FailureClass, tuple[int, int]] = {}
        for result in self.results:
            matched, total = counts.get(result.failure_class, (0, 0))
            counts[result.failure_class] = (
                matched + int(result.matched),
                total + 1,
            )
        return counts


def discover_cases(root: Path) -> list[EvalCase]:
    """Load every case in a corpus directory, in name order.

    Args:
        root: The corpus root, containing one directory per case.

    Returns:
        The loaded cases.

    Raises:
        ConfigError: If a case file is missing or invalid.
    """
    cases = []
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        case_file = directory / CASE_FILENAME
        if case_file.is_file():
            cases.append(load_case(directory))
    return cases


def load_case(directory: Path) -> EvalCase:
    """Read one case definition.

    Args:
        directory: The case directory, containing ``case.yaml``.

    Returns:
        The validated case.

    Raises:
        ConfigError: If the case file is missing, malformed, or invalid.
    """
    case_file = directory / CASE_FILENAME
    try:
        raw = yaml.safe_load(case_file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Could not read {case_file}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{case_file} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{case_file} must contain a YAML mapping.")
    return EvalCase.model_validate({**raw, "directory": directory})


def run_case(
    case: EvalCase,
    *,
    agent: DiagnosisAgent | None = None,
    runner: Runner | None = None,
) -> CaseResult:
    """Run one case through the whole repair loop.

    The case's repository is copied to a temporary directory first, so a run
    never mutates the corpus and a failed run leaves nothing behind.

    Args:
        case: The case to run.
        agent: Diagnosis agent. Defaults to the deterministic one.
        runner: Sandbox backend. Defaults to the local runner, since eval
            fixtures are code this repository ships and already trusts.

    Returns:
        What Mender did, compared against what the case expects.
    """
    with tempfile.TemporaryDirectory(prefix=f"mender-eval-{case.name}-") as temporary:
        root = Path(temporary)
        workspace = root / "workspace"
        shutil.copytree(case.repo_dir, workspace)
        config = load_config(workspace / "mender.yaml")

        repairer = Repairer(
            config,
            runner=runner or LocalRunner(),
            agent=agent or HeuristicAgent(),
            publisher=DryRunPublisher(root / "evidence"),
        )
        report = repairer.repair(
            FailedRun(
                repository=case.repository,
                commit=case.commit,
                job="eval",
                logs=case.logs,
            ),
            workspace,
        )

    return CaseResult(
        name=case.name,
        failure_class=case.failure_class,
        expected=case.expect,
        actual=report.outcome,
        stopped_at=str(report.stopped_at),
        reason=report.reason,
        duration_seconds=report.duration_seconds,
        cost_usd=report.cost_usd,
        touched_forbidden_paths=_forbidden_paths(report, config.policy.never_touch),
    )


def run_corpus(
    root: Path,
    *,
    agent: DiagnosisAgent | None = None,
    runner: Runner | None = None,
) -> CorpusResult:
    """Run every case in a corpus and aggregate the results.

    Args:
        root: The corpus root.
        agent: Diagnosis agent. Defaults to the deterministic one.
        runner: Sandbox backend. Defaults to the local runner.

    Returns:
        Per-case results and the aggregate rates.
    """
    return CorpusResult(
        results=[run_case(case, agent=agent, runner=runner) for case in discover_cases(root)]
    )


def _forbidden_paths(report: RepairReport, never_touch: list[str]) -> list[str]:
    """Report any protected path a patch touched, whatever the outcome.

    Checked on every case, not only the ones that shipped. A patch that reached
    a protected path and was then rejected for some other reason is still a
    result worth seeing.
    """
    if report.patch is None:
        return []
    return [path for path in report.patch.paths if matches_any(never_touch, path)]
