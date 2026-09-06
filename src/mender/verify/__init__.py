"""The proof step: the failing test passes and nothing else regressed.

This is what separates Mender from a suggestion engine, and the only stage that
can turn a diagnosis into a pull request.
"""

from mender.verify.prover import (
    FAILING_CHECK_PASSES,
    NOTHING_ELSE_BROKE,
    REGRESSION_CATCHES_BUG,
    Check,
    Proof,
    Prover,
)

__all__ = [
    "FAILING_CHECK_PASSES",
    "NOTHING_ELSE_BROKE",
    "REGRESSION_CATCHES_BUG",
    "Check",
    "Proof",
    "Prover",
]
