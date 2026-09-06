"""Tests for the webhook receiver, driven over a real HTTP connection."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from tests.watch.test_events import SECRET, signed, workflow_run

from mender.watch.events import SIGNATURE_HEADER
from mender.watch.server import build_server


@pytest.fixture
def receiver(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    """A running receiver, and the directory it records into."""
    inbox = tmp_path / "inbox"
    server: ThreadingHTTPServer = build_server(secret=SECRET, inbox=inbox, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield f"http://{host!s}:{port}/", inbox
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def post_raw(url: str, body: bytes, *, signature: str | None) -> tuple[int, str]:
    """POST raw bytes and return the status and body, closing everything."""
    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers[SIGNATURE_HEADER] = signature
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        with error:
            return error.code, error.read().decode()


def post(url: str, payload: dict[str, Any], *, signature: str | None) -> tuple[int, str]:
    """POST a JSON payload and return the status and body."""
    return post_raw(url, json.dumps(payload).encode(), signature=signature)


def test_a_signed_failed_run_is_recorded(receiver: tuple[str, Path]) -> None:
    url, inbox = receiver
    payload = workflow_run()

    status, _ = post(url, payload, signature=signed(json.dumps(payload).encode()))

    assert status == 202
    recorded = list(inbox.iterdir())
    assert len(recorded) == 1
    assert json.loads(recorded[0].read_text())["commit"] == "a1b2c3d4e5f6"


def test_an_unsigned_delivery_is_rejected(receiver: tuple[str, Path]) -> None:
    url, inbox = receiver

    status, body = post(url, workflow_run(), signature=None)

    assert status == 401
    assert "bad signature" in body
    assert not inbox.exists()


def test_a_forged_signature_is_rejected(receiver: tuple[str, Path]) -> None:
    url, inbox = receiver

    status, _ = post(url, workflow_run(), signature="sha256=" + "0" * 64)

    assert status == 401
    assert not inbox.exists()


def test_a_green_run_is_accepted_and_ignored(receiver: tuple[str, Path]) -> None:
    url, inbox = receiver
    payload = workflow_run(conclusion="success")

    status, body = post(url, payload, signature=signed(json.dumps(payload).encode()))

    assert status == 200
    assert "not a failed run" in body
    assert not inbox.exists()


def test_a_body_that_is_not_json_is_rejected(receiver: tuple[str, Path]) -> None:
    url, _ = receiver
    body = b"not json at all"

    status, detail = post_raw(url, body, signature=signed(body))

    assert status == 400
    assert "not valid JSON" in detail
