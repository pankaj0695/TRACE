import pytest

from app.container import DatasetMissing, build_container
from app.core import config
from app.core.config import Settings, db_candidates, default_db_path


def test_db_found_in_alternative_locations(tmp_path, monkeypatch):
    """A trace.db that was unzipped next to the process (not in <repo>/data) is still discovered."""
    monkeypatch.delenv("TRACE_DATA_DIR", raising=False)
    monkeypatch.setattr(config, "BACKEND_DIR", tmp_path / "repo" / "backend")
    (tmp_path / "elsewhere" / "data").mkdir(parents=True)
    db = tmp_path / "elsewhere" / "data" / "trace.db"
    db.write_bytes(b"x")
    monkeypatch.chdir(tmp_path / "elsewhere")
    assert default_db_path() == db.resolve()


def test_data_dir_env_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACE_DATA_DIR", str(tmp_path))
    assert db_candidates()[0] == (tmp_path / "trace.db").resolve()
    (tmp_path / "trace.db").write_bytes(b"x")
    assert Settings().db_path == (tmp_path / "trace.db").resolve()


def test_relative_db_path_is_anchored_to_backend_dir(monkeypatch):
    monkeypatch.setenv("TRACE_DB_PATH", "../data/trace.db")
    assert Settings().db_path == (config.BACKEND_DIR.parent / "data" / "trace.db").resolve()


def test_missing_db_gives_actionable_error(tmp_path):
    with pytest.raises(DatasetMissing, match="Searched"):
        build_container(Settings(db_path=tmp_path / "nope.db"))
    assert not (tmp_path / "nope.db").exists()  # must not silently create an empty database


def test_app_starts_degraded_without_dataset(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(Settings(db_path=tmp_path / "nope.db"))) as client:
        health = client.get("/api/health").json()
        assert health["status"] == "degraded" and "not found" in health["error"]
        assert client.get("/api/stats").status_code == 503
        assert client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 503
