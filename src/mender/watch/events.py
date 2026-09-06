"""Step 1 of the loop: turn a CI webhook into a failed run record.

Webhook bodies are attacker-shaped input from an untrusted network. Everything
here validates the signature first and reads fields defensively second — a
payload that does not describe a failed run produces ``None``, not an exception
and not a half-populated record.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from mender.models import FailedRun

SIGNATURE_HEADER = "X-Hub-Signature-256"
EVENT_HEADER = "X-GitHub-Event"
SUPPORTED_EVENTS = ("workflow_run", "check_run", "check_suite")


class WebhookError(ValueError):
    """Raised when a webhook body cannot be trusted or cannot be read."""


def verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    """Check a GitHub webhook signature in constant time.

    Args:
        secret: The shared webhook secret.
        body: The exact request body, unparsed.
        signature: The ``X-Hub-Signature-256`` header value, if present.

    Returns:
        ``True`` when the signature matches.
    """
    if not signature or not signature.startswith("sha256="):
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={digest}", signature)


def parse_payload(body: bytes) -> dict[str, Any]:
    """Parse a webhook body into a mapping.

    Args:
        body: The raw request body.

    Returns:
        The decoded payload.

    Raises:
        WebhookError: If the body is not a JSON object.
    """
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WebhookError(f"Webhook body is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise WebhookError("Webhook body must be a JSON object.")
    return data


def failed_run_from(payload: dict[str, Any], *, logs: str = "") -> FailedRun | None:
    """Build a failed run record, or return ``None`` if the run was not red.

    Args:
        payload: A decoded ``workflow_run``, ``check_run``, or ``check_suite``
            webhook payload.
        logs: Log text fetched separately. The webhook itself never carries it.

    Returns:
        The failed run, or ``None`` when the event does not describe a
        completed, failed run.
    """
    repository = _string(_dig(payload, "repository", "full_name"))
    run = _first_mapping(payload, "workflow_run", "check_run", "check_suite")
    if run is None or not repository:
        return None

    if _string(run.get("status") or payload.get("action")) not in {
        "completed",
        "",
    }:
        return None
    if _string(run.get("conclusion")) not in {"failure", "timed_out", "startup_failure"}:
        return None

    commit = _string(run.get("head_sha")) or _string(_dig(run, "head_commit", "id"))
    if not commit:
        return None

    return FailedRun(
        repository=repository,
        commit=commit,
        job=_string(run.get("name")) or "unknown",
        logs=logs,
        branch=_string(run.get("head_branch")) or None,
        run_url=_string(run.get("html_url")) or None,
    )


def _first_mapping(payload: dict[str, Any], *keys: str) -> dict[str, Any] | None:
    """Return the first key whose value is a mapping."""
    for key in keys:
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return None


def _dig(data: Any, *keys: str) -> Any:  # noqa: ANN401
    """Walk nested mappings, returning ``None`` the moment one is missing."""
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _string(value: Any) -> str:  # noqa: ANN401
    """Coerce a payload field to a string, treating anything else as absent."""
    return value if isinstance(value, str) else ""
