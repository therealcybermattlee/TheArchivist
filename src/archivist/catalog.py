"""SQLite catalog — the derived index of archived assets.

Not the source of truth: the files + JSON run manifests are authoritative, and
the whole catalog is rebuildable via `scan-archive`. One row per archived file.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS assets (
    id              INTEGER PRIMARY KEY,
    -- identity & state
    quick_hash      TEXT,           -- size + head/tail; cheap dedup-candidate key
    content_hash    TEXT,           -- full sha256; computed lazily (dedup/ingest)
    source_label    TEXT,
    original_path   TEXT,
    archive_path    TEXT,
    asset_group_id  TEXT,
    ingested_at     TEXT,
    run_manifest_id TEXT,
    -- date
    capture_dt      TEXT,
    date_source     TEXT,   -- exif | sidecar | filename | mtime
    confidence      TEXT,   -- high | medium | low
    -- comparison metadata (for similarity, not just exact match)
    phash           TEXT,
    width           INTEGER,
    height          INTEGER,
    file_size       INTEGER,
    duration        REAL,
    camera_make     TEXT,
    camera_model    TEXT,
    mime_type       TEXT,
    -- capture location (v3): NULL gps_status = never examined
    gps_lat         REAL,
    gps_lon         REAL,
    gps_alt         REAL,
    gps_source      TEXT,   -- exif | video-meta | sidecar
    gps_status      TEXT    -- present | absent | rejected
);

CREATE INDEX IF NOT EXISTS idx_assets_quick  ON assets(quick_hash);
CREATE INDEX IF NOT EXISTS idx_assets_hash   ON assets(content_hash);
CREATE INDEX IF NOT EXISTS idx_assets_phash  ON assets(phash);
CREATE INDEX IF NOT EXISTS idx_assets_group  ON assets(asset_group_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_assets_arcpath
    ON assets(archive_path) WHERE archive_path IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_assets_gps_status ON assets(gps_status);
"""

ASSET_COLUMNS = (
    "quick_hash", "content_hash", "source_label", "original_path", "archive_path",
    "asset_group_id", "ingested_at", "run_manifest_id",
    "capture_dt", "date_source", "confidence",
    "phash", "width", "height", "file_size", "duration",
    "camera_make", "camera_model", "mime_type",
    "gps_lat", "gps_lon", "gps_alt", "gps_source", "gps_status",
)

GPS_COLUMNS = ("gps_lat", "gps_lon", "gps_alt", "gps_source", "gps_status")

# v2 -> v3: purely additive; NULL gps_status marks rows as never examined.
_MIGRATE_V3 = [
    "ALTER TABLE assets ADD COLUMN gps_lat REAL",
    "ALTER TABLE assets ADD COLUMN gps_lon REAL",
    "ALTER TABLE assets ADD COLUMN gps_alt REAL",
    "ALTER TABLE assets ADD COLUMN gps_source TEXT",
    "ALTER TABLE assets ADD COLUMN gps_status TEXT",
    "CREATE INDEX IF NOT EXISTS idx_assets_gps_status ON assets(gps_status)",
]


@dataclass
class CatalogStats:
    total: int
    by_confidence: dict[str, int]
    by_source: dict[str, int]
    schema_version: int


