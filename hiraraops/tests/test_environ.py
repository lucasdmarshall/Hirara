"""environment_read unit tests."""

from __future__ import annotations

from pathlib import Path

from hiraraops.config import OpsConfig
from hiraraops.environ import environment_read


def test_self_environ():
    r = environment_read(
        environ={"FOO": "bar", "API_TOKEN": "secret", "PATH": "/bin"},
        config=OpsConfig(),
    )
    assert r.error is None
    assert r.source == "self"
    assert r.variables["FOO"] == "bar"
    assert r.variables["API_TOKEN"] == "***"
    assert "API_TOKEN" in r.redacted_keys
    assert r.variables["PATH"] == "/bin"


def test_keys_and_pattern_filter():
    env = {"ALPHA": "1", "BETA": "2", "GAMMA_SECRET": "x"}
    r = environment_read(
        environ=env,
        keys=["ALPHA", "GAMMA_SECRET"],
        config=OpsConfig(),
    )
    assert set(r.keys) == {"ALPHA", "GAMMA_SECRET"}
    assert r.variables["GAMMA_SECRET"] == "***"

    r2 = environment_read(
        environ=env,
        pattern=r"^B",
        config=OpsConfig(),
    )
    assert r2.keys == ["BETA"]
    assert r2.variables["BETA"] == "2"


def test_include_values_false():
    r = environment_read(
        environ={"A": "1", "B": "2"},
        include_values=False,
        config=OpsConfig(redact_env=False),
    )
    assert r.error is None
    assert r.keys == ["A", "B"]
    assert r.variables == {}


def test_redact_override_and_disabled():
    env = {"DB_PASSWORD": "pw", "OK": "yes"}
    r = environment_read(environ=env, redact=False, config=OpsConfig(redact_env=True))
    assert r.variables["DB_PASSWORD"] == "pw"
    assert r.redacted_keys == []

    disabled = environment_read(
        environ=env, config=OpsConfig(allow_environment_read=False)
    )
    assert disabled.error is not None
    assert "disabled" in disabled.error


def test_proc_environ(tmp_path: Path):
    proc = tmp_path / "42"
    proc.mkdir()
    (proc / "environ").write_bytes(b"HOME=/tmp\0SECRET_TOKEN=abc\0")
    r = environment_read(
        pid=42,
        proc_root=tmp_path,
        config=OpsConfig(),
    )
    assert r.error is None
    assert r.source == "proc"
    assert r.pid == 42
    assert r.variables["HOME"] == "/tmp"
    assert r.variables["SECRET_TOKEN"] == "***"


def test_proc_missing(tmp_path: Path):
    r = environment_read(pid=99999, proc_root=tmp_path, config=OpsConfig())
    assert r.error is not None
    assert "not found" in r.error


def test_truncation_and_invalid_pattern():
    env = {f"K{i}": str(i) for i in range(10)}
    r = environment_read(
        environ=env,
        max_vars=3,
        config=OpsConfig(redact_env=False),
    )
    assert r.truncated is True
    assert r.variable_count == 3

    bad = environment_read(environ=env, pattern="(", config=OpsConfig())
    assert bad.error is not None
    assert "invalid pattern" in bad.error
