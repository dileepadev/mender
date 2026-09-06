"""A minimal webhook receiver.

Enough to take real events from a CI provider and record them for the repair
loop, with no web framework in the dependency tree. It verifies the signature,
discards anything that is not a failed run, and writes what survives to a
directory as JSON.

It deliberately does not run repairs inline: a webhook handler that blocks for
the length of a container build is a webhook handler that times out.
"""

from __future__ import annotations

import json
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from mender.watch.events import (
    EVENT_HEADER,
    SIGNATURE_HEADER,
    WebhookError,
    failed_run_from,
    parse_payload,
    verify_signature,
)

MAX_BODY_BYTES = 5_000_000


class WebhookHandler(BaseHTTPRequestHandler):
    """Handles one webhook delivery."""

    server_version = "mender"
    secret: str = ""
    inbox: Path = Path("inbox")

    def do_POST(self) -> None:
        """Accept a webhook delivery, verify it, and record a failed run."""
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            self._reply(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "body too large")
            return

        body = self.rfile.read(length)
        if not verify_signature(self.secret, body, self.headers.get(SIGNATURE_HEADER)):
            self._reply(HTTPStatus.UNAUTHORIZED, "bad signature")
            return

        try:
            payload = parse_payload(body)
        except WebhookError as exc:
            self._reply(HTTPStatus.BAD_REQUEST, str(exc))
            return

        run = failed_run_from(payload)
        if run is None:
            self._reply(HTTPStatus.OK, "ignored: not a failed run")
            return

        self.inbox.mkdir(parents=True, exist_ok=True)
        target = self.inbox / f"{int(time.time() * 1000)}-{run.short_commit}.json"
        target.write_text(run.model_dump_json(indent=2), encoding="utf-8")
        self._reply(HTTPStatus.ACCEPTED, f"recorded {target.name}")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, ANN401
        """Silence the default stderr access log."""

    def _reply(self, status: HTTPStatus, message: str) -> None:
        """Send a short JSON response."""
        body = json.dumps({"status": status.phrase, "detail": message}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_server(
    *, secret: str, inbox: Path, host: str = "127.0.0.1", port: int = 8000
) -> ThreadingHTTPServer:
    """Create a receiver bound to ``host:port``.

    Args:
        secret: The shared webhook secret. Deliveries without a matching
            signature are rejected.
        inbox: Directory failed runs are written to.
        host: Interface to bind. Loopback by default.
        port: Port to bind.

    Returns:
        A server ready for ``serve_forever()``.
    """
    handler = type(
        "BoundWebhookHandler",
        (WebhookHandler,),
        {"secret": secret, "inbox": inbox},
    )
    return ThreadingHTTPServer((host, port), handler)


__all__ = ["EVENT_HEADER", "WebhookHandler", "build_server"]
