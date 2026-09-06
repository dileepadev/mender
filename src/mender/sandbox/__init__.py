"""Containerised reproduction of a failure at a given commit.

``DockerRunner`` is the real sandbox: ephemeral, network-off, resource-capped,
torn down unconditionally. ``LocalRunner`` trades those guarantees for the
ability to run without a daemon, and is documented accordingly.
"""

from mender.sandbox.docker import DockerRunner, SandboxError, available
from mender.sandbox.reproduce import Reproduction, reproduce
from mender.sandbox.runner import CommandResult, LocalRunner, Runner

__all__ = [
    "CommandResult",
    "DockerRunner",
    "LocalRunner",
    "Reproduction",
    "Runner",
    "SandboxError",
    "available",
    "reproduce",
]
