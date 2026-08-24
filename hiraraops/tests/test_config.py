"""Config defaults / env."""

from hiraraops.config import OpsConfig


def test_defaults():
    cfg = OpsConfig()
    assert cfg.default_lines == 100
    assert cfg.max_lines == 5_000
    assert cfg.allow_any_path is True
    assert cfg.allow_process_list is True
    assert cfg.max_processes == 500
    assert cfg.proc_root == "/proc"
    assert cfg.resolved_sources() == {}


def test_from_env(monkeypatch):
    monkeypatch.setenv("COPS_LOG_SOURCES", "app=/logs/app.log,web=/logs/web.log")
    monkeypatch.setenv("COPS_ROOTS", "/logs")
    monkeypatch.setenv("COPS_ALLOW_ANY_PATH", "false")
    monkeypatch.setenv("COPS_DEFAULT_LINES", "20")
    monkeypatch.setenv("COPS_MAX_LINES", "100")
    monkeypatch.setenv("COPS_MAX_BYTES", "5000")
    monkeypatch.setenv("COPS_MAX_PROCESSES", "50")
    monkeypatch.setenv("COPS_ALLOW_PROCESS_LIST", "false")
    monkeypatch.setenv("COPS_PROC_ROOT", "/tmp/fakeproc")
    cfg = OpsConfig.from_env()
    assert cfg.roots == ("/logs",)
    assert cfg.allow_any_path is False
    assert cfg.default_lines == 20
    assert cfg.max_lines == 100
    assert cfg.max_bytes == 5000
    assert cfg.max_processes == 50
    assert cfg.allow_process_list is False
    assert cfg.proc_root == "/tmp/fakeproc"
    assert cfg.resolved_sources()["app"] == "/logs/app.log"
    assert cfg.resolved_sources()["web"] == "/logs/web.log"
