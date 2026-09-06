"""Assembling the packet an agent is given.

The diff since the last green run does most of the work here. It narrows a
haystack of thousands of files down to the handful that changed since things
last worked, which is where the cause of a new failure usually is.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from mender.classify import Classification
from mender.config import MenderConfig
from mender.diagnose.agent import DiagnosisRequest

MAX_CONTEXT_FILES = 12
MAX_FILE_CHARS = 20_000
MAX_DIFF_CHARS = 40_000
MAX_OUTPUT_CHARS = 20_000
GIT_TIMEOUT_SECONDS = 60

_TRACEBACK_FILE = re.compile(r'File "(?P<path>[^"]+\.py)", line \d+')
_DIAGNOSTIC_FILE = re.compile(r"^\s*(?P<path>[\w./-]+\.py):\d+", re.MULTILINE)
_NODE_ID_FILE = re.compile(r"(?P<path>[\w./-]+\.py)::")


def tail(text: str, limit: int) -> str:
    """Keep the last ``limit`` characters of a string, noting what was dropped."""
    if len(text) <= limit:
        return text
    return f"[... {len(text) - limit} characters truncated ...]\n{text[-limit:]}"


def referenced_files(text: str, workspace: Path) -> list[str]:
    """Find repository files mentioned in a traceback or diagnostic output.

    Args:
        text: Captured output. Untrusted; used only to look paths up.
        workspace: The repository root. Paths outside it are discarded.

    Returns:
        Repository-relative paths that exist, in first-seen order.
    """
    root = workspace.resolve()
    found: dict[str, None] = {}
    for pattern in (_TRACEBACK_FILE, _DIAGNOSTIC_FILE, _NODE_ID_FILE):
        for match in pattern.finditer(text):
            candidate = Path(match.group("path"))
            absolute = (candidate if candidate.is_absolute() else root / candidate).resolve()
            if not absolute.is_file():
                continue
            try:
                relative = absolute.relative_to(root)
            except ValueError:
                continue  # A path outside the workspace is not ours to read.
            found.setdefault(relative.as_posix(), None)
    return list(found)


def diff_since_last_green(workspace: Path, commit: str, last_green: str | None) -> str:
    """Return the diff between the last green commit and the failing one.

    Args:
        workspace: A git checkout.
        commit: The failing commit.
        last_green: The last commit whose pipeline passed, if known.

    Returns:
        A unified diff, or an empty string when it cannot be determined.
    """
    if not last_green:
        return ""
    try:
        completed = subprocess.run(  # noqa: S603 - argument list, never a shell
            ["git", "diff", f"{last_green}..{commit}"],  # noqa: S607 - git from PATH
            cwd=workspace,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if completed.returncode != 0:
        return ""
    return tail(completed.stdout, MAX_DIFF_CHARS)


def build_request(
    *,
    classification: Classification,
    failing_output: str,
    workspace: Path,
    config: MenderConfig,
    commit: str = "",
    last_green_commit: str | None = None,
    extra_paths: list[str] | None = None,
) -> DiagnosisRequest:
    """Assemble the diagnosis packet for one reproduced failure.

    Args:
        classification: What the classifier concluded.
        failing_output: Output from the reproduction run.
        workspace: The checked-out repository.
        config: The repository's validated configuration.
        commit: The failing commit, used for the diff since last green.
        last_green_commit: The last commit whose pipeline passed, if known.
        extra_paths: Files to include regardless of what the output mentions.

    Returns:
        The request an agent receives, with output and file content capped.
    """
    paths = list(dict.fromkeys((extra_paths or []) + referenced_files(failing_output, workspace)))
    context: dict[str, str] = {}
    for relative in paths[:MAX_CONTEXT_FILES]:
        target = workspace / relative
        try:
            context[relative] = tail(target.read_text(encoding="utf-8"), MAX_FILE_CHARS)
        except (OSError, UnicodeDecodeError):
            continue

    return DiagnosisRequest(
        classification=classification,
        failing_output=tail(failing_output, MAX_OUTPUT_CHARS),
        workspace=workspace,
        test_command=config.test_command,
        diff_since_last_green=diff_since_last_green(workspace, commit, last_green_commit),
        file_context=context,
        allow_paths=list(config.policy.allow_paths),
        never_touch=list(config.policy.never_touch),
        max_files_changed=config.policy.max_files_changed,
        max_lines_changed=config.policy.max_lines_changed,
    )
