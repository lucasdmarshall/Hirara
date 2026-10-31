import pytest


@pytest.fixture(autouse=True)
def isolate_local_connector_discovery(monkeypatch, tmp_path):
    """Unit tests must never discover a developer's real connected accounts."""
    monkeypatch.setenv("HIRARA_CONNECTOR_LOCAL_DIR", str(tmp_path / "no-local-runtime"))
