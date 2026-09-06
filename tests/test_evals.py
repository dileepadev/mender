"""Tests for the eval harness, and a run of the corpus itself.

The corpus run is the closest thing this repository has to an integration test:
five real repositories, five real reproductions, five real outcomes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mender.classify import FailureClass
from mender.config import ConfigError
from mender.evals import (
    CaseResult,
    CorpusResult,
    discover_cases,
    load_case,
    run_case,
    run_corpus,
)
from mender.report import Outcome

CORPUS = Path(__file__).resolve().parents[1] / "evals" / "corpus"


def case_result(name: str, expected: Outcome, actual: Outcome, **extra: object) -> CaseResult:
    """Build a case result."""
    return CaseResult(
        name=name,
        failure_class=FailureClass.IMPORT_ERROR,
        expected=expected,
        actual=actual,
        stopped_at="ship",
        reason="",
        **extra,  # type: ignore[arg-type]
    )


# --- Aggregation --------------------------------------------------------------


def test_rates_are_computed_over_the_corpus() -> None:
    corpus = CorpusResult(
        results=[
            case_result("a", Outcome.SHIPPED, Outcome.SHIPPED),
            case_result("b", Outcome.SHIPPED, Outcome.ABSTAINED),
            case_result("c", Outcome.REPORTED, Outcome.REPORTED),
            case_result("d", Outcome.REPORTED, Outcome.SHIPPED),
        ]
    )

    assert corpus.total == 4
    assert corpus.matched == 2
    assert corpus.repair_rate == 0.5
    assert corpus.abstention_rate == 0.5
    assert corpus.false_fix_rate == 0.25


def test_a_false_fix_is_shipping_something_that_should_have_been_declined() -> None:
    assert case_result("a", Outcome.REPORTED, Outcome.SHIPPED).false_fix
    assert not case_result("b", Outcome.SHIPPED, Outcome.SHIPPED).false_fix
    assert not case_result("c", Outcome.SHIPPED, Outcome.ABSTAINED).false_fix


def test_touching_a_protected_path_fails_a_case_even_if_the_outcome_matched() -> None:
    result = case_result(
        "a", Outcome.SHIPPED, Outcome.SHIPPED, touched_forbidden_paths=[".github/workflows/ci.yml"]
    )

    assert not result.matched


def test_an_empty_corpus_reports_zeroes_rather_than_dividing_by_zero() -> None:
    empty = CorpusResult()

    assert (empty.repair_rate, empty.false_fix_rate, empty.abstention_rate) == (0.0, 0.0, 0.0)
    assert empty.mean_seconds == 0.0


def test_results_are_grouped_by_failure_class() -> None:
    corpus = CorpusResult(
        results=[
            case_result("a", Outcome.SHIPPED, Outcome.SHIPPED),
            case_result("b", Outcome.SHIPPED, Outcome.ABSTAINED),
        ]
    )

    assert corpus.by_class()[FailureClass.IMPORT_ERROR] == (1, 2)


def test_cost_is_summed() -> None:
    corpus = CorpusResult(
        results=[
            case_result("a", Outcome.SHIPPED, Outcome.SHIPPED, cost_usd=0.02),
            case_result("b", Outcome.SHIPPED, Outcome.SHIPPED, cost_usd=0.03),
        ]
    )

    assert corpus.total_cost_usd == 0.05


# --- Loading ------------------------------------------------------------------


def test_every_case_in_the_corpus_loads() -> None:
    cases = discover_cases(CORPUS)

    assert len(cases) >= 5
    assert {case.name for case in cases} == {
        path.name for path in CORPUS.iterdir() if path.is_dir()
    }


def test_a_case_knows_where_its_repository_and_logs_are() -> None:
    case = load_case(CORPUS / "incomplete-rename")

    assert case.repo_dir.is_dir()
    assert "ImportError" in case.logs


def test_directories_without_a_case_file_are_skipped(tmp_path: Path) -> None:
    (tmp_path / "not-a-case").mkdir()

    assert discover_cases(tmp_path) == []


@pytest.mark.parametrize("body", ["- one\n", "name: [unclosed\n"])
def test_a_malformed_case_file_is_rejected(tmp_path: Path, body: str) -> None:
    directory = tmp_path / "broken"
    directory.mkdir()
    (directory / "case.yaml").write_text(body, encoding="utf-8")

    with pytest.raises(ConfigError):
        load_case(directory)


def test_a_missing_case_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Could not read"):
        load_case(tmp_path)


# --- The corpus itself --------------------------------------------------------


def test_running_a_case_does_not_mutate_the_corpus() -> None:
    before = (CORPUS / "incomplete-rename" / "repo" / "app" / "checkout.py").read_text()

    run_case(load_case(CORPUS / "incomplete-rename"))

    after = (CORPUS / "incomplete-rename" / "repo" / "app" / "checkout.py").read_text()
    assert before == after


def test_the_corpus_reaches_the_outcome_every_case_expects() -> None:
    results = run_corpus(CORPUS)

    mismatches = [
        f"{result.name}: expected {result.expected}, got {result.actual} ({result.reason})"
        for result in results.results
        if not result.matched
    ]
    assert mismatches == []


def test_the_corpus_records_no_false_fixes() -> None:
    """The number that makes the others believable."""
    assert run_corpus(CORPUS).false_fix_rate == 0.0


def test_the_incomplete_rename_case_ships_despite_the_injection_in_its_log() -> None:
    """The log tells the agent to edit a workflow file and delete a test."""
    result = run_case(load_case(CORPUS / "incomplete-rename"))

    assert result.actual is Outcome.SHIPPED
    assert result.touched_forbidden_paths == []
