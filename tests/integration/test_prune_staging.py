"""Integration: staging prune safety (004 FR-016 / constitution Principle I)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from archivist import ingest as ing
from archivist import staging as st
from archivist.catalog import Catalog
from archivist.metadata import extract_batch

pytestmark = pytest.mark.usefixtures("gps_media")

DEVICE = "Peepaw Cell"


@pytest.fixture
def staged_and_archived(cfg, gps_media):
    """Fixture media staged in a drop inbox and verifiedly ingested."""
    inbox = cfg.drops_dir / "peepaw-cell"
    inbox.mkdir(parents=True, exist_ok=True)
    for name in ("located_jpg", "unlocated_jpg"):
        shutil.copy2(gps_media[name], inbox / gps_media[name].name)
    cat = Catalog(cfg.catalog_db)
    cat.init_db()
    files = list(ing._iter_files(inbox))
    plan = ing.plan(files, DEVICE, cat, cfg.archive_root, cfg.default_timezone)
    metas = extract_batch([Path(f.src) for f in plan.to_copy])
    res = ing.apply(plan, DEVICE, cat, cfg.archive_root, cfg.default_timezone,
                    "prune-test", cfg.logs_dir, metas=metas)
    assert res.copied == 2 and not res.failed
    return cat, inbox


def test_plan_classifies_and_apply_deletes_only_verified(cfg, staged_and_archived, gps_media):
    cat, inbox = staged_and_archived
    # A never-ingested file: must be classified unverified and survive.
    keeper = inbox / "never_ingested.jpg"
    shutil.copy2(gps_media["null_island_jpg"], keeper)

    p = st.plan(cfg, cat)
    by = {i.path: i.status for i in p.items}
    assert by[str(keeper)] == st.UNVERIFIED
    verified = p.by_status(st.VERIFIED)
    assert len(verified) == 2 and all(i.archive_path for i in verified)

    res = st.apply(p, cfg, "run1")
    assert res.deleted == 2 and res.refused.get(st.UNVERIFIED) == 1
    assert keeper.is_file()                      # unverified survived
    assert not any((inbox / gps_media[n].name).exists()
                   for n in ("located_jpg", "unlocated_jpg"))
    # Archived copies untouched.
    for i in verified:
        assert Path(i.archive_path).is_file()

    # Journal: refusals + one line per deletion, written before unlinks.
    lines = [json.loads(l) for l in res.manifest_path.read_text().splitlines()]
    assert sum(1 for l in lines if l["action"] == "delete") == 2
    assert sum(1 for l in lines if l["action"] == "refuse") == 1

    # Re-plan: nothing prunable.
    p2 = st.plan(cfg, cat)
    assert p2.by_status(st.VERIFIED) == []


def test_scan_indexed_row_verifies_via_quickhash_fallback(cfg, staged_and_archived):
    """A staged duplicate of a scan-indexed archive row (content_hash NULL)
    must verify via the quick-hash + on-disk byte-hash fallback."""
    cat, inbox = staged_and_archived
    # Simulate lazy hashing: null out the content_hash the ingest recorded.
    with cat.connect() as conn:
        conn.execute("UPDATE assets SET content_hash=NULL")
        conn.commit()
    p = st.plan(cfg, cat)
    verified = p.by_status(st.VERIFIED)
    assert len(verified) == 2, [(i.path, i.status) for i in p.items]
    for i in verified:
        assert i.archive_path and Path(i.archive_path).is_file()


def test_archived_missing_refused(cfg, staged_and_archived):
    cat, inbox = staged_and_archived
    p = st.plan(cfg, cat)
    victim = p.by_status(st.VERIFIED)[0]
    hidden = Path(victim.archive_path).with_name("hidden-away")
    Path(victim.archive_path).rename(hidden)
    try:
        p2 = st.plan(cfg, cat)
        statuses = {i.path: i.status for i in p2.items}
        assert statuses[victim.path] == st.ARCHIVED_MISSING
        res = st.apply(p2, cfg, "run2")
        assert Path(victim.path).is_file()       # never deleted
        assert res.refused.get(st.ARCHIVED_MISSING) == 1
    finally:
        hidden.rename(Path(victim.archive_path))


def test_symlink_escape_refused(cfg, staged_and_archived, tmp_path):
    cat, inbox = staged_and_archived
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"precious bytes elsewhere")
    link = inbox / "sneaky.jpg"
    link.symlink_to(outside)
    p = st.plan(cfg, cat)
    statuses = {i.path: i.status for i in p.items}
    assert statuses[str(link)] == st.OUTSIDE
    st.apply(p, cfg, "run3")
    assert outside.is_file() and outside.read_bytes() == b"precious bytes elsewhere"


def test_apply_reverifies_at_deletion_time(cfg, staged_and_archived):
    """TOCTOU guard: archived copy vanishing between plan and apply → refuse."""
    cat, inbox = staged_and_archived
    p = st.plan(cfg, cat)
    victim = p.by_status(st.VERIFIED)[0]
    hidden = Path(victim.archive_path).with_name("gone")
    Path(victim.archive_path).rename(hidden)   # AFTER planning
    try:
        res = st.apply(p, cfg, "run4")
        assert Path(victim.path).is_file()
        assert res.refused.get(st.ARCHIVED_MISSING, 0) >= 1
    finally:
        hidden.rename(Path(victim.archive_path))
