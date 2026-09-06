"""Fixtures shared across the test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from mender.config import MenderConfig, load_config


@pytest.fixture
def config(tmp_path: Path) -> MenderConfig:
    """A minimal valid configuration with all three commands set."""
    path = tmp_path / "mender.yaml"
    path.write_text(
        "test_command: run-tests\n"
        "lint_command: run-lint\n"
        "type_check_command: run-types\n"
        "sandbox:\n  flaky_reruns: 2\n",
        encoding="utf-8",
    )
    return load_config(path)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A small repository with one source file and one test."""
    root = tmp_path / "repo"
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "pkg" / "money.py").write_text(
        "def total(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8"
    )
    (root / "tests" / "test_money.py").write_text(
        "def test_total():\n    assert 1 + 1 == 2\n", encoding="utf-8"
    )
    return root
