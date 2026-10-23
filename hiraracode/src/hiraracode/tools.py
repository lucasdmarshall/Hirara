"""The tool layer: schema and JSON-ready results.

Both front ends (HTTP service and MCP server) call into here, so the two can
never drift apart in behaviour — only in transport.

One tool, ``execute_code``: run a snippet in a sandboxed, single-use container
and get back stdout, stderr and the exit code.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from .config import ExecConfig
from .runner import DockerRunner, RunnerError, build_runner

log = logging.getLogger(__name__)


def _execute_schema(languages: list[str]) -> dict:
    listed = ", ".join(languages) if languages else "python, node, bash"
    return {
        "name": "execute_code",
        "description": (
            "Run a short program in a sandboxed, throwaway container and get "
            "back its stdout, stderr and exit code.\n\n"
            "Use this to actually *run* code rather than reason about it: check "
            "a calculation, test a snippet, parse or transform data, or verify "
            "that an example works. The sandbox has no network by default and "
            "no persistent filesystem — each call starts clean and nothing "
            "survives it, so write self-contained code that prints its "
            "results.\n\n"
            f"Available languages: {listed}. Provide the source in `code`. "
            "Optionally pass `stdin` (fed to the program's standard input) and "
            "`timeout` in seconds (clamped to the server's ceiling). A non-zero "
            "exit_code is a normal result to reason about, not a tool failure."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "language": {
                    "type": "string",
                    "enum": languages,
                    "description": "Which runtime to use.",
                },
                "code": {
                    "type": "string",
                    "description": "Source code to run. Make it self-contained and print output.",
                },
                "stdin": {
                    "type": "string",
                    "description": "Optional text fed to the program's standard input.",
                },
                "timeout": {
                    "type": "number",
                    "description": "Optional wall-clock limit in seconds (clamped to the server ceiling).",
                },
            },
            "required": ["language", "code"],
            "additionalProperties": False,
        },
    }


def _envelope(**overrides) -> dict:
    envelope = {
        "stdout": None,
        "stderr": None,
        "exit_code": None,
        "timed_out": None,
        "oom_killed": None,
        "duration": None,
        "truncated": None,
        "language": None,
        "image": None,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


@dataclass
class Toolset:
    """The execute_code tool over a shared runner and config."""

    config: ExecConfig
    runner: DockerRunner = field(init=False)

    def __post_init__(self) -> None:
        # build_runner does not connect to Docker — the client is created
        # lazily on first use — so constructing a Toolset is cheap and safe
        # even where Docker is not (yet) reachable.
        self.runner = build_runner(self.config)

    @classmethod
    def from_env(cls) -> "Toolset":
        return cls(config=ExecConfig.from_env())

    def schemas(self) -> list[dict]:
        return [_execute_schema(self.runner.languages())]

    def health(self) -> dict:
        info = self.runner.info()
        status = "ok" if info["docker_reachable"] else "degraded"
        return {"status": status, "version": "0.1.0", "runner": info}

    async def execute(
        self,
        *,
        language: str,
        code: str,
        stdin: str | None = None,
        timeout: float | None = None,
    ) -> dict:
        try:
            # The Docker SDK is blocking; keep the event loop free.
            result = await asyncio.to_thread(
                self.runner.run,
                language=language,
                code=code,
                stdin=stdin,
                timeout=timeout,
            )
            payload = result.as_dict()
            payload["error"] = None
            return payload
        except RunnerError as exc:
            return _envelope(error=str(exc), language=language)
        except Exception as exc:  # noqa: BLE001 — agent gets a body, not a 500
            log.exception("execute_code failed")
            return _envelope(error=f"execute_code failed: {exc}", language=language)


__all__ = ["Toolset", "TOOL_NAMES", "call_tool", "tool_schemas"]


# --- local backend: in-process dispatch for the hirara SDK -------------------
# Discovered by the hirara SDK through the ``hirara.backends`` entry point and
# called directly (no HTTP hop). Reuses the same Toolset the service and MCP
# server use, so behaviour cannot drift between local and networked calls.
# execute_code still needs a reachable Docker daemon in this process; without
# one it returns its usual error envelope, exactly as the service would.
TOOL_NAMES = ("execute_code",)
_local_toolset: "Toolset | None" = None


def _backend() -> "Toolset":
    global _local_toolset
    if _local_toolset is None:
        _local_toolset = Toolset.from_env()
    return _local_toolset


async def call_tool(name: str, arguments: dict | None = None) -> dict:
    """Run one tool in-process and return its response envelope."""
    if name != "execute_code":
        raise KeyError(f"unknown tool: {name}")
    return await _backend().execute(**(arguments or {}))


def tool_schemas() -> list[dict]:
    return _backend().schemas()
