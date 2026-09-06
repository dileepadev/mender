"""Domain models shared across the repair loop.

Every stage of the loop hands the next one a value defined here. Keeping them in
one module means the pipeline's data flow can be read in a single sitting, and
that the safety-relevant invariants — a patch path can never escape the
workspace, for one — are enforced once, at the boundary, rather than repeated at
each stage.
"""

from __future__ import annotations

import difflib
from pathlib import PurePosixPath
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PathError(ValueError):
    """Raised when a patch names a path that cannot be part of a repository."""


def normalise_repo_path(path: str) -> str:
    """Normalise a repository-relative path and reject anything that escapes it.

    Args:
        path: A path as supplied by an agent, a webhook, or a fixture.

    Returns:
        The path in normalised POSIX form, relative to the repository root.

    Raises:
        PathError: If the path is empty, absolute, or climbs above the root.
    """
    text = path.strip().replace("\\", "/")
    if not text:
        raise PathError("Patch path is empty.")
    pure = PurePosixPath(text)
    if pure.is_absolute():
        raise PathError(f"Patch path must be repository-relative, got {path!r}.")
    parts = [part for part in pure.parts if part != "."]
    if any(part == ".." for part in parts):
        raise PathError(f"Patch path escapes the repository root: {path!r}.")
    if not parts:
        raise PathError(f"Patch path resolves to the repository root: {path!r}.")
    return "/".join(parts)


class FailedRun(BaseModel):
    """A CI run that finished red, as ingested by :mod:`mender.watch`.

    The ``logs`` field is attacker-controlled on any public repository. It is
    carried as data and never interpreted as instructions — see
    ``docs/safety-and-limits.md``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    repository: Annotated[str, Field(min_length=1)]
    commit: Annotated[str, Field(min_length=1)]
    job: str = "unknown"
    logs: str = ""
    branch: str | None = None
    run_url: str | None = None
    last_green_commit: str | None = None

    @property
    def short_commit(self) -> str:
        """The first seven characters of the commit SHA."""
        return self.commit[:7]


class FileEdit(BaseModel):
    """A single file's before-and-after content.

    Mender represents a patch as whole-file contents rather than a diff to be
    applied. Applying a diff can fail halfway and leave a workspace in an
    undefined state; writing a known result cannot. The unified diff is derived
    for display and for the blast-radius count.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    before: str | None = None
    after: str | None = None

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        return normalise_repo_path(value)

    @property
    def is_creation(self) -> bool:
        """Whether this edit adds a file that did not exist."""
        return self.before is None and self.after is not None

    @property
    def is_deletion(self) -> bool:
        """Whether this edit removes an existing file."""
        return self.before is not None and self.after is None

    @property
    def changed(self) -> bool:
        """Whether the edit alters anything at all."""
        return self.before != self.after

    def unified_diff(self) -> str:
        """Render the edit as a unified diff against the original content."""
        before = (self.before or "").splitlines(keepends=True)
        after = (self.after or "").splitlines(keepends=True)
        from_file = "/dev/null" if self.is_creation else f"a/{self.path}"
        to_file = "/dev/null" if self.is_deletion else f"b/{self.path}"
        return "".join(difflib.unified_diff(before, after, from_file, to_file))

    def line_count(self) -> int:
        """Count the added and removed lines this edit represents."""
        return sum(
            1
            for line in self.unified_diff().splitlines()
            if line[:1] in {"+", "-"} and not line.startswith(("+++", "---"))
        )


class Patch(BaseModel):
    """A complete proposed change, ready for policy evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    edits: list[FileEdit] = Field(default_factory=list)
    summary: str = ""

    @property
    def effective_edits(self) -> list[FileEdit]:
        """The edits that actually change something."""
        return [edit for edit in self.edits if edit.changed]

    @property
    def paths(self) -> list[str]:
        """The repository-relative paths this patch touches."""
        return [edit.path for edit in self.effective_edits]

    @property
    def files_changed(self) -> int:
        """How many files this patch touches."""
        return len(self.effective_edits)

    @property
    def lines_changed(self) -> int:
        """How many lines this patch adds or removes in total."""
        return sum(edit.line_count() for edit in self.effective_edits)

    @property
    def is_empty(self) -> bool:
        """Whether the patch would change nothing."""
        return not self.effective_edits

    def unified_diff(self) -> str:
        """Render the whole patch as a single unified diff."""
        return "".join(edit.unified_diff() for edit in self.effective_edits)

    def edit_for(self, path: str) -> FileEdit | None:
        """Return the edit touching ``path``, if this patch has one."""
        wanted = normalise_repo_path(path)
        return next((edit for edit in self.edits if edit.path == wanted), None)

    def without(self, *paths: str) -> Patch:
        """Return a copy of this patch with the named paths removed.

        Used by the proof step, which needs the regression test on its own to
        check that the test genuinely fails without the fix.
        """
        excluded = {normalise_repo_path(path) for path in paths}
        return Patch(
            edits=[edit for edit in self.edits if edit.path not in excluded],
            summary=self.summary,
        )

    def only(self, *paths: str) -> Patch:
        """Return a copy of this patch containing only the named paths."""
        wanted = {normalise_repo_path(path) for path in paths}
        return Patch(
            edits=[edit for edit in self.edits if edit.path in wanted],
            summary=self.summary,
        )
