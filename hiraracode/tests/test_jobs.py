"""job_start / job_status / job_stop against a fake Docker client."""

from __future__ import annotations

import time

import pytest

from hiraracode.config import ExecConfig
from hiraracode.runner import build_runner
from hiraracode.tools import TOOL_NAMES, Toolset


class JobContainer:
    """Running until ``finish_after`` reloads, emitting a line per reload."""

    def __init__(self, finish_after: int | None, exit_code: int = 0) -> None:
        self.finish_after = finish_after
        self.exit_code = exit_code
        self.reloads = 0
        self.status = "created"
        self.out = b""
        self.err = b""
        self.killed = self.removed = False
        self.attrs = {"State": {"ExitCode": None, "OOMKilled": False}}

    def start(self):
        self.status = "running"

    def reload(self):
        if self.removed:
            raise RuntimeError("no such container")
        if self.status != "running":
            return
        self.reloads += 1
        self.out += f"line {self.reloads}\n".encode()
        if self.finish_after is not None and self.reloads >= self.finish_after:
            self.status = "exited"
            self.err += b"done\n"
            self.attrs["State"]["ExitCode"] = self.exit_code

    def logs(self, stdout=False, stderr=False):
        return self.out if stdout else self.err

    def kill(self):
        self.killed = True
        self.status = "exited"
        self.attrs["State"]["ExitCode"] = 137

    def remove(self, force=False):
        self.removed = True


class Images:
    def get(self, image):
        return object()


class Containers:
    def __init__(self, factory):
        self.factory = factory
        self.created: list[dict] = []
        self.made: list[JobContainer] = []

    def create(self, **kwargs):
        self.created.append(kwargs)
        c = self.factory()
        self.made.append(c)
        return c


class Client:
    def __init__(self, factory):
        self.images = Images()
        self.containers = Containers(factory)


def toolset(factory, **cfg) -> tuple[Toolset, Client]:
    ts = Toolset(ExecConfig(**cfg))
    client = Client(factory)
    ts.runner = build_runner(ts.config, client=client)
    from hiraracode.jobs import JobManager

    ts.jobs = JobManager(ts.runner)
    return ts, client


async def test_job_runs_in_the_same_locked_down_sandbox():
    ts, client = toolset(lambda: JobContainer(finish_after=3))
    r = await ts.job_start(language="python", code="print(1)")
    assert r["error"] is None and r["state"] == "running" and r["job_id"]
    kw = client.containers.created[0]
    assert kw["network_disabled"] is True and kw["read_only"] is True
    assert kw["cap_drop"] == ["ALL"] and kw["user"] == "65534:65534"
    assert kw["labels"]["hiraracode-job"] == r["job_id"]


async def test_status_streams_new_output_with_cursors_then_exit():
    ts, client = toolset(lambda: JobContainer(finish_after=3, exit_code=2))
    job = await ts.job_start(language="python", code="x")
    s1 = await ts.job_status(job_id=job["job_id"])
    assert s1["stdout"] == "line 1\n" and s1["running"] is True
    s2 = await ts.job_status(job_id=job["job_id"], stdout_cursor=s1["stdout_cursor"])
    assert s2["stdout"] == "line 2\n"
    s3 = await ts.job_status(job_id=job["job_id"], stdout_cursor=s2["stdout_cursor"])
    assert s3["state"] == "exited" and s3["exit_code"] == 2
    assert s3["stdout"] == "line 3\n" and s3["stderr"] == "done\n"
    assert client.containers.made[0].removed is True
    # Logs survive the container's removal.
    again = await ts.job_status(job_id=job["job_id"])
    assert again["stdout"] == "line 1\nline 2\nline 3\n"


async def test_timeout_kills_the_job():
    ts, client = toolset(lambda: JobContainer(finish_after=None))
    job = await ts.job_start(language="python", code="x", timeout=1)
    ts.jobs.get(job["job_id"]).deadline = time.monotonic() - 1
    s = await ts.job_status(job_id=job["job_id"])
    assert s["state"] == "timed_out" and client.containers.made[0].killed


async def test_stop_list_and_limits():
    ts, client = toolset(lambda: JobContainer(finish_after=None), max_jobs=1)
    job = await ts.job_start(language="python", code="x")
    second = await ts.job_start(language="python", code="y")
    assert "CCODE_MAX_JOBS" in second["error"]
    listed = await ts.job_status()
    assert [j["job_id"] for j in listed["jobs"]] == [job["job_id"]]
    stopped = await ts.job_stop(job_id=job["job_id"])
    assert stopped["state"] == "stopped"
    assert client.containers.made[0].killed and client.containers.made[0].removed
    third = await ts.job_start(language="python", code="z")
    assert third["error"] is None


async def test_job_errors():
    ts, _ = toolset(lambda: JobContainer(finish_after=1))
    assert "not allowed" in (await ts.job_start(language="cobol", code="x"))["error"]
    assert "empty" in (await ts.job_start(language="python", code=" "))["error"]
    assert "unknown job_id" in (await ts.job_status(job_id="nope"))["error"]


def test_tool_names_and_schemas():
    assert TOOL_NAMES == ("execute_code", "job_start", "job_status", "job_stop")
    ts = Toolset(ExecConfig())
    assert [s["name"] for s in ts.schemas()] == list(TOOL_NAMES)
