"""Rendering the evidence package a human actually reads.

Mender never merges its own work, so every pull request has to be judged by
somebody in a few minutes. That is only possible if the diagnosis, the patch,
the regression test, the before-and-after logs, the policy limits that applied,
and the cost all arrive together.

An abstention gets the same treatment. An issue that says "could not fix it" is
worth very little; one that says what was wrong, what Mender would have changed,
and exactly which check refused to hold is worth reading.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from mender.report import Outcome, RepairReport

MAX_LOG_CHARS = 4_000
MAX_DIFF_CHARS = 20_000


class Evidence(BaseModel):
    """A rendered title and body, ready to become a pull request or an issue."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str
    body: str
    labels: list[str] = []


def render(report: RepairReport) -> Evidence:
    """Render the right evidence package for however the attempt ended."""
    if report.outcome is Outcome.SHIPPED:
        return render_pull_request(report)
    return render_issue(report)


def render_pull_request(report: RepairReport) -> Evidence:
    """Render the pull request for a proven fix."""
    diagnosis = report.diagnosis
    patch = report.patch
    proof = report.proof
    if diagnosis is None or patch is None or proof is None:  # pragma: no cover
        raise ValueError("A shipped report must carry a diagnosis, a patch, and a proof.")

    lines = [
        f"**Diagnosis:** {diagnosis.root_cause}",
        "",
        f"Mender reproduced the failure at `{report.run.short_commit}`, patched it, and "
        f"proved the patch in a sandbox. A human decides whether to merge — Mender "
        f"never merges its own work.",
        "",
        "## Patch",
        "",
        f"{patch.files_changed} file(s), {patch.lines_changed} changed line(s).",
        "",
        _fence(_truncate(patch.unified_diff(), MAX_DIFF_CHARS), "diff"),
    ]

    if diagnosis.regression_test is not None:
        lines += [
            "",
            "## Regression test",
            "",
            f"`{diagnosis.regression_test.test_id}`",
            "",
            diagnosis.regression_test.rationale
            or "Verified failing before the patch, passing after.",
        ]

    lines += ["", "## Proof", ""]
    lines += [
        f"- {'✅' if check.passed else '❌'} **{check.name}** — {check.detail}"
        for check in proof.checks
    ]

    lines += ["", "## Suite", ""]
    lines += [
        f"- baseline: {_suite_line(proof.baseline_failures)}",
        f"- after the patch: {_suite_line(proof.remaining_failures)}",
    ]

    lines += _classification_section(report)
    lines += _policy_section(report)
    lines += _logs_section(report)
    lines += _footer(report)

    title = _title(diagnosis.root_cause)
    return Evidence(title=title, body="\n".join(lines), labels=["mender"])


def render_issue(report: RepairReport) -> Evidence:
    """Render the issue Mender opens when it declines to ship."""
    lines = [
        f"Mender stopped at **{report.stopped_at}** and did not open a pull request.",
        "",
        f"**Why:** {report.reason}",
        "",
        f"Failing run: `{report.run.job}` at commit `{report.run.short_commit}`"
        + (f" — {report.run.run_url}" if report.run.run_url else ""),
    ]

    if report.diagnosis is not None and report.diagnosis.root_cause:
        lines += ["", "## Diagnosis", "", report.diagnosis.root_cause]
        if report.diagnosis.notes:
            lines += ["", report.diagnosis.notes]

    if report.proof is not None and report.proof.failed_checks:
        lines += ["", "## What could not be proved", ""]
        lines += [f"- **{check.name}** — {check.detail}" for check in report.proof.failed_checks]

    if report.decision is not None and not report.decision.approved:
        lines += ["", "## Policy rejections", ""]
        lines += [f"- `{v.rule}` {v.path or ''} — {v.detail}" for v in report.decision.violations]
        if report.decision.weakened_a_test:
            lines += [
                "",
                "> This patch tried to make a test easier to pass. That is the one "
                "> rejection Mender never negotiates. See `docs/safety-and-limits.md`.",
            ]

    if report.patch is not None and not report.patch.is_empty:
        lines += [
            "",
            "## What Mender would have changed",
            "",
            "Not applied — recorded so a human can judge the reasoning.",
            "",
            _fence(_truncate(report.patch.unified_diff(), MAX_DIFF_CHARS), "diff"),
        ]

    if report.reproduction is not None and report.reproduction.flaky:
        lines += [
            "",
            "## Flaky test",
            "",
            report.reproduction.summary,
            "",
            "Mender does not edit flaky tests. There is usually nothing in the test "
            "to fix, and changing it to stop failing would hide the problem. "
            "Quarantine it and investigate the source of the nondeterminism.",
        ]

    lines += _classification_section(report)
    lines += _logs_section(report)
    lines += _footer(report)

    return Evidence(
        title=_title(report.reason, prefix="CI failure Mender could not repair"),
        body="\n".join(lines),
        labels=["mender", "mender:abstained"],
    )


