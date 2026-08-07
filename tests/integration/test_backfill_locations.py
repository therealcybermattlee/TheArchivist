"""Integration: scan-locations backfill against a fake archive (US1).

Covers spec acceptance scenarios for Story 1 plus SC-002 (archive bytes
untouched) via before/after hashing.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from archivist.catalog import Catalog
from archivist.scanner import backfill_locations, scan

from build_fixtures import GR_LAT, GR_LON

pytestmark = pytest.mark.usefixtures("gps_media")

TOL = 2e-4


def _hash_tree(root: Path) -> dict[str, str]:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


@pytest.fixture
def seeded(cfg, gps_media):
    """Fixture media copied into the fake archive and indexed (v3 catalog)."""
    dest = cfg.archive_root / "2024" / "06152024 - Unsorted" / "Peepaw Cell"
    dest.mkdir(parents=True)
    for name in ("located_jpg", "unlocated_jpg", "null_island_jpg",
                 "pair_heic", "pair_mov", "located_mp4"):
        shutil.copy2(gps_media[name], dest / gps_media[name].name)
    cat = Catalog(cfg.catalog_db)
    cat.init_db()
    scan(cfg.archive_root, cat, cfg.default_timezone, do_phash=False)
    # Simulate a pre-v3 archive: clear the same-pass gps outcome so the
    # backfill path (not scan) is what gets exercised.
    with cat.connect() as conn:
        conn.execute("UPDATE assets SET gps_lat=NULL, gps_lon=NULL, gps_alt=NULL, "
                     "gps_source=NULL, gps_status=NULL")
        conn.commit()
    return cat


def _row(cat: Catalog, name: str):
    with cat.connect() as conn:
        return conn.execute(
            "SELECT * FROM assets WHERE archive_path LIKE ?", (f"%{name}",)
        ).fetchone()


def test_backfill_populates_and_is_incremental(cfg, seeded, gps_media):
    before = _hash_tree(cfg.archive_root)

    res = backfill_locations(seeded)
    assert res.examined == 6
    assert res.located >= 3          # located jpg, heic (pair), mp4
    assert res.location_rejected == 1  # null island

    r = _row(seeded, "IMG_0001.JPG")
    assert r["gps_status"] == "present"
    assert abs(r["gps_lat"] - GR_LAT) < TOL and abs(r["gps_lon"] - GR_LON) < TOL
    assert r["gps_source"] == "exif"

    r = _row(seeded, "IMG_0002.JPG")
    assert r["gps_status"] == "absent" and r["gps_lat"] is None

    r = _row(seeded, "IMG_0003.JPG")
    assert r["gps_status"] == "rejected"
    assert r["gps_lat"] is None and r["gps_lon"] is None

    r = _row(seeded, "VID_0005.MP4")
    assert r["gps_status"] == "present"
    assert abs(r["gps_lat"] - GR_LAT) < TOL
    assert r["gps_source"] == "video-meta"

    # SC-002: archive bytes untouched.
    assert _hash_tree(cfg.archive_root) == before

    # Incremental: everything examined, second run touches nothing.
    res2 = backfill_locations(seeded)
    assert res2.examined == 0


def test_backfill_limit_resumes(cfg, seeded):
    res1 = backfill_locations(seeded, limit=2)
    assert res1.examined == 2
    res2 = backfill_locations(seeded)
    assert res2.examined == 4  # only the remaining rows — no re-reads
    with seeded.connect() as conn:
        left = conn.execute(
            "SELECT COUNT(*) FROM assets WHERE gps_status IS NULL"
        ).fetchone()[0]
    assert left == 0


def test_missing_file_left_unexamined(cfg, seeded):
    victim = next((cfg.archive_root.rglob("IMG_0001.JPG")))
    moved = victim.with_name("moved-away.bin")
    victim.rename(moved)
    try:
        res = backfill_locations(seeded)
        assert res.missing_files == 1
        r = _row(seeded, "IMG_0001.JPG")
        assert r["gps_status"] is None  # stays NULL for a future run
    finally:
        moved.rename(victim)
