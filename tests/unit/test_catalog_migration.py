"""Unit tests: v2 -> v3 catalog migration and location-preserving writes."""

import sqlite3
from pathlib import Path

from archivist.catalog import Catalog
from archivist.location import LocationResult

# The v2 schema as it shipped (no gps_* columns), for building legacy DBs.
_V2_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE assets (
    id              INTEGER PRIMARY KEY,
    quick_hash      TEXT,
    content_hash    TEXT,
    source_label    TEXT,
    original_path   TEXT,
    archive_path    TEXT,
    asset_group_id  TEXT,
    ingested_at     TEXT,
    run_manifest_id TEXT,
    capture_dt      TEXT,
    date_source     TEXT,
    confidence      TEXT,
    phash           TEXT,
    width           INTEGER,
    height          INTEGER,
    file_size       INTEGER,
    duration        REAL,
    camera_make     TEXT,
    camera_model    TEXT,
    mime_type       TEXT
);
CREATE UNIQUE INDEX idx_assets_arcpath
    ON assets(archive_path) WHERE archive_path IS NOT NULL;
"""


def _make_v2_db(path: Path, rows: int = 3) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(_V2_SCHEMA)
    conn.execute("INSERT INTO meta(key, value) VALUES('schema_version', '2')")
    for i in range(rows):
        conn.execute(
            "INSERT INTO assets(archive_path, capture_dt, confidence) VALUES(?, ?, 'high')",
            (f"/archive/2024/f{i}.jpg", "2024-06-01T12:00:00"),
        )
    conn.commit()
    conn.close()


def test_v2_migrates_in_place(tmp_path: Path):
    db = tmp_path / "cat.sqlite3"
    _make_v2_db(db, rows=3)
    cat = Catalog(db)
    with cat.connect() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(assets)")}
        assert {"gps_lat", "gps_lon", "gps_alt", "gps_source", "gps_status"} <= cols
        # Existing rows intact, location columns NULL (= never examined).
        rows = list(conn.execute("SELECT archive_path, gps_status FROM assets"))
        assert len(rows) == 3
        assert all(r["gps_status"] is None for r in rows)
        ver = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        assert ver[0] == "3"


def test_migration_idempotent(tmp_path: Path):
    db = tmp_path / "cat.sqlite3"
    _make_v2_db(db)
    cat = Catalog(db)
    cat.connect().close()
    cat.connect().close()  # second connect must not fail on existing columns
    assert cat.stats().schema_version == 3


def test_set_location_examines_null_row(tmp_path: Path):
    db = tmp_path / "cat.sqlite3"
    _make_v2_db(db, rows=1)
    cat = Catalog(db)
    with cat.connect() as conn:
        loc = LocationResult("present", lat=42.9, lon=-85.6, alt=200.0, source="exif")
        assert cat.set_location(conn, 1, loc) is True
        row = conn.execute("SELECT gps_lat, gps_status FROM assets WHERE id=1").fetchone()
        assert row["gps_status"] == "present" and row["gps_lat"] == 42.9


def test_set_location_never_downgrades_present(tmp_path: Path):
    db = tmp_path / "cat.sqlite3"
    _make_v2_db(db, rows=1)
    cat = Catalog(db)
    with cat.connect() as conn:
        cat.set_location(conn, 1, LocationResult("present", lat=1.0, lon=2.0, source="exif"))
        assert cat.set_location(conn, 1, LocationResult("absent")) is False
        row = conn.execute("SELECT gps_lat, gps_status FROM assets WHERE id=1").fetchone()
        assert row["gps_status"] == "present" and row["gps_lat"] == 1.0
        # present -> present (re-examination) is allowed
        assert cat.set_location(conn, 1, LocationResult("present", lat=3.0, lon=4.0, source="exif"))
        assert conn.execute("SELECT gps_lat FROM assets WHERE id=1").fetchone()[0] == 3.0


def test_upsert_without_location_preserves_stored(tmp_path: Path):
    db = tmp_path / "cat.sqlite3"
    _make_v2_db(db, rows=1)
    cat = Catalog(db)
    with cat.connect() as conn:
        cat.set_location(conn, 1, LocationResult("present", lat=42.9, lon=-85.6, source="exif"))
        # A writer with no location info (e.g. an older code path) must not clobber.
        cat.upsert_by_archive_path(conn, {
            "archive_path": "/archive/2024/f0.jpg",
            "capture_dt": "2024-06-01T12:00:00",
            "confidence": "high",
        })
        row = conn.execute(
            "SELECT gps_lat, gps_status FROM assets WHERE archive_path='/archive/2024/f0.jpg'"
        ).fetchone()
        assert row["gps_status"] == "present" and row["gps_lat"] == 42.9


def test_rows_missing_location_incremental(tmp_path: Path):
    db = tmp_path / "cat.sqlite3"
    _make_v2_db(db, rows=3)
    cat = Catalog(db)
    with cat.connect() as conn:
        assert len(cat.rows_missing_location(conn)) == 3
        cat.set_location(conn, 1, LocationResult("absent"))
        assert len(cat.rows_missing_location(conn)) == 2
        assert len(cat.rows_missing_location(conn, full=True)) == 3
        assert len(cat.rows_missing_location(conn, limit=1)) == 1
