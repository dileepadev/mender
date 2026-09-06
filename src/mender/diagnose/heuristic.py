"""A deterministic agent for the failure classes that do not need judgement.

Some failures have exactly one correct repair, derivable from the error message
and the code. An incomplete rename is one: the log names the symbol that
disappeared, the module says what replaced it, and finishing the rename is the
only fix that respects what the author was doing. An unused import flagged by
the linter is another.

Running these through a model would add cost, latency, and a chance of a
creative answer to a question that has a boring correct one. This agent handles
them without a network call, and abstains — loudly — on everything else.
"""

from __future__ import annotations

import ast
import difflib
import re
from collections.abc import Iterable
from pathlib import Path

from mender.classify import FailureClass
from mender.diagnose.agent import (
    Diagnosis,
    DiagnosisRequest,
    ProposedEdit,
    RegressionTest,
)
from mender.policy.globs import matches_any
from mender.policy.weakening import is_test_file

SKIP_DIRECTORIES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "build",
        "dist",
        ".tox",
    }
)
MAX_SCANNED_FILES = 2000
CLOSE_MATCH_CUTOFF = 0.6

_F401_PATTERNS = (
    # Concise layout: path, position, then the rule code.
    re.compile(
        r"^\s*(?P<path>[\w./-]+\.py):(?P<line>\d+):\d+: F401 (?:\[\*\] )?"
        r"`(?P<name>[\w.]+)` imported but unused",
        re.MULTILINE,
    ),
    # Full layout: the rule code first, the location on the next line.
    re.compile(
        r"^F401 (?:\[\*\] )?`(?P<name>[\w.]+)` imported but unused\n"
        r"\s*-->\s(?P<path>[\w./-]+\.py):(?P<line>\d+):\d+",
        re.MULTILINE,
    ),
)


