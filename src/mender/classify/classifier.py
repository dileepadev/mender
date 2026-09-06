"""Turn raw CI output into a failure class and a confidence score.

The classifier is a deterministic, ordered set of pattern rules. It is
deliberately not a model: the very first thing Mender does with untrusted log
text should not be to hand it to something that can be talked into a different
answer. A rule either matches a distinctive error signature or it does not.

Rules are ordered by *root-cause precedence*, not by pattern specificity. A
network outage during dependency installation produces both a connection error
and a resolver error; the connection error is the real cause, so infrastructure
signals are tested first.
"""

from __future__ import annotations

import re
from typing import Annotated, NamedTuple

from pydantic import BaseModel, ConfigDict, Field

from mender.classify.classes import FailureClass, Support, support_for

MAX_EVIDENCE_CHARS = 200
AMBIGUITY_PENALTY = 0.15
"""Confidence deducted when a second, different class also matched.

Mender abstains below a threshold, so an honest penalty for an ambiguous log is
worth more than a confident guess.
"""


class Rule(NamedTuple):
    """One classification rule."""

    name: str
    failure_class: FailureClass
    confidence: float
    pattern: re.Pattern[str]


def _rule(name: str, failure_class: FailureClass, confidence: float, pattern: str) -> Rule:
    return Rule(name, failure_class, confidence, re.compile(pattern, re.MULTILINE))


RULES: tuple[Rule, ...] = (
    # --- Infrastructure: tested first, see the module docstring ---------------
    _rule(
        "dns-failure",
        FailureClass.INFRASTRUCTURE,
        0.85,
        r"Temporary failure in name resolution|Could not resolve host|"
        r"Name or service not known",
    ),
    _rule(
        "connection-failure",
        FailureClass.INFRASTRUCTURE,
        0.8,
        r"Connection refused|Connection reset by peer|Read timed out|"
        r"ConnectTimeoutError|502 Bad Gateway|503 Service Unavailable",
    ),
    _rule(
        "runner-failure",
        FailureClass.INFRASTRUCTURE,
        0.85,
        r"docker: Error response from daemon|lost communication with the server|"
        r"The runner has received a shutdown signal|No space left on device",
    ),
    # --- Dependency drift ----------------------------------------------------
    _rule(
        "resolver-conflict",
        FailureClass.DEPENDENCY_DRIFT,
        0.9,
        r"ResolutionImpossible|The conflict is caused by|"
        r"pkg_resources\.(?:VersionConflict|DistributionNotFound)|"
        r"ERROR: Cannot install",
    ),
    _rule(
        "distribution-missing",
        FailureClass.DEPENDENCY_DRIFT,
        0.85,
        r"No matching distribution found for|"
        r"because it (?:requires|depends on) .*which (?:is|are) not available",
    ),
    # --- Broken imports ------------------------------------------------------
    _rule(
        "import-name-missing",
        FailureClass.IMPORT_ERROR,
        0.95,
        r"ImportError: cannot import name '(?P<name>[^']+)' from '(?P<module>[^']+)'",
    ),
    _rule(
        "module-missing",
        FailureClass.IMPORT_ERROR,
        0.8,
        r"ModuleNotFoundError: No module named '(?P<module>[^']+)'",
    ),
    _rule(
        "relative-import",
        FailureClass.IMPORT_ERROR,
        0.9,
        r"ImportError: attempted relative import",
    ),
    # --- Types ---------------------------------------------------------------
    _rule(
        "mypy-error",
        FailureClass.TYPE_ERROR,
        0.9,
        r"^.+:\d+: error: .+\[[a-z][a-z-]+\]\s*$",
    ),
    _rule(
        "mypy-summary",
        FailureClass.TYPE_ERROR,
        0.85,
        r"^Found \d+ errors? in \d+ files?",
    ),
    # --- Formatting ----------------------------------------------------------
    _rule(
        "would-reformat",
        FailureClass.FORMAT,
        0.95,
        r"^Would reformat: |^\d+ files? would be reformatted",
    ),
    # --- Lint ----------------------------------------------------------------
    _rule(
        "ruff-diagnostic",
        FailureClass.LINT,
        0.9,
        r"^\s*[^\s:]+:\d+:\d+: [A-Z]{1,4}\d{3,4} ",
    ),
    # Ruff's newer default layout puts the rule code first and the location on
    # the following line. Both are in the wild; both are recognised.
    _rule(
        "ruff-diagnostic-full",
        FailureClass.LINT,
        0.9,
        r"^[A-Z]{1,4}\d{3,4} (?:\[\*\] )?.*\n\s*-->\s\S+:\d+:\d+",
    ),
    _rule(
        "ruff-summary",
        FailureClass.LINT,
        0.8,
        r"^Found \d+ errors?\.$",
    ),
    # --- Missing configuration ----------------------------------------------
    _rule(
        "missing-env-var",
        FailureClass.MISSING_CONFIG,
        0.7,
        r"[Ee]nvironment variable [\"'`]?[A-Z_][A-Z0-9_]* ?[\"'`]? (?:is )?not set|"
        r"KeyError: '(?P<key>[A-Z_][A-Z0-9_]+)'",
    ),
    _rule(
        "missing-config-file",
        FailureClass.MISSING_CONFIG,
        0.7,
        r"FileNotFoundError: \[Errno 2\][^\n]*'[^']*\.(?:ya?ml|toml|ini|cfg|json|env)'",
    ),
    # --- Assertions ----------------------------------------------------------
    _rule(
        "assertion-error",
        FailureClass.ASSERTION,
        0.75,
        r"^E\s+(?:AssertionError|assert )|^\s*AssertionError\b",
    ),
)

