"""The failure taxonomy, and how far Mender is willing to go with each class."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum


class FailureClass(StrEnum):
    """What kind of failure a red run represents."""

    DEPENDENCY_DRIFT = "dependency_drift"
    FLAKY_TEST = "flaky_test"
    LINT = "lint"
    FORMAT = "format"
    TYPE_ERROR = "type_error"
    IMPORT_ERROR = "import_error"
    MISSING_CONFIG = "missing_config"
    ASSERTION = "assertion"
    INFRASTRUCTURE = "infrastructure"
    UNKNOWN = "unknown"


class Support(StrEnum):
    """How Mender treats a class it has recognised."""

    TARGET = "target"
    """Repair is attempted end to end."""

    LATER = "later"
    """Recognised and reported, but repair is not attempted yet."""

    REPORT_ONLY = "report_only"
    """Never Mender's to repair. Diagnose, report, stop."""

    UNSUPPORTED = "unsupported"
    """Not understood. Stop and say so."""


SUPPORT: Mapping[FailureClass, Support] = {
    FailureClass.DEPENDENCY_DRIFT: Support.TARGET,
    FailureClass.LINT: Support.TARGET,
    FailureClass.FORMAT: Support.TARGET,
    FailureClass.TYPE_ERROR: Support.TARGET,
    FailureClass.IMPORT_ERROR: Support.TARGET,
    FailureClass.MISSING_CONFIG: Support.TARGET,
    FailureClass.FLAKY_TEST: Support.REPORT_ONLY,
    FailureClass.INFRASTRUCTURE: Support.REPORT_ONLY,
    FailureClass.ASSERTION: Support.LATER,
    FailureClass.UNKNOWN: Support.UNSUPPORTED,
}
"""Support level per failure class.

Mirrors the table in ``README.md``. ``FLAKY_TEST`` is report-only by design:
there is usually nothing in a flaky test to fix, and editing it to stop failing
would hide the problem rather than solve it.
"""


def support_for(failure_class: FailureClass) -> Support:
    """Return the support level for a failure class."""
    return SUPPORT.get(failure_class, Support.UNSUPPORTED)