class HeuristicAgent:
    """Repairs the mechanical failure classes without consulting a model."""

    name = "heuristic"

    def diagnose(self, request: DiagnosisRequest) -> Diagnosis:
        """Diagnose a reproduced failure, or abstain.

        Args:
            request: The assembled diagnosis packet.

        Returns:
            A diagnosis with edits when the class is one this agent handles, and
            a zero-edit diagnosis explaining why not when it is not.
        """
        handlers = {
            FailureClass.IMPORT_ERROR: self._incomplete_rename,
            FailureClass.LINT: self._unused_imports,
        }
        handler = handlers.get(request.classification.failure_class)
        if handler is None:
            return self._abstain(
                f"No deterministic repair exists for a "
                f"{request.classification.failure_class} failure."
            )
        return handler(request)

    # --- Broken imports ------------------------------------------------------

    def _incomplete_rename(self, request: DiagnosisRequest) -> Diagnosis:
        """Finish a rename whose call sites were not all updated."""
        detail = request.classification.detail
        missing, module = detail.get("name"), detail.get("module")
        if not missing or not module:
            return self._abstain(
                "The import error does not name both a symbol and a module, so "
                "the rename cannot be resolved deterministically."
            )

        module_path = _resolve_module(request.workspace, module)
        if module_path is None:
            return self._abstain(
                f"Module {module!r} is imported but has no file in the workspace. "
                f"This is a missing dependency or a deleted module, not a rename."
            )

        replacement = _closest_definition(request.workspace / module_path, missing)
        if replacement is None:
            return self._abstain(
                f"Module {module!r} defines nothing resembling {missing!r}, so the "
                f"symbol was removed rather than renamed. A human should decide "
                f"what replaces it."
            )

        edits = _rewrite_symbol(request, missing, replacement)
        if not edits:
            return self._abstain(
                f"{missing!r} is not referenced anywhere Mender is allowed to edit."
            )

        modules = _importable_modules(edit.path for edit in edits)
        regression = _import_regression_test(module, modules, missing, replacement)

        return Diagnosis(
            root_cause=(
                f"{missing!r} was renamed to {replacement!r} in {module}, but "
                f"{len(edits)} call site(s) still reference the old name, so the "
                f"module fails to import."
            ),
            confidence=0.9,
            edits=edits,
            regression_test=regression,
            agent=self.name,
            notes=(
                "Renaming the definition back would also turn the pipeline green "
                "and would undo a deliberate change. The minimal patch that "
                "respects the author's intent is to finish the rename."
            ),
        )

    # --- Lint ----------------------------------------------------------------

    def _unused_imports(self, request: DiagnosisRequest) -> Diagnosis:
        """Remove imports the linter reported as unused."""
        by_file: dict[str, list[tuple[int, str]]] = {}
        for pattern in _F401_PATTERNS:
            for match in pattern.finditer(request.failing_output):
                findings = by_file.setdefault(match.group("path"), [])
                finding = (int(match.group("line")), match.group("name"))
                if finding not in findings:
                    findings.append(finding)
        if not by_file:
            return self._abstain(
                "The lint failure is not an unused import, which is the only "
                "lint rule this agent repairs deterministically."
            )

        edits: list[ProposedEdit] = []
        for path, findings in by_file.items():
            if not _editable(request, path):
                continue
            target = request.workspace / path
            try:
                source = target.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            updated = source
            for line_number, name in sorted(findings, reverse=True):
                updated = _remove_import(updated, line_number, name)
            if updated != source:
                edits.append(ProposedEdit(path=path, content=updated))

        if not edits:
            return self._abstain(
                "Every unused import the linter reported is outside the paths "
                "Mender is allowed to edit."
            )

        removed = sum(len(findings) for findings in by_file.values())
        return Diagnosis(
            root_cause=(
                f"{removed} unused import(s) across {len(edits)} file(s) fail the "
                f"linter (ruff F401)."
            ),
            confidence=0.9,
            edits=edits,
            regression_test=None,
            agent=self.name,
            notes=(
                "No new test is added: the lint command is itself the check that "
                "fails before this patch and passes after it."
            ),
        )

    # --- Abstention ----------------------------------------------------------

    def _abstain(self, reason: str) -> Diagnosis:
        """Return a diagnosis that proposes nothing, and says why."""
        return Diagnosis(
            root_cause=reason,
            confidence=0.0,
            edits=[],
            regression_test=None,
            agent=self.name,
        )


# --- Module and symbol resolution --------------------------------------------


def _resolve_module(workspace: Path, module: str) -> str | None:
    """Find the file backing a dotted module name, if the repository has one."""
    relative = Path(*module.split("."))
    for root in ("", "src"):
        for candidate in (relative.with_suffix(".py"), relative / "__init__.py"):
            path = Path(root) / candidate if root else candidate
            if (workspace / path).is_file():
                return path.as_posix()
    return None


