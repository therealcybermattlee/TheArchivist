"""Ingest engine: sort a pile of media into the archive (safe, copy-only).

Flow per asset group:
  1. resolve ONE date for the group (from the primary file) + confidence
  2. compute target dir: <archive_root>/<YYYY>/<MMDDYYYY> - Unsorted/<device>/
  3. for each member: dedup-check (quick_hash already archived -> skip), else plan
     a hash-verified COPY into the target (collision -> short hash suffix)

Safety: the source is only ever READ. Files are COPIED (shutil.copy2) and the
destination is re-hashed and compared before the catalog records success. Every
copy is appended to a JSONL manifest. Dry-run computes the full plan and writes
nothing.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .catalog import Catalog
from .dates import DateResult, resolve
from .grouping import AssetGroup, group_files
from .hashing import perceptual_hash, quick_hash, sha256_file
from .location import LocationResult, from_evidence, resolve_group_location
from .metadata import Meta, extract_batch
from .scanner import is_noise

_CONF_RANK = {"high": 0, "medium": 1, "low": 2}


@dataclass
class PlannedFile:
    src: str
    dst: str               # planned archive path
    action: str            # copy | skip-duplicate
    size: int
    date: str              # ISO
    confidence: str
    date_source: str
    dup_of: str | None = None   # existing archive path, when skipped
    # Group-resolved capture location (rides the plan so apply needs no re-read).
    gps_status: str | None = None   # present | absent | rejected
    gps_lat: float | None = None
    gps_lon: float | None = None
    gps_alt: float | None = None
    gps_source: str | None = None


@dataclass
class IngestPlan:
    files: list[PlannedFile] = field(default_factory=list)

    @property
    def to_copy(self) -> list[PlannedFile]:
        return [f for f in self.files if f.action == "copy"]

    @property
    def skipped(self) -> list[PlannedFile]:
        return [f for f in self.files if f.action == "skip-duplicate"]

    @property
    def copy_bytes(self) -> int:
        return sum(f.size for f in self.to_copy)


def _iter_files(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_file() and not is_noise(p):
            yield p


def _group_date(group: AssetGroup, metas: dict[Path, Meta], tz: str) -> DateResult:
    """Resolve the whole group's date from its members, best confidence wins."""
    best: DateResult | None = None
    # Try the primary first, then the rest, keeping the highest-confidence result.
    order = [group.primary] + [m for m in group.members if m != group.primary]
    for m in order:
        meta = metas.get(m)
        raw = meta.raw if meta else {}
        dr = resolve(m, raw, tz, is_video=bool(meta and meta.is_video))
        if best is None or _CONF_RANK[dr.confidence] < _CONF_RANK[best.confidence]:
            best = dr
        if best.confidence == "high":
            break
    return best  # never None: mtime always yields a result


def _group_location(group: AssetGroup, metas: dict[Path, Meta]) -> LocationResult:
    """Resolve ONE capture location for the group (best-located member, FR-004)."""
    outcomes: dict[Path, LocationResult] = {}
    for m in group.members:
        meta = metas.get(m)
        raw = meta.raw if meta else {}
        outcomes[m] = from_evidence(raw, is_video=bool(meta and meta.is_video))
    return resolve_group_location(outcomes, group.primary)


def _target_dir(archive_root: Path, dt: datetime, device_folder: str) -> Path:
    year = f"{dt.year:04d}"
    event = f"{dt.month:02d}{dt.day:02d}{dt.year:04d} - Unsorted"
    return archive_root / year / event / device_folder


def _case_match(dst: Path) -> Path | None:
    """The existing directory entry whose name matches `dst` case-insensitively.

    Makes collision detection portable: on case-sensitive filesystems (Linux/
    NFS) `IMG_1.JPG` and `img_1.jpg` are distinct entries, but the archive
    must never hold case-twin names (SMB clients can't tell them apart).
    """
    parent = dst.parent
    if not parent.is_dir():
        return None
    want = dst.name.casefold()
    for entry in parent.iterdir():
        if entry.name.casefold() == want:
            return entry
    return None


