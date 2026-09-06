"""Mender — CI that fixes itself, and proves the fix.

Mender watches a pipeline, reproduces failures in a sandbox, diagnoses the root
cause, and opens a pull request containing both the fix and the regression test
that proves it. When it cannot prove a fix, it opens an issue with its diagnosis
instead of guessing.

See ``docs/how-it-works.md`` for the repair loop and ``docs/safety-and-limits.md``
for the guardrails that constrain it.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _package_version

try:
    __version__ = _package_version("mender")
except PackageNotFoundError:  # pragma: no cover - only hit in a non-installed tree
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
