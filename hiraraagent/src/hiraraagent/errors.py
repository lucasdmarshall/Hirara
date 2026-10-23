"""The one error type tools turn into an ``{"error": ...}`` envelope."""

from __future__ import annotations


class AgentError(Exception):
    """A problem worth telling the caller about: bad input, unknown id, a limit."""


__all__ = ["AgentError"]