def _collision_free(
    dst: Path, src: Path, src_hash: str, planned: set[str]
) -> tuple[Path | None, str | None]:
    """Resolve a destination that never clobbers and never duplicates.

    Returns (destination, None) to copy, or (None, existing_path) when the
    colliding existing file is byte-identical to the source — a duplicate to
    skip, per PLAN.md §E. Collision detection is case-insensitive so
    behavior is identical on case-sensitive and case-insensitive
    filesystems. Different-content collisions get a short hash suffix.
    """
    existing = _case_match(dst)
    planned_hit = str(dst).casefold() in planned
    if existing is None and not planned_hit:
        return dst, None
    if existing is not None and existing.is_file():
        # Same bytes already at (a case-variant of) this destination:
        # duplicate, not a collision — never file it twice (PLAN.md §E).
        if sha256_file(existing) == sha256_file(src):
            return None, str(existing)
    suffix = src_hash[:8]
    return dst.with_name(f"{dst.stem}__{suffix}{dst.suffix}"), None


def plan(paths: list[Path], device_folder: str, catalog: Catalog,
         archive_root: Path, tz: str) -> IngestPlan:
    groups = group_files(paths)
    all_members = [m for g in groups for m in g.members]
    metas = extract_batch(all_members) if all_members else {}

    p = IngestPlan()
    planned_dsts: set[str] = set()
    # Within-batch dedup (FR-022): quick_hash -> (planned dst, sha256) of files
    # already planned to copy in THIS run. Exactly one copy of identical
    # content is filed; the rest are reported as duplicates.
    planned_content: dict[str, tuple[str, str]] = {}
    conn = catalog.connect()
    try:
        for g in groups:
            dr = _group_date(g, metas, tz)
            gloc = _group_location(g, metas)
            tdir = _target_dir(archive_root, dr.dt, device_folder)
            for m in g.members:
                size = m.stat().st_size
                qh = quick_hash(m)
                existing = catalog.paths_for_quick_hash(conn, qh)
                # Confirm a true duplicate by full hash before skipping.
                dup = None
                for ex in existing:
                    exp = Path(ex)
                    if exp.is_file() and sha256_file(exp) == sha256_file(m):
                        dup = ex
                        break
                if dup is None and qh in planned_content:
                    planned_dst, planned_sha = planned_content[qh]
                    if sha256_file(m) == planned_sha:
                        dup = planned_dst
                if dup:
                    p.files.append(PlannedFile(
                        str(m), dup, "skip-duplicate", size,
                        dr.dt.isoformat(), dr.confidence, dr.source, dup_of=dup,
                        gps_status=gloc.status, gps_lat=gloc.lat, gps_lon=gloc.lon,
                        gps_alt=gloc.alt, gps_source=gloc.source,
                    ))
                    continue
                dst, dup_existing = _collision_free(tdir / m.name, m, qh, planned_dsts)
                if dup_existing:
                    p.files.append(PlannedFile(
                        str(m), dup_existing, "skip-duplicate", size,
                        dr.dt.isoformat(), dr.confidence, dr.source,
                        dup_of=dup_existing,
                        gps_status=gloc.status, gps_lat=gloc.lat, gps_lon=gloc.lon,
                        gps_alt=gloc.alt, gps_source=gloc.source,
                    ))
                    continue
                planned_dsts.add(str(dst).casefold())
                planned_content.setdefault(qh, (str(dst), sha256_file(m)))
                p.files.append(PlannedFile(
                    str(m), str(dst), "copy", size,
                    dr.dt.isoformat(), dr.confidence, dr.source,
                    gps_status=gloc.status, gps_lat=gloc.lat, gps_lon=gloc.lon,
                    gps_alt=gloc.alt, gps_source=gloc.source,
                ))
    finally:
        conn.close()
    return p


