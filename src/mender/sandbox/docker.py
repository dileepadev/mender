"""The containerised backend: ephemeral, network-off, resource-capped.

Every guarantee in ``docs/safety-and-limits.md`` about sandboxed reproduction is
implemented by the argument list this module builds and by its teardown block.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import time
import uuid
from collections.abc import Mapping
from pathlib import Path

from mender.config import SandboxConfig
from mender.sandbox.runner import CommandResult, _tail

TEARDOWN_TIMEOUT_SECONDS = 30


class SandboxError(RuntimeError):
    """Raised when the sandbox itself could not be started."""


class DockerRunner:
    """Runs commands inside a throwaway container.

    The container is created with no network, a memory cap, a CPU cap, a
    process-count cap, every Linux capability dropped, and privilege escalation
    disabled. It is removed on exit, on timeout, and on crash.
    """

    name = "docker"

    def __init__(self, config: SandboxConfig, *, docker_binary: str = "docker") -> None:
        """Store the sandbox limits this runner enforces.

        Args:
            config: The validated ``sandbox`` block from ``mender.yaml``.
            docker_binary: Executable to invoke. Overridable for testing.
        """
        self.config = config
        self.docker_binary = docker_binary

    def run(
        self,
        command: str,
        *,
        workspace: Path,
        timeout_seconds: int,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        """Run ``command`` inside a fresh container over ``workspace``.

        Args:
            command: The shell command to run inside the container.
            workspace: Host directory mounted at ``/workspace``.
            timeout_seconds: Hard wall-clock limit, enforced on the host.
            env: Extra environment variables set inside the container.

        Returns:
            The captured result. A container that had to be killed comes back
            with ``timed_out`` set and exit code 124.

        Raises:
            SandboxError: If the Docker CLI is not available.
        """
        container = f"mender-{uuid.uuid4().hex[:12]}"
        args = self._container_args(container, command, workspace, env)
        started = time.monotonic()
        timed_out = False
        try:
            completed = subprocess.run(  # noqa: S603 - argument list, never a shell
                args,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=timeout_seconds,
                check=False,
            )
            stdout, stderr, exit_code = (
                completed.stdout,
                completed.stderr,
                completed.returncode,
            )
        except subprocess.TimeoutExpired as expired:
            timed_out = True
            stdout = _decode(expired.stdout)
            stderr = _decode(expired.stderr)
            exit_code = 124
        except FileNotFoundError as exc:
            raise SandboxError(
                f"Could not run {self.docker_binary!r}. Install Docker, or use the "
                f"local runner with --runner local."
            ) from exc
        finally:
            self._force_remove(container)

        return CommandResult(
            command=command,
            exit_code=exit_code,
            stdout=_tail(stdout),
            stderr=_tail(stderr),
            duration_seconds=round(time.monotonic() - started, 3),
            timed_out=timed_out,
        )

    def _container_args(
        self,
        container: str,
        command: str,
        workspace: Path,
        env: Mapping[str, str] | None,
    ) -> list[str]:
        """Build the full ``docker run`` argument list, limits included."""
        args = [
            self.docker_binary,
            "run",
            "--rm",
            "--name",
            container,
            "--network",
            "bridge" if self.config.network else "none",
            "--memory",
            f"{self.config.memory_mb}m",
            "--memory-swap",
            f"{self.config.memory_mb}m",
            "--cpus",
            str(self.config.cpus),
            "--pids-limit",
            "512",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--volume",
            f"{workspace.resolve()}:/workspace",
            "--workdir",
            "/workspace",
        ]
        for key, value in (env or {}).items():
            args += ["--env", f"{key}={value}"]
        args += [self.config.image, "sh", "-c", command]
        return args

    def _force_remove(self, container: str) -> None:
        """Remove the container, whatever happened to the run.

        ``--rm`` covers the normal exit. This covers the rest: a timeout, a
        crash in the middle of ``communicate``, a daemon that stalled. Nothing
        survives a run.
        """
        # Best effort by definition: if the daemon is gone there is nothing
        # left to remove, and a teardown failure must not mask the run's result.
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(  # noqa: S603 - argument list, never a shell
                [self.docker_binary, "rm", "--force", container],
                capture_output=True,
                check=False,
                timeout=TEARDOWN_TIMEOUT_SECONDS,
            )


def _decode(raw: str | bytes | None) -> str:
    """Normalise the partial output Docker returned before a timeout."""
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return raw


def available(docker_binary: str = "docker") -> bool:
    """Report whether a usable Docker daemon is reachable."""
    try:
        completed = subprocess.run(  # noqa: S603 - argument list, never a shell
            [docker_binary, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            check=False,
            timeout=TEARDOWN_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0
