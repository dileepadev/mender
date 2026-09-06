"""Tests for webhook ingestion."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import pytest

from mender.watch import (
    WebhookError,
    failed_run_from,
    parse_payload,
    verify_signature,
)

SECRET = "shh"


def signed(body: bytes, secret: str = SECRET) -> str:
    """Compute the signature GitHub would send."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def workflow_run(**overrides: Any) -> dict[str, Any]:
    """A completed, failed ``workflow_run`` payload."""
    run: dict[str, Any] = {
        "name": "CI",
        "status": "completed",
        "conclusion": "failure",
        "head_sha": "a1b2c3d4e5f6",
        "head_branch": "main",
        "html_url": "https://github.com/owner/repo/actions/runs/1",
    }
    run.update(overrides)
    return {"action": "completed", "workflow_run": run, "repository": {"full_name": "owner/repo"}}


# --- Signatures --------------------------------------------------------------


def test_a_correct_signature_is_accepted() -> None:
    body = b'{"a": 1}'

    assert verify_signature(SECRET, body, signed(body))


def test_a_signature_from_the_wrong_secret_is_rejected() -> None:
    body = b'{"a": 1}'

    assert not verify_signature(SECRET, body, signed(body, "wrong"))


def test_a_signature_over_different_bytes_is_rejected() -> None:
    assert not verify_signature(SECRET, b'{"a": 2}', signed(b'{"a": 1}'))


@pytest.mark.parametrize("signature", [None, "", "deadbeef", "sha1=abc"])
def test_missing_or_malformed_signatures_are_rejected(signature: str | None) -> None:
    assert not verify_signature(SECRET, b"{}", signature)


# --- Payloads ----------------------------------------------------------------


def test_a_valid_body_parses() -> None:
    assert parse_payload(b'{"a": 1}') == {"a": 1}


@pytest.mark.parametrize("body", [b"not json", b"[1, 2]", b'"a string"'])
def test_a_body_that_is_not_a_json_object_is_rejected(body: bytes) -> None:
    with pytest.raises(WebhookError):
        parse_payload(body)


def test_a_failed_workflow_run_becomes_a_failed_run() -> None:
    run = failed_run_from(workflow_run(), logs="boom\n")

    assert run is not None
    assert run.repository == "owner/repo"
    assert run.commit == "a1b2c3d4e5f6"
    assert run.job == "CI"
    assert run.branch == "main"
    assert run.logs == "boom\n"


@pytest.mark.parametrize("conclusion", ["success", "cancelled", "skipped", "neutral"])
def test_a_run_that_was_not_red_is_ignored(conclusion: str) -> None:
    assert failed_run_from(workflow_run(conclusion=conclusion)) is None


@pytest.mark.parametrize("conclusion", ["failure", "timed_out", "startup_failure"])
def test_every_red_conclusion_is_ingested(conclusion: str) -> None:
    assert failed_run_from(workflow_run(conclusion=conclusion)) is not None


def test_a_run_still_in_progress_is_ignored() -> None:
    assert failed_run_from(workflow_run(status="in_progress")) is None


def test_a_payload_with_no_commit_is_ignored() -> None:
    payload = workflow_run()
    del payload["workflow_run"]["head_sha"]

    assert failed_run_from(payload) is None


def test_a_payload_with_no_repository_is_ignored() -> None:
    payload = workflow_run()
    del payload["repository"]

    assert failed_run_from(payload) is None


def test_an_unrelated_event_is_ignored() -> None:
    assert failed_run_from({"action": "opened", "issue": {"number": 1}}) is None


def test_a_check_run_payload_works_too() -> None:
    payload = {
        "action": "completed",
        "check_run": {
            "name": "tests",
            "status": "completed",
            "conclusion": "failure",
            "head_sha": "abc1234",
        },
        "repository": {"full_name": "owner/repo"},
    }

    run = failed_run_from(payload)

    assert run is not None
    assert run.job == "tests"


def test_hostile_field_types_do_not_crash_the_parser() -> None:
    payload = {
        "action": "completed",
        "workflow_run": {"name": {"nested": "object"}, "conclusion": "failure", "head_sha": 12345},
        "repository": {"full_name": ["not", "a", "string"]},
    }

    assert failed_run_from(payload) is None


def test_a_round_trip_through_json_bytes_works() -> None:
    body = json.dumps(workflow_run()).encode()

    assert failed_run_from(parse_payload(body)) is not None
