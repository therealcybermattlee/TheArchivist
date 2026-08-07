"""Integration: KMZ export + status coverage from a populated catalog (US3)."""

from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest

from archivist.catalog import Catalog
from archivist.mapexport import export_kmz
from archivist.scanner import backfill_locations, scan

pytestmark = pytest.mark.usefixtures("gps_media")

KML_NS = "{http://www.opengis.net/kml/2.2}"


@pytest.fixture
def populated(cfg, gps_media):
    """Fake archive seeded, scanned, and location-backfilled."""
    d2024 = cfg.archive_root / "2024" / "06152024 - Unsorted" / "Peepaw Cell"
    d2024.mkdir(parents=True)
    for name in ("located_jpg", "unlocated_jpg", "pair_heic", "pair_mov", "located_mp4"):
        shutil.copy2(gps_media[name], d2024 / gps_media[name].name)
    cat = Catalog(cfg.catalog_db)
    cat.init_db()
    scan(cfg.archive_root, cat, cfg.default_timezone, do_phash=False)
    backfill_locations(cat, full=True)
    return cat


def _hash_tree(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_kmz_valid_and_complete(cfg, populated, tmp_path):
    archive_before = _hash_tree(cfg.archive_root)
    with populated.connect() as conn:
        rows_before = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]

    out = cfg.work_base / "exports" / "map-test.kmz"
    conn = populated.connect()
    try:
        res = export_kmz(conn, out, tmp_path / "wk")
    finally:
        conn.close()

    # Located: jpg, heic+mov (one group -> collapse expected via grouping in
    # ingest; scan-archive rows are ungrouped so both plot), mp4.
    assert res.out_path == out and out.is_file()
    assert res.exported >= 3

    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        assert "doc.kml" in names
        kml = z.read("doc.kml").decode("utf-8")
        root = ElementTree.fromstring(kml)  # well-formed XML
        placemarks = root.findall(f".//{KML_NS}Placemark")
        assert len(placemarks) == res.exported
        # Every thumbnail referenced by the KML exists inside the KMZ zip.
        for n in names:
            if n.startswith("thumbs/"):
                assert n.endswith(".jpg")
        referenced = {seg.split('"')[0] for seg in kml.split('src="')[1:]}
        assert referenced <= names
        # Year folder present.
        folders = [f.find(f"{KML_NS}name").text for f in root.findall(f".//{KML_NS}Folder")]
        assert "2024" in folders

    # Read-only: archive bytes and catalog row count unchanged.
    assert _hash_tree(cfg.archive_root) == archive_before
    with populated.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == rows_before


def test_year_and_source_filters(cfg, populated, tmp_path):
    conn = populated.connect()
    try:
        all_res = export_kmz(conn, tmp_path / "all.kmz", tmp_path / "w1")
        none_res = export_kmz(conn, tmp_path / "none.kmz", tmp_path / "w2", year="1999")
        src_res = export_kmz(conn, tmp_path / "src.kmz", tmp_path / "w3",
                             source="No Such Source")
    finally:
        conn.close()
    assert all_res.exported >= 3
    assert none_res.exported == 0 and none_res.out_path is None  # nothing written
    assert not (tmp_path / "none.kmz").exists()
    assert src_res.exported == 0


def test_status_coverage_counts(cfg, populated):
    cov = populated.location_coverage()
    o = cov["overall"]
    assert o["present"] >= 3      # jpg, heic, mp4 (+ mov via group pass)
    assert o["absent"] >= 1       # unlocated jpg (+ possibly mov)
    assert o["unexamined"] == 0   # full backfill ran
    assert "2024" in cov["by_year"]
    y = cov["by_year"]["2024"]
    assert sum(y.values()) == 5