@dataclass
class IngestResult:
    copied: int = 0
    skipped: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)
    copied_bytes: int = 0
    manifest_path: Path | None = None
    # Location outcome counters (FR-009), over filed items.
    located: int = 0
    location_absent: int = 0
    location_rejected: int = 0
    # Duplicate skips whose existing catalog row gained a location (FR-007).
    location_retained: int = 0


def apply(plan: IngestPlan, device_folder: str, catalog: Catalog, archive_root: Path,
          tz: str, run_id: str, logs_dir: Path, metas: dict[Path, Meta] | None = None,
          progress=None) -> IngestResult:
    """Execute the plan: copy + verify + catalog. Source is never modified."""
    res = IngestResult()
    logs_dir.mkdir(parents=True, exist_ok=True)
    mpath = logs_dir / f"ingest-{run_id}.jsonl"
    res.manifest_path = mpath
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    metas = metas or {}

    conn = catalog.connect()
    mf = mpath.open("a", encoding="utf-8")
    try:
        for i, pf in enumerate(plan.files, 1):
            if progress:
                progress(i, pf)
            if pf.action != "copy":
                res.skipped += 1
                # FR-007: a located duplicate may add a location to the kept
                # copy's row — never downgrade an existing `present`.
                if pf.gps_status == "present" and pf.dup_of:
                    loc = LocationResult("present", lat=pf.gps_lat, lon=pf.gps_lon,
                                         alt=pf.gps_alt, source=pf.gps_source)
                    row = conn.execute(
                        "SELECT id, gps_status FROM assets WHERE archive_path=?",
                        (pf.dup_of,),
                    ).fetchone()
                    if row and row["gps_status"] != "present":
                        if catalog.set_location(conn, row["id"], loc):
                            res.location_retained += 1
                            conn.commit()
                continue
            src, dst = Path(pf.src), Path(pf.dst)
            try:
                if not src.is_file():
                    res.failed.append((pf.src, "source missing")); continue
                if dst.exists():
                    res.failed.append((pf.src, "destination exists — skipped")); continue
                src_hash = sha256_file(src)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                # Verify the copy byte-for-byte before recording it.
                if sha256_file(dst) != src_hash:
                    try:
                        dst.unlink()
                    except OSError:
                        pass
                    res.failed.append((pf.src, "hash mismatch after copy — removed")); continue

                meta = metas.get(src)
                mime = meta.mime_type if meta else None
                conn.execute("DELETE FROM assets WHERE archive_path=?", (str(dst),))
                catalog.upsert_by_archive_path(conn, {
                    "quick_hash": quick_hash(dst),
                    "content_hash": src_hash,
                    "source_label": device_folder,
                    "original_path": pf.src,
                    "archive_path": str(dst),
                    "asset_group_id": None,
                    "ingested_at": now,
                    "run_manifest_id": run_id,
                    "capture_dt": pf.date,
                    "date_source": pf.date_source,
                    "confidence": pf.confidence,
                    "phash": perceptual_hash(dst) if (meta and meta.is_image) else None,
                    "width": meta.width if meta else None,
                    "height": meta.height if meta else None,
                    "file_size": pf.size,
                    "duration": None,
                    "camera_make": meta.camera_make if meta else None,
                    "camera_model": meta.camera_model if meta else None,
                    "mime_type": mime,
                    "gps_lat": pf.gps_lat,
                    "gps_lon": pf.gps_lon,
                    "gps_alt": pf.gps_alt,
                    "gps_source": pf.gps_source,
                    "gps_status": pf.gps_status,
                })
                conn.commit()
                mf.write(json.dumps({"from": pf.src, "to": pf.dst, "size": pf.size}) + "\n")
                mf.flush()
                res.copied += 1
                res.copied_bytes += pf.size
                if pf.gps_status == "present":
                    res.located += 1
                elif pf.gps_status == "rejected":
                    res.location_rejected += 1
                else:
                    res.location_absent += 1
            except Exception as exc:
                res.failed.append((pf.src, f"error: {exc}"))
    finally:
        mf.close()
        conn.close()
    return res
