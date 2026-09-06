"""Rule identifiers and the shape of a policy rejection.

Every rejection names the specific rule that was broken, so a human reading the
log can see exactly what was attempted and why it was stopped.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

# --- Blast radius -----------------------------------------------------------
EMPTY_PATCH = "empty-patch"
NEVER_TOUCH = "never-touch"
PATH_ALLOWLIST = "path-allowlist"
MAX_FILES_CHANGED = "max-files-changed"
MAX_LINES_CHANGED = "max-lines-changed"

# --- Test weakening ---------------------------------------------------------
TEST_DELETED = "test-deleted"
TEST_SKIPPED = "test-skipped"
TEST_UNPARSEABLE = "test-file-unparseable"
ASSERTION_REMOVED = "assertion-removed"
ASSERTION_WEAKENED = "assertion-weakened"
ASSERTION_MODIFIED = "assertion-modified"
TOLERANCE_WIDENED = "tolerance-widened"
PARAMETRIZE_REDUCED = "parametrize-reduced"
COVERAGE_THRESHOLD_LOWERED = "coverage-threshold-lowered"

WEAKENING_RULES: frozenset[str] = frozenset(
    {
        TEST_DELETED,
        TEST_SKIPPED,
        TEST_UNPARSEABLE,
        ASSERTION_REMOVED,
        ASSERTION_WEAKENED,
        ASSERTION_MODIFIED,
        TOLERANCE_WIDENED,
        PARAMETRIZE_REDUCED,
        COVERAGE_THRESHOLD_LOWERED,
    }
)
"""The rules that exist to stop a patch making a test easier to pass.

These are the non-negotiable ones. A blast-radius violation means a patch was
too big; one of these means it was dishonest.
"""


class Violation(BaseModel):
    """One specific rule a patch broke."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule: str
    detail: str
    path: str | None = None

    @property
    def is_weakening(self) -> bool:
        """Whether this violation is a test-weakening attempt."""
        return self.rule in WEAKENING_RULES

    def __str__(self) -> str:
        """Render as ``rule: detail`` with the path when there is one."""
        where = f" ({self.path})" if self.path else ""
        return f"{self.rule}{where}: {self.detail}"
