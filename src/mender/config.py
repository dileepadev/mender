"""Loading and validation for ``mender.yaml``, the per-repository configuration.

The schema is deliberately strict. Unknown keys are rejected rather than
ignored, so a typo in a safety limit fails loudly instead of silently falling
back to a permissive default.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

CONFIG_FILENAME = "mender.yaml"

BUILTIN_NEVER_TOUCH: tuple[str, ...] = (
    ".github/workflows/**",
    ".gitlab-ci.yml",
    "mender.yaml",
    "policies/**",
    "**/migrations/**",
    "**/secrets/**",
    "**/*.pem",
    "**/*.key",
    ".env",
    ".env.*",
)
"""Globs that may never be modified by a Mender patch.

A repository may add to this set through its own configuration, but it can never
remove an entry. These are the paths where a mistake is hardest to reverse, and
where an agent could otherwise disable its own guardrails. Enforced here in
code rather than requested in a prompt — see ``docs/safety-and-limits.md``.
"""


class ConfigError(Exception):
    """Raised when a ``mender.yaml`` file is missing, unreadable, or invalid."""


class SandboxConfig(BaseModel):
    """Limits applied to the ephemeral container used for reproduction."""

    model_config = ConfigDict(extra="forbid")

    image: str = "python:3.12-slim"
    network: bool = False
    timeout_seconds: Annotated[int, Field(gt=0, le=3600)] = 600
    memory_mb: Annotated[int, Field(gt=0, le=32768)] = 2048
    cpus: Annotated[float, Field(gt=0, le=16)] = 2.0
    flaky_reruns: Annotated[int, Field(ge=1, le=20)] = 5


class PolicyConfig(BaseModel):
    """Blast-radius limits applied to every generated patch."""

    model_config = ConfigDict(extra="forbid")

    max_files_changed: Annotated[int, Field(gt=0, le=50)] = 5
    max_lines_changed: Annotated[int, Field(gt=0, le=1000)] = 120
    allow_paths: list[str] = Field(default_factory=lambda: ["src/**", "tests/**"])
    never_touch: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _apply_builtin_never_touch(self) -> Self:
        """Union the repository's never-touch globs with the built-in set.

        A repository can add protections. It can never remove them.
        """
        merged = list(self.never_touch)
        merged.extend(glob for glob in BUILTIN_NEVER_TOUCH if glob not in merged)
        self.never_touch = merged
        return self


class DiagnoseConfig(BaseModel):
    """Limits on the agent layer that produces diagnoses and patches."""

    model_config = ConfigDict(extra="forbid")

    confidence_threshold: Annotated[float, Field(ge=0.0, le=1.0)] = 0.8
    max_attempts: Annotated[int, Field(ge=1, le=10)] = 3
    max_cost_usd: Annotated[float, Field(gt=0)] = 1.0


class MenderConfig(BaseModel):
    """The full, validated contents of a ``mender.yaml`` file."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    language: Literal["python"] = "python"
    test_command: Annotated[str, Field(min_length=1)]
    lint_command: str | None = None
    type_check_command: str | None = None
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    diagnose: DiagnoseConfig = Field(default_factory=DiagnoseConfig)


def find_config(start: Path | None = None) -> Path:
    """Search ``start`` and its parent directories for a ``mender.yaml`` file.

    Args:
        start: Directory to begin searching from. Defaults to the current
            working directory.

    Returns:
        The path to the first ``mender.yaml`` found.

    Raises:
        ConfigError: If no configuration file exists in the tree.
    """
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        candidate = directory / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    raise ConfigError(f"No {CONFIG_FILENAME} found in {current} or any parent directory.")


def load_config(path: Path) -> MenderConfig:
    """Read and validate a ``mender.yaml`` file.

    Args:
        path: Path to the configuration file.

    Returns:
        The validated configuration.

    Raises:
        ConfigError: If the file cannot be read, is not valid YAML, or does not
            satisfy the schema.
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

    try:
        return MenderConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"{path} is invalid:\n{exc}") from exc
