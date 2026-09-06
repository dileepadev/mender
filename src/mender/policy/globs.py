"""Glob matching for path allowlists and never-touch patterns.

``fnmatch`` is not usable here: its ``*`` crosses directory separators, so
``src/*`` would match ``src/a/b/c.py`` and a never-touch pattern would match far
more than intended. Path patterns decide what an agent may edit, so the
semantics are implemented explicitly rather than borrowed.
"""

from __future__ import annotations

import re
from functools import lru_cache

_SEGMENT_SPECIALS = {"*": "[^/]*", "?": "[^/]"}


def _segment_regex(segment: str) -> str:
    """Translate one path segment, where ``*`` and ``?`` never cross a ``/``."""
    return "".join(_SEGMENT_SPECIALS.get(char, re.escape(char)) for char in segment)


@lru_cache(maxsize=512)
def _compile(pattern: str) -> re.Pattern[str]:
    """Compile a glob into an anchored regular expression."""
    parts = pattern.split("/")
    pieces: list[str] = []
    for index, segment in enumerate(parts):
        last = index == len(parts) - 1
        if segment == "**":
            # Trailing ``**`` matches everything below; an interior one matches
            # zero or more directories, consuming its own separator.
            pieces.append(".*" if last else "(?:[^/]+/)*")
            continue
        pieces.append(_segment_regex(segment))
        if not last:
            pieces.append("/")
    return re.compile("".join(pieces))


def glob_match(pattern: str, path: str) -> bool:
    """Report whether ``path`` matches ``pattern``.

    Args:
        pattern: A glob such as ``src/**`` or ``**/*.pem``. ``**`` spans any
            number of directories; ``*`` and ``?`` never cross a ``/``.
        path: A repository-relative POSIX path.

    Returns:
        ``True`` if the path matches.
    """
    return _compile(pattern).fullmatch(path) is not None


def matches_any(patterns: list[str], path: str) -> str | None:
    """Return the first pattern in ``patterns`` that matches ``path``."""
    return next((pattern for pattern in patterns if glob_match(pattern, path)), None)
