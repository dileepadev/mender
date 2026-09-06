"""Tests for the container backend's arguments and its teardown guarantee.

These do not need a Docker daemon: what matters is that the limits documented in
``docs/safety-and-limits.md`` are actually on the command line, and that the
container is removed whatever happens.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mender.config import SandboxConfig
from mender.sandbox.docker import DockerRunner, SandboxError, available


def args_for(config: SandboxConfig, tmp_path: Path) -> list[str]:
    """Build the argument list a run would use."""
    runner = DockerRunner(config)
    return runner._container_args("mender-test", "pytest", tmp_path, None)


def test_the_network_is_off_by_default(tmp_path: Path) -> None:
    args = args_for(SandboxConfig(), tmp_path)

    assert args[args.index("--network") + 1] == "none"


def test_the_network_can_be_turned_on_explicitly(tmp_path: Path) -> None:
    args = args_for(SandboxConfig(network=True), tmp_path)

    assert args[args.index("--network") + 1] == "bridge"


def test_resource_caps_are_on_the_command_line(tmp_path: Path) -> None:
    args = args_for(SandboxConfig(memory_mb=512, cpus=1.5), tmp_path)

    assert args[args.index("--memory") + 1] == "512m"
    assert args[args.index("--memory-swap") + 1] == "512m"
    assert args[args.index("--cpus") + 1] == "1.5"
    assert "--pids-limit" in args


def test_privileges_are_dropped(tmp_path: Path) -> None:
    args = args_for(SandboxConfig(), tmp_path)

    assert args[args.index("--cap-drop") + 1] == "ALL"
    assert args[args.index("--security-opt") + 1] == "no-new-privileges"


def test_the_container_removes_itself(tmp_path: Path) -> None:
    assert "--rm" in args_for(SandboxConfig(), tmp_path)


def test_the_workspace_is_mounted_and_used_as_the_working_directory(tmp_path: Path) -> None:
    args = args_for(SandboxConfig(), tmp_path)

    assert args[args.index("--volume") + 1] == f"{tmp_path.resolve()}:/workspace"
    assert args[args.index("--workdir") + 1] == "/workspace"


def test_the_command_is_never_passed_to_a_host_shell(tmp_path: Path) -> None:
    args = args_for(SandboxConfig(), tmp_path)

    assert args[-3:] == ["sh", "-c", "pytest"]


def test_environment_variables_are_passed_through(tmp_path: Path) -> None:
    runner = DockerRunner(SandboxConfig())
    args = runner._container_args("c", "pytest", tmp_path, {"CI": "true"})

    assert args[args.index("--env") + 1] == "CI=true"


def test_a_missing_docker_binary_is_an_actionable_error(tmp_path: Path) -> None:
    runner = DockerRunner(SandboxConfig(), docker_binary="definitely-not-installed")

    with pytest.raises(SandboxError, match="local runner"):
        runner.run("pytest", workspace=tmp_path, timeout_seconds=5)


def test_the_container_is_force_removed_even_when_the_run_explodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[1] == "run":
            raise subprocess.TimeoutExpired(cmd=args, timeout=1)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = DockerRunner(SandboxConfig()).run("pytest", workspace=tmp_path, timeout_seconds=1)

    assert result.timed_out
    assert result.exit_code == 124
    assert calls[-1][:3] == ["docker", "rm", "--force"]


def test_availability_is_false_without_a_daemon() -> None:
    assert available("definitely-not-installed") is False
