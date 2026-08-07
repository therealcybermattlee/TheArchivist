"""Cleanup engine: duplicates, corrupt files, and junk -> quarantine.

Safety model:
  - Planning is read-only and uses quick_hash (instant).
  - For DUPLICATES, every file is FULL-HASH confirmed byte-identical to the kept
    copy immediately before it is moved. A group that fails confirmation is
    skipped and reported (a quick_hash collision that is not a true duplicate).
  - Removal = MOVE within the archive volume to `<archive_root>/_Quarantine/...`
    preserving the original relative path. This is an atomic, reversible rename,
    not a delete. A JSON manifest records every move for undo / later purge.
  - Nothing touches a source; only the archive's own redundant copies move.

Keep-rule for duplicates (old copy errors): keep the copy whose event-folder
date best matches the file's capture date; ties prefer a real event over
Unsorted/Misc, then the shortest path, then lexicographic order.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .catalog import Catalog
from .hashing import sha256_file

QUARANTINE_DIRNAME = "_Quarantine"

# Event-folder date patterns, most specific first. Returns dict with y[/m/d].
_FOLDER_DATE_PATTERNS = [
    (re.compile(r"(?<!\d)(\d{4})[ ._-](\d{2})[ ._-](\d{2})(?!\d)"), ("y", "m", "d")),  # YYYY MM DD
    (re.compile(r"(?<!\d)(\d{2})[-.](\d{2})[-.](\d{4})(?!\d)"), ("m", "d", "y")),       # MM-DD-YYYY
    (re.compile(r"(?<!\d)(\d{2})(\d{2})(\d{4})(?!\d)"), ("m", "d", "y")),               # MMDDYYYY
    (re.compile(r"(?<!\d)(\d{2})(\d{4})(?!\d)"), ("m", "y")),                           # MMYYYY
    (re.compile(r"(?<!\d)(20\d{2})(?!\d)"), ("y",)),                                    # bare YYYY
]

_UNSORTED_HINTS = ("unsorted", "misc")


@dataclass
class MoveItem:
    category: str            # duplicate | corrupt | junk
    archive_path: str        # file to quarantine
    size: int
    keep_path: str | None = None      # the copy we keep (duplicates only)
    quick_hash: str | None = None
    confirmed: bool | None = None     # set at apply time (full-hash result)


@dataclass
class CleanupPlan:
    items: list[MoveItem] = field(default_factory=list)

    def by_category(self, cat: str) -> list[MoveItem]:
        return [i for i in self.items if i.category == cat]

    @property
    def total_bytes(self) -> int:
        return sum(i.size for i in self.items)


def parse_folder_date(name: str) -> dict:
    for pat, keys in _FOLDER_DATE_PATTERNS:
        m = pat.search(name)
        if not m:
            continue
        vals = {k: int(v) for k, v in zip(keys, m.groups())}
        y, mo, d = vals.get("y"), vals.get("m"), vals.get("d")
        if y and not (1990 <= y <= 2100):
            continue
        if mo and not (1 <= mo <= 12):
            continue
        if d and not (1 <= d <= 31):
            continue
        return vals
    return {}


def _under_root(archive_root: Path, archive_path: str) -> bool:
    """True only if archive_path is a real path strictly inside archive_root."""
    if not archive_path or not archive_path.strip():
        return False
    try:
        Path(archive_path).relative_to(archive_root)
        return True
    except ValueError:
        return False


def _event_folder(archive_root: Path, archive_path: str) -> str:
    """The Level-2 event folder name (component right under <root>/<year>/)."""
    try:
        rel = Path(archive_path).relative_to(archive_root)
    except ValueError:
        return ""
    parts = rel.parts
    # parts[0] = year, parts[1] = event folder
    return parts[1] if len(parts) >= 2 else ""


def _match_score(archive_root: Path, archive_path: str, capture_dt: str | None) -> int:
    """How well the event-folder date matches the file's capture date (higher=better)."""
    if not capture_dt:
        return 0
    fd = parse_folder_date(_event_folder(archive_root, archive_path))
    if not fd:
        return 0
    cy, cm, cd = int(capture_dt[0:4]), int(capture_dt[5:7]), int(capture_dt[8:10])
    score = 0
    if fd.get("y") == cy:
        score += 4
    if fd.get("m") == cm:
        score += 2
    if fd.get("d") == cd:
        score += 2
    return score


