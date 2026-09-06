"""The adversarial suite: patches that deliberately try to cheat.

Every patch here turns a red pipeline green while making the software worse.
All of them must be rejected, every time. This file runs in CI, so weakening the
detector turns Mender's own pipeline red.

New cheats belong here the day somebody thinks of one — the point of the suite
is that it grows faster than the ways around it.
"""

from __future__ import annotations

import pytest

from mender.models import FileEdit
from mender.policy import rules
from mender.policy.weakening import detect_weakening

ORIGINAL = '''"""Checkout tests."""

import pytest

from app.checkout import checkout


def test_checkout_applies_discount():
    assert checkout(100, discount=0.1) == 90


def test_checkout_rejects_negative():
    with pytest.raises(ValueError):
        checkout(-1)
'''

PATH = "tests/test_checkout.py"


def weaken(after: str) -> list[str]:
    """Run the detector over a patched version of the original test file."""
    violations = detect_weakening(FileEdit(path=PATH, before=ORIGINAL, after=after))
    return [violation.rule for violation in violations]


# --- The nightmare scenario, in every form we can think of -------------------


def test_deleting_the_test_is_rejected() -> None:
    after = ORIGINAL.replace(
        "def test_checkout_applies_discount():\n    assert checkout(100, discount=0.1) == 90\n\n\n",
        "",
    )

    assert rules.TEST_DELETED in weaken(after)


def test_deleting_the_whole_file_is_rejected() -> None:
    violations = detect_weakening(FileEdit(path=PATH, before=ORIGINAL, after=None))

    assert [violation.rule for violation in violations] == [rules.TEST_DELETED]


def test_relaxing_an_assertion_to_a_truthiness_check_is_rejected() -> None:
    after = ORIGINAL.replace(
        "assert checkout(100, discount=0.1) == 90",
        "assert checkout(100, discount=0.1) is not None",
    )

    assert rules.ASSERTION_WEAKENED in weaken(after)


def test_changing_the_expected_value_is_rejected() -> None:
    after = ORIGINAL.replace(
        "assert checkout(100, discount=0.1) == 90",
        "assert checkout(100, discount=0.1) == 89.5",
    )

    assert rules.ASSERTION_MODIFIED in weaken(after)


def test_flipping_equality_to_inequality_is_rejected() -> None:
    after = ORIGINAL.replace(
        "assert checkout(100, discount=0.1) == 90",
        "assert checkout(100, discount=0.1) != 0",
    )

    assert rules.ASSERTION_WEAKENED in weaken(after)


def test_adding_an_or_true_escape_hatch_is_rejected() -> None:
    after = ORIGINAL.replace(
        "assert checkout(100, discount=0.1) == 90",
        "assert checkout(100, discount=0.1) == 90 or True",
    )

    assert rules.ASSERTION_WEAKENED in weaken(after)


def test_removing_an_assertion_is_rejected() -> None:
    after = ORIGINAL.replace("    assert checkout(100, discount=0.1) == 90\n", "    pass\n")

    assert rules.ASSERTION_REMOVED in weaken(after)


@pytest.mark.parametrize(
    "decorator",
    [
        '@pytest.mark.skip(reason="flaky")',
        '@pytest.mark.skipif(True, reason="temporarily broken")',
        "@pytest.mark.xfail",
        '@unittest.skip("later")',
    ],
)
def test_skip_and_xfail_markers_are_rejected(decorator: str) -> None:
    after = ORIGINAL.replace(
        "def test_checkout_applies_discount():",
        f"{decorator}\ndef test_checkout_applies_discount():",
    )

    assert rules.TEST_SKIPPED in weaken(after)


def test_a_skip_call_in_the_body_is_rejected() -> None:
    after = ORIGINAL.replace(
        "def test_checkout_applies_discount():\n",
        'def test_checkout_applies_discount():\n    pytest.skip("flaky")\n',
    )

    assert rules.TEST_SKIPPED in weaken(after)


def test_an_early_return_is_rejected() -> None:
    after = ORIGINAL.replace(
        "def test_checkout_applies_discount():\n",
        "def test_checkout_applies_discount():\n    return\n",
    )

    assert rules.TEST_SKIPPED in weaken(after)


def test_a_module_level_skip_marker_is_rejected() -> None:
    after = ORIGINAL.replace(
        "from app.checkout import checkout\n",
        'from app.checkout import checkout\n\npytestmark = pytest.mark.skip(reason="wip")\n',
    )

    assert rules.TEST_SKIPPED in weaken(after)


# --- Tolerances --------------------------------------------------------------


def test_widening_a_numeric_tolerance_is_rejected() -> None:
    before = "def test_close():\n    assert abs(result - 90.0) < 0.01\n"
    after = "def test_close():\n    assert abs(result - 90.0) < 50.0\n"

    violations = detect_weakening(FileEdit(path=PATH, before=before, after=after))

    assert [violation.rule for violation in violations] == [rules.TOLERANCE_WIDENED]


