"""Blast-radius evaluation. The agent proposes; policy disposes.

The engine takes a finished patch and a policy, and returns an approval or a
list of the specific rules that were broken. It never sees the logs, the
diagnosis, or the prompt — which is the point. An injection that successfully
persuades the agent still has to get a forbidden patch past code that was never
exposed to the text that did the persuading.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mender.config import ConfigError, PolicyConfig
from mender.models import Patch
from mender.policy import rules
from mender.policy.globs import matches_any
from mender.policy.rules import Violation
from mender.policy.weakening import detect_weakening

DEFAULT_POLICY_FILENAME = "policies/default.yaml"


class PolicyDecision(BaseModel):
    """The verdict on one patch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approved: bool
    violations: list[Violation] = Field(default_factory=list)
    files_changed: int = 0
    lines_changed: int = 0
    limits: dict[str, str] = Field(default_factory=dict)

    @property
    def weakening_violations(self) -> list[Violation]:
        """Violations that represent an attempt to weaken a test."""
        return [violation for violation in self.violations if violation.is_weakening]

    @property
    def weakened_a_test(self) -> bool:
        """Whether the patch tried to make a test easier to pass."""
        return bool(self.weakening_violations)

    @property
    def reason(self) -> str:
        """A one-line summary naming the rules that were broken."""
        if self.approved:
            return (
                f"Approved: {self.files_changed} file(s), {self.lines_changed} line(s) "
                f"changed, within policy."
            )
        broken = ", ".join(dict.fromkeys(violation.rule for violation in self.violations))
        return f"Rejected by policy: {broken}."


class PolicyEngine:
    """Evaluates patches against a repository's blast-radius limits."""

    def __init__(self, policy: PolicyConfig) -> None:
        """Store the policy this engine enforces.

        Args:
            policy: The validated ``policy`` block, with the built-in
                never-touch globs already merged in by
                :class:`mender.config.PolicyConfig`.
        """
        self.policy = policy

    def evaluate(self, patch: Patch) -> PolicyDecision:
        """Decide whether a patch may proceed.

        Every rule is checked, and every violation is reported. Stopping at the
        first one would hide the rest from the human who has to judge what the
        agent was attempting.

        Args:
            patch: The proposed change.

        Returns:
            The decision, including the counts the limits were measured against.
        """
        violations: list[Violation] = []
        edits = patch.effective_edits

        if not edits:
            violations.append(
                Violation(rule=rules.EMPTY_PATCH, detail="The patch changes nothing.")
            )

        for edit in edits:
            forbidden = matches_any(self.policy.never_touch, edit.path)
            if forbidden is not None:
                violations.append(
                    Violation(
                        rule=rules.NEVER_TOUCH,
                        detail=f"Path is protected by the never-touch glob {forbidden!r}.",
                        path=edit.path,
                    )
                )
                # A protected path is out of bounds regardless of the allowlist;
                # reporting both rules for the same path would be noise.
                continue
            if self.policy.allow_paths and not matches_any(self.policy.allow_paths, edit.path):
                violations.append(
                    Violation(
                        rule=rules.PATH_ALLOWLIST,
                        detail=(
                            f"Path is outside the allowlist ({', '.join(self.policy.allow_paths)})."
                        ),
                        path=edit.path,
                    )
                )

        files_changed = patch.files_changed
        lines_changed = patch.lines_changed

        if files_changed > self.policy.max_files_changed:
            violations.append(
                Violation(
                    rule=rules.MAX_FILES_CHANGED,
                    detail=(
                        f"{files_changed} files changed, limit is {self.policy.max_files_changed}."
                    ),
                )
            )
        if lines_changed > self.policy.max_lines_changed:
            violations.append(
                Violation(
                    rule=rules.MAX_LINES_CHANGED,
                    detail=(
                        f"{lines_changed} lines changed, limit is {self.policy.max_lines_changed}."
                    ),
                )
            )

        for edit in edits:
            violations += detect_weakening(edit)

        return PolicyDecision(
            approved=not violations,
            violations=violations,
            files_changed=files_changed,
            lines_changed=lines_changed,
            limits=self.describe_limits(),
        )

    def describe_limits(self) -> dict[str, str]:
        """Summarise the limits that were applied, for the evidence package."""
        return {
            "max files changed": str(self.policy.max_files_changed),
            "max lines changed": str(self.policy.max_lines_changed),
            "allowed paths": ", ".join(self.policy.allow_paths) or "(any)",
            "never touch": f"{len(self.policy.never_touch)} protected globs",
        }


def load_policy(path: Path) -> PolicyConfig:
    """Read a standalone policy file.

    Args:
        path: Path to a YAML file containing a policy mapping.

    Returns:
        The validated policy, with the built-in never-touch globs merged in.

    Raises:
        ConfigError: If the file cannot be read or does not satisfy the schema.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Could not read {path}: {exc}") from exc

    try:
        data: Any = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc

    if data is None:
        raise ConfigError(f"{path} is empty.")
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a YAML mapping at the top level.")

    body = data.get("policy", data)
    if not isinstance(body, dict):
        raise ConfigError(f"{path} has a 'policy' key that is not a mapping.")

    try:
        return PolicyConfig.model_validate(body)
    except ValidationError as exc:
        raise ConfigError(f"{path} is invalid:\n{exc}") from exc
