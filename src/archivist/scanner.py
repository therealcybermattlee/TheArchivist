"""Filesystem walking + the read-only `scan-archive` indexer.

scan-archive NEVER writes to the archive. It reads files under archive_root,
extracts metadata, resolves dates, hashes content, and records rows in the
catalog (which lives on the work drive). It is the baseline that makes dedup
and skip-already-archived meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

from .catalog import Catalog
from .dates import resolve
from .hashing import perceptual_hash, quick_hash, sha256_file
from .location import from_evidence as _from_evidence
from .metadata import Meta, extract_batch

# OS-noise files we never index.
_NOISE_NAMES = {"Thumbs.db", "desktop.ini"}

# macOS / volume system directories — any file beneath these is skipped.
_SYSTEM_DIRS = {
    ".fseventsd", ".Spotlight-V100", ".Trashes", ".TemporaryItems",
    ".DocumentRevisions-V100", ".PKInstallSandboxManager", ".vol",
    "$RECYCLE.BIN", "System Volume Information",
    "_Quarantine",  # the tool's own quarantine holding area
}

# Extensions whose content should be image/* or video/*. If the detected MIME
# top-level disagrees (e.g. an .mp4 that is really text/html), the file is
# suspect — likely a corrupt / failed-download placeholder.
_MEDIA_EXTS = {
    ".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif", ".tif", ".tiff", ".webp",
    ".cr2", ".cr3", ".nef", ".arw", ".dng", ".raf", ".orf", ".rw2",
    ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".mts", ".m2ts", ".3gp", ".insv", ".lrv",
}


def is_noise(p: Path) -> bool:
    # Any dotfile (.DS_Store, ._*, .bashrc, app caches, .metadata_never_index, …).
    # Real media is never hidden, so this is safe and catches most junk.
    if p.name.startswith("."):
        return True
    if p.name in _NOISE_NAMES:
        return True
    # Anything inside a known system directory.
    if _SYSTEM_DIRS.intersection(p.parts):
        return True
    return False


def is_suspect(p: Path, mime: str | None) -> bool:
    """True if a media-extension file does not actually contain media."""
    if p.suffix.lower() not in _MEDIA_EXTS:
        return False
    if not mime:
        return True
    return not (mime.startswith("image/") or mime.startswith("video/"))


def iter_media(root: Path) -> Iterator[Path]:
    for p in sorted(root.rglob("*")):
        if p.is_file() and not is_noise(p):
            yield p


@dataclass
class ScanResult:
    indexed: int = 0
    errors: list[tuple[Path, str]] = field(default_factory=list)
    suspect: list[tuple[Path, str]] = field(default_factory=list)  # (path, detected mime)
    conf_counts: dict[str, int] = field(default_factory=dict)
    sample_rows: list[dict] = field(default_factory=list)  # first N rows, for display


def _chunked(it: Iterator[Path], size: int) -> Iterator[list[Path]]:
    batch: list[Path] = []
    for item in it:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def scan(
    root: Path,
    catalog: Catalog,
    tz_name: str,
    do_quick: bool = True,
    do_full: bool = False,
    do_phash: bool = True,
    limit: int | None = None,
    write: bool = True,
    chunk: int = 200,
    sample: int = 50,
    progress: Callable[[int, Path], None] | None = None,
) -> ScanResult:
    """Index files under `root`, processing in chunks (extract -> hash -> commit).

    Hashing modes:
      do_quick  -> cheap size+head/tail identity (default; scales to TB).
      do_full   -> full sha256 of every file (slow; reads all bytes).
      do_phash  -> perceptual hash for still images.
    Bounds memory and commits incrementally so a long SMB run is resilient.
    `write=False` computes everything but never touches the DB.
    """
    result = ScanResult()
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn = catalog.connect() if write else None

    def _src() -> Iterator[Path]:
        n = 0
        for p in iter_media(root):
            yield p
            n += 1
            if limit and n >= limit:
                return

    try:
        seen = 0
        for batch in _chunked(_src(), chunk):
            metas: dict[Path, Meta] = extract_batch(batch)
            for p in batch:
                seen += 1
                if progress:
                    progress(seen, p)
                try:
                    meta = metas.get(p) or metas.get(Path(str(p)))
                    raw = meta.raw if meta else {}
                    dr = resolve(p, raw, tz_name, is_video=bool(meta and meta.is_video))
                    mime = meta.mime_type if meta else None
                    loc = _from_evidence(raw, is_video=bool(meta and meta.is_video))
                    row = {
                        "quick_hash": quick_hash(p) if do_quick else None,
                        "content_hash": sha256_file(p) if do_full else None,
                        "source_label": None,  # existing archive: source unknown
                        "original_path": None,
                        "archive_path": str(p),
                        "asset_group_id": None,  # grouping is Phase 2
                        "ingested_at": now,
                        "run_manifest_id": None,
                        "capture_dt": dr.dt.isoformat(),
                        "date_source": dr.source,
                        "confidence": dr.confidence,
                        "phash": perceptual_hash(p) if (do_phash and meta and meta.is_image) else None,
                        "width": meta.width if meta else None,
                        "height": meta.height if meta else None,
                        "file_size": p.stat().st_size,
                        "duration": _as_float(raw.get("Duration")),
                        "camera_make": meta.camera_make if meta else None,
                        "camera_model": meta.camera_model if meta else None,
                        "mime_type": mime,
                        "gps_lat": loc.lat,
                        "gps_lon": loc.lon,
                        "gps_alt": loc.alt,
                        "gps_source": loc.source,
                        "gps_status": loc.status,
                    }
                    if write and conn is not None:
                        catalog.upsert_by_archive_path(conn, row)
                    result.indexed += 1
                    result.conf_counts[dr.confidence] = result.conf_counts.get(dr.confidence, 0) + 1
                    if len(result.sample_rows) < sample:
                        result.sample_rows.append(row)
                    if is_suspect(p, mime):
                        result.suspect.append((p, mime or "unknown"))
                except Exception as exc:  # keep going; record the failure
                    result.errors.append((p, str(exc)))
            if write and conn is not None:
                conn.commit()  # checkpoint after each chunk
    finally:
        if conn is not None:
            conn.close()
    return result


def _as_float(val) -> float | None:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


@dataclass
class LocationBackfillResult:
    examined: int = 0
    located: int = 0
    location_absent: int = 0
    location_rejected: int = 0
    missing_files: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)


def backfill_locations(
    catalog: Catalog,
    *,
    full: bool = False,
    limit: int | None = None,
    chunk: int = 200,
    progress: Callable[[int, str], None] | None = None,
) -> LocationBackfillResult:
    """Populate `gps_*` columns for cataloged files, reading them in place.

    Read-only with respect to the archive: only the catalog is written.
    Incremental: examines rows with gps_status IS NULL (all rows with `full`).
    Commits per batch so an interrupted run resumes where it left off. Group
    stamping runs at the end of the pass so companion members that landed in
    different batches still share one location.
    """
    from .location import ABSENT, from_evidence, resolve_group_location

    res = LocationBackfillResult()
    conn = catalog.connect()
    try:
        targets = catalog.rows_missing_location(conn, full=full, limit=limit)
        # asset_group_id -> {path: outcome}, for the end-of-run group pass.
        group_outcomes: dict[str, dict[Path, object]] = {}
        group_rows: dict[str, list[int]] = {}

        for i in range(0, len(targets), chunk):
            batch = targets[i : i + chunk]
            paths = [Path(r["archive_path"]) for r in batch if r["archive_path"]]
            present_paths = [p for p in paths if p.is_file()]
            metas = extract_batch(present_paths) if present_paths else {}
            for row in batch:
                ap = row["archive_path"]
                if progress:
                    progress(res.examined + 1, ap or "?")
                p = Path(ap) if ap else None
                if p is None or not p.is_file():
                    res.missing_files += 1
                    continue  # not examined: stays NULL for a future run
                try:
                    meta = metas.get(p)
                    raw = meta.raw if meta else {}
                    is_video = bool(meta and meta.is_video)
                    loc = from_evidence(raw, is_video=is_video)
                    # Video with no exiftool evidence: try the ffprobe fallback.
                    if loc.status == ABSENT and is_video:
                        from .metadata import ffprobe_location
                        loc_str = ffprobe_location(p)
                        if loc_str:
                            loc = from_evidence({"Location": loc_str}, is_video=True)
                    catalog.set_location(conn, row["id"], loc)
                    res.examined += 1
                    if loc.status == "present":
                        res.located += 1
                    elif loc.status == "rejected":
                        res.location_rejected += 1
                    else:
                        res.location_absent += 1
                    gid = row["asset_group_id"]
                    if gid:
                        group_outcomes.setdefault(gid, {})[p] = loc
                        group_rows.setdefault(gid, []).append(row["id"])
                except Exception as exc:
                    res.errors.append((str(p), str(exc)))
            conn.commit()  # checkpoint: resumable after each batch

        # Group pass: stamp one location across every member of each group.
        for gid, outcomes in group_outcomes.items():
            rows = conn.execute(
                "SELECT id, archive_path FROM assets WHERE asset_group_id=?", (gid,)
            ).fetchall()
            primary = _group_primary([Path(r["archive_path"]) for r in rows if r["archive_path"]])
            if primary is None:
                continue
            group_loc = resolve_group_location(outcomes, primary)
            if group_loc.status == "present":
                for r in rows:
                    catalog.set_location(conn, r["id"], group_loc)
        conn.commit()
    finally:
        conn.close()
    return res


def _group_primary(paths: list[Path]) -> Path | None:
    """Primary member of a group of paths (still image first), or None."""
    if not paths:
        return None
    from .grouping import AssetGroup
    return AssetGroup(key=("", ""), members=list(paths)).primary