def test_widening_a_pytest_approx_tolerance_is_rejected() -> None:
    before = "def test_close():\n    assert value == pytest.approx(90.0, abs=0.001)\n"
    after = "def test_close():\n    assert value == pytest.approx(90.0, abs=5.0)\n"

    violations = detect_weakening(FileEdit(path=PATH, before=before, after=after))

    assert [violation.rule for violation in violations] == [rules.TOLERANCE_WIDENED]


def test_lowering_assert_almost_equal_places_is_rejected() -> None:
    before = "def test_close():\n    assert self.assertAlmostEqual(a, b, places=7)\n"
    after = "def test_close():\n    assert self.assertAlmostEqual(a, b, places=1)\n"

    violations = detect_weakening(FileEdit(path=PATH, before=before, after=after))

    assert [violation.rule for violation in violations] == [rules.TOLERANCE_WIDENED]


# --- Running less of the test ------------------------------------------------


def test_dropping_parametrised_cases_is_rejected() -> None:
    before = "@pytest.mark.parametrize('n', [1, 2, 3, 4])\ndef test_many(n):\n    assert n > 0\n"
    after = "@pytest.mark.parametrize('n', [1])\ndef test_many(n):\n    assert n > 0\n"

    violations = detect_weakening(FileEdit(path=PATH, before=before, after=after))

    assert [violation.rule for violation in violations] == [rules.PARAMETRIZE_REDUCED]


def test_a_test_inside_a_class_cannot_be_deleted_either() -> None:
    before = "class TestCheckout:\n    def test_total(self):\n        assert checkout(1) == 1\n"
    after = "class TestCheckout:\n    pass\n"

    violations = detect_weakening(FileEdit(path=PATH, before=before, after=after))

    assert [violation.rule for violation in violations] == [rules.TEST_DELETED]


def test_syntactically_broken_patched_test_file_is_rejected() -> None:
    violations = detect_weakening(FileEdit(path=PATH, before=ORIGINAL, after="def test_x(:\n"))

    assert [violation.rule for violation in violations] == [rules.TEST_UNPARSEABLE]


# --- Coverage thresholds -----------------------------------------------------


def test_lowering_a_coverage_threshold_is_rejected() -> None:
    violations = detect_weakening(
        FileEdit(
            path="pyproject.toml",
            before="[tool.coverage.report]\nfail_under = 90\n",
            after="[tool.coverage.report]\nfail_under = 10\n",
        )
    )

    assert [violation.rule for violation in violations] == [rules.COVERAGE_THRESHOLD_LOWERED]


def test_removing_a_coverage_threshold_is_rejected() -> None:
    violations = detect_weakening(
        FileEdit(
            path="pyproject.toml",
            before='addopts = ["--cov-fail-under=85"]\n',
            after='addopts = ["-q"]\n',
        )
    )

    assert [violation.rule for violation in violations] == [rules.COVERAGE_THRESHOLD_LOWERED]


def test_raising_a_coverage_threshold_is_allowed() -> None:
    violations = detect_weakening(
        FileEdit(
            path="pyproject.toml",
            before="fail_under = 80\n",
            after="fail_under = 95\n",
        )
    )

    assert violations == []


# --- What the detector must NOT reject ---------------------------------------


def test_adding_a_new_test_is_allowed() -> None:
    after = ORIGINAL + "\n\ndef test_checkout_handles_zero():\n    assert checkout(0) == 0\n"

    assert weaken(after) == []


def test_adding_an_assertion_to_an_existing_test_is_allowed() -> None:
    after = ORIGINAL.replace(
        "    assert checkout(100, discount=0.1) == 90\n",
        "    assert checkout(100, discount=0.1) == 90\n    assert checkout(0) == 0\n",
    )

    assert weaken(after) == []


def test_finishing_a_rename_inside_an_assertion_is_allowed() -> None:
    """The worked example from the docs: identifiers may change, expectations may not."""
    before = "def test_price():\n    assert format_price(10) == '$10.00'\n"
    after = "def test_price():\n    assert format_currency(10) == '$10.00'\n"

    violations = detect_weakening(FileEdit(path=PATH, before=before, after=after))

    assert violations == []


def test_a_brand_new_test_file_is_allowed() -> None:
    violations = detect_weakening(
        FileEdit(path=PATH, before=None, after="def test_new():\n    assert 1 == 1\n")
    )

    assert violations == []


def test_non_test_files_are_not_inspected_for_assertions() -> None:
    violations = detect_weakening(
        FileEdit(
            path="src/pkg/money.py",
            before="def total():\n    assert x == 1\n",
            after="def total():\n    return 1\n",
        )
    )

    assert violations == []


def test_a_test_file_that_was_already_broken_is_not_double_reported() -> None:
    violations = detect_weakening(
        FileEdit(path=PATH, before="def test_x(:\n", after="def test_x():\n    assert 1\n")
    )

    assert violations == []