def _closest_definition(module_file: Path, missing: str) -> str | None:
    """Find the top-level name in a module that a missing symbol became.

    Uses the closest textual match among the module's public definitions. A
    rename is nearly always a small edit to a name; anything that is not a close
    match is a removal, and this agent abstains on those.
    """
    try:
        tree = ast.parse(module_file.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None

    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.append(node.name)
        elif isinstance(node, ast.Assign):
            names.extend(target.id for target in node.targets if isinstance(target, ast.Name))
    if missing in names:
        return None  # The symbol is present; this is not an incomplete rename.

    matches = difflib.get_close_matches(missing, names, n=1, cutoff=CLOSE_MATCH_CUTOFF)
    return matches[0] if matches else None


def _rewrite_symbol(request: DiagnosisRequest, old: str, new: str) -> list[ProposedEdit]:
    """Replace whole-word occurrences of a symbol everywhere it is allowed."""
    pattern = re.compile(rf"\b{re.escape(old)}\b")
    edits: list[ProposedEdit] = []
    for path in _candidate_files(request):
        target = request.workspace / path
        try:
            source = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if old not in source:
            continue
        updated = pattern.sub(new, source)
        if updated != source:
            edits.append(ProposedEdit(path=path, content=updated))
    return edits


def _candidate_files(request: DiagnosisRequest) -> list[str]:
    """Python files in the workspace that policy would allow Mender to edit."""
    root = request.workspace
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if len(found) >= MAX_SCANNED_FILES:
            break
        if any(part in SKIP_DIRECTORIES for part in path.relative_to(root).parts):
            continue
        relative = path.relative_to(root).as_posix()
        if _editable(request, relative):
            found.append(relative)
    return found


def _editable(request: DiagnosisRequest, path: str) -> bool:
    """Whether policy would let a patch touch this path.

    The agent checks so that it does not waste an attempt proposing an edit the
    policy engine will reject. The engine still checks independently — this is a
    convenience, never the enforcement.
    """
    if matches_any(request.never_touch, path) is not None:
        return False
    return not request.allow_paths or matches_any(request.allow_paths, path) is not None


# --- Import rewriting --------------------------------------------------------


def _remove_import(source: str, line_number: int, qualified: str) -> str:
    """Drop one unused name from the import statement on a given line.

    A single-name import is removed outright. A multi-name import keeps its
    other names, so removing one unused symbol never silently deletes three
    used ones.
    """
    lines = source.splitlines(keepends=True)
    if not 1 <= line_number <= len(lines):
        return source
    index = line_number - 1
    raw = lines[index]
    stripped = raw.strip()
    indent = raw[: len(raw) - len(raw.lstrip())]

    try:
        statement = ast.parse(stripped).body[0]
    except (SyntaxError, IndexError):
        return source
    if not isinstance(statement, ast.Import | ast.ImportFrom):
        return source

    kept = [alias for alias in statement.names if not _is_alias(statement, alias, qualified)]
    if len(kept) == len(statement.names):
        return source
    if not kept:
        del lines[index]
        return "".join(lines)

    statement.names = kept
    newline = "\n" if raw.endswith("\n") else ""
    lines[index] = f"{indent}{ast.unparse(statement)}{newline}"
    return "".join(lines)


def _is_alias(statement: ast.Import | ast.ImportFrom, alias: ast.alias, qualified: str) -> bool:
    """Whether an alias is the one the linter named."""
    if alias.asname == qualified or alias.name == qualified:
        return True
    if isinstance(statement, ast.ImportFrom) and statement.module:
        return f"{statement.module}.{alias.name}" == qualified
    return False


# --- Regression test authoring -----------------------------------------------


def _importable_modules(paths: Iterable[str]) -> list[str]:
    """Convert repository paths into importable dotted module names."""
    modules: list[str] = []
    for text in paths:
        if is_test_file(text) or not text.endswith(".py"):
            continue
        trimmed = text[4:] if text.startswith("src/") else text
        dotted = trimmed[:-3].replace("/", ".")
        dotted = dotted.removesuffix(".__init__")
        if dotted:
            modules.append(dotted)
    return sorted(set(modules))


def _import_regression_test(
    module: str, modules: list[str], old: str, new: str
) -> RegressionTest | None:
    """Author a test that fails while any call site still uses the old name.

    Importing a module executes its imports, so a stale reference raises at
    collection time. The test therefore fails without the patch and passes with
    it, which is exactly what the proof step has to demonstrate.
    """
    targets = sorted(set(modules) | {module})
    if not targets:
        return None
    slug = module.replace(".", "_")
    path = f"tests/test_mender_regression_{slug}.py"
    listed = "\n".join(f'    "{name}",' for name in targets)
    content = f'''"""Regression test authored by Mender.

Guards the rename of `{old}` to `{new}` in `{module}`. Every module listed here
referenced the old name and failed to import while it was still there.
"""

from __future__ import annotations

import importlib

MODULES = (
{listed}
)


def test_{slug}_call_sites_import() -> None:
    for name in MODULES:
        importlib.import_module(name)
'''
    return RegressionTest(
        path=path,
        content=content,
        test_id=f"{path}::test_{slug}_call_sites_import",
        rationale=(
            f"Importing each call site fails with the stale reference to "
            f"`{old}` and succeeds once the rename is finished."
        ),
    )
