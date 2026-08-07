"""Unit tests: catalog meta key-value helpers (004 pull state)."""

from pathlib import Path

from archivist.catalog import Catalog


def test_meta_roundtrip(tmp_path: Path):
    cat = Catalog(tmp_path / "c.sqlite3")
    cat.init_db()
    with cat.connect() as conn:
        assert cat.get_meta(conn, "pull_state:matt-personal") is None
        cat.set_meta(conn, "pull_state:matt-personal", "2026-07-31T12:00:00")
        assert cat.get_meta(conn, "pull_state:matt-personal") == "2026-07-31T12:00:00"
        cat.set_meta(conn, "pull_state:matt-personal", "2026-08-01T09:00:00")
        assert cat.get_meta(conn, "pull_state:matt-personal") == "2026-08-01T09:00:00"


def test_meta_keys_independent(tmp_path: Path):
    cat = Catalog(tmp_path / "c.sqlite3")
    cat.init_db()
    with cat.connect() as conn:
        cat.set_meta(conn, "pull_state:a", "1")
        cat.set_meta(conn, "pull_state:b", "2")
        assert cat.get_meta(conn, "pull_state:a") == "1"
        assert cat.get_meta(conn, "pull_state:b") == "2"
        # schema_version key untouched
        assert cat.get_meta(conn, "schema_version") == "3"
