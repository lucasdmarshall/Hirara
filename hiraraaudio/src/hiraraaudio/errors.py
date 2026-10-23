"""The one error type tools turn into an ``{"error": ...}`` envelope."""

from __future__ import annotations


class AudioError(Exception):
    """A problem worth telling the caller about: bad input, missing binary,
    a limit hit. Anything else is a bug and is logged with a traceback."""


__all__ = ["AudioError"]
