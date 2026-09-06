"""The test-weakening detector.

This is the guardrail the whole project is designed around. An agent told to
make a pipeline green does not have to fix the bug — it can delete the test,
skip it, relax the assertion, or widen a tolerance. Every one of those turns red
into green while making the software strictly worse, and every one of them looks
plausible in a diff.

The detector works on the abstract syntax tree, not on the text. A regular
expression looking for the word ``skip`` is trivially avoided; comparing the
structure of the assertions before and after is not.

**The rule for existing assertions is that they may be renamed, not rewritten.**
Two assertions are considered the same assertion when their trees are identical
after every identifier is normalised away — so finishing an incomplete rename is
allowed, and changing an expected value, an operator, or a tolerance is not.
Mender does not repair logic bugs, so it never has a legitimate reason to
change what a test expects. Anything else is rejected and a human is told what
was attempted.
"""

from __future__ import annotations

import ast
import copy
import difflib
import re

from mender.models import FileEdit
from mender.policy import rules
from mender.policy.globs import glob_match
from mender.policy.rules import Violation

type FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef

TEST_PATH_PATTERNS: tuple[str, ...] = (
    "tests/**",
    "**/tests/**",
    "**/test_*.py",
    "**/*_test.py",
    "**/conftest.py",
)

COVERAGE_CONFIG_PATTERNS: tuple[str, ...] = (
    "**/pyproject.toml",
    "**/setup.cfg",
    "**/tox.ini",
    "**/pytest.ini",
    "**/.coveragerc",
)

_SKIP_MARKERS = ("skip", "skipif", "xfail")
_COVERAGE_THRESHOLD = re.compile(r"(?:--cov-fail-under[= ]|fail[-_]under\s*[=:]\s*)(\d+(?:\.\d+)?)")

# Comparison operators ranked by how much they actually pin down. A patch that
# moves an assertion down this ranking has made the test easier to pass.
_STRICT_OPS = (ast.Eq, ast.Is)
_LOOSE_OPS = (ast.NotEq, ast.IsNot, ast.In, ast.NotIn, ast.Lt, ast.LtE, ast.Gt, ast.GtE)

_TOLERANCE_KEYWORDS = frozenset({"abs", "rel", "abs_tol", "rel_tol", "delta", "tolerance"})
_INVERSE_TOLERANCE_KEYWORDS = frozenset({"places", "ndigits"})


def is_test_file(path: str) -> bool:
    """Report whether a repository path holds tests."""
    return any(glob_match(pattern, path) for pattern in TEST_PATH_PATTERNS)


def detect_weakening(edit: FileEdit) -> list[Violation]:
    """Inspect one file edit for any attempt to make a test easier to pass.

    Args:
        edit: The before-and-after content of a single file.

    Returns:
        Every violation found, in the order detected. An empty list means the
        edit does not weaken anything the detector can see.
    """
    violations: list[Violation] = []
    violations += _detect_coverage_threshold(edit)

    if not is_test_file(edit.path):
        return violations

    if edit.is_deletion:
        violations.append(
            Violation(
                rule=rules.TEST_DELETED,
                detail="The whole test file was deleted.",
                path=edit.path,
            )
        )
        return violations

    if edit.before is None or edit.after is None:
        return violations  # A newly added test file cannot weaken anything.

    try:
        before_tree = ast.parse(edit.before)
    except SyntaxError:
        # The file did not parse before the patch either; there is no earlier
        # meaning to compare against.
        return violations

    try:
        after_tree = ast.parse(edit.after)
    except SyntaxError as exc:
        violations.append(
            Violation(
                rule=rules.TEST_UNPARSEABLE,
                detail=f"The patched test file does not parse: {exc.msg} (line {exc.lineno}).",
                path=edit.path,
            )
        )
        return violations

    violations += _detect_module_skip(edit.path, before_tree, after_tree)

    before_tests = _collect_tests(before_tree)
    after_tests = _collect_tests(after_tree)

    for name, before_func in before_tests.items():
        after_func = after_tests.get(name)
        if after_func is None:
            violations.append(
                Violation(
                    rule=rules.TEST_DELETED,
                    detail=f"Test {name} was removed.",
                    path=edit.path,
                )
            )
            continue
        violations += _compare_test(edit.path, name, before_func, after_func)

    return violations


