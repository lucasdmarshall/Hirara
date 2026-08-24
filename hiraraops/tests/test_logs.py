"""application_logs unit tests."""

from __future__ import annotations

from hiraraops.config import OpsConfig
from hiraraops.logs import application_logs


def test_tail(tmp_path):
    f = tmp_path / "app.log"
    f.write_text("\n".join(f"line {i}" for i in range(1, 11)) + "\n", encoding="utf-8")
    r = application_logs(path=str(f), lines=3, config=OpsConfig(allow_any_path=True))
    assert r.error is None
    assert r.from_end is True
    assert [x.text for x in r.lines] == ["line 8", "line 9", "line 10"]


def test_head(tmp_path):
    f = tmp_path / "app.log"
    f.write_text("a\nb\nc\nd\n", encoding="utf-8")
    r = application_logs(
        path=str(f),
        lines=2,
        from_end=False,
        config=OpsConfig(allow_any_path=True),
    )
    assert [x.text for x in r.lines] == ["a", "b"]


def test_pattern_and_level(tmp_path):
    f = tmp_path / "app.log"
    f.write_text(
        "INFO ok\nERROR boom timeout\nWARN slow\nERROR other\n",
        encoding="utf-8",
    )
    r = application_logs(
        path=str(f),
        level="ERROR",
        pattern="timeout",
        config=OpsConfig(allow_any_path=True),
    )
    assert r.error is None
    assert len(r.lines) == 1
    assert "timeout" in r.lines[0].text
    assert r.lines[0].level == "ERROR"


def test_named_source(tmp_path):
    f = tmp_path / "svc.log"
    f.write_text("hello\n", encoding="utf-8")
    cfg = OpsConfig(
        log_sources={"svc": str(f)},
        allow_any_path=True,
    )
    r = application_logs(source="svc", config=cfg)
    assert r.error is None
    assert r.source == "svc"
    assert r.lines[0].text == "hello"


def test_roots_deny(tmp_path):
    allowed = tmp_path / "ok"
    allowed.mkdir()
    f = tmp_path / "nope.log"
    f.write_text("x\n", encoding="utf-8")
    r = application_logs(
        path=str(f),
        config=OpsConfig(roots=(str(allowed),), allow_any_path=False),
    )
    assert r.error and "outside allowed roots" in r.error


def test_missing(tmp_path):
    r = application_logs(
        path=str(tmp_path / "missing.log"),
        config=OpsConfig(allow_any_path=True),
    )
    assert r.error and "not found" in r.error


def test_bad_pattern(tmp_path):
    f = tmp_path / "a.log"
    f.write_text("x\n", encoding="utf-8")
    r = application_logs(
        path=str(f),
        pattern="(",
        config=OpsConfig(allow_any_path=True),
    )
    assert r.error and "invalid pattern" in r.error
