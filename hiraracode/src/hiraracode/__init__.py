"""Hiraracode — sandboxed code execution for AI agents, via HTTP and MCP.

Runs untrusted snippets in throwaway Docker containers: no network by default,
read-only root filesystem, non-root user, dropped capabilities, and
CPU/memory/pids/time caps. The caller names a language, never an image.
"""

from .config import DEFAULT_LANGUAGES, ExecConfig, LanguageSpec
from .runner import DockerRunner, RunnerError, RunResult, build_runner
from .tools import Toolset

__all__ = [
    "DEFAULT_LANGUAGES",
    "DockerRunner",
    "ExecConfig",
    "LanguageSpec",
    "RunResult",
    "RunnerError",
    "Toolset",
    "build_runner",
]

__version__ = "0.2.0"
