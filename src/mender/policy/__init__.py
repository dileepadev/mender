"""Blast-radius limits, forbidden edits, and the test-weakening detector.

This package is built to be reached before a patch can become a pull request.
Anything that must never happen is enforced here, in code that inspects the
patch — not in a sentence in a prompt. See ``docs/safety-and-limits.md``.
"""

from mender.policy.engine import PolicyDecision, PolicyEngine, load_policy
from mender.policy.globs import glob_match, matches_any
from mender.policy.rules import WEAKENING_RULES, Violation
from mender.policy.weakening import detect_weakening, is_test_file

__all__ = [
    "WEAKENING_RULES",
    "PolicyDecision",
    "PolicyEngine",
    "Violation",
    "detect_weakening",
    "glob_match",
    "is_test_file",
    "load_policy",
    "matches_any",
]
