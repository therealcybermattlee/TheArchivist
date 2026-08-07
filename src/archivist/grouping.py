"""Asset grouping: keep related files together through ingest.

Files that share a parent directory and a base name are one asset group — e.g.
a Live Photo (IMG_1234.HEIC + IMG_1234.MOV), a RAW+JPEG pair (IMG_1234.CR3 +
IMG_1234.JPG), an edit sidecar (IMG_1234.AAE), or a drone clip + telemetry
(DJI_0219.MP4 + DJI_0219.SRT). A group gets ONE date decision and all members
are placed in the same target folder, so a date-less sidecar inherits the
primary file's date instead of falling to a low-confidence mtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

IMAGE_EXTS = {
    ".jpg", ".jpeg", ".heic", ".heif", ".png", ".tif", ".tiff", ".gif", ".webp", ".bmp",
}
RAW_EXTS = {".dng", ".cr2", ".cr3", ".nef", ".arw", ".raf", ".orf", ".rw2", ".raw"}
VIDEO_EXTS = {
    ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".mts", ".m2ts", ".3gp", ".insv", ".lrv",
}
SIDECAR_EXTS = {".aae", ".xmp", ".srt", ".json", ".thm"}

# Primary-file preference: a still image is the best date source, then RAW,
# then video, then a sidecar as last resort.
def _type_rank(ext: str) -> int:
    ext = ext.lower()
    if ext in IMAGE_EXTS:
        return 0
    if ext in RAW_EXTS:
        return 1
    if ext in VIDEO_EXTS:
        return 2
    if ext in SIDECAR_EXTS:
        return 4
    return 3  # unknown – above sidecars, below known media


@dataclass
class AssetGroup:
    key: tuple[str, str]          # (parent dir, lowercase stem)
    members: list[Path] = field(default_factory=list)

    @property
    def primary(self) -> Path:
        """Best file to derive the group's date from (image > raw > video > sidecar)."""
        return min(self.members, key=lambda p: (_type_rank(p.suffix), p.name.lower()))

    @property
    def total_size(self) -> int:
        return sum((m.stat().st_size for m in self.members if m.is_file()), 0)


def group_files(paths: list[Path]) -> list[AssetGroup]:
    """Group by (parent directory, case-folded stem)."""
    groups: dict[tuple[str, str], AssetGroup] = {}
    for p in paths:
        key = (str(p.parent), p.stem.lower())
        g = groups.get(key)
        if g is None:
            g = groups[key] = AssetGroup(key=key)
        g.members.append(p)
    return list(groups.values())