_FAILING_TEST_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^(?:FAILED|ERROR) (?P<test>[^\s:]+::[^\s]+)", re.MULTILINE),
    re.compile(r"^(?P<test>[^\s:]+::[^\s]+) (?:FAILED|ERROR)", re.MULTILINE),
)


class Classification(BaseModel):
    """What the classifier concluded about a red run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    failure_class: FailureClass
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    rule: str = ""
    evidence: str = ""
    failing_tests: list[str] = Field(default_factory=list)
    competing_classes: list[FailureClass] = Field(default_factory=list)
    detail: dict[str, str] = Field(default_factory=dict)

    @property
    def support(self) -> Support:
        """How far Mender is willing to go with this class."""
        return support_for(self.failure_class)

    @property
    def is_repairable(self) -> bool:
        """Whether Mender attempts a repair for this class at all."""
        return self.support is Support.TARGET


def extract_failing_tests(logs: str) -> list[str]:
    """Pull pytest node IDs for failing tests out of a log.

    Args:
        logs: Raw CI output.

    Returns:
        Node IDs in first-seen order, deduplicated.
    """
    seen: dict[str, None] = {}
    for pattern in _FAILING_TEST_PATTERNS:
        for match in pattern.finditer(logs):
            seen.setdefault(match.group("test"), None)
    return list(seen)


def _evidence_line(logs: str, match: re.Match[str]) -> str:
    """Return the single log line a rule matched, truncated for reuse in a PR."""
    start = logs.rfind("\n", 0, match.start()) + 1
    end = logs.find("\n", match.end())
    line = logs[start:] if end == -1 else logs[start:end]
    line = line.strip()
    if len(line) > MAX_EVIDENCE_CHARS:
        line = line[: MAX_EVIDENCE_CHARS - 1] + "…"
    return line


def classify(logs: str) -> Classification:
    """Classify a failure from its CI output.

    Args:
        logs: Raw CI output. Treated strictly as data — never as instructions.

    Returns:
        The failure class, a confidence score, the rule and log line that
        justify it, and any other classes whose signals also appeared.
    """
    matches: list[tuple[Rule, re.Match[str]]] = []
    for rule in RULES:
        found = rule.pattern.search(logs)
        if found is not None:
            matches.append((rule, found))

    failing_tests = extract_failing_tests(logs)

    if not matches:
        return Classification(
            failure_class=FailureClass.UNKNOWN,
            confidence=0.0,
            evidence="No recognised failure signature in the log.",
            failing_tests=failing_tests,
        )

    rule, match = matches[0]
    competing = [
        other.failure_class
        for other, _ in matches[1:]
        if other.failure_class is not rule.failure_class
    ]
    confidence = rule.confidence - (AMBIGUITY_PENALTY if competing else 0.0)

    detail = {key: value for key, value in match.groupdict().items() if value}

    return Classification(
        failure_class=rule.failure_class,
        confidence=round(max(confidence, 0.0), 3),
        rule=rule.name,
        evidence=_evidence_line(logs, match),
        failing_tests=failing_tests,
        competing_classes=list(dict.fromkeys(competing)),
        detail=detail,
    )
