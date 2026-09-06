"""CI webhook ingestion and failed-run intake.

The entry point to the loop. Webhook bodies arrive from an untrusted network:
the signature is verified before the payload is read, and a payload that does
not describe a failed run is discarded rather than partially trusted.
"""

from mender.watch.events import (
    EVENT_HEADER,
    SIGNATURE_HEADER,
    SUPPORTED_EVENTS,
    WebhookError,
    failed_run_from,
    parse_payload,
    verify_signature,
)
from mender.watch.server import WebhookHandler, build_server

__all__ = [
    "EVENT_HEADER",
    "SIGNATURE_HEADER",
    "SUPPORTED_EVENTS",
    "WebhookError",
    "WebhookHandler",
    "build_server",
    "failed_run_from",
    "parse_payload",
    "verify_signature",
]
