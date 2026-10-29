"""Background jobs: job_start, job_status, job_stop.

execute_code waits for the program to finish, so it cannot run a dev
server, a long build or a test suite that takes ten minutes. A job runs in
exactly the same locked-down container (allowlisted image, no network by
default, read-only root, non-root, caps dropped, pids/memory/CPU limits) but
detached: job_start returns at once, job_status returns new log output since
the caller's cursor plus the state and exit code, and job_stop kills and
removes it. A supervisor enforces deadlines independently of status polling.
"""

from __future__ import annotations

import threading
import time
import uuid
import logging
import math
import atexit
from dataclasses import dataclass, field

from .config import ExecConfig
from .runner import DockerRunner, RunnerError, _oom_killed, read_logs

log = logging.getLogger(__name__)


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
    cleanup_pending: bool = False
    error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class JobManager:
    def __init__(self, runner: DockerRunner) -> None:
        self.runner = runner
        self.config: ExecConfig = runner.config
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pending = 0
        self._closed = False
        self._stop = threading.Event()
        self._supervisor = None
        atexit.register(self.close)

    def supervise(self):
        with self._lock:
            if self._closed:
                raise RunnerError("executor is shutting down")
            if self._supervisor is None:
                self._supervisor = threading.Thread(target=self._maintain,
                                                    name="hiraracode-supervisor", daemon=True)
                self._supervisor.start()

    def _maintain(self):
        while not self._stop.wait(0.25):
            try:
                for job in self.all():
                    self.refresh(job)
            except Exception:
                log.exception("job supervision failed; will retry")

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
        atexit.unregister(self.close)
        self._stop.set()
        if self._supervisor is not None:
            self._supervisor.join(timeout=5)
        for job in self.all():
            try:
                self.stop(job)
            except Exception:
                log.exception("job shutdown cleanup failed")
        self.runner.close()

    # --- lifecycle ---------------------------------------------------------------

    def start(self, *, language: str, code: str, stdin: str | None = None,
              timeout: float | None = None) -> Job:
        spec = self.config.languages.get(language)
        if spec is None:
            allowed = ", ".join(self.runner.languages()) or "(none configured)"
            raise RunnerError(f"language '{language}' is not allowed. Allowed: {allowed}")
        self.runner.validate_input(code, stdin)
        self.runner.prepare()
        self.supervise()
        self._prune()
        with self._lock:
            if self._closed:
                raise RunnerError("executor is shutting down")
            running = [j for j in self._jobs.values() if j.state == "running" or j.cleanup_pending]
            if len(running) + self._pending >= self.config.max_jobs:
                raise RunnerError(
                    f"{len(running)} jobs already running (CCODE_MAX_JOBS); stop one first")
            self._pending += 1
        container = None
        try:
            wall = self.config.job_timeout if timeout is None else float(timeout)
            if not math.isfinite(wall) or wall <= 0:
                raise RunnerError("timeout must be finite and > 0")
            wall = min(wall, self.config.job_max_timeout)
            self.runner._ensure_image(spec.image)
            kwargs = self.runner._create_kwargs(spec, code, stdin)
            job_id = uuid.uuid4().hex[:12]
            kwargs["labels"] = {**kwargs.get("labels", {}), "hiraracode-job": job_id}
            container = self.runner.client.containers.create(**kwargs)
            now = time.monotonic()
            job = Job(id=job_id, language=language, image=spec.image, container=container,
                      started=now, deadline=now + wall)
            with self._lock:
                if self._closed:
                    raise RunnerError("executor is shutting down")
                # Register before starting: shutdown cannot miss this container.
                self._jobs[job_id] = job
                container.start()
            return job
        except Exception as exc:  # noqa: BLE001
            if container is not None:
                removed = _remove(container)
                with self._lock:
                    if removed:
                        self._jobs.pop(job_id, None)
                    else:
                        self._jobs[job_id] = job
                        job.cleanup_pending = True
                        job.error = "job start failed; cleanup pending"
            raise RunnerError(f"could not start the job container: {exc}") from exc
        finally:
            with self._lock:
                self._pending -= 1

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
            if job.cleanup_pending:
                job.cleanup_pending = not _remove(job.container)
                if not job.cleanup_pending:
                    job.error = None
                    if job.state == "running":
                        job.state, job.finished = "stopped", time.monotonic()
                return
            if job.state != "running":
                return
            try:
                job.container.reload()
                status = job.container.status
            except Exception as exc:  # noqa: BLE001
                from docker.errors import NotFound
                if isinstance(exc, NotFound):
                    job.state, job.finished = "lost", time.monotonic()
                    job.error = "container no longer exists"
                else:
                    # Unknown daemon state is not proof the container stopped.
                    job.error = "Docker state unavailable; supervision will retry"
                    if time.monotonic() >= job.deadline:
                        job.cleanup_pending = not _remove(job.container)
                        if not job.cleanup_pending:
                            job.state, job.finished = "timed_out", time.monotonic()
                return
            job.error = None
            if status in ("exited", "dead"):
                job.exit_code = int(job.container.attrs.get("State", {}).get("ExitCode", -1))
                job.oom_killed = _oom_killed(job.container)
                job.state, job.finished = "exited", time.monotonic()
                self._capture(job)
            elif time.monotonic() >= job.deadline:
                try:
                    job.container.kill()
                except Exception:
                    job.error = "deadline exceeded; termination pending"
                    return
                job.state, job.finished = "timed_out", time.monotonic()
                self._capture(job)

    def stop(self, job: Job) -> None:
        with job.lock:
            if job.state == "running":
                try:
                    job.container.kill()
                except Exception:
                    if not _remove(job.container):
                        job.cleanup_pending = True
                        job.error = "stop failed; termination pending"
                        return
                job.state, job.finished = "stopped", time.monotonic()
            self._capture(job)
            job.cleanup_pending = not _remove(job.container)

    def logs(self, job: Job) -> tuple[bytes, bytes]:
        if job.final_logs is not None:
            return job.final_logs
        try:
            return (read_logs(job.container, stdout=True, limit=self.config.max_output_bytes + 1),
                    read_logs(job.container, stdout=False, limit=self.config.max_output_bytes + 1))
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
                job.final_logs = self.logs(job)
            except Exception:  # noqa: BLE001
                job.final_logs = (b"", b"")
            if self.config.remove:
                job.cleanup_pending = not _remove(job.container)
                if job.cleanup_pending:
                    job.error = "container cleanup pending"

    def _prune(self) -> None:
        cutoff = time.monotonic() - self.config.job_retention
        with self._lock:
            finished = sorted((j for j in self._jobs.values()
                               if j.finished and not j.cleanup_pending), key=lambda j: j.finished)
            stale = [j for j in finished if j.finished < cutoff]
            stale.extend(finished[:max(0, len(finished) - self.config.max_retained_jobs)])
            for job in stale:
                self._jobs.pop(job.id, None)


def _remove(container) -> bool:
    try:
        container.remove(force=True)
        return True
    except Exception as exc:  # noqa: BLE001
        from docker.errors import NotFound
        if isinstance(exc, NotFound):
            return True
        log.warning("container cleanup failed; will retry")
        return False


def snapshot(manager: JobManager, job: Job, *, stdout_cursor: int = 0,
             stderr_cursor: int = 0, limit: int = 100_000) -> dict:
    out, err = manager.logs(job)
    truncated = len(out) > manager.config.max_output_bytes or len(err) > manager.config.max_output_bytes
    out, err = out[:manager.config.max_output_bytes], err[:manager.config.max_output_bytes]
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
        "truncated": truncated,
        "cleanup_pending": job.cleanup_pending,
        "error": job.error,
    }


__all__ = ["Job", "JobManager", "snapshot"]
