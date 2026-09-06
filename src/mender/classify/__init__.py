"""Log parsers that turn raw CI output into a failure class and confidence.

Log text is untrusted input. Nothing in this package interprets it as anything
but data — see ``docs/safety-and-limits.md``.
"""

from mender.classify.classes import SUPPORT, FailureClass, Support, support_for
from mender.classify.classifier import (
    RULES,
    Classification,
    classify,
    extract_failing_tests,
)

__all__ = [
    "RULES",
    "SUPPORT",
    "Classification",
    "FailureClass",
    "Support",
    "classify",
    "extract_failing_tests",
    "support_for",
]
