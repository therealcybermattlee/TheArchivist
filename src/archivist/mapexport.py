"""Google Earth map export: located catalog items -> one .kmz bundle.

The KMZ (a zip of doc.kml + thumbs/) is a generated, read-only product: it
reads archived files to make thumbnails and writes ONLY into the exports
directory on the working volume. Neither the archive nor the catalog is
modified. Balloons embed the thumbnail so pins stay clickable-to-photo even
when the archive volume isn't mounted.

Thumbnails (cross-platform, no macOS tooling): Pillow for formats it reads
natively, pillow-heif for HEIC/HEIF, exiftool embedded-preview extraction
for RAW, `ffmpeg` single-frame grab for video. Per-item thumbnail failure
never drops the placemark — the balloon just notes the missing preview.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

import pillow_heif
from PIL import Image

from .grouping import RAW_EXTS, VIDEO_EXTS
from .metadata import extract_preview

pillow_heif.register_heif_opener()

THUMB_PX = 800

_PILLOW_EXTS = {
    ".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff", ".webp", ".bmp",
    ".heic", ".heif",  # via pillow-heif opener
}


class ThumbnailError(Exception):
    pass


def make_thumbnail(src: Path, dst_jpg: Path, px: int = THUMB_PX) -> None:
    """Write a JPEG thumbnail of a photo/video to dst_jpg. Read-only on src."""
    dst_jpg.parent.mkdir(parents=True, exist_ok=True)
    ext = src.suffix.lower()
    if ext in _PILLOW_EXTS:
        with Image.open(src) as im:
            im.thumbnail((px, px))
            im.convert("RGB").save(dst_jpg, "JPEG", quality=85)
        return
    if ext in RAW_EXTS:
        preview = extract_preview(src)
        if preview is None:
            raise ThumbnailError("no embedded preview recoverable from RAW file")
        with Image.open(io.BytesIO(preview)) as im:
            im.thumbnail((px, px))
            im.convert("RGB").save(dst_jpg, "JPEG", quality=85)
        return
    if ext in VIDEO_EXTS:
        if shutil.which("ffmpeg") is None:
            raise ThumbnailError("ffmpeg not available for video thumbnail")
        proc = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
             "-frames:v", "1", "-vf", f"scale='min({px},iw)':-2", str(dst_jpg)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0 or not dst_jpg.is_file():
            raise ThumbnailError(f"ffmpeg failed: {proc.stderr.strip()}")
        return
    raise ThumbnailError(f"no thumbnail strategy for {ext or 'extension-less file'}")


@dataclass
class ExportItem:
    """One located catalog row (a group's primary member) to plot."""
    asset_id: int
    archive_path: str
    lat: float
    lon: float
    alt: float | None
    capture_dt: str | None
    source_label: str | None


@dataclass
class ExportResult:
    out_path: Path | None = None
    exported: int = 0
    thumbs_ok: int = 0
    thumb_failures: list[tuple[str, str]] = field(default_factory=list)


def select_items(conn, year: str | None = None, source: str | None = None) -> list[ExportItem]:
    """Located rows, one per asset group (primary member preferred).

    Grouped rows collapse to a single placemark: the still image (image/*
    mime) wins, then lowest id. Ungrouped rows export individually.
    """
    where = ["gps_status='present'", "archive_path IS NOT NULL"]
    args: list = []
    if year:
        where.append("substr(capture_dt, 1, 4)=?")
        args.append(year)
    if source:
        where.append("source_label=?")
        args.append(source)
    rows = conn.execute(
        "SELECT id, archive_path, gps_lat, gps_lon, gps_alt, capture_dt, "
        "source_label, asset_group_id, mime_type "
        f"FROM assets WHERE {' AND '.join(where)} ORDER BY id",
        args,
    ).fetchall()

    items: list[ExportItem] = []
    best_by_group: dict[str, tuple[tuple[int, int], object]] = {}
    for r in rows:
        gid = r["asset_group_id"]
        if not gid:
            items.append(_to_item(r))
            continue
        mime = r["mime_type"] or ""
        rank = (0 if mime.startswith("image/") else 1, r["id"])
        cur = best_by_group.get(gid)
        if cur is None or rank < cur[0]:
            best_by_group[gid] = (rank, r)
    items.extend(_to_item(r) for _, r in best_by_group.values())
    items.sort(key=lambda i: (i.capture_dt or "", i.archive_path))
    return items


def _to_item(r) -> ExportItem:
    return ExportItem(
        asset_id=r["id"], archive_path=r["archive_path"],
        lat=r["gps_lat"], lon=r["gps_lon"], alt=r["gps_alt"],
        capture_dt=r["capture_dt"], source_label=r["source_label"],
    )


def placemark_kml(item: ExportItem, thumb_rel: str | None) -> str:
    """One KML Placemark: pin at the coordinates, balloon with photo + facts."""
    name = escape(f"{(item.capture_dt or '')[:10]}  {Path(item.archive_path).name}".strip())
    img = (f'<img src="{escape(thumb_rel)}" width="400"/><br/>'
           if thumb_rel else "<i>(no preview available)</i><br/>")
    desc = (
        f"{img}"
        f"<b>Captured:</b> {escape(item.capture_dt or 'unknown')}<br/>"
        f"<b>Source:</b> {escape(item.source_label or 'unknown')}<br/>"
        f"<b>Archive:</b> {escape(item.archive_path)}"
    )
    coords = f"{item.lon},{item.lat}" + (f",{item.alt}" if item.alt is not None else "")
    return (
        "<Placemark>"
        f"<name>{name}</name>"
        f"<description><![CDATA[{desc}]]></description>"
        f"<Point><coordinates>{coords}</coordinates></Point>"
        "</Placemark>"
    )


def build_kml(items: list[ExportItem], thumbs: dict[int, str]) -> str:
    """Full KML document, items foldered by capture year."""
    by_year: dict[str, list[ExportItem]] = {}
    for it in items:
        year = (it.capture_dt or "")[:4] or "Undated"
        by_year.setdefault(year, []).append(it)
    folders = []
    for year in sorted(by_year):
        marks = "".join(placemark_kml(it, thumbs.get(it.asset_id)) for it in by_year[year])
        folders.append(f"<Folder><name>{escape(year)}</name>{marks}</Folder>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2">'
        "<Document><name>The Archivist — Family Media Map</name>"
        + "".join(folders) +
        "</Document></kml>"
    )


def export_kmz(
    conn,
    out_path: Path,
    workdir: Path,
    year: str | None = None,
    source: str | None = None,
    progress=None,
) -> ExportResult:
    """Generate the KMZ at out_path. Reads archive files; writes only under
    out_path/workdir. Catalog connection is used read-only."""
    res = ExportResult()
    items = select_items(conn, year=year, source=source)
    if not items:
        return res

    thumb_dir = workdir / "thumbs"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    thumbs: dict[int, str] = {}
    for i, it in enumerate(items, 1):
        if progress:
            progress(i, it.archive_path)
        src = Path(it.archive_path)
        dst = thumb_dir / f"{it.asset_id}.jpg"
        try:
            if not src.is_file():
                raise ThumbnailError("archived file not found on disk")
            make_thumbnail(src, dst)
            thumbs[it.asset_id] = f"thumbs/{it.asset_id}.jpg"
            res.thumbs_ok += 1
        except ThumbnailError as exc:
            res.thumb_failures.append((it.archive_path, str(exc)))

    kml = build_kml(items, thumbs)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", kml)
        for rel in thumbs.values():
            z.write(thumb_dir / Path(rel).name, rel)
    res.out_path = out_path
    res.exported = len(items)
    return res
