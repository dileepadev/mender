"""Step 3 of the loop: make the failure happen again, on purpose.

Everything downstream depends on this. You cannot prove you fixed something you
were never able to make happen deliberately, so a failure that will not
reproduce is never repaired — it is reported as flaky and left alone.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from mender.config import MenderConfig
from mender.sandbox.runner import CommandResult, Runner


class Reproduction(BaseModel):
    """What happened when Mender tried to reproduce a failure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    command: str
    reproduced: bool
    flaky: bool
    attempts: Annotated[int, Field(ge=1)]
    failures: Annotated[int, Field(ge=0)]
    runs: list[CommandResult] = Field(default_factory=list)

    @property
    def failure_rate(self) -> float:
        """The share of attempts that failed."""
        return round(self.failures / self.attempts, 3)

    @property
    def first_run(self) -> CommandResult:
        """The first attempt, whose output is the one worth diagnosing."""
        return self.runs[0]

    @property
    def summary(self) -> str:
        """A one-line description suitable for a PR or issue body."""
        if self.reproduced:
            return f"Reproduced on the first attempt in {self.first_run.duration_seconds}s."
        if self.flaky:
            return (
                f"Did not reproduce. Failed {self.failures} of {self.attempts} attempts "
                f"({self.failure_rate:.0%}) — treated as flaky."
            )
        return f"Did not reproduce in {self.attempts} attempts. The failure appears resolved."


def reproduce(
    runner: Runner,
    config: MenderConfig,
    workspace: Path,
    *,
    command: str | None = None,
) -> Reproduction:
    """Run the failing command in a sandbox and decide what kind of failure it is.

    A first run that fails is a real, reproducible failure and the loop
    continues. A first run that passes is not: the command is re-run
    ``sandbox.flaky_reruns`` times to measure how often it actually fails, and
    the result is reported rather than repaired.

    Args:
        runner: The sandbox backend to execute in.
        config: The repository's validated configuration.
        workspace: The checked-out repository at the failing commit.
        command: Command to run. Defaults to the configured test command.

    Returns:
        The reproduction result, including every run's captured output.
    """
    target = command or config.test_command
    timeout = config.sandbox.timeout_seconds

    first = runner.run(target, workspace=workspace, timeout_seconds=timeout)
    if not first.ok:
        return Reproduction(
            command=target,
            reproduced=True,
            flaky=False,
            attempts=1,
            failures=1,
            runs=[first],
        )

    runs = [first]
    for _ in range(config.sandbox.flaky_reruns):
        runs.append(runner.run(target, workspace=workspace, timeout_seconds=timeout))

    failures = sum(1 for run in runs if not run.ok)
    return Reproduction(
        command=target,
        reproduced=False,
        flaky=failures > 0,
        attempts=len(runs),
        failures=failures,
        runs=runs,
    )