# --- Shared sections ---------------------------------------------------------


def _classification_section(report: RepairReport) -> list[str]:
    """Render what the classifier concluded, and on what evidence."""
    classification = report.classification
    if classification is None:
        return []
    lines = [
        "",
        "## Classification",
        "",
        f"- class: `{classification.failure_class}` "
        f"(confidence {classification.confidence}, rule `{classification.rule}`)",
        f"- evidence: `{classification.evidence}`",
    ]
    if classification.competing_classes:
        competing = ", ".join(f"`{name}`" for name in classification.competing_classes)
        lines.append(f"- other signals present: {competing}")
    if report.reproduction is not None:
        lines.append(f"- reproduction: {report.reproduction.summary}")
    return lines


def _policy_section(report: RepairReport) -> list[str]:
    """Render the blast-radius limits the patch was measured against."""
    if report.decision is None:
        return []
    lines = ["", "## Policy", ""]
    lines += [f"- {name}: {value}" for name, value in report.decision.limits.items()]
    lines.append(f"- verdict: {report.decision.reason}")
    return lines


def _logs_section(report: RepairReport) -> list[str]:
    """Render the before and after logs, collapsed."""
    lines: list[str] = []
    if report.reproduction is not None:
        lines += _details(
            "Before — reproduction output",
            _truncate(report.reproduction.first_run.output, MAX_LOG_CHARS),
        )
    if report.proof is not None and report.proof.after is not None:
        lines += _details(
            "After — full suite with the patch applied",
            _truncate(report.proof.after.output, MAX_LOG_CHARS),
        )
    return lines


def _footer(report: RepairReport) -> list[str]:
    """Render the run metadata every package ends with."""
    return [
        "",
        "---",
        "",
        f"Agent `{report.agent or 'unknown'}` · sandbox `{report.runner or 'unknown'}` · "
        f"{report.duration_seconds:.1f}s · cost ${report.cost_usd:.4f}",
    ]


# --- Formatting helpers ------------------------------------------------------


def _title(text: str, prefix: str = "Fix") -> str:
    """Build a one-line title from a root cause or a reason."""
    first = text.strip().splitlines()[0] if text.strip() else "unexplained failure"
    first = first.rstrip(".")
    if len(first) > 90:
        first = first[:89] + "…"
    return f"{prefix}: {first}"


def _suite_line(failures: list[str]) -> str:
    """Describe a suite result by its failing tests."""
    if not failures:
        return "no failing tests"
    return f"{len(failures)} failing — {', '.join(failures[:5])}" + (
        ", …" if len(failures) > 5 else ""
    )


def _fence(text: str, language: str = "") -> str:
    """Wrap text in a fenced code block."""
    return f"```{language}\n{text.rstrip()}\n```"


def _details(summary: str, text: str) -> list[str]:
    """Wrap a log in a collapsed disclosure block."""
    return [
        "",
        "<details>",
        f"<summary>{summary}</summary>",
        "",
        _fence(text),
        "",
        "</details>",
    ]


def _truncate(text: str, limit: int) -> str:
    """Keep the tail of a long block, noting what was dropped."""
    if len(text) <= limit:
        return text or "(no output)"
    return f"[... {len(text) - limit} characters truncated ...]\n{text[-limit:]}"
