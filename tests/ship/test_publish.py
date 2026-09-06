"""Tests for publishing the evidence package."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from tests.helpers import edit, patch_of

from mender.models import FailedRun
from mender.report import Outcome, RepairReport, Stage
from mender.ship.evidence import Evidence
from mender.ship.publish import DryRunPublisher, GitHubPublisher, Publisher, ShipError

RUN = FailedRun(repository="owner/repo", commit="a1b2c3d4")
EVIDENCE = Evidence(title="Fix: a thing", body="the body", labels=["mender"])
PATCH = patch_of(edit("src/a.py", "one\n", "two\n"))


def report(outcome: Outcome = Outcome.SHIPPED) -> RepairReport:
    """A minimal report in the given outcome."""
    return RepairReport(
        run=RUN,
        outcome=outcome,
        stopped_at=Stage.SHIP,
        reason="done",
        patch=PATCH,
    )


def test_both_publishers_satisfy_the_protocol(tmp_path: Path) -> None:
    assert isinstance(DryRunPublisher(tmp_path), Publisher)
    assert isinstance(GitHubPublisher(), Publisher)


def test_the_dry_run_publisher_writes_a_pull_request_file(tmp_path: Path) -> None:
    target = DryRunPublisher(tmp_path / "out").publish(report(), EVIDENCE, workspace=tmp_path)

    assert Path(target).name == "pull-request-a1b2c3d.md"
    assert "the body" in Path(target).read_text()


def test_the_dry_run_publisher_names_abstentions_differently(tmp_path: Path) -> None:
    target = DryRunPublisher(tmp_path / "out").publish(
        report(Outcome.ABSTAINED), EVIDENCE, workspace=tmp_path
    )

    assert Path(target).name == "issue-a1b2c3d.md"


def test_the_dry_run_publisher_creates_its_output_directory(tmp_path: Path) -> None:
    DryRunPublisher(tmp_path / "deep" / "out").publish(report(), EVIDENCE, workspace=tmp_path)

    assert (tmp_path / "deep" / "out").is_dir()


# --- GitHub ------------------------------------------------------------------


class FakeProcess:
    """Records every command instead of running it."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.returncode = 0

    def __call__(self, args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        """Record the command and pretend it succeeded."""
        self.calls.append(args)
        return subprocess.CompletedProcess(args, self.returncode, "https://example/pr/1\n", "")


def test_a_shipped_report_branches_commits_pushes_and_opens_a_pull_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeProcess()
    monkeypatch.setattr(subprocess, "run", fake)
    (tmp_path / "src").mkdir()

    url = GitHubPublisher().publish(report(), EVIDENCE, workspace=tmp_path)

    verbs = [call[1] for call in fake.calls]
    assert verbs == ["checkout", "add", "commit", "push", "pr"]
    assert url == "https://example/pr/1"


def test_the_branch_name_is_derived_from_the_title(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeProcess()
    monkeypatch.setattr(subprocess, "run", fake)
    (tmp_path / "src").mkdir()

    GitHubPublisher().publish(report(), EVIDENCE, workspace=tmp_path)

    assert fake.calls[0][-1] == "mender/fix-a-thing"


def test_the_patch_is_written_before_it_is_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "run", FakeProcess())
    (tmp_path / "src").mkdir()

    GitHubPublisher().publish(report(), EVIDENCE, workspace=tmp_path)

    assert (tmp_path / "src" / "a.py").read_text() == "two\n"


def test_an_abstention_opens_an_issue_instead(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeProcess()
    monkeypatch.setattr(subprocess, "run", fake)

    GitHubPublisher().publish(report(Outcome.ABSTAINED), EVIDENCE, workspace=tmp_path)

    assert [call[1] for call in fake.calls] == ["issue"]
    assert "--label" in fake.calls[0]


def test_a_failing_command_is_reported_with_its_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 1, "", "not a git repository")

    monkeypatch.setattr(subprocess, "run", failing)

    with pytest.raises(ShipError, match="not a git repository"):
        GitHubPublisher().publish(report(Outcome.ABSTAINED), EVIDENCE, workspace=tmp_path)


def test_a_missing_binary_is_an_actionable_error(tmp_path: Path) -> None:
    publisher = GitHubPublisher(gh_binary="definitely-not-installed")

    with pytest.raises(ShipError, match="not installed"):
        publisher.publish(report(Outcome.ABSTAINED), EVIDENCE, workspace=tmp_path)
