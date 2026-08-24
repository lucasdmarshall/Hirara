"""Config defaults / env."""

from hirarautil.config import UtilConfig


def test_defaults():
    cfg = UtilConfig()
    assert cfg.max_input_chars == 1_000_000
    assert cfg.max_output_bytes == 2_000_000


def test_from_env(monkeypatch):
    monkeypatch.setenv("CUTIL_MAX_INPUT_CHARS", "100")
    monkeypatch.setenv("CUTIL_MAX_OUTPUT_BYTES", "50")
    cfg = UtilConfig.from_env()
    assert cfg.max_input_chars == 100
    assert cfg.max_output_bytes == 50
