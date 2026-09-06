"""Tests for the deterministic agent."""

from __future__ import annotations

from pathlib import Path

from mender.classify import classify
from mender.diagnose.agent import DiagnosisAgent, DiagnosisRequest
from mender.diagnose.heuristic import HeuristicAgent

RENAME_LOG = "E   ImportError: cannot import name 'format_price' from 'app.utils'\n"
LINT_LOG = "src/pkg/money.py:1:8: F401 [*] `os` imported but unused\n"


def request_for(workspace: Path, logs: str, **overrides: object) -> DiagnosisRequest:
    """Build a diagnosis request without touching git or the network."""
    fields: dict[str, object] = {
        "classification": classify(logs),
        "failing_output": logs,
        "workspace": workspace,
        "test_command": "pytest",
        "allow_paths": ["app/**", "src/**", "tests/**"],
        "never_touch": [".github/workflows/**"],
    }
    fields.update(overrides)
    return DiagnosisRequest(**fields)  # type: ignore[arg-type]


def rename_repo(root: Path) -> Path:
    """Build the incomplete-rename scenario from the docs."""
    (root / "app").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "app" / "utils.py").write_text(
        "def format_currency(amount):\n    return f'${amount:.2f}'\n", encoding="utf-8"
    )
    (root / "app" / "checkout.py").write_text(
        "from app.utils import format_price\n\n\ndef checkout(total):\n"
        "    return format_price(total)\n",
        encoding="utf-8",
    )
    return root


def test_the_agent_satisfies_the_protocol() -> None:
    assert isinstance(HeuristicAgent(), DiagnosisAgent)


def test_an_incomplete_rename_is_finished_at_the_call_sites(tmp_path: Path) -> None:
    workspace = rename_repo(tmp_path / "repo")

    diagnosis = HeuristicAgent().diagnose(request_for(workspace, RENAME_LOG))

    assert diagnosis.has_fix
    assert diagnosis.confidence >= 0.8
    assert [edit.path for edit in diagnosis.edits] == ["app/checkout.py"]
    assert "format_currency" in diagnosis.edits[0].content
    assert "format_price" not in diagnosis.edits[0].content


def test_the_definition_is_never_renamed_back(tmp_path: Path) -> None:
    """Renaming the definition back would also go green, and would be wrong."""
    workspace = rename_repo(tmp_path / "repo")

    diagnosis = HeuristicAgent().diagnose(request_for(workspace, RENAME_LOG))

    assert "app/utils.py" not in [edit.path for edit in diagnosis.edits]


def test_the_rename_fix_ships_a_regression_test_that_imports_the_call_sites(tmp_path: Path) -> None:
    workspace = rename_repo(tmp_path / "repo")

    diagnosis = HeuristicAgent().diagnose(request_for(workspace, RENAME_LOG))

    assert diagnosis.regression_test is not None
    assert diagnosis.regression_test.path.startswith("tests/")
    assert "app.checkout" in diagnosis.regression_test.content


def test_a_removed_symbol_is_not_guessed_at(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    (workspace / "app").mkdir(parents=True)
    (workspace / "app" / "utils.py").write_text("def unrelated():\n    pass\n", encoding="utf-8")

    diagnosis = HeuristicAgent().diagnose(request_for(workspace, RENAME_LOG))

    assert not diagnosis.has_fix
    assert "removed rather than renamed" in diagnosis.root_cause


def test_a_module_with_no_file_is_a_dependency_problem_not_a_rename(tmp_path: Path) -> None:
    diagnosis = HeuristicAgent().diagnose(request_for(tmp_path, RENAME_LOG))

    assert not diagnosis.has_fix
    assert "no file in the workspace" in diagnosis.root_cause


def test_an_unused_import_is_removed(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    (workspace / "src" / "pkg").mkdir(parents=True)
    (workspace / "src" / "pkg" / "money.py").write_text(
        "import os\n\n\ndef total():\n    return 1\n", encoding="utf-8"
    )

    diagnosis = HeuristicAgent().diagnose(request_for(workspace, LINT_LOG))

    assert diagnosis.edits[0].content == "\n\ndef total():\n    return 1\n"
    assert diagnosis.regression_test is None


def test_removing_one_unused_name_keeps_the_others(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    (workspace / "src" / "pkg").mkdir(parents=True)
    (workspace / "src" / "pkg" / "money.py").write_text(
        "from decimal import Decimal, getcontext\n\nx = Decimal(1)\n", encoding="utf-8"
    )
    log = "src/pkg/money.py:1:31: F401 [*] `decimal.getcontext` imported but unused\n"

    diagnosis = HeuristicAgent().diagnose(request_for(workspace, log))

    assert diagnosis.edits[0].content.startswith("from decimal import Decimal\n")


def test_ruffs_newer_output_layout_is_understood(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    (workspace / "src" / "pkg").mkdir(parents=True)
    (workspace / "src" / "pkg" / "money.py").write_text("import os\n", encoding="utf-8")
    log = "F401 [*] `os` imported but unused\n --> src/pkg/money.py:1:8\n"

    diagnosis = HeuristicAgent().diagnose(request_for(workspace, log))

    assert diagnosis.has_fix


def test_a_lint_failure_that_is_not_an_unused_import_is_declined(tmp_path: Path) -> None:
    log = "src/pkg/money.py:1:1: E731 do not assign a lambda expression\n"

    diagnosis = HeuristicAgent().diagnose(request_for(tmp_path, log))

    assert not diagnosis.has_fix


def test_files_outside_the_allowlist_are_left_alone(tmp_path: Path) -> None:
    workspace = rename_repo(tmp_path / "repo")

    diagnosis = HeuristicAgent().diagnose(
        request_for(workspace, RENAME_LOG, allow_paths=["nothing/**"])
    )

    assert not diagnosis.has_fix
    assert "not referenced anywhere Mender is allowed to edit" in diagnosis.root_cause


def test_never_touch_paths_are_never_proposed(tmp_path: Path) -> None:
    workspace = rename_repo(tmp_path / "repo")
    (workspace / ".github" / "workflows").mkdir(parents=True)
    (workspace / ".github" / "workflows" / "ci.py").write_text(
        "format_price = 1\n", encoding="utf-8"
    )

    diagnosis = HeuristicAgent().diagnose(request_for(workspace, RENAME_LOG))

    assert ".github/workflows/ci.py" not in [edit.path for edit in diagnosis.edits]


def test_classes_the_agent_does_not_handle_are_declined_explicitly(tmp_path: Path) -> None:
    diagnosis = HeuristicAgent().diagnose(request_for(tmp_path, "E   AssertionError\n"))

    assert not diagnosis.has_fix
    assert diagnosis.confidence == 0.0
    assert "No deterministic repair" in diagnosis.root_cause
