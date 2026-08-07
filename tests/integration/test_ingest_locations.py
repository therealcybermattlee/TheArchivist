"""Integration: location capture through the ingest pipeline (US2)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from archivist import ingest as ing
from archivist.catalog import Catalog
from archivist.location import LocationResult
from archivist.metadata import extract_batch

from build_fixtures import GR_LAT, GR_LON

pytestmark = pytest.mark.usefixtures("gps_media")

TOL = 2e-4
DEVICE = "Peepaw Cell"


def _ingest(cfg, src_dir: Path, cat: Catalog):
    files = list(ing._iter_files(src_dir))
    plan = ing.plan(files, DEVICE, cat, cfg.archive_root, cfg.default_timezone)
    metas = extract_batch([Path(f.src) for f in plan.to_copy]) if plan.to_copy else {}
    res = ing.apply(plan, DEVICE, cat, cfg.archive_root, cfg.default_timezone,
                    "test-run", cfg.logs_dir, metas=metas)
    return plan, res


def _row(cat: Catalog, name: str):
    with cat.connect() as conn:
        return conn.execute(
            "SELECT * FROM assets WHERE archive_path LIKE ?", (f"%{name}",)
        ).fetchone()


@pytest.fixture
def source_dir(tmp_path: Path, gps_media) -> Path:
    d = tmp_path / "source"
    d.mkdir()
    for name in ("located_jpg", "unlocated_jpg", "null_island_jpg",
                 "pair_heic", "pair_mov", "located_mp4"):
        shutil.copy2(gps_media[name], d / gps_media[name].name)
    return d


def test_ingest_captures_locations(cfg, source_dir, gps_media):
    cat = Catalog(cfg.catalog_db)
    cat.init_db()
    plan, res = _ingest(cfg, source_dir, cat)
    assert res.copied == 6 and not res.failed

    # Located photo: correct coordinates, no extra operator step.
    r = _row(cat, "IMG_0001.JPG")
    assert r["gps_status"] == "present"
    assert abs(r["gps_lat"] - GR_LAT) < TOL and abs(r["gps_lon"] - GR_LON) < TOL

    # Unlocated: absent, not an error.
    assert _row(cat, "IMG_0002.JPG")["gps_status"] == "absent"

    # Null island: rejected, no coordinates stored.
    r = _row(cat, "IMG_0003.JPG")
    assert r["gps_status"] == "rejected" and r["gps_lat"] is None

    # Live-Photo pair: both members share the still's location (FR-004).
    heic, mov = _row(cat, "IMG_0004.HEIC"), _row(cat, "IMG_0004.MOV")
    assert heic["gps_status"] == "present" and mov["gps_status"] == "present"
    assert heic["gps_lat"] == mov["gps_lat"] and heic["gps_lon"] == mov["gps_lon"]
    assert mov["gps_source"] == "exif"  # supplied by the still, not the clip

    # Video ISO 6709 atom.
    r = _row(cat, "VID_0005.MP4")
    assert r["gps_status"] == "present" and r["gps_source"] == "video-meta"

    # FR-009 counters.
    assert res.located == 4  # jpg + heic + mov (group) + mp4
    assert res.location_absent == 1 and res.location_rejected == 1

    # Sources untouched.
    assert sorted(p.name for p in source_dir.iterdir()) == sorted(
        gps_media[n].name for n in ("located_jpg", "unlocated_jpg", "null_island_jpg",
                                    "pair_heic", "pair_mov", "located_mp4"))


def test_duplicate_adds_location_to_unlocated_row(cfg, tmp_path, gps_media):
    cat = Catalog(cfg.catalog_db)
    cat.init_db()
    src = tmp_path / "src1"
    src.mkdir()
    shutil.copy2(gps_media["located_jpg"], src / "IMG_0001.JPG")
    _ingest(cfg, src, cat)

    # Force the row to absent (harness only) to simulate a pre-location row.
    with cat.connect() as conn:
        conn.execute("UPDATE assets SET gps_lat=NULL, gps_lon=NULL, gps_alt=NULL, "
                     "gps_source=NULL, gps_status='absent'")
        conn.commit()

    # Re-ingest the byte-identical file: skipped as duplicate, location restored.
    src2 = tmp_path / "src2"
    src2.mkdir()
    shutil.copy2(gps_media["located_jpg"], src2 / "IMG_0001.JPG")
    plan, res = _ingest(cfg, src2, cat)
    assert res.copied == 0 and res.skipped == 1
    assert res.location_retained == 1
    r = _row(cat, "IMG_0001.JPG")
    assert r["gps_status"] == "present" and abs(r["gps_lat"] - GR_LAT) < TOL


def test_unlocated_duplicate_never_downgrades(cfg, tmp_path, gps_media):
    cat = Catalog(cfg.catalog_db)
    cat.init_db()
    src = tmp_path / "srcA"
    src.mkdir()
    shutil.copy2(gps_media["located_jpg"], src / "IMG_0001.JPG")
    _ingest(cfg, src, cat)
    before = _row(cat, "IMG_0001.JPG")
    assert before["gps_status"] == "present"

    # Byte-identical re-ingest (same embedded GPS) must leave the row located;
    # counters must not report a retention (row already present).
    src2 = tmp_path / "srcB"
    src2.mkdir()
    shutil.copy2(gps_media["located_jpg"], src2 / "IMG_0001.JPG")
    plan, res = _ingest(cfg, src2, cat)
    assert res.skipped == 1 and res.location_retained == 0
    after = _row(cat, "IMG_0001.JPG")
    assert after["gps_status"] == "present" and after["gps_lat"] == before["gps_lat"]


def test_within_batch_duplicate_single_copy(cfg, tmp_path, gps_media):
    """Two byte-identical copies in one batch: one filed, one skipped (FR-022)."""
    cat = Catalog(cfg.catalog_db)
    cat.init_db()
    src = tmp_path / "srcdup"
    src.mkdir()
    shutil.copy2(gps_media["dup_located_a"], src / "IMG_0006.JPG")
    sub = src / "copies"
    sub.mkdir()
    shutil.copy2(gps_media["dup_located_b"], sub / "IMG_0006 copy.JPG")

    plan, res = _ingest(cfg, src, cat)
    assert res.copied == 1 and res.skipped == 1  # one filed, one within-batch dup
    with cat.connect() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM assets WHERE archive_path LIKE '%IMG_0006%'"
        ).fetchone()[0]
    assert n == 1  # exactly one archived row for the content
    skipped = [f for f in plan.files if f.action == "skip-duplicate"]
    assert len(skipped) == 1 and skipped[0].dup_of is not None
