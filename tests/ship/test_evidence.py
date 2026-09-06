"""Tests for the evidence package a human reads."""

from __future__ import annotations

from tests.helpers import edit, patch_of, result

from mender.classify import classify
from mender.config import PolicyConfig
from mender.diagnose.agent import Diagnosis, ProposedEdit, RegressionTest
from mender.models import FailedRun
from mender.policy.engine import PolicyEngine
from mender.report import Outcome, RepairReport, Stage
from mender.sandbox.reproduce import Reproduction
from mender.ship.evidence import render, render_issue, render_pull_request
from mender.verify.prover import Check, Proof

RUN = FailedRun(repository="owner/repo", commit="a1b2c3d4", job="pytest", logs="boom\n")
PATCH = patch_of(
    edit(
        "app/checkout.py",
        "from app.utils import format_price\n",
        "from app.utils import format_currency\n",
    ),
    edit("tests/test_regression.py", None, "def test_it():\n    assert True\n"),
)
DIAGNOSIS = Diagnosis(
    root_cause="'format_price' was renamed to 'format_currency'.",
    confidence=0.9,
    edits=[ProposedEdit(path="app/checkout.py", content="x")],
    regression_test=RegressionTest(
        path="tests/test_regression.py",
        content="def test_it():\n    assert True\n",
        test_id="tests/test_regression.py::test_it",
        rationale="Fails without the patch.",
    ),
    agent="heuristic",
    cost_usd=0.0412,
)
REPRODUCTION = Reproduction(
    command="pytest",
    reproduced=True,
    flaky=False,
    attempts=1,
    failures=1,
    runs=[result("pytest", exit_code=1, stdout="ImportError: boom\n")],
)
PROOF = Proof(
    proven=True,
    checks=[
        Check(name="the failing check now passes", passed=True, detail="exited 0."),
        Check(name="the regression test catches the bug", passed=True, detail="fails without."),
        Check(name="nothing else broke", passed=True, detail="The full suite passes."),
    ],
    after=result("pytest", stdout="2 passed"),
    baseline_failures=["tests/test_checkout.py::test_total"],
    remaining_failures=[],
)


def shipped_report() -> RepairReport:
    """A report that ended in a pull request."""
    return RepairReport(
        run=RUN,
        outcome=Outcome.SHIPPED,
        stopped_at=Stage.SHIP,
        reason="Proven.",
        classification=classify(
            "E   ImportError: cannot import name 'format_price' from 'app.utils'\n"
        ),
        reproduction=REPRODUCTION,
        diagnosis=DIAGNOSIS,
        patch=PATCH,
        decision=PolicyEngine(PolicyConfig(allow_paths=["app/**", "tests/**"])).evaluate(PATCH),
        proof=PROOF,
        agent="heuristic",
        runner="docker",
        duration_seconds=12.5,
    )


def test_a_pull_request_carries_the_whole_evidence_package() -> None:
    evidence = render_pull_request(shipped_report())

    for section in ("## Patch", "## Regression test", "## Proof", "## Policy", "## Classification"):
        assert section in evidence.body


def test_the_diff_is_in_the_pull_request() -> None:
    body = render_pull_request(shipped_report()).body

    assert "-from app.utils import format_price" in body
    assert "+from app.utils import format_currency" in body


def test_the_cost_and_runner_are_reported() -> None:
    body = render_pull_request(shipped_report()).body

    assert "$0.0412" in body
    assert "sandbox `docker`" in body


def test_the_pull_request_says_a_human_decides() -> None:
    assert "never merges its own work" in render_pull_request(shipped_report()).body


def test_before_and_after_logs_are_both_included() -> None:
    body = render_pull_request(shipped_report()).body

    assert "Before — reproduction output" in body
    assert "After — full suite with the patch applied" in body


def test_the_title_is_derived_from_the_root_cause() -> None:
    assert render_pull_request(shipped_report()).title.startswith("Fix: 'format_price'")


def test_render_dispatches_on_the_outcome() -> None:
    report = shipped_report()
    report.outcome = Outcome.ABSTAINED

    assert render(report).title.startswith("CI failure Mender could not repair")


# --- Abstention --------------------------------------------------------------


def abstained_report(**overrides: object) -> RepairReport:
    """A report that declined to open a pull request."""
    fields: dict[str, object] = {
        "run": RUN,
        "outcome": Outcome.ABSTAINED,
        "stopped_at": Stage.PROVE,
        "reason": "The regression test does not catch the bug.",
        "classification": classify("E   AssertionError\n"),
        "reproduction": REPRODUCTION,
        "diagnosis": DIAGNOSIS,
        "patch": PATCH,
    }
    fields.update(overrides)
    return RepairReport(**fields)  # type: ignore[arg-type]


def test_an_abstention_explains_itself() -> None:
    body = render_issue(abstained_report()).body

    assert "Mender stopped at **prove**" in body
    assert "The regression test does not catch the bug." in body


def test_an_abstention_shows_what_it_would_have_changed() -> None:
    body = render_issue(abstained_report()).body

    assert "## What Mender would have changed" in body
    assert "Not applied" in body


def test_an_abstention_lists_the_checks_that_did_not_hold() -> None:
    failed = Proof(
        proven=False,
        checks=[Check(name="nothing else broke", passed=False, detail="tests/test_x.py broke.")],
    )

    body = render_issue(abstained_report(proof=failed)).body

    assert "## What could not be proved" in body
    assert "tests/test_x.py broke." in body


def test_a_policy_rejection_names_the_rule() -> None:
    decision = PolicyEngine(PolicyConfig()).evaluate(
        patch_of(edit(".github/workflows/ci.yml", "a\n", "b\n"))
    )

    body = render_issue(
        abstained_report(outcome=Outcome.REJECTED, stopped_at=Stage.FIX, decision=decision)
    ).body

    assert "never-touch" in body


def test_a_weakening_rejection_is_called_out_as_non_negotiable() -> None:
    decision = PolicyEngine(PolicyConfig()).evaluate(
        patch_of(
            edit(
                "tests/test_a.py",
                "def test_a():\n    assert f() == 1\n",
                "def test_a():\n    assert f() is not None\n",
            )
        )
    )

    body = render_issue(
        abstained_report(outcome=Outcome.REJECTED, stopped_at=Stage.FIX, decision=decision)
    ).body

    assert "never negotiates" in body


def test_a_flaky_report_says_the_test_is_not_edited() -> None:
    flaky = Reproduction(
        command="pytest",
        reproduced=False,
        flaky=True,
        attempts=6,
        failures=2,
        runs=[result("pytest")],
    )

    body = render_issue(
        abstained_report(outcome=Outcome.REPORTED, stopped_at=Stage.REPRODUCE, reproduction=flaky)
    ).body

    assert "## Flaky test" in body
    assert "does not edit flaky tests" in body


def test_an_abstention_is_labelled_for_triage() -> None:
    assert render_issue(abstained_report()).labels == ["mender", "mender:abstained"]
