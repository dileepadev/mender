"""The shipped policy file must not drift from the defaults enforced in code."""

from __future__ import annotations

from pathlib import Path

import pytest

from mender.config import BUILTIN_NEVER_TOUCH, ConfigError, PolicyConfig
from mender.policy.engine import load_policy

DEFAULT_POLICY = Path(__file__).resolve().parents[2] / "policies" / "default.yaml"


def test_the_shipped_policy_matches_the_code_defaults() -> None:
    assert load_policy(DEFAULT_POLICY) == PolicyConfig()


def test_the_shipped_policy_still_carries_the_builtin_protections() -> None:
    """The file lists no never-touch globs; the code adds them anyway."""
    policy = load_policy(DEFAULT_POLICY)

    assert set(BUILTIN_NEVER_TOUCH) <= set(policy.never_touch)


def test_a_bare_policy_mapping_loads_too(tmp_path: Path) -> None:
    path = tmp_path / "policy.yaml"
    path.write_text("max_files_changed: 2\n", encoding="utf-8")

    assert load_policy(path).max_files_changed == 2


@pytest.mark.parametrize(
    ("body", "match"),
    [
        ("", "empty"),
        ("- one\n- two\n", "mapping"),
        ("policy: 3\n", "not a mapping"),
        ("policy:\n  max_files_changed: 0\n", "invalid"),
        ("policy: [unclosed\n", "not valid YAML"),
    ],
)
def test_invalid_policy_files_are_rejected(tmp_path: Path, body: str, match: str) -> None:
    path = tmp_path / "policy.yaml"
    path.write_text(body, encoding="utf-8")

    with pytest.raises(ConfigError, match=match):
        load_policy(path)


def test_a_missing_policy_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Could not read"):
        load_policy(tmp_path / "absent.yaml")