def _keep_sort_key(archive_root: Path, row: dict):
    """Sort copies so the BEST keep candidate is first."""
    path = row["archive_path"]
    score = _match_score(archive_root, path, row.get("capture_dt"))
    event = _event_folder(archive_root, path).lower()
    is_unsorted = any(h in event for h in _UNSORTED_HINTS) or "unsorted" in path.lower() or "misc" in path.lower()
    # Higher score first; real event before unsorted/misc; shorter path; lexicographic.
    return (-score, 1 if is_unsorted else 0, len(path), path)


def plan(catalog: Catalog, archive_root: Path,
         do_dupes=True, do_corrupt=True, do_junk=True) -> CleanupPlan:
    """Read-only: build the cleanup plan from the catalog (uses quick_hash)."""
    p = CleanupPlan()
    seen: set[str] = set()  # a path is planned at most once, across all categories
    with catalog.connect() as conn:
        if do_corrupt:
            for r in conn.execute(
                "SELECT archive_path, file_size FROM assets WHERE mime_type='text/html'"
            ):
                ap = r["archive_path"]
                if ap in seen or not _under_root(archive_root, ap):
                    continue
                seen.add(ap)
                p.items.append(MoveItem("corrupt", ap, r["file_size"] or 0))

        if do_junk:
            for r in conn.execute(
                "SELECT archive_path, file_size FROM assets "
                "WHERE LOWER(archive_path) LIKE '%.argb'"
            ):
                ap = r["archive_path"]
                if ap in seen or not _under_root(archive_root, ap):
                    continue
                seen.add(ap)
                p.items.append(MoveItem("junk", ap, r["file_size"] or 0))

        if do_dupes:
            groups = conn.execute(
                "SELECT quick_hash FROM assets WHERE quick_hash IS NOT NULL "
                "GROUP BY quick_hash HAVING COUNT(*)>1"
            ).fetchall()
            for (qh,) in [(g["quick_hash"],) for g in groups]:
                rows = [dict(r) for r in conn.execute(
                    "SELECT archive_path, file_size, capture_dt FROM assets WHERE quick_hash=?",
                    (qh,),
                )]
                # Only consider paths that are inside archive_root and not already
                # slated for removal by another category.
                rows = [r for r in rows
                        if _under_root(archive_root, r["archive_path"]) and r["archive_path"] not in seen]
                if len(rows) < 2:
                    continue  # nothing left to dedupe in this group
                rows.sort(key=lambda r: _keep_sort_key(archive_root, r))
                keep = rows[0]["archive_path"]
                seen.add(keep)  # immunize the survivor — it must never be quarantined
                for r in rows[1:]:
                    ap = r["archive_path"]
                    seen.add(ap)
                    p.items.append(MoveItem(
                        "duplicate", ap, r["file_size"] or 0,
                        keep_path=keep, quick_hash=qh,
                    ))
    return p


def load_manifest(manifest_path: Path) -> list[dict]:
    return [json.loads(line) for line in manifest_path.open(encoding="utf-8") if line.strip()]


@dataclass
class PurgePlan:
    deletable: list[dict] = field(default_factory=list)
    protected: list[tuple[dict, str]] = field(default_factory=list)  # (entry, reason kept)

    @property
    def free_bytes(self) -> int:
        return sum(e.get("size") or 0 for e in self.deletable)


def purge_plan(entries: list[dict], archive_root: Path) -> PurgePlan:
    """Decide which quarantined files are safe to delete.

    A quarantined DUPLICATE is only deletable if its kept copy still exists in the
    live archive — otherwise we would be deleting the last surviving copy.
    """
    qroot = (archive_root / QUARANTINE_DIRNAME).resolve()
    p = PurgePlan()
    for e in entries:
        to = Path(e.get("to", ""))
        # Hard guard: only ever delete inside <archive_root>/_Quarantine.
        try:
            to.resolve().relative_to(qroot)
        except (ValueError, OSError):
            p.protected.append((e, "NOT under _Quarantine — refusing"))
            continue
        if not to.is_file():
            p.protected.append((e, "quarantine file already gone"))
            continue
        if e.get("category") == "duplicate":
            keep = e.get("keep")
            if not keep or not Path(keep).is_file():
                p.protected.append((e, "kept copy missing in archive — keeping this copy"))
                continue
        p.deletable.append(e)
    return p


