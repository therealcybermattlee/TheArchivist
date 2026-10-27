"""Unit tests: how a duplicate-skip decision is settled (005, Principle III).

Amended 2026-09-28: the archived side of the comparison is settled from the
catalog's recorded full hash — after confirming the file exists and still has
its recorded size — instead of re-reading the archived bytes every time. A
random sample re-reads anyway, and `--verify-archive` re-reads everything.

Re-reading every candidate over SMB made a 33k-file sweep a ~22-hour job.
These tests pin both the speed property (no archive read on the settled path)
and every safety property that had to survive it.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from archivist import ingest as ing
from archivist.catalog import Catalog
from archivist.hashing import quick_hash, sha256_file

CONTENT = b"the only copy of a photograph" * 400


class NeverSamples(random.Random):
    """Draws 1.0, so `rng.random() < rate` is false for every rate <= 1.0.

    The previous version drew 0.5, which meant any rate above 0.5 passed the
    sampling test identically — it could not tell "sampling works" from "the
    rate happens to exceed 0.5".
    """

    def random(self) -> float:  # noqa: D102
        return 1.0


class AlwaysSamples(random.Random):
    def random(self) -> float:  # noqa: D102
        return 0.0


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A staged file whose byte-identical twin is already in the archive."""
    monkeypatch.setattr(ing, "extract_batch", lambda paths: {})
    archive = tmp_path / "archive"
    (archive / "2026" / "09202026 - Unsorted" / "A Cell").mkdir(parents=True)
    archived = archive / "2026" / "09202026 - Unsorted" / "A Cell" / "IMG_1.JPG"
    archived.write_bytes(CONTENT)

    staged = tmp_path / "staging" / "IMG_1.JPG"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(CONTENT)

    cat = Catalog(tmp_path / "cat.sqlite3")
    cat.init_db()
    with cat.connect() as conn:
        cat.upsert_by_archive_path(conn, {
            "quick_hash": quick_hash(archived),
            "content_hash": sha256_file(archived),
            "source_label": "A Cell", "original_path": "x",
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
    return {"archive": archive, "archived": archived, "staged": staged, "cat": cat}


def run_plan(world, **kw):
    kw.setdefault("rng", NeverSamples())
    return ing.plan([world["staged"]], "A Cell", world["cat"],
                    world["archive"], "America/Detroit", **kw)


def track_reads(monkeypatch):
    """Record every path the planner fully hashes."""
    reads: list[Path] = []
    real = ing.sha256_file

    def spy(path):
        reads.append(Path(path))
        return real(path)
    monkeypatch.setattr(ing, "sha256_file", spy)
    return reads


# --- the speed property ----------------------------------------------------

def test_duplicate_is_settled_without_reading_the_archived_bytes(world, monkeypatch):
    reads = track_reads(monkeypatch)
    p = run_plan(world)
    assert [f.action for f in p.files] == ["skip-duplicate"]
    assert world["archived"] not in reads      # the network read is gone
    assert world["staged"] in reads            # the source is always hashed fresh


def test_the_source_is_hashed_exactly_once_on_the_duplicate_path(world, monkeypatch):
    """It used to be re-read per candidate and again when recorded.

    Scoped deliberately: the copy path goes on to `_collision_free`, which
    calls `sha256_file` directly and is unchanged by this work.
    """
    reads = track_reads(monkeypatch)
    run_plan(world)
    assert reads.count(world["staged"]) == 1


# --- catalog rows that are missing or malformed ----------------------------

@pytest.mark.parametrize("column,value", [
    ("content_hash", None), ("file_size", None), ("content_hash", ""),
])
def test_incomplete_catalog_rows_never_settle_a_skip(world, monkeypatch, column, value):
    """A row that cannot prove anything must force a read or a copy — never a
    skip taken on its word."""
    with world["cat"].connect() as conn:
        conn.execute(f"UPDATE assets SET {column}=?", (value,))
        conn.commit()
    reads = track_reads(monkeypatch)
    p = run_plan(world)
    if value is None:
        # NULL forces the re-read path, which then compares real bytes.
        assert world["archived"] in reads
        assert [f.action for f in p.files] == ["skip-duplicate"]
    else:
        # An empty recorded hash matches nothing; the file gets filed.
        assert [f.action for f in p.files] == ["copy"]


# --- the safety properties that had to survive -----------------------------

def test_missing_archived_file_is_not_a_duplicate(world, monkeypatch):
    """The catalog says it is archived; the shelf says otherwise. File it."""
    world["archived"].unlink()
    reads = track_reads(monkeypatch)
    p = run_plan(world)
    assert [f.action for f in p.files] == ["copy"]


def test_size_drift_forces_a_full_re_read(world, monkeypatch):
    """A file whose size no longer matches the catalog is not trusted."""
    world["archived"].write_bytes(CONTENT + b"appended")
    reads = track_reads(monkeypatch)
    p = run_plan(world)
    assert world["archived"] in reads          # fell back to reading it
    assert [f.action for f in p.files] == ["copy"]   # and it is not a duplicate


def test_verify_archive_always_re_reads(world, monkeypatch):
    reads = track_reads(monkeypatch)
    p = run_plan(world, verify_archive=True)
    assert world["archived"] in reads
    assert [f.action for f in p.files] == ["skip-duplicate"]


def test_spot_check_re_reads_only_when_the_draw_lands(world, monkeypatch):
    """Pins the sampling MECHANISM, not a rate that happens to exceed the draw."""
    reads = track_reads(monkeypatch)
    run_plan(world, spot_check_rate=0.01, rng=AlwaysSamples())
    assert world["archived"] in reads

    reads.clear()
    run_plan(world, spot_check_rate=0.99, rng=NeverSamples())
    assert world["archived"] not in reads


def test_the_default_sample_rate_is_not_zero():
    """The sample is the only routine check that archived bytes still match."""
    assert ing.ARCHIVE_SPOT_CHECK_RATE > 0


def test_a_zero_sample_rate_is_refused(world):
    """One config wire-up away from disabling rot detection entirely."""
    with pytest.raises(ValueError, match="spot_check_rate must be > 0"):
        run_plan(world, spot_check_rate=0.0)
    # ...unless every candidate is read anyway, which subsumes the sample.
    run_plan(world, spot_check_rate=0.0, verify_archive=True)


def test_corrupted_archive_is_never_skipped_WHEN_READ(world, monkeypatch):
    """Same size, different bytes — but only on a path that actually reads.

    Renamed to say what it pins. The previous name claimed the property held
    generally while passing `verify_archive=True`; on the DEFAULT path with the
    sample missing, this same fixture skips. The protection for that case is at
    the unlink, not here — see
    tests/integration/test_ingest_prune_chain.py::test_rotted_archive_does_not_cost_the_staged_copy
    """
    rotted = bytearray(CONTENT)
    rotted[17] ^= 0xFF                          # flip a bit, same length
    world["archived"].write_bytes(bytes(rotted))
    assert world["archived"].stat().st_size == len(CONTENT)

    p = run_plan(world, verify_archive=True)
    assert [f.action for f in p.files] == ["copy"]        # kept, not skipped
    assert len(p.integrity_warnings) == 1
    arc, recorded, actual = p.integrity_warnings[0]
    assert arc == str(world["archived"])
    assert recorded != actual


def test_clean_run_reports_no_integrity_warnings(world):
    assert run_plan(world).integrity_warnings == []
