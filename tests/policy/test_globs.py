"""Tests for glob matching, which decides what an agent may edit."""

from __future__ import annotations

import pytest

from mender.policy.globs import glob_match, matches_any


@pytest.mark.parametrize(
    ("pattern", "path"),
    [
        ("src/**", "src/app.py"),
        ("src/**", "src/deep/nested/app.py"),
        ("**/migrations/**", "db/migrations/0001.py"),
        ("**/migrations/**", "migrations/0001.py"),
        ("**/*.pem", "key.pem"),
        ("**/*.pem", "deploy/keys/key.pem"),
        (".env.*", ".env.production"),
        (".github/workflows/**", ".github/workflows/ci.yml"),
        ("mender.yaml", "mender.yaml"),
        ("**", "anything/at/all.txt"),
        ("tests/test_?.py", "tests/test_a.py"),
    ],
)
def test_patterns_that_should_match(pattern: str, path: str) -> None:
    assert glob_match(pattern, path)


@pytest.mark.parametrize(
    ("pattern", "path"),
    [
        # A single star must never cross a directory separator — this is the
        # whole reason fnmatch is not used here.
        ("src/*", "src/deep/app.py"),
        ("src/**", "tests/app.py"),
        ("**/migrations/**", "db/migration/0001.py"),
        (".env.*", ".env"),
        ("mender.yaml", "docs/mender.yaml"),
        ("tests/test_?.py", "tests/test_ab.py"),
        ("policies/**", "policies"),
    ],
)
def test_patterns_that_should_not_match(pattern: str, path: str) -> None:
    assert not glob_match(pattern, path)


def test_dots_in_a_pattern_are_literal() -> None:
    assert not glob_match("a.py", "axpy")


def test_matches_any_returns_the_first_matching_pattern() -> None:
    assert matches_any(["tests/**", "src/**"], "src/a.py") == "src/**"
    assert matches_any(["tests/**"], "src/a.py") is None
