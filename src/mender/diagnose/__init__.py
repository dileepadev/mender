"""Provider-agnostic agent layer that explains why a run failed.

Mender talks to :class:`DiagnosisAgent`, never to a vendor SDK. Two
implementations ship: a deterministic one for the failure classes with exactly
one correct repair, and one backed by a Claude model for everything else.
"""

from mender.diagnose.agent import (
    Diagnosis,
    DiagnosisAgent,
    DiagnosisRequest,
    ProposedEdit,
    RegressionTest,
)
from mender.diagnose.context import build_request, diff_since_last_green
from mender.diagnose.heuristic import HeuristicAgent
from mender.diagnose.prompt import SYSTEM_PROMPT, build_user_message

__all__ = [
    "SYSTEM_PROMPT",
    "Diagnosis",
    "DiagnosisAgent",
    "DiagnosisRequest",
    "HeuristicAgent",
    "ProposedEdit",
    "RegressionTest",
    "build_request",
    "build_user_message",
    "diff_since_last_green",
]