# --- Collection --------------------------------------------------------------


def _collect_tests(tree: ast.Module) -> dict[str, FunctionNode]:
    """Map qualified test names to their function nodes.

    Nested classes are joined with ``::`` so ``TestCheckout::test_total`` stays
    distinct from a module-level ``test_total``.
    """
    found: dict[str, FunctionNode] = {}

    def walk(body: list[ast.stmt], prefix: str) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                walk(node.body, f"{prefix}{node.name}::")
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and (
                node.name.startswith("test")
            ):
                found[f"{prefix}{node.name}"] = node

    walk(tree.body, "")
    return found


def _asserts(function: FunctionNode) -> list[ast.Assert]:
    """Every assertion inside a test function, in source order."""
    return [node for node in ast.walk(function) if isinstance(node, ast.Assert)]


def _decorator_names(function: FunctionNode) -> list[str]:
    """Dotted names of a function's decorators, calls unwrapped."""
    names = []
    for decorator in function.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        names.append(_dotted_name(target))
    return names


def _dotted_name(node: ast.expr) -> str:
    """Render an attribute or name expression as a dotted string."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted_name(node.value)}.{node.attr}"
    return ""


# --- Normalisation -----------------------------------------------------------


class _IdentifierNormaliser(ast.NodeTransformer):
    """Erase identifiers so a rename compares equal but a rewrite does not."""

    def visit_Name(self, node: ast.Name) -> ast.AST:
        """Replace a variable or function name with a placeholder."""
        return ast.copy_location(ast.Name(id="_", ctx=node.ctx), node)

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        """Replace an attribute name with a placeholder, keeping its target."""
        self.generic_visit(node)
        node.attr = "_"
        return node


def _shape(node: ast.AST) -> str:
    """Return a node's structure with identifiers normalised away.

    Constants, operators, and keyword argument names survive, so an expected
    value or a comparison operator cannot change without changing the shape.
    """
    normalised = _IdentifierNormaliser().visit(copy.deepcopy(node))
    return ast.dump(normalised)


# --- Comparison --------------------------------------------------------------


def _compare_test(
    path: str, name: str, before: FunctionNode, after: FunctionNode
) -> list[Violation]:
    """Compare one test before and after the patch."""
    violations: list[Violation] = []
    violations += _detect_skip_markers(path, name, before, after)
    violations += _detect_early_return(path, name, before, after)
    violations += _detect_parametrize_reduction(path, name, before, after)
    violations += _compare_assertions(path, name, _asserts(before), _asserts(after))
    return violations


def _detect_skip_markers(
    path: str, name: str, before: FunctionNode, after: FunctionNode
) -> list[Violation]:
    """Flag skip or xfail markers, and skip calls, that the patch introduced."""
    violations: list[Violation] = []

    added_decorators = _added(_decorator_names(before), _decorator_names(after))
    for decorator in added_decorators:
        if any(marker in decorator.split(".")[-1] for marker in _SKIP_MARKERS):
            violations.append(
                Violation(
                    rule=rules.TEST_SKIPPED,
                    detail=f"Test {name} gained a @{decorator} decorator.",
                    path=path,
                )
            )

    added_calls = _added(_skip_calls(before), _skip_calls(after))
    for call in added_calls:
        violations.append(
            Violation(
                rule=rules.TEST_SKIPPED,
                detail=f"Test {name} gained a {call}() call in its body.",
                path=path,
            )
        )
    return violations


def _skip_calls(function: FunctionNode) -> list[str]:
    """Names of ``skip``/``xfail`` calls made inside a function body."""
    calls = []
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            dotted = _dotted_name(node.func)
            if dotted and dotted.split(".")[-1] in _SKIP_MARKERS:
                calls.append(dotted)
    return calls


def _detect_early_return(
    path: str, name: str, before: FunctionNode, after: FunctionNode
) -> list[Violation]:
    """Flag a bare ``return`` inserted at the top of a test to neuter it."""
    if not after.body or not isinstance(after.body[0], ast.Return):
        return []
    if before.body and isinstance(before.body[0], ast.Return):
        return []
    return [
        Violation(
            rule=rules.TEST_SKIPPED,
            detail=f"Test {name} now returns before running anything.",
            path=path,
        )
    ]


def _detect_parametrize_reduction(
    path: str, name: str, before: FunctionNode, after: FunctionNode
) -> list[Violation]:
    """Flag parametrised cases that the patch dropped.

    Deleting half the cases from a ``parametrize`` list makes a test pass by
    running less of it — the same move as deleting the test, in miniature.
    """
    before_cases = _parametrize_cases(before)
    after_cases = _parametrize_cases(after)
    if before_cases and after_cases < before_cases:
        return [
            Violation(
                rule=rules.PARAMETRIZE_REDUCED,
                detail=(
                    f"Test {name} went from {before_cases} parametrised cases to {after_cases}."
                ),
                path=path,
            )
        ]
    return []


def _parametrize_cases(function: FunctionNode) -> int:
    """Count the parametrised cases declared on a test."""
    total = 0
    for decorator in function.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        if not _dotted_name(decorator.func).endswith("parametrize"):
            continue
        for argument in decorator.args:
            if isinstance(argument, ast.List | ast.Tuple):
                total += len(argument.elts)
    return total


def _compare_assertions(
    path: str,
    name: str,
    before: list[ast.Assert],
    after: list[ast.Assert],
) -> list[Violation]:
    """Align a test's assertions before and after, and judge every change.

    Alignment uses the normalised shapes so that inserting a new assertion does
    not make every later one look modified.
    """
    violations: list[Violation] = []
    before_shapes = [_shape(node.test) for node in before]
    after_shapes = [_shape(node.test) for node in after]
    matcher = difflib.SequenceMatcher(a=before_shapes, b=after_shapes, autojunk=False)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in {"equal", "insert"}:
            continue  # Unchanged, or a new assertion — strengthening is welcome.
        pairs = min(i2 - i1, j2 - j1)
        for offset in range(pairs):
            violations.append(_judge_assertion(path, name, before[i1 + offset], after[j1 + offset]))
        for offset in range(pairs, i2 - i1):
            violations.append(
                Violation(
                    rule=rules.ASSERTION_REMOVED,
                    detail=(f"Test {name} lost an assertion: {_render(before[i1 + offset])}"),
                    path=path,
                )
            )
    return violations


def _judge_assertion(path: str, name: str, before: ast.Assert, after: ast.Assert) -> Violation:
    """Name the most specific reason a rewritten assertion is not allowed."""
    rendered = f"{_render(before)} → {_render(after)}"

    if _strictness(after.test) < _strictness(before.test):
        return Violation(
            rule=rules.ASSERTION_WEAKENED,
            detail=f"Test {name} relaxed an assertion: {rendered}",
            path=path,
        )
    if _tolerance_widened(before.test, after.test):
        return Violation(
            rule=rules.TOLERANCE_WIDENED,
            detail=f"Test {name} widened a tolerance: {rendered}",
            path=path,
        )
    return Violation(
        rule=rules.ASSERTION_MODIFIED,
        detail=(
            f"Test {name} rewrote an existing assertion: {rendered}. Mender may "
            f"rename what an assertion refers to, never change what it expects."
        ),
        path=path,
    )


def _strictness(node: ast.expr) -> int:
    """Rank how much an assertion's condition actually pins down.

    Higher is stricter. A patch that lowers this rank has replaced a real check
    with a weaker one — ``== 90`` becoming ``is not None``, say.
    """
    if isinstance(node, ast.BoolOp):
        ranks = [_strictness(value) for value in node.values]
        # ``and`` demands every clause; ``or`` is only as strict as its weakest.
        return max(ranks) if isinstance(node.op, ast.And) else min(ranks)
    if isinstance(node, ast.Compare):
        ops = tuple(type(op) for op in node.ops)
        if all(op in _STRICT_OPS for op in ops):
            return 3
        if all(op in _LOOSE_OPS for op in ops):
            return 2
        return 2
    if isinstance(node, ast.Call):
        return 1
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return 0
    return 0


def _tolerance_widened(before: ast.expr, after: ast.expr) -> bool:
    """Report whether any numeric bound in an assertion got more forgiving."""
    widened = any(
        later > earlier
        for earlier, later in zip(_tolerances(before), _tolerances(after), strict=False)
    )
    loosened = any(
        later < earlier
        for earlier, later in zip(
            _inverse_tolerances(before), _inverse_tolerances(after), strict=False
        )
    )
    return widened or loosened


def _tolerances(node: ast.expr) -> list[float]:
    """Numeric bounds where a larger value means a more forgiving test."""
    values: list[float] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Compare):
            for op, comparator in zip(child.ops, child.comparators, strict=True):
                if isinstance(op, ast.Lt | ast.LtE):
                    number = _number(comparator)
                    if number is not None:
                        values.append(number)
        elif isinstance(child, ast.Call):
            for keyword in child.keywords:
                if keyword.arg in _TOLERANCE_KEYWORDS:
                    number = _number(keyword.value)
                    if number is not None:
                        values.append(number)
    return values


def _inverse_tolerances(node: ast.expr) -> list[float]:
    """Numeric bounds where a *smaller* value means a more forgiving test."""
    values: list[float] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            for keyword in child.keywords:
                if keyword.arg in _INVERSE_TOLERANCE_KEYWORDS:
                    number = _number(keyword.value)
                    if number is not None:
                        values.append(number)
    return values


def _number(node: ast.expr) -> float | None:
    """Extract a numeric literal, including a negated one."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _number(node.operand)
        return None if inner is None else -inner
    return None


