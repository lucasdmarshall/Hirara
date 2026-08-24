"""process_list unit tests against a fake /proc tree."""

from __future__ import annotations

from pathlib import Path

from hiraraops.config import OpsConfig
from hiraraops.processes import process_list


def _fake_proc(root: Path, pid: int, *, name: str, state: str, uid: int, ppid: int, cmdline: str) -> None:
    d = root / str(pid)
    d.mkdir(parents=True)
    (d / "status").write_text(
        f"Name:\t{name}\n"
        f"State:\t{state} (running)\n"
        f"Uid:\t{uid}\t{uid}\t{uid}\t{uid}\n"
        f"PPid:\t{ppid}\n",
        encoding="utf-8",
    )
    (d / "cmdline").write_bytes(cmdline.encode("utf-8").replace(b" ", b"\0") + b"\0")


def test_list_and_filter(tmp_path):
    proc = tmp_path / "proc"
    _fake_proc(proc, 1, name="init", state="S", uid=0, ppid=0, cmdline="/sbin/init")
    _fake_proc(
        proc, 42, name="python", state="R", uid=1000, ppid=1, cmdline="python app.py"
    )
    _fake_proc(
        proc, 99, name="nginx", state="S", uid=1000, ppid=1, cmdline="nginx: worker"
    )

    r = process_list(proc_root=proc, config=OpsConfig())
    assert r.error is None
    assert r.process_count == 3
    assert {p.pid for p in r.processes} == {1, 42, 99}

    filtered = process_list(pattern="python", proc_root=proc, config=OpsConfig())
    assert filtered.process_count == 1
    assert filtered.processes[0].pid == 42
    assert filtered.processes[0].cmdline == "python app.py"


def test_pid_lookup(tmp_path):
    proc = tmp_path / "proc"
    _fake_proc(proc, 7, name="sleep", state="S", uid=1000, ppid=1, cmdline="sleep 10")
    r = process_list(pid=7, proc_root=proc, config=OpsConfig())
    assert r.error is None
    assert r.process_count == 1
    assert r.processes[0].name == "sleep"


def test_max_processes_truncates(tmp_path):
    proc = tmp_path / "proc"
    for i in range(1, 6):
        _fake_proc(proc, i, name=f"p{i}", state="S", uid=1, ppid=0, cmdline=f"p{i}")
    r = process_list(max_processes=2, proc_root=proc, config=OpsConfig())
    assert r.process_count == 2
    assert r.truncated is True


def test_disabled():
    r = process_list(config=OpsConfig(allow_process_list=False))
    assert r.error and "disabled" in r.error


def test_bad_pattern(tmp_path):
    proc = tmp_path / "proc"
    proc.mkdir()
    r = process_list(pattern="(", proc_root=proc, config=OpsConfig())
    assert r.error and "invalid pattern" in r.error
