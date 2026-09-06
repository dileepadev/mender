"""Tests for the agent interface and the Anthropic implementation.

The Anthropic agent is exercised against a stub client. No network call is made
and no API key is required — the point is that the mapping from a model response
to a ``Diagnosis`` is correct, including the paths where the model declines.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mender.classify import classify
from mender.diagnose.agent import (
    Diagnosis,
    DiagnosisAgent,
    DiagnosisRequest,
    ProposedEdit,
    RegressionTest,
)
from mender.diagnose.anthropic_agent import (
    AnthropicAgent,
    _Edit,
    _RegressionTest,
    _Response,
)
from mender.models import PathError


class StubUsage:
    """Token usage as the SDK reports it."""

    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class StubResponse:
    """A parsed Messages API response."""

    def __init__(self, parsed: _Response | None, stop_reason: str = "end_turn") -> None:
        self.parsed_output = parsed
        self.stop_reason = stop_reason
        self.usage = StubUsage(10_000, 2_000)


class StubClient:
    """Stands in for ``anthropic.Anthropic``."""

    def __init__(self, response: StubResponse) -> None:
        self.response = response
        self.kwargs: dict[str, Any] = {}
        self.messages = self

    def parse(self, **kwargs: Any) -> StubResponse:
        """Record the request and return the canned response."""
        self.kwargs = kwargs
        return self.response


def request_for(workspace: Path) -> DiagnosisRequest:
    """A minimal diagnosis request."""
    return DiagnosisRequest(
        classification=classify("E   ImportError: cannot import name 'x' from 'y'\n"),
        failing_output="boom\n",
        workspace=workspace,
        test_command="pytest",
    )


def agent_with(client: StubClient, **options: Any) -> AnthropicAgent:
    """Build an agent wired to a stub client."""
    return AnthropicAgent(client=client, **options)  # type: ignore[arg-type]


def test_the_anthropic_agent_satisfies_the_protocol() -> None:
    assert isinstance(AnthropicAgent(), DiagnosisAgent)


def test_a_model_answer_becomes_a_diagnosis(tmp_path: Path) -> None:
    parsed = _Response(
        root_cause="An incomplete rename.",
        confidence=0.9,
        edits=[_Edit(path="src/a.py", content="fixed\n")],
        regression_test=_RegressionTest(
            path="tests/test_a.py",
            content="def test_a(): pass\n",
            test_id="tests/test_a.py::test_a",
            rationale="fails before",
        ),
        notes="",
    )

    diagnosis = agent_with(StubClient(StubResponse(parsed))).diagnose(request_for(tmp_path))

    assert diagnosis.root_cause == "An incomplete rename."
    assert diagnosis.edits[0].path == "src/a.py"
    assert diagnosis.regression_test is not None
    assert diagnosis.agent == "anthropic"


def test_the_request_uses_the_configured_model_and_effort(tmp_path: Path) -> None:
    client = StubClient(StubResponse(_Response(root_cause="", confidence=0.0)))

    agent_with(client, model="claude-opus-5", effort="max").diagnose(request_for(tmp_path))

    assert client.kwargs["model"] == "claude-opus-5"
    assert client.kwargs["output_config"] == {"effort": "max"}
    assert client.kwargs["output_format"] is _Response


def test_cost_is_reported_from_token_usage(tmp_path: Path) -> None:
    client = StubClient(StubResponse(_Response(root_cause="", confidence=0.0)))

    diagnosis = agent_with(client).diagnose(request_for(tmp_path))

    assert diagnosis.cost_usd == pytest.approx(10_000 * 5e-6 + 2_000 * 25e-6)


def test_a_refusal_becomes_an_abstention_not_an_exception(tmp_path: Path) -> None:
    client = StubClient(StubResponse(None, stop_reason="refusal"))

    diagnosis = agent_with(client).diagnose(request_for(tmp_path))

    assert not diagnosis.has_fix
    assert diagnosis.confidence == 0.0
    assert "declined" in diagnosis.root_cause


# --- Turning a proposal into a patch -----------------------------------------


def test_a_proposal_becomes_a_patch_against_the_workspace(workspace: Path) -> None:
    diagnosis = Diagnosis(
        root_cause="x",
        confidence=0.9,
        edits=[ProposedEdit(path="src/pkg/money.py", content="changed\n")],
    )

    patch = diagnosis.to_patch(workspace)

    assert patch.edits[0].before is not None
    assert patch.edits[0].after == "changed\n"


def test_a_regression_test_is_part_of_the_patch(workspace: Path) -> None:
    diagnosis = Diagnosis(
        root_cause="x",
        confidence=0.9,
        edits=[ProposedEdit(path="src/pkg/money.py", content="changed\n")],
        regression_test=RegressionTest(
            path="tests/test_new.py",
            content="def test_new(): pass\n",
            test_id="tests/test_new.py::test_new",
        ),
    )

    assert set(diagnosis.to_patch(workspace).paths) == {
        "src/pkg/money.py",
        "tests/test_new.py",
    }


def test_a_proposal_that_escapes_the_repository_is_refused(workspace: Path) -> None:
    diagnosis = Diagnosis(
        root_cause="x",
        confidence=0.9,
        edits=[ProposedEdit(path="../../.ssh/authorized_keys", content="key\n")],
    )

    with pytest.raises(PathError):
        diagnosis.to_patch(workspace)
