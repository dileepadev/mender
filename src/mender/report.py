"""The record of one trip through the repair loop.

Every stage appends to this. It is what the CLI prints, what the evidence
package is rendered from, and what the eval harness scores — so a run that
abstained carries exactly as much detail as one that shipped.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from mender.classify import Classification
from mender.diagnose.agent import Diagnosis
from mender.models import FailedRun, Patch
from mender.policy.engine import PolicyDecision
from mender.sandbox.reproduce import Reproduction
from mender.verify.prover import Proof


class Stage(StrEnum):
    """The seven steps of the loop."""

    WATCH = "watch"
    CLASSIFY = "classify"
    REPRODUCE = "reproduce"
    DIAGNOSE = "diagnose"
    FIX = "fix"
    PROVE = "prove"
    SHIP = "ship"


class Outcome(StrEnum):
    """How a repair attempt ended.

    Only ``SHIPPED`` produces a pull request. The rest are the abstention paths,
    and they are the expected result more often than not — see
    ``docs/safety-and-limits.md``.
    """

    SHIPPED = "shipped"
    """A proven fix, opened as a pull request with its evidence."""

    ABSTAINED = "abstained"
    """Diagnosed but not proven. An issue carries the diagnosis instead."""

    REJECTED = "rejected"
    """The patch broke policy. The attempt is reported, never shipped."""

    REPORTED = "reported"
    """Nothing to repair: an unknown class, a flaky test, or infrastructure."""

    ERROR = "error"
    """Mender itself failed. Not the repository's fault."""


class RepairReport(BaseModel):
    """Everything one repair attempt produced."""

    model_config = ConfigDict(extra="forbid")

    run: FailedRun
    outcome: Outcome
    stopped_at: Stage
    reason: str
    command: str = ""
    classification: Classification | None = None
    reproduction: Reproduction | None = None
    diagnosis: Diagnosis | None = None
    patch: Patch | None = None
    decision: PolicyDecision | None = None
    proof: Proof | None = None
    url: str | None = None
    duration_seconds: float = 0.0
    agent: str = ""
    runner: str = ""
    trace: list[str] = Field(default_factory=list)

    @property
    def shipped(self) -> bool:
        """Whether this attempt ended in a pull request."""
        return self.outcome is Outcome.SHIPPED

    @property
    def cost_usd(self) -> float:
        """What the attempt cost in agent spend."""
        return self.diagnosis.cost_usd if self.diagnosis else 0.0

    @property
    def headline(self) -> str:
        """A single line describing the outcome, for a terminal or a log."""
        return f"{self.outcome} at {self.stopped_at}: {self.reason}"
