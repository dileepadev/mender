"""The provider-agnostic agent interface.

Mender talks to one interface and never to a vendor SDK directly. Two things
follow from that. The repair loop can be tested end to end without a network
call or an API key, using a deterministic agent; and the guardrails downstream
do not care which agent produced a patch, because they inspect the patch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from mender.classify import Classification
from mender.models import FileEdit, Patch, normalise_repo_path


class ProposedEdit(BaseModel):
    """A file an agent wants to write, given in full.

    Whole-file content rather than a diff: a diff can fail to apply halfway and
    leave a workspace in an undefined state, and a malformed hunk is a class of
    bug Mender should not have to reason about at all.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    content: str

    def normalised_path(self) -> str:
        """The path, validated as repository-relative."""
        return normalise_repo_path(self.path)


class RegressionTest(BaseModel):
    """The test that proves the fix, and the node ID that runs it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    content: str
    test_id: str
    rationale: str = ""


class DiagnosisRequest(BaseModel):
    """Everything an agent is given, and nothing it is not.

    ``failing_output`` and the classification's evidence are derived from CI
    logs, which are attacker-controlled on any public repository. They are
    carried here as data. See ``docs/safety-and-limits.md``.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    classification: Classification
    failing_output: str
    workspace: Path
    test_command: str
    diff_since_last_green: str = ""
    file_context: dict[str, str] = Field(default_factory=dict)
    previous_attempts: list[str] = Field(default_factory=list)
    """Why earlier attempts at this failure were rejected, oldest first."""

    allow_paths: list[str] = Field(default_factory=list)
    never_touch: list[str] = Field(default_factory=list)
    max_files_changed: int = 5
    max_lines_changed: int = 120


class Diagnosis(BaseModel):
    """An agent's explanation, and what it proposes to do about it."""

    model_config = ConfigDict(extra="forbid")

    root_cause: str
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    edits: list[ProposedEdit] = Field(default_factory=list)
    regression_test: RegressionTest | None = None
    agent: str = "unknown"
    cost_usd: float = 0.0
    notes: str = ""

    @property
    def has_fix(self) -> bool:
        """Whether the agent actually proposed a change."""
        return bool(self.edits)

    def to_patch(self, workspace: Path) -> Patch:
        """Turn the proposal into a patch, read against the current workspace.

        Args:
            workspace: The checked-out repository the edits apply to.

        Returns:
            A patch carrying both the before and after content of every file.

        Raises:
            PathError: If any proposed path escapes the repository root.
        """
        proposals = list(self.edits)
        if self.regression_test is not None:
            proposals.append(
                ProposedEdit(
                    path=self.regression_test.path,
                    content=self.regression_test.content,
                )
            )

        edits: list[FileEdit] = []
        for proposal in proposals:
            relative = proposal.normalised_path()
            target = workspace / relative
            before = target.read_text(encoding="utf-8") if target.is_file() else None
            edits.append(FileEdit(path=relative, before=before, after=proposal.content))
        return Patch(edits=edits, summary=self.root_cause)


@runtime_checkable
class DiagnosisAgent(Protocol):
    """Explains why a run failed and proposes a minimal change."""

    name: str

    def diagnose(self, request: DiagnosisRequest) -> Diagnosis:
        """Return a root cause and a proposed fix for one reproduced failure."""
        ...
