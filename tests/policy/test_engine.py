"""Tests for blast-radius evaluation."""

from __future__ import annotations

from tests.helpers import edit, patch_of

from mender.config import BUILTIN_NEVER_TOUCH, PolicyConfig
from mender.policy import rules
from mender.policy.engine import PolicyEngine


def engine(**overrides: object) -> PolicyEngine:
    """Build an engine from a policy with the given overrides."""
    return PolicyEngine(PolicyConfig(**overrides))  # type: ignore[arg-type]


def test_a_small_in_bounds_patch_is_approved() -> None:
    decision = engine().evaluate(patch_of(edit("src/a.py", "one\n", "two\n")))

    assert decision.approved
    assert decision.files_changed == 1
    assert "Approved" in decision.reason


def test_an_empty_patch_is_rejected() -> None:
    decision = engine().evaluate(patch_of(edit("src/a.py", "same\n", "same\n")))

    assert not decision.approved
    assert decision.violations[0].rule == rules.EMPTY_PATCH


def test_a_never_touch_path_is_rejected() -> None:
    decision = engine().evaluate(
        patch_of(edit(".github/workflows/ci.yml", "on: push\n", "on: pull_request\n"))
    )

    assert not decision.approved
    assert [v.rule for v in decision.violations] == [rules.NEVER_TOUCH]


def test_a_repository_cannot_widen_its_own_policy_file() -> None:
    decision = engine().evaluate(patch_of(edit("mender.yaml", "a: 1\n", "a: 2\n")))

    assert [v.rule for v in decision.violations] == [rules.NEVER_TOUCH]


def test_every_builtin_never_touch_glob_is_enforced() -> None:
    for glob in BUILTIN_NEVER_TOUCH:
        path = glob.replace("**", "x").replace("*", "x").strip("/")
        decision = engine().evaluate(patch_of(edit(path, "before\n", "after\n")))

        assert not decision.approved, path


def test_a_path_outside_the_allowlist_is_rejected() -> None:
    decision = engine().evaluate(patch_of(edit("scripts/deploy.sh", "a\n", "b\n")))

    assert [v.rule for v in decision.violations] == [rules.PATH_ALLOWLIST]


def test_a_protected_path_reports_one_rule_not_two() -> None:
    decision = engine(allow_paths=["src/**"]).evaluate(patch_of(edit(".env", "A=1\n", "A=2\n")))

    assert [v.rule for v in decision.violations] == [rules.NEVER_TOUCH]


def test_too_many_files_is_rejected() -> None:
    edits = [edit(f"src/a{index}.py", "one\n", "two\n") for index in range(6)]

    decision = engine(max_files_changed=5).evaluate(patch_of(*edits))

    assert rules.MAX_FILES_CHANGED in [v.rule for v in decision.violations]


def test_too_many_lines_is_rejected() -> None:
    decision = engine(max_lines_changed=2).evaluate(
        patch_of(edit("src/a.py", "1\n2\n3\n", "4\n5\n6\n"))
    )

    assert rules.MAX_LINES_CHANGED in [v.rule for v in decision.violations]


def test_every_broken_rule_is_reported_not_just_the_first() -> None:
    decision = engine(max_lines_changed=1).evaluate(
        patch_of(
            edit(".github/workflows/ci.yml", "a\n", "b\n"),
            edit("scripts/x.sh", "a\n", "b\n"),
        )
    )

    assert {v.rule for v in decision.violations} == {
        rules.NEVER_TOUCH,
        rules.PATH_ALLOWLIST,
        rules.MAX_LINES_CHANGED,
    }


def test_a_weakening_patch_is_rejected_and_flagged_as_such() -> None:
    decision = engine().evaluate(
        patch_of(
            edit(
                "tests/test_a.py",
                "def test_a():\n    assert f() == 1\n",
                "def test_a():\n    assert f() is not None\n",
            )
        )
    )

    assert not decision.approved
    assert decision.weakened_a_test
    assert decision.weakening_violations[0].rule == rules.ASSERTION_WEAKENED


def test_a_blast_radius_violation_is_not_a_weakening_violation() -> None:
    decision = engine(max_files_changed=1).evaluate(
        patch_of(edit("src/a.py", "1\n", "2\n"), edit("src/b.py", "1\n", "2\n"))
    )

    assert not decision.weakened_a_test


def test_limits_are_described_for_the_evidence_package() -> None:
    limits = engine().describe_limits()

    assert limits["max files changed"] == "5"
    assert "src/**" in limits["allowed paths"]


def test_a_violation_renders_readably() -> None:
    decision = engine().evaluate(patch_of(edit(".env", "A=1\n", "A=2\n")))

    assert "never-touch (.env)" in str(decision.violations[0])