class Catalog:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        self._migrate(conn)
        return conn

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Run additive schema migrations on an existing database."""
        has_assets = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='assets'"
        ).fetchone()
        if not has_assets:
            return
        cols = {r[1] for r in conn.execute("PRAGMA table_info(assets)")}
        if "gps_status" not in cols:
            for stmt in _MIGRATE_V3:
                conn.execute(stmt)
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )

    def exists(self) -> bool:
        return self.db_path.is_file()

    def stats(self) -> CatalogStats:
        if not self.exists():
            return CatalogStats(0, {}, {}, SCHEMA_VERSION)
        with self.connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
            by_conf = {
                row[0] or "unknown": row[1]
                for row in conn.execute(
                    "SELECT confidence, COUNT(*) FROM assets GROUP BY confidence"
                )
            }
            by_src = {
                row[0] or "unknown": row[1]
                for row in conn.execute(
                    "SELECT source_label, COUNT(*) FROM assets GROUP BY source_label"
                )
            }
            ver_row = conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()
            ver = int(ver_row[0]) if ver_row else SCHEMA_VERSION
        return CatalogStats(total, by_conf, by_src, ver)

    def has_hash(self, content_hash: str) -> bool:
        if not self.exists():
            return False
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM assets WHERE content_hash = ? LIMIT 1",
                (content_hash,),
            ).fetchone()
        return row is not None

    def paths_for_quick_hash(self, conn: sqlite3.Connection, quick_hash: str) -> list[str]:
        """Archive paths already holding this quick_hash (dedup-skip candidates)."""
        return [
            r[0] for r in conn.execute(
                "SELECT archive_path FROM assets WHERE quick_hash=? AND archive_path IS NOT NULL",
                (quick_hash,),
            )
        ]

    def rows_for_quick_hash(self, conn: sqlite3.Connection, quick_hash: str):
        """Archived (path, content_hash, file_size) sharing this quick_hash.

        Carries the recorded full hash and size so a duplicate check can be
        settled without re-reading the archived bytes over the network (005,
        constitution Principle III as amended 2026-09-28).
        """
        return [
            (r[0], r[1], r[2]) for r in conn.execute(
                "SELECT archive_path, content_hash, file_size FROM assets "
                "WHERE quick_hash=? AND archive_path IS NOT NULL",
                (quick_hash,),
            )
        ]

    def upsert_by_archive_path(self, conn: sqlite3.Connection, record: dict) -> None:
        """Insert or replace the row for record['archive_path'].

        GPS columns are location-preserving: a writer that carries no location
        info (gps_status NULL) leaves the stored location alone, and a stored
        `present` location is never downgraded by absent/rejected evidence.
        """
        cols = ", ".join(ASSET_COLUMNS)
        placeholders = ", ".join("?" for _ in ASSET_COLUMNS)
        updates = []
        for c in ASSET_COLUMNS:
            if c == "archive_path":
                continue
            if c in GPS_COLUMNS:
                updates.append(
                    f"{c}=CASE "
                    f"WHEN excluded.gps_status IS NULL THEN {c} "
                    f"WHEN gps_status='present' AND excluded.gps_status<>'present' THEN {c} "
                    f"ELSE excluded.{c} END"
                )
            else:
                updates.append(f"{c}=excluded.{c}")
        values = [record.get(c) for c in ASSET_COLUMNS]
        conn.execute(
            f"INSERT INTO assets ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(archive_path) WHERE archive_path IS NOT NULL "
            f"DO UPDATE SET {', '.join(updates)}",
            values,
        )

    # ---- meta key-value helpers (pull state etc., 004) ------------------

    def get_meta(self, conn: sqlite3.Connection, key: str) -> str | None:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    # ---- location (v3) helpers ----------------------------------------

    def rows_missing_location(
        self, conn: sqlite3.Connection, full: bool = False, limit: int | None = None
    ) -> list[sqlite3.Row]:
        """Rows to examine for location: never-examined (NULL), or all with full."""
        where = "" if full else "WHERE gps_status IS NULL"
        sql = (
            "SELECT id, archive_path, asset_group_id, mime_type "
            f"FROM assets {where} ORDER BY id"
        )
        if limit:
            sql += f" LIMIT {int(limit)}"
        return list(conn.execute(sql))

    def set_location(self, conn: sqlite3.Connection, asset_id: int, loc) -> bool:
        """Record a LocationResult on a row. Never downgrades `present`.

        Returns True if the row was updated.
        """
        cur = conn.execute(
            "UPDATE assets SET gps_lat=?, gps_lon=?, gps_alt=?, gps_source=?, gps_status=? "
            "WHERE id=? AND NOT (COALESCE(gps_status,'')='present' AND ?<>'present')",
            (loc.lat, loc.lon, loc.alt, loc.source, loc.status, asset_id, loc.status),
        )
        return cur.rowcount > 0

    def location_coverage(self) -> dict:
        """Coverage counts: overall, by capture year, by source. Catalog-only."""
        empty = {"present": 0, "absent": 0, "rejected": 0, "unexamined": 0}
        out = {"overall": dict(empty), "by_year": {}, "by_source": {}}
        if not self.exists():
            return out
        with self.connect() as conn:
            for key, expr in (("by_year", "substr(capture_dt, 1, 4)"),
                              ("by_source", "COALESCE(source_label, 'unknown')")):
                rows = conn.execute(
                    f"SELECT {expr}, COALESCE(gps_status, 'unexamined'), COUNT(*) "
                    f"FROM assets GROUP BY 1, 2"
                )
                for bucket, status, n in rows:
                    b = out[key].setdefault(bucket or "unknown", dict(empty))
                    b[status] = b.get(status, 0) + n
                    out["overall"][status] = out["overall"].get(status, 0) + (n if key == "by_year" else 0)
        return out
