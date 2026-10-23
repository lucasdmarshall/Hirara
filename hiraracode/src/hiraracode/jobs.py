"""Background jobs: job_start, job_status, job_stop.

execute_code waits for the program to finish, so it cannot run a dev
server, a long build or a test suite that takes ten minutes. A job runs in
exactly the same locked-down container (allowlisted image, no network by
default, read-only root, non-root, caps dropped, pids/memory/CPU limits) but
detached: job_start returns at once, job_status returns new log output since
the caller's cursor plus the state and exit code, and job_stop kills and
removes it. A job past its wall-clock limit is killed on the next status.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

from .config import ExecConfig
from .runner import DockerRunner, RunnerError, _oom_killed, _safe_kill


@dataclass
class Job:
    id: str
    language: str
    image: str
    container: object
    started: float
    deadline: float
    state: str = "running"  # running | exited | timed_out | stopped | lost
    exit_code: int | None = None
    oom_killed: bool = False
    finished: float | None = None
    final_logs: tuple[bytes, bytes] | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class JobManager:
    def __init__(self, runner: DockerRunner) -> None:
        self.runner = runner
        self.config: ExecConfig = runner.config
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    # --- lifecycle ---------------------------------------------------------------

    def start(self, *, language: str, code: str, stdin: str | None = None,
              timeout: float | None = None) -> Job:
        spec = self.config.languages.get(language)
        if spec is None:
            allowed = ", ".join(self.runner.languages()) or "(none configured)"
            raise RunnerError(f"language '{language}' is not allowed. Allowed: {allowed}")
        if not code or not code.strip():
            raise RunnerError("code is empty")
        self._prune()
        with self._lock:
            running = [j for j in self._jobs.values() if j.state == "running"]
            if len(running) >= self.config.max_jobs:
                raise RunnerError(
                    f"{len(running)} jobs already running (CCODE_MAX_JOBS); stop one first")
        wall = self.config.job_timeout if timeout is None else max(1.0, float(timeout))
        wall = min(wall, self.config.job_max_timeout)

        self.runner._ensure_image(spec.image)
        kwargs = self.runner._create_kwargs(spec, code, stdin)
        job_id = uuid.uuid4().hex[:12]
        kwargs["labels"] = {**kwargs.get("labels", {}), "hiraracode-job": job_id}
        container = self.runner.client.containers.create(**kwargs)
        try:
            container.start()
        except Exception as exc:  # noqa: BLE001
            _remove(container)
            raise RunnerError(f"could not start the job container: {exc}") from exc
        now = time.monotonic()
        job = Job(id=job_id, language=language, image=spec.image, container=container,
                  started=now, deadline=now + wall)
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get(self, job_id: str | None) -> Job:
        if not job_id:
            raise RunnerError("job_id is required")
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise RunnerError(f"unknown job_id: {job_id}")
        return job

    def refresh(self, job: Job) -> None:
        """Update state from the daemon; enforce the wall-clock limit."""
        with job.lock:
            if job.state != "running":
                return
            try:
                job.container.reload()
                status = job.container.status
            except Exception:  # noqa: BLE001 — container vanished underneath us
                job.state, job.finished = "lost", time.monotonic()
                return
            if status in ("exited", "dead"):
                job.exit_code = int(job.container.attrs.get("State", {}).get("ExitCode", -1))
                job.oom_killed = _oom_killed(job.container)
                job.state, job.finished = "exited", time.monotonic()
                self._capture(job)
            elif time.monotonic() >= job.deadline:
                _safe_kill(job.container)
                job.state, job.finished = "timed_out", time.monotonic()
                self._capture(job)

    def stop(self, job: Job) -> None:
        with job.lock:
            if job.state == "running":
                _safe_kill(job.container)
                job.state, job.finished = "stopped", time.monotonic()
            self._capture(job)
            _remove(job.container)

    def logs(self, job: Job) -> tuple[bytes, bytes]:
        if job.final_logs is not None:
            return job.final_logs
        try:
            return (job.container.logs(stdout=True, stderr=False),
                    job.container.logs(stdout=False, stderr=True))
        except Exception:  # noqa: BLE001
            return b"", b""

    def all(self) -> list[Job]:
        self._prune()
        with self._lock:
            return list(self._jobs.values())

    # --- internals ---------------------------------------------------------------

    def _capture(self, job: Job) -> None:
        """Keep the final logs in memory so the container can be removed."""
        if job.final_logs is None:
            try:
                job.final_logs = (job.container.logs(stdout=True, stderr=False),
                                  job.container.logs(stdout=False, stderr=True))
            except Exception:  # noqa: BLE001
                job.final_logs = (b"", b"")
            if self.config.remove:
                _remove(job.container)

    def _prune(self) -> None:
        cutoff = time.monotonic() - self.config.job_retention
        with self._lock:
            stale = [j for j in self._jobs.values() if j.finished and j.finished < cutoff]
            for job in stale:
                self._jobs.pop(job.id, None)


def _remove(container) -> None:
    try:
        container.remove(force=True)
    except Exception:  # noqa: BLE001 — best effort
        pass


def snapshot(manager: JobManager, job: Job, *, stdout_cursor: int = 0,
             stderr_cursor: int = 0, limit: int = 100_000) -> dict:
    out, err = manager.logs(job)
    new_out, new_err = out[stdout_cursor:], err[stderr_cursor:]
    more = len(new_out) > limit or len(new_err) > limit
    new_out, new_err = new_out[:limit], new_err[:limit]
    now = job.finished or time.monotonic()
    return {
        "job_id": job.id,
        "language": job.language,
        "image": job.image,
        "state": job.state,
        "running": job.state == "running",
        "exit_code": job.exit_code,
        "oom_killed": job.oom_killed,
        "elapsed": round(now - job.started, 1),
        "time_left": round(max(0.0, job.deadline - time.monotonic()), 1) if job.state == "running" else 0,
        "stdout": new_out.decode("utf-8", "replace"),
        "stderr": new_err.decode("utf-8", "replace"),
        "stdout_cursor": stdout_cursor + len(new_out),
        "stderr_cursor": stderr_cursor + len(new_err),
        "more_output": more,
        "error": None,
    }


__all__ = ["Job", "JobManager", "snapshot"]
