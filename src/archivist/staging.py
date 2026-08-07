"""Staging prune: reclaim working storage, never touch an unverified byte.

The ONLY files this module may delete are inside the tool's own staging and
drop-inbox areas (constitution Principle I carve-out; baseline FR-011 as
amended 2026-07-31), and only when a byte-verified archived copy is
confirmed present AT PLAN/APPLY TIME. Everything else is refused and
reported. Plan/apply shape mirrors dedupe.py; every unlink is journaled
first (JSONL), so an interrupted run is fully accounted for.

Statuses (data-model.md, 004):
  verified-archived — sha256 matches a catalog row with an archive_path
                      whose file exists on the mounted archive right now
  unverified        — no catalog match: may be the only copy; untouchable
  archived-missing  — catalog match but the archived file is absent:
                      archive-integrity question; refused loudly
  outside-staging   — path escapes the staging roots after resolution
                      (symlink etc.); refused
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .catalog import Catalog
from .config import Config
from .hashing import sha256_file
from .scanner import is_noise

VERIFIED = "verified-archived"
UNVERIFIED = "unverified"
ARCHIVED_MISSING = "archived-missing"
OUTSIDE = "outside-staging"


@dataclass
class StagedItem:
    path: str
    status: str
    size: int
    archive_path: str | None = None   # the verified counterpart (when known)


@dataclass
class PrunePlan:
    items: list[StagedItem] = field(default_factory=list)

    def by_status(self, status: str) -> list[StagedItem]:
        return [i for i in self.items if i.status == status]

    @property
    def prunable_bytes(self) -> int:
        return sum(i.size for i in self.by_status(VERIFIED))


def staging_roots(cfg: Config) -> list[Path]:
    """The ONLY trees prune may ever touch (resolved)."""
    return [cfg.staging_dir.resolve(), cfg.drops_dir.resolve()]


def _inside(path: Path, roots: list[Path]) -> bool:
    try:
        rp = path.resolve(strict=True)
    except OSError:
        return False
    return any(rp == r or r in rp.parents for r in roots)


def plan(cfg: Config, catalog: Catalog, source: str | None = None,
         progress=None) -> PrunePlan:
    """Classify every staged media file. Read-only."""
    roots = staging_roots(cfg)
    scan_roots: list[Path] = []
    for r in roots:
        if source:
            candidate_dirs = [r / "icloud" / source, r / source]
            scan_roots.extend(d for d in candidate_dirs if d.is_dir())
        elif r.is_dir():
            scan_roots.append(r)

    p = PrunePlan()
    conn = catalog.connect()
    try:
        seen = 0
        for root in scan_roots:
            for f in sorted(root.rglob("*")):
                if not f.is_file() or is_noise(f):
                    continue
                seen += 1
                if progress:
                    progress(seen, f)
                size = f.lstat().st_size
                # Containment first: symlinks / escapes are never candidates.
                if f.is_symlink() or not _inside(f, roots):
                    p.items.append(StagedItem(str(f), OUTSIDE, size))
                    continue
                content = sha256_file(f)
                row = conn.execute(
                    "SELECT archive_path FROM assets "
                    "WHERE content_hash=? AND archive_path IS NOT NULL LIMIT 1",
                    (content,),
                ).fetchone()
                if row is not None:
                    arc = Path(row["archive_path"])
                    if arc.is_file():
                        p.items.append(StagedItem(str(f), VERIFIED, size,
                                                  archive_path=str(arc)))
                    else:
                        p.items.append(StagedItem(str(f), ARCHIVED_MISSING, size,
                                                  archive_path=str(arc)))
                    continue
                # content_hash is lazily populated (scan-indexed rows carry only
                # a quick hash) — fall back to ingest's two-tier check: quick-
                # hash candidates, then byte-hash the ACTUAL archive file now.
                # Stronger than the column check: it proves today's bytes.
                from .hashing import quick_hash
                verified_arc = None
                for cand in catalog.paths_for_quick_hash(conn, quick_hash(f)):
                    cp = Path(cand)
                    if cp.is_file() and sha256_file(cp) == content:
                        verified_arc = cp
                        break
                if verified_arc is not None:
                    p.items.append(StagedItem(str(f), VERIFIED, size,
                                              archive_path=str(verified_arc)))
                else:
                    p.items.append(StagedItem(str(f), UNVERIFIED, size))
    finally:
        conn.close()
    return p


@dataclass
class PruneResult:
    deleted: int = 0
    freed_bytes: int = 0
    refused: dict[str, int] = field(default_factory=dict)
    errors: list[tuple[str, str]] = field(default_factory=list)
    manifest_path: Path | None = None


def apply(prune_plan: PrunePlan, cfg: Config, run_id: str,
          progress=None) -> PruneResult:
    """Delete verified-archived staged files, journal-first. Refuse the rest."""
    res = PruneResult()
    roots = staging_roots(cfg)
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)
    mpath = cfg.logs_dir / f"prune-{run_id}.jsonl"
    res.manifest_path = mpath
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    with mpath.open("a", encoding="utf-8") as mf:
        for status in (UNVERIFIED, ARCHIVED_MISSING, OUTSIDE):
            items = prune_plan.by_status(status)
            if items:
                res.refused[status] = len(items)
                for it in items:
                    mf.write(json.dumps({"run_id": run_id, "at": now,
                                         "staged_path": it.path,
                                         "action": "refuse",
                                         "status": it.status}) + "\n")
        mf.flush()

        for i, it in enumerate(prune_plan.by_status(VERIFIED), 1):
            if progress:
                progress(i, it)
            f = Path(it.path)
            try:
                # Re-verify at the moment of deletion: containment, symlink,
                # and the archived counterpart must still hold.
                if f.is_symlink() or not _inside(f, roots):
                    res.refused[OUTSIDE] = res.refused.get(OUTSIDE, 0) + 1
                    continue
                if not (it.archive_path and Path(it.archive_path).is_file()):
                    res.refused[ARCHIVED_MISSING] = res.refused.get(ARCHIVED_MISSING, 0) + 1
                    continue
                # Journal BEFORE the unlink (constitution Principle IV).
                mf.write(json.dumps({"run_id": run_id, "at": now,
                                     "staged_path": it.path,
                                     "archive_path": it.archive_path,
                                     "size": it.size,
                                     "action": "delete"}) + "\n")
                mf.flush()
                f.unlink()
                res.deleted += 1
                res.freed_bytes += it.size
            except Exception as exc:
                res.errors.append((it.path, str(exc)))
    return res
