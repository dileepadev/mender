"""Command execution, and the interface every backend implements.

Everything Mender runs on behalf of a repository goes through a ``Runner``.
Having one interface means the proof step cannot accidentally run a repository's
test command outside a sandbox: it holds a ``Runner``, not a subprocess.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

MAX_CAPTURED_CHARS = 200_000
"""Cap on captured output per stream.

A runaway test can emit gigabytes. Mender only ever needs the tail, and an
unbounded read would take the whole process down with it.
"""


class CommandResult(BaseModel):
    """The outcome of one command run inside a sandbox."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    command: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        """Whether the command succeeded."""
        return self.exit_code == 0 and not self.timed_out

    @property
    def output(self) -> str:
        """Standard output and standard error, in that order."""
        return "\n".join(part for part in (self.stdout, self.stderr) if part)


@runtime_checkable
class Runner(Protocol):
    """Executes a shell command against a workspace under hard limits."""

    name: str

    def run(
        self,
        command: str,
        *,
        workspace: Path,
        timeout_seconds: int,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        """Run ``command`` in ``workspace`` and capture its result."""
        ...


def _tail(text: str, limit: int = MAX_CAPTURED_CHARS) -> str:
    """Keep the last ``limit`` characters, noting anything dropped."""
    if len(text) <= limit:
        return text
    dropped = len(text) - limit
    return f"[... {dropped} characters truncated ...]\n{text[-limit:]}"


class LocalRunner:
    """Runs commands directly on this machine, in a subprocess.

    This backend gives up the isolation guarantees in
    ``docs/safety-and-limits.md``: there is no container, so the only limit it
    enforces is the timeout. It exists so Mender's own test suite can exercise
    the full repair loop without a Docker daemon, and so the CLI can be pointed
    at a workspace you already trust. Never point it at a repository whose code
    you would not run yourself.
    """

    name = "local"

    def run(
        self,
        command: str,
        *,
        workspace: Path,
        timeout_seconds: int,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        """Run ``command`` with ``workspace`` as the working directory.

        Args:
            command: The shell command, taken from validated configuration.
            workspace: Directory to run in.
            timeout_seconds: Hard wall-clock limit.
            env: Extra environment variables layered over the current ones.

        Returns:
            The captured result, with ``timed_out`` set if the limit was hit.
        """
        environment = {**os.environ, **(env or {})}
        started = time.monotonic()
        # shell=True is deliberate: `test_command` is a shell string supplied by
        # the repository's own validated mender.yaml, not by an agent or a log.
        process = subprocess.Popen(  # noqa: S602
            command,
            shell=True,
            cwd=workspace,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            start_new_session=True,
        )
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_group(process)
            stdout, stderr = process.communicate()
        return CommandResult(
            command=command,
            exit_code=process.returncode if not timed_out else 124,
            stdout=_tail(stdout or ""),
            stderr=_tail(stderr or ""),
            duration_seconds=round(time.monotonic() - started, 3),
            timed_out=timed_out,
        )


def _terminate_group(process: subprocess.Popen[str]) -> None:
    """Kill a timed-out process and everything it spawned.

    ``shell=True`` means the direct child is a shell; killing only that leaves
    the test runner orphaned and still burning CPU. The process group is the
    unit that has to die.
    """
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):  # pragma: no cover - race
        process.kill()