@dataclass
class PurgeResult:
    deleted: int = 0
    freed_bytes: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)


def purge_apply(plan: PurgePlan, archive_root: Path, run_dir: Path, progress=None) -> PurgeResult:
    res = PurgeResult()
    for i, e in enumerate(plan.deletable, 1):
        if progress:
            progress(i, e)
        to = Path(e["to"])
        try:
            sz = to.stat().st_size
            to.unlink()
            res.deleted += 1
            res.freed_bytes += sz
        except FileNotFoundError:
            pass
        except OSError as exc:
            res.errors.append((str(to), str(exc)))
    # Remove now-empty directories under the run dir (bottom-up), but never the
    # quarantine root itself unless empty.
    if run_dir.is_dir():
        for d in sorted((p for p in run_dir.rglob("*") if p.is_dir()), key=lambda x: -len(x.parts)):
            try:
                d.rmdir()
            except OSError:
                pass
        try:
            run_dir.rmdir()
        except OSError:
            pass
    return res


def quarantine_path(archive_root: Path, run_id: str, archive_path: str) -> Path:
    """Destination under <root>/_Quarantine/<run_id>/<original-relative-path>."""
    rel = Path(archive_path).relative_to(archive_root)
    return archive_root / QUARANTINE_DIRNAME / run_id / rel


@dataclass
class ApplyResult:
    moved: list[MoveItem] = field(default_factory=list)
    skipped: list[tuple[MoveItem, str]] = field(default_factory=list)
    manifest_path: Path | None = None

    @property
    def moved_bytes(self) -> int:
        return sum(i.size for i in self.moved)


def apply(plan: CleanupPlan, catalog: Catalog, archive_root: Path, run_id: str,
          logs_dir: Path, progress=None) -> ApplyResult:
    """Move planned files to quarantine. Duplicates are full-hash confirmed first.

    Each successful move is appended to a JSONL manifest IMMEDIATELY (before the
    next item) so an interrupted run is still fully recorded and reversible.
    """
    res = ApplyResult()
    keep_hash_cache: dict[str, str] = {}
    logs_dir.mkdir(parents=True, exist_ok=True)
    mpath = logs_dir / f"cleanup-{run_id}.jsonl"
    res.manifest_path = mpath

    conn = catalog.connect()
    mf = mpath.open("a", encoding="utf-8")
    try:
        for idx, item in enumerate(plan.items, 1):
            if progress:
                progress(idx, item)
            try:
                if not _under_root(archive_root, item.archive_path):
                    res.skipped.append((item, "path not under archive_root"))
                    continue
                src = Path(item.archive_path)
                if src.is_symlink():
                    res.skipped.append((item, "is a symlink — left in place"))
                    continue
                if not src.is_file():
                    res.skipped.append((item, "source missing"))
                    continue

                # Confirm true duplicate by full content hash before moving.
                if item.category == "duplicate":
                    keep = item.keep_path
                    if not keep or not Path(keep).is_file():
                        res.skipped.append((item, "keep copy missing"))
                        continue
                    if keep not in keep_hash_cache:
                        keep_hash_cache[keep] = sha256_file(Path(keep))
                    if sha256_file(src) != keep_hash_cache[keep]:
                        item.confirmed = False
                        res.skipped.append((item, "NOT byte-identical (quick_hash collision)"))
                        continue
                    item.confirmed = True

                dst = quarantine_path(archive_root, run_id, item.archive_path)
                if dst.exists():
                    res.skipped.append((item, "quarantine destination already exists — not overwriting"))
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))

                # Record the move FIRST (durable), then update the catalog index.
                mf.write(json.dumps({
                    "category": item.category, "from": item.archive_path, "to": str(dst),
                    "size": item.size, "keep": item.keep_path, "quick_hash": item.quick_hash,
                }) + "\n")
                mf.flush()
                conn.execute("DELETE FROM assets WHERE archive_path=?", (item.archive_path,))
                conn.commit()
                res.moved.append(item)
            except Exception as exc:  # one bad item never aborts the whole run
                res.skipped.append((item, f"error: {exc}"))
    finally:
        mf.close()
        conn.close()
    return res