# --- Module and configuration level ------------------------------------------


def _detect_module_skip(path: str, before: ast.Module, after: ast.Module) -> list[Violation]:
    """Flag a module-level ``pytestmark`` that skips the whole file."""
    added = _added(_module_marks(before), _module_marks(after))
    return [
        Violation(
            rule=rules.TEST_SKIPPED,
            detail=f"The module gained a skip marker: pytestmark = {mark}.",
            path=path,
        )
        for mark in added
        if any(marker in mark.split(".")[-1] for marker in _SKIP_MARKERS)
    ]


def _module_marks(tree: ast.Module) -> list[str]:
    """Dotted names assigned to a module-level ``pytestmark``."""
    marks: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets
        ):
            continue
        for value in _iter_marks(node.value):
            marks.append(value)
    return marks


def _iter_marks(node: ast.expr) -> list[str]:
    """Flatten a ``pytestmark`` value, which may be a single mark or a list."""
    if isinstance(node, ast.List | ast.Tuple):
        return [name for element in node.elts for name in _iter_marks(element)]
    target = node.func if isinstance(node, ast.Call) else node
    dotted = _dotted_name(target)
    return [dotted] if dotted else []


def _detect_coverage_threshold(edit: FileEdit) -> list[Violation]:
    """Flag a lowered coverage gate in any configuration file.

    Coverage thresholds are checked on every edit, not only test files: the
    number can live in ``pyproject.toml``, a pytest ini section, or a command
    line, and lowering it anywhere has the same effect.
    """
    if not any(glob_match(pattern, edit.path) for pattern in COVERAGE_CONFIG_PATTERNS):
        return []
    before = _thresholds(edit.before or "")
    after = _thresholds(edit.after or "")
    if not before:
        return []
    if not after:
        return [
            Violation(
                rule=rules.COVERAGE_THRESHOLD_LOWERED,
                detail=f"The coverage threshold ({min(before)}) was removed entirely.",
                path=edit.path,
            )
        ]
    if min(after) < min(before):
        return [
            Violation(
                rule=rules.COVERAGE_THRESHOLD_LOWERED,
                detail=(f"The coverage threshold dropped from {min(before)} to {min(after)}."),
                path=edit.path,
            )
        ]
    return []


def _thresholds(text: str) -> list[float]:
    """Every coverage threshold declared in a configuration file."""
    return [float(match.group(1)) for match in _COVERAGE_THRESHOLD.finditer(text)]


# --- Small helpers -----------------------------------------------------------


def _added(before: list[str], after: list[str]) -> list[str]:
    """Items present in ``after`` more often than in ``before``."""
    remaining = list(before)
    added = []
    for item in after:
        if item in remaining:
            remaining.remove(item)
        else:
            added.append(item)
    return added


def _render(node: ast.Assert) -> str:
    """Render an assertion back to source for a human-readable rejection."""
    try:
        return ast.unparse(node)
    except (AttributeError, ValueError):  # pragma: no cover - defensive
        return "<unrenderable assertion>"
