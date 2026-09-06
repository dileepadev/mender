"""Pull request authoring, with the evidence package attached.

Mender never merges its own work. Everything this package produces is something
a human reads and decides on.
"""

from mender.ship.evidence import Evidence, render, render_issue, render_pull_request
from mender.ship.publish import (
    DryRunPublisher,
    GitHubPublisher,
    Publisher,
    ShipError,
)

__all__ = [
    "DryRunPublisher",
    "Evidence",
    "GitHubPublisher",
    "Publisher",
    "ShipError",
    "render",
    "render_issue",
    "render_pull_request",
]
