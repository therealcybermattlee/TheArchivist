"""Integration: the ingest -> prune chain that can destroy the only good copy.

The 2026-09-28 Principle III amendment reasoned that "skipping wrongly costs a
copy that still exists in staging". That premise was FALSE in this codebase:
`prune-staging` is what empties staging, and its primary branch classified a
staged file as deletable using the catalog's recorded hash plus an existence
check on the archived file — never reading the archived bytes.

So the chain was: archived file rots in place at the same size -> ingest settles
the duplicate from the catalog and skips -> prune matches the same catalog row,
sees the file exists, and deletes the staged good copy. Only copy gone, nothing
printed.

The byte guarantee now lives at the unlink, where Principle I's carve-out always
said it belonged ("a byte-verified archived copy confirmed present at that
moment"). These tests pin the whole chain, not just its halves.
"""

from __future__ import annotations

import pytest

from archivist import ingest as ing, staging as st
from archivist.catalog import Catalog
from archivist.hashing import quick_hash, sha256_file

GOOD = b"irreplaceable photograph bytes " * 500


@pytest.fixture
def world(fake_volumes, cfg, monkeypatch):
    """A staged file, its archived twin, and a catalog row describing them."""
    monkeypatch.setattr(ing, "extract_batch", lambda paths: {})
    arc_dir = cfg.archive_root / "2026" / "09202026 - Unsorted" / "Peepaw Cell"
    arc_dir.mkdir(parents=True)
    archived = arc_dir / "IMG_1.JPG"
    archived.write_bytes(GOOD)

    staged = cfg.staging_dir / "icloud" / "peepaw-cell" / "IMG_1.JPG"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(GOOD)

    cat = Catalog(cfg.catalog_db)
    cat.init_db()
    with cat.connect() as conn:
        cat.upsert_by_archive_path(conn, {
            "quick_hash": quick_hash(archived), "content_hash": sha256_file(archived),
            "source_label": "Peepaw Cell", "original_path": "x",
            "archive_path": str(archived), "asset_group_id": None,
            "ingested_at": "2026-08-01T00:00:00", "run_manifest_id": "r",
            "capture_dt": "2026-09-20T10:00:00", "date_source": "exif",
            "confidence": "high", "phash": None, "width": None, "height": None,
            "file_size": archived.stat().st_size, "duration": None,
            "camera_make": None, "camera_model": None, "mime_type": "image/jpeg",
            "gps_lat": None, "gps_lon": None, "gps_alt": None,
            "gps_source": None, "gps_status": "absent",
        })
        conn.commit()
    return {"cfg": cfg, "cat": cat, "archived": archived, "staged": staged}


def rot_in_place(path):
    """Corrupt bytes without changing length — the case the sample can miss."""
    data = bytearray(path.read_bytes())
    data[11] ^= 0xFF
    path.write_bytes(bytes(data))


# --- the chain, end to end -------------------------------------------------

def test_rotted_archive_does_not_cost_the_staged_copy(world):
    """THE data-loss path. Even when ingest is fooled, the delete must refuse."""
    rot_in_place(world["archived"])

    # Ingest, default path (no verify_archive): the catalog still records the
    # good hash and the right size, so the skip decision IS fooled.
    plan = ing.plan([world["staged"]], "Peepaw Cell", world["cat"],
                    world["cfg"].archive_root, "America/Detroit",
                    spot_check_rate=0.0001)
    assert [f.action for f in plan.files] == ["skip-duplicate"]

    # Prune still classifies it deletable from the same catalog...
    p = st.plan(world["cfg"], world["cat"])
    assert [i.status for i in p.items] == [st.VERIFIED]

    # ...but the unlink re-reads the archived bytes and refuses.
    res = st.apply(p, world["cfg"], "testrun")
    assert res.deleted == 0
    assert res.refused.get(st.ARCHIVE_MISMATCH) == 1
    assert world["staged"].is_file()              # the good copy survives
    assert "scan-archive" in res.errors[0][1]


def test_healthy_pair_still_prunes(world):
    """The guard must not make prune refuse everything."""
    p = st.plan(world["cfg"], world["cat"])
    assert [i.status for i in p.items] == [st.VERIFIED]
    res = st.apply(p, world["cfg"], "testrun")
    assert res.deleted == 1
    assert not world["staged"].exists()
    assert res.refused == {}


def test_deleted_file_is_journaled_before_the_unlink(world):
    res = st.apply(st.plan(world["cfg"], world["cat"]), world["cfg"], "testrun")
    entries = res.manifest_path.read_text().strip().splitlines()
    assert len(entries) == 1 and "IMG_1.JPG" in entries[0]


def test_refused_mismatch_is_not_journaled_as_a_delete(world):
    rot_in_place(world["archived"])
    res = st.apply(st.plan(world["cfg"], world["cat"]), world["cfg"], "testrun")
    assert res.manifest_path.read_text().strip() == ""


# --- ingest-side: the default path, not just --verify-archive --------------

def test_default_path_raises_a_warning_when_it_samples_the_rot(world):
    """With the sample forced on, the default path catches it and files instead."""
    rot_in_place(world["archived"])
    plan = ing.plan([world["staged"]], "Peepaw Cell", world["cat"],
                    world["cfg"].archive_root, "America/Detroit",
                    spot_check_rate=1.0)
    assert [f.action for f in plan.files] == ["copy"]
    assert len(plan.integrity_warnings) == 1


def test_a_warning_stops_the_catalog_settling_that_same_file(world, monkeypatch):
    """Once the catalog is caught lying about this content, no other row of it
    may settle the same file without a read."""
    rot_in_place(world["archived"])
    # A second archived row for identical content, deliberately left readable.
    twin = world["archived"].with_name("IMG_1__dupe.JPG")
    twin.write_bytes(GOOD)
    with world["cat"].connect() as conn:
        world["cat"].upsert_by_archive_path(conn, {
            "quick_hash": quick_hash(world["staged"]),
            "content_hash": sha256_file(twin),
            "source_label": "Peepaw Cell", "original_path": "y",
            "archive_path": str(twin), "asset_group_id": None,
            "ingested_at": "2026-08-01T00:00:00", "run_manifest_id": "r",
            "capture_dt": "2026-09-20T10:00:00", "date_source": "exif",
            "confidence": "high", "phash": None, "width": None, "height": None,
            "file_size": twin.stat().st_size, "duration": None,
            "camera_make": None, "camera_model": None, "mime_type": "image/jpeg",
            "gps_lat": None, "gps_lon": None, "gps_alt": None,
            "gps_source": None, "gps_status": "absent",
        })
        conn.commit()

    reads = []
    real = ing.sha256_file
    monkeypatch.setattr(ing, "sha256_file", lambda p: (reads.append(p), real(p))[1])
    plan = ing.plan([world["staged"]], "Peepaw Cell", world["cat"],
                    world["cfg"].archive_root, "America/Detroit",
                    spot_check_rate=1.0)
    assert len(plan.integrity_warnings) == 1
    # The surviving twin was PROVEN by a read, not settled from the catalog.
    assert twin in [p for p in reads]
