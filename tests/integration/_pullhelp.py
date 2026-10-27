"""Shared helpers for the 005 pull integration tests.

`icloud.download` now returns a CoverageProof rather than an exit code, so
mocks must produce evidence, not a status. These builders make the three
shapes that matter easy to write: a covered run, a bounded run that did not
clear its window, and the 2026-09-26 shape (reported success, fetched nothing).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml

from archivist.catalog import Catalog
from archivist.icloud import CoverageProof

COVERED = CoverageProof(
    enumeration_complete=True, reached_before_cutoff=True, examined=120,
    downloaded=0, already_present=0, exit_code=0,
    session_present_before=True, parser_confident=True,
)

#: The scan ceiling was hit before the cutoff was reached. Modelled as a walk
#: over items already on disk, which is what a busy source looks like when the
#: bound is too small: real work done, window still not cleared.
WINDOW_NOT_CLEARED = CoverageProof(
    enumeration_complete=True, reached_before_cutoff=False, examined=500,
    downloaded=0, already_present=500, exit_code=0,
    session_present_before=True, parser_confident=True,
)

#: Reported success, fetched nothing, no completion signal — the incident.
UNCONFIRMED = CoverageProof(
    enumeration_complete=False, examined=0, downloaded=0, exit_code=0,
    session_present_before=True, parser_confident=False,
    notes=("no completion signal in icloudpd output",),
)


def mock_download(calls, *, proof=COVERED, proof_for=None, make_mirror=True):
    """Record each invocation and return a per-username CoverageProof."""
    proof_for = proof_for or {}

    def fake(username, mirror, session_dir, recent=None, until_found=None,
             since=None, until=None, dry_run=False, verbose=False,
             on_line=None, version=None):
        calls.append({"username": username, "since": since, "until": until,
                      "recent": recent, "until_found": until_found,
                      "mirror": Path(mirror)})
        if make_mirror:
            Path(mirror).mkdir(parents=True, exist_ok=True)
        return proof_for.get(username, proof)

    return fake


def write_config(tmp: Path, cfg, sources: dict, **extra) -> Path:
    path = tmp / "config.yaml"
    payload = {
        "archive_root": str(cfg.archive_root),
        "work_root": str(cfg.work_root),
        "default_timezone": cfg.default_timezone,
        "sources": sources,
    }
    payload.update(extra)
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    Catalog(cfg.catalog_db).init_db()
    return path


def seed_meta(cfg, pairs: dict[str, str]) -> None:
    """Seed catalog meta keys. Takes a dict, not kwargs: source keys contain
    hyphens ("matt-personal") which cannot be Python identifiers."""
    cat = Catalog(cfg.catalog_db)
    with cat.connect() as conn:
        for key, value in pairs.items():
            cat.set_meta(conn, key, value)
        conn.commit()


def seed_source(cfg, source: str, *, pull_state: str | None = None,
                reconcile_state: str | None = None) -> None:
    pairs = {}
    if pull_state is not None:
        pairs[f"pull_state:{source}"] = pull_state
    if reconcile_state is not None:
        pairs[f"reconcile_state:{source}"] = reconcile_state
    if pairs:
        seed_meta(cfg, pairs)


def read_meta(cfg, key: str):
    cat = Catalog(cfg.catalog_db)
    with cat.connect() as conn:
        return cat.get_meta(conn, key)


def fresh(days_ago: int = 0) -> str:
    from datetime import timedelta
    return (datetime.now() - timedelta(days=days_ago)).replace(
        microsecond=0).isoformat()


# --- 006 helpers -----------------------------------------------------------

def mock_enumerate(calls, *, paths=(), complete=True, notes=(), per_user=None):
    """Stand in for icloud.enumerate_library, recording each invocation."""
    from archivist.icloud import Listing
    per_user = per_user or {}

    def fake(username, mirror, session_dir, version=None, on_line=None):
        calls.append({"username": username, "mirror": Path(mirror)})
        if username in per_user:
            return per_user[username]
        return Listing(paths=frozenset(paths), listed_lines=len(tuple(paths)),
                       complete=complete, notes=tuple(notes))

    return fake


def seed_assets(cfg, source: str, relatives, *, size: int = 4 * 1024 * 1024):
    """Record `relatives` as filed from `source`, as ingest would have."""
    cat = Catalog(cfg.catalog_db)
    mirror = cfg.icloud_dir / source
    with cat.connect() as conn:
        for rel in relatives:
            # Key off the relative path, not an index: upsert replaces by
            # archive_path, so index-derived names make a second seeding
            # OVERWRITE the first instead of adding to it.
            ident = rel.replace("/", "_")
            cat.upsert_by_archive_path(conn, {
                "quick_hash": f"q{source}{ident}",
                "content_hash": f"c{source}{ident}",
                "source_label": source,
                "original_path": str(mirror / rel),
                "archive_path": str(cfg.archive_root / source / ident),
                "file_size": size,
                "ingested_at": datetime.now().isoformat(),
            })
        conn.commit()
