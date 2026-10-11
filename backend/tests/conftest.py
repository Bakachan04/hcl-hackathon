import pytest

from app import config


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Point the store at a fresh SQLite file for one test."""
    path = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    return path
