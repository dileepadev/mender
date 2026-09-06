"""Step 7 of the loop: put the evidence where a human will see it.

Two publishers ship. The dry-run one writes the package to a file and is the
default, because opening pull requests on somebody's repository is not a thing
to do by accident. The GitHub one does the real work, and only when asked.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol, runtime_checkable

from mender.models import Patch
from mender.patch.workspace import apply_patch
from mender.report import Outcome, RepairReport
from mender.ship.evidence import Evidence

GIT_TIMEOUT_SECONDS = 300


class ShipError(RuntimeError):
    """Raised when the evidence package could not be published."""


@runtime_checkable
class Publisher(Protocol):
    """Delivers a rendered evidence package somewhere a human will read it."""

    name: str

    def publish(self, report: RepairReport, evidence: Evidence, *, workspace: Path) -> str:
        """Publish the package and return a reference to it."""
        ...


class DryRunPublisher:
    """Writes the evidence package to a local file instead of publishing it.

    The default. Mender's output is reviewable before anything reaches a
    repository, which is also what makes the eval corpus runnable without a
    GitHub account.
    """

    name = "dry-run"

    def __init__(self, output_dir: Path) -> None:
        """Store the directory packages are written to."""
        self.output_dir = output_dir

    def publish(self, report: RepairReport, evidence: Evidence, *, workspace: Path) -> str:
        """Write the package to a markdown file.

        Args:
            report: The finished repair report.
            evidence: The rendered title and body.
            workspace: Unused; kept to satisfy the publisher interface.

        Returns:
            The path the package was written to.
        """
        del workspace
        self.output_dir.mkdir(parents=True, exist_ok=True)
        kind = "pull-request" if report.outcome is Outcome.SHIPPED else "issue"
        target = self.output_dir / f"{kind}-{report.run.short_commit or 'run'}.md"
        target.write_text(f"# {evidence.title}\n\n{evidence.body}\n", encoding="utf-8")
        return str(target)


class GitHubPublisher:
    """Opens a real pull request, or a real issue, through the ``gh`` CLI.

    A shipped fix becomes a branch, a commit, and a pull request. Everything
    else becomes an issue carrying the diagnosis. Mender never merges either.
    """

    name = "github"

    def __init__(
        self,
        *,
        base_branch: str = "main",
        branch_prefix: str = "mender/fix",
        remote: str = "origin",
        git_binary: str = "git",
        gh_binary: str = "gh",
    ) -> None:
        """Configure how the branch and pull request are created.

        Args:
            base_branch: The branch the pull request targets.
            branch_prefix: Prefix for the branch Mender pushes.
            remote: Git remote to push to.
            git_binary: Git executable.
            gh_binary: GitHub CLI executable.
        """
        self.base_branch = base_branch
        self.branch_prefix = branch_prefix
        self.remote = remote
        self.git_binary = git_binary
        self.gh_binary = gh_binary

    def publish(self, report: RepairReport, evidence: Evidence, *, workspace: Path) -> str:
        """Open a pull request for a proven fix, or an issue for anything else.

        Args:
            report: The finished repair report.
            evidence: The rendered title and body.
            workspace: The git checkout the patch applies to.

        Returns:
            The URL of the pull request or issue.

        Raises:
            ShipError: If git or the GitHub CLI failed.
        """
        if report.outcome is Outcome.SHIPPED and report.patch is not None:
            return self._open_pull_request(report.patch, evidence, workspace)
        return self._open_issue(evidence, workspace)

    def _open_pull_request(self, patch: Patch, evidence: Evidence, workspace: Path) -> str:
        """Branch, commit, push, and open the pull request."""
        branch = f"{self.branch_prefix}-{_slug(evidence.title)}"
        self._git(workspace, "checkout", "-b", branch)
        apply_patch(workspace, patch)
        self._git(workspace, "add", "--", *patch.paths)
        self._git(
            workspace,
            "commit",
            "-m",
            f"fix(mender): {evidence.title.removeprefix('Fix: ')}",
            "-m",
            "Authored by Mender. The regression test and proof are in the pull request.",
        )
        self._git(workspace, "push", "--set-upstream", self.remote, branch)
        return self._gh(
            workspace,
            "pr",
            "create",
            "--base",
            self.base_branch,
            "--head",
            branch,
            "--title",
            evidence.title,
            "--body",
            evidence.body,
        )

    def _open_issue(self, evidence: Evidence, workspace: Path) -> str:
        """Open the abstention issue."""
        args = ["issue", "create", "--title", evidence.title, "--body", evidence.body]
        for label in evidence.labels:
            args += ["--label", label]
        return self._gh(workspace, *args)

    def _git(self, workspace: Path, *args: str) -> str:
        """Run a git command in the workspace."""
        return _run([self.git_binary, *args], workspace)

    def _gh(self, workspace: Path, *args: str) -> str:
        """Run a GitHub CLI command in the workspace."""
        return _run([self.gh_binary, *args], workspace)


def _run(args: list[str], workspace: Path) -> str:
    """Run a command and return its trimmed output, or raise."""
    try:
        completed = subprocess.run(  # noqa: S603 - argument list, never a shell
            args,
            cwd=workspace,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ShipError(f"{args[0]!r} is not installed or not on PATH.") from exc
    except subprocess.SubprocessError as exc:
        raise ShipError(f"{' '.join(args[:2])} failed: {exc}") from exc
    if completed.returncode != 0:
        raise ShipError(
            f"{' '.join(args[:2])} exited {completed.returncode}: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    return completed.stdout.strip()


def _slug(text: str) -> str:
    """Turn a title into a branch-safe slug."""
    allowed = [
        char.lower() if char.isalnum() else "-" for char in text.removeprefix("Fix: ").strip()
    ]
    slug = "".join(allowed)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:60] or "repair"
