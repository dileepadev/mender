"""Tests for mender.yaml loading, validation, and safety invariants."""

from __future__ import annotations

from pathlib import Path

import pytest

from mender.config import (
    BUILTIN_NEVER_TOUCH,
    ConfigError,
    PolicyConfig,
    find_config,
    load_config,
)

MINIMAL = "test_command: pytest\n"


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "mender.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_minimal_config_loads_with_defaults(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, MINIMAL))

    assert config.version == 1
    assert config.language == "python"
    assert config.test_command == "pytest"
    assert config.lint_command is None
    assert config.policy.max_files_changed == 5
    assert config.diagnose.confidence_threshold == 0.8


def test_sandbox_network_is_off_by_default(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, MINIMAL))

    assert config.sandbox.network is False


def test_unknown_top_level_key_is_rejected(tmp_path: Path) -> None:
    body = MINIMAL + "max_files: 3\n"

    with pytest.raises(ConfigError, match="invalid"):
        load_config(write(tmp_path, body))


def test_unknown_nested_key_is_rejected(tmp_path: Path) -> None:
    body = MINIMAL + "policy:\n  max_flies_changed: 3\n"

    with pytest.raises(ConfigError, match="invalid"):
        load_config(write(tmp_path, body))


def test_missing_test_command_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="invalid"):
        load_config(write(tmp_path, "language: python\n"))


def test_empty_test_command_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="invalid"):
        load_config(write(tmp_path, 'test_command: ""\n'))


def test_empty_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="empty"):
        load_config(write(tmp_path, ""))


def test_non_mapping_document_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="mapping"):
        load_config(write(tmp_path, "- one\n- two\n"))


def test_malformed_yaml_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_config(write(tmp_path, "test_command: [unclosed\n"))


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Could not read"):
        load_config(tmp_path / "absent.yaml")


def test_out_of_range_limit_is_rejected(tmp_path: Path) -> None:
    body = MINIMAL + "policy:\n  max_files_changed: 0\n"

    with pytest.raises(ConfigError, match="invalid"):
        load_config(write(tmp_path, body))


def test_confidence_threshold_above_one_is_rejected(tmp_path: Path) -> None:
    body = MINIMAL + "diagnose:\n  confidence_threshold: 1.5\n"

    with pytest.raises(ConfigError, match="invalid"):
        load_config(write(tmp_path, body))


# --- Safety invariant: the built-in never-touch set cannot be escaped --------


def test_builtin_never_touch_present_by_default() -> None:
    policy = PolicyConfig()

    assert set(BUILTIN_NEVER_TOUCH) <= set(policy.never_touch)


def test_repository_cannot_remove_builtin_never_touch(tmp_path: Path) -> None:
    body = MINIMAL + "policy:\n  never_touch: []\n"

    config = load_config(write(tmp_path, body))

    assert set(BUILTIN_NEVER_TOUCH) <= set(config.policy.never_touch)


def test_workflow_glob_survives_an_override_attempt(tmp_path: Path) -> None:
    body = MINIMAL + 'policy:\n  never_touch: ["docs/**"]\n'

    config = load_config(write(tmp_path, body))

    assert ".github/workflows/**" in config.policy.never_touch


def test_repository_can_add_its_own_never_touch(tmp_path: Path) -> None:
    body = MINIMAL + 'policy:\n  never_touch: ["infra/**"]\n'

    config = load_config(write(tmp_path, body))

    assert "infra/**" in config.policy.never_touch
    assert set(BUILTIN_NEVER_TOUCH) <= set(config.policy.never_touch)


def test_never_touch_entries_are_not_duplicated() -> None:
    policy = PolicyConfig(never_touch=[".github/workflows/**"])

    assert policy.never_touch.count(".github/workflows/**") == 1


# --- Discovery ---------------------------------------------------------------


def test_find_config_locates_file_in_start_directory(tmp_path: Path) -> None:
    expected = write(tmp_path, MINIMAL)

    assert find_config(tmp_path) == expected


def test_find_config_searches_parent_directories(tmp_path: Path) -> None:
    expected = write(tmp_path, MINIMAL)
    nested = tmp_path / "src" / "deep"
    nested.mkdir(parents=True)

    assert find_config(nested) == expected


def test_find_config_raises_when_absent(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"No mender\.yaml found"):
        find_config(tmp_path)
