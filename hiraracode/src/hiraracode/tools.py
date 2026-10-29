"""The tool layer: schema and JSON-ready results.

Both front ends (HTTP service and MCP server) call into here, so the two can
never drift apart in behaviour — only in transport.

One tool, ``execute_code``: run a snippet in a sandboxed, single-use container
and get back stdout, stderr and the exit code.
"""

from __future__ import annotations

from hirara_core.policy import tool_permission, visible_schemas

import asyncio
import logging
from dataclasses import dataclass, field

from .config import ExecConfig
from .jobs import JobManager, snapshot
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


def _job_schemas(languages: list[str]) -> list[dict]:
    listed = ", ".join(languages) if languages else "python, node, bash"
    return [
        {
            "name": "job_start",
            "description": (
                "Start a long-running program (a server, a build, a test suite, a "
                "crawl) in the same sandbox as execute_code, but in the background: "
                "it returns a job_id at once. Poll job_status for output and the "
                "exit code; job_stop ends it. Killed at its timeout (default 10 "
                f"minutes, capped by the server). Languages: {listed}."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "language": {"type": "string", "enum": languages},
                    "code": {"type": "string", "description": "Source code to run."},
                    "stdin": {"type": "string", "description": "Optional standard input."},
                    "timeout": {"type": "number", "description": "Seconds before it is killed."},
                },
                "required": ["language", "code"],
                "additionalProperties": False,
            },
        },
        {
            "name": "job_status",
            "description": (
                "Check a background job: state (running / exited / timed_out / "
                "stopped), exit code, and the stdout / stderr written since the "
                "cursors you pass (use the cursors returned last time to get only "
                "new output). Without job_id, lists all jobs."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string"},
                    "stdout_cursor": {"type": "integer", "minimum": 0},
                    "stderr_cursor": {"type": "integer", "minimum": 0},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "job_stop",
            "description": "Stop a background job, remove its container, and return its final output.",
            "input_schema": {
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
                "required": ["job_id"],
                "additionalProperties": False,
            },
        },
    ]


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
        self.jobs = JobManager(self.runner)

    @classmethod
    def from_env(cls) -> "Toolset":
        return cls(config=ExecConfig.from_env())

    @visible_schemas
    def schemas(self) -> list[dict]:
        langs = self.runner.languages()
        return [_execute_schema(langs), *_job_schemas(langs)]

    def health(self) -> dict:
        info = self.runner.info()
        status = "ok" if info["docker_reachable"] else "degraded"
        return {"status": status, "version": "0.2.0", "runner": info}

    @tool_permission('execute_code')
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


    @tool_permission('job_start')
    async def job_start(self, *, language: str, code: str, stdin: str | None = None,
                        timeout: float | None = None) -> dict:
        try:
            job = await asyncio.to_thread(self.jobs.start, language=language, code=code,
                                          stdin=stdin, timeout=timeout)
            return snapshot(self.jobs, job, limit=self.config.max_output_bytes)
        except RunnerError as exc:
            return {"job_id": None, "state": None, "language": language, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            log.exception("job_start failed")
            return {"job_id": None, "state": None, "language": language,
                    "error": f"job_start failed: {exc}"}

    @tool_permission('job_status')
    async def job_status(self, *, job_id: str | None = None, stdout_cursor: int = 0,
                         stderr_cursor: int = 0) -> dict:
        try:
            if not job_id:
                jobs = await asyncio.to_thread(self.jobs.all)
                for job in jobs:
                    await asyncio.to_thread(self.jobs.refresh, job)
                return {"jobs": [{"job_id": j.id, "language": j.language, "state": j.state,
                                  "exit_code": j.exit_code} for j in jobs], "error": None}
            job = self.jobs.get(job_id)
            await asyncio.to_thread(self.jobs.refresh, job)
            return await asyncio.to_thread(
                snapshot, self.jobs, job, stdout_cursor=max(0, int(stdout_cursor)),
                stderr_cursor=max(0, int(stderr_cursor)), limit=self.config.max_output_bytes)
        except RunnerError as exc:
            return {"job_id": job_id, "state": None, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            log.exception("job_status failed")
            return {"job_id": job_id, "state": None, "error": f"job_status failed: {exc}"}

    @tool_permission('job_stop')
    async def job_stop(self, *, job_id: str) -> dict:
        try:
            job = self.jobs.get(job_id)
            await asyncio.to_thread(self.jobs.refresh, job)
            await asyncio.to_thread(self.jobs.stop, job)
            return snapshot(self.jobs, job, limit=self.config.max_output_bytes)
        except RunnerError as exc:
            return {"job_id": job_id, "state": None, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            log.exception("job_stop failed")
            return {"job_id": job_id, "state": None, "error": f"job_stop failed: {exc}"}


__all__ = ["Toolset", "TOOL_NAMES", "call_tool", "tool_schemas"]


# --- local backend: in-process dispatch for the hirara SDK -------------------
# Discovered by the hirara SDK through the ``hirara.backends`` entry point and
# called directly (no HTTP hop). Reuses the same Toolset the service and MCP
# server use, so behaviour cannot drift between local and networked calls.
# execute_code still needs a reachable Docker daemon in this process; without
# one it returns its usual error envelope, exactly as the service would.
TOOL_NAMES = ("execute_code", "job_start", "job_status", "job_stop")
_local_toolset: "Toolset | None" = None


def _backend() -> "Toolset":
    global _local_toolset
    if _local_toolset is None:
        _local_toolset = Toolset.from_env()
    return _local_toolset


async def call_tool(name: str, arguments: dict | None = None) -> dict:
    """Run one tool in-process and return its response envelope."""
    if name not in TOOL_NAMES:
        raise KeyError(f"unknown tool: {name}")
    method = "execute" if name == "execute_code" else name
    return await getattr(_backend(), method)(**(arguments or {}))


@visible_schemas
def tool_schemas() -> list[dict]:
    return _backend().schemas()
