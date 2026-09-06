"""Minimal-diff patch generation, constrained by policy.

A patch is built from an agent's proposal against the current workspace
(:meth:`mender.diagnose.Diagnosis.to_patch`), evaluated by
:mod:`mender.policy`, and only then written by anything here.
"""

from mender.patch.workspace import (
    WorkspaceError,
    applied,
    apply_patch,
    resolve_within,
    revert_patch,
)

__all__ = [
    "WorkspaceError",
    "applied",
    "apply_patch",
    "resolve_within",
    "revert_patch",
]
