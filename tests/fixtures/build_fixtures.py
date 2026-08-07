"""Build small real media files with genuine embedded GPS metadata.

Fixtures are generated at test time into a tmp directory (nothing binary is
committed). Requires exiftool and ffmpeg on PATH (the application's own
external tools); HEIC fixtures are written via pillow-heif, so the builder
is host-agnostic (macOS and Linux alike).

Reference point: Grand Rapids, MI (42.9634 N, 85.6681 W), altitude 200 m.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pillow_heif
from PIL import Image

pillow_heif.register_heif_opener()

GR_LAT = 42.9634
GR_LON = -85.6681
GR_ALT = 200.0

# All fixtures are "captured" on this local day (UTC for video atoms).
CAPTURE_DAY = "2024:06:15 14:00:00"
CAPTURE_DAY_UTC = "2024-06-15T18:00:00Z"  # 14:00 EDT
CAPTURE_YEAR = "2024"


def tools_available() -> bool:
    return all(shutil.which(t) for t in ("exiftool", "ffmpeg"))


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {proc.stderr.strip()}")


def _make_jpeg(path: Path, color: tuple[int, int, int]) -> Path:
    img = Image.new("RGB", (64, 64), color)
    img.save(path, "JPEG")
    _run(["exiftool", "-overwrite_original", "-q",
          f"-DateTimeOriginal={CAPTURE_DAY}", str(path)])
    return path


def _write_gps(path: Path, lat: float, lon: float, alt: float | None = None) -> None:
    cmd = [
        "exiftool", "-overwrite_original", "-q",
        f"-GPSLatitude={abs(lat)}", f"-GPSLatitudeRef={'N' if lat >= 0 else 'S'}",
        f"-GPSLongitude={abs(lon)}", f"-GPSLongitudeRef={'E' if lon >= 0 else 'W'}",
    ]
    if alt is not None:
        cmd += [f"-GPSAltitude={alt}", "-GPSAltitudeRef=0"]
    cmd.append(str(path))
    _run(cmd)


def build_all(out_dir: Path) -> dict[str, Path]:
    """Create the full fixture set under `out_dir`; return name -> path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    f: dict[str, Path] = {}

    # Located JPEG (Grand Rapids, with altitude).
    f["located_jpg"] = _make_jpeg(out_dir / "IMG_0001.JPG", (200, 30, 30))
    _write_gps(f["located_jpg"], GR_LAT, GR_LON, GR_ALT)

    # Unlocated JPEG (no GPS tags at all).
    f["unlocated_jpg"] = _make_jpeg(out_dir / "IMG_0002.JPG", (30, 200, 30))

    # Null-island JPEG: (0, 0) placeholder coordinates.
    f["null_island_jpg"] = _make_jpeg(out_dir / "IMG_0003.JPG", (30, 30, 200))
    _write_gps(f["null_island_jpg"], 0.0, 0.0)

    # Live-Photo-style pair: located HEIC still + unlocated MOV clip, same stem.
    heic = out_dir / "IMG_0004.HEIC"
    Image.new("RGB", (64, 64), (220, 220, 40)).save(heic, "HEIF")
    _write_gps(heic, GR_LAT, GR_LON)
    _run(["exiftool", "-overwrite_original", "-q",
          f"-DateTimeOriginal={CAPTURE_DAY}", str(heic)])
    f["pair_heic"] = heic
    mov = out_dir / "IMG_0004.MOV"
    _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
          "-i", "color=c=yellow:s=64x64:d=0.3",
          "-metadata", f"creation_time={CAPTURE_DAY_UTC}", str(mov)])
    f["pair_mov"] = mov

    # Located MP4: ISO 6709 location atom written by ffmpeg.
    mp4 = out_dir / "VID_0005.MP4"
    _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
          "-i", "color=c=purple:s=64x64:d=0.3",
          "-metadata", f"creation_time={CAPTURE_DAY_UTC}",
          "-metadata", f"location={GR_LAT:+.4f}{GR_LON:+09.4f}/",
          str(mp4)])
    f["located_mp4"] = mp4

    # Byte-identical duplicate pair of a NEW located file (within-batch dup case).
    dup_a = _make_jpeg(out_dir / "IMG_0006.JPG", (120, 60, 180))
    _write_gps(dup_a, GR_LAT, GR_LON)
    dup_b = out_dir / "copies" / "IMG_0006 copy.JPG"
    dup_b.parent.mkdir(exist_ok=True)
    shutil.copy2(dup_a, dup_b)
    f["dup_located_a"] = dup_a
    f["dup_located_b"] = dup_b

    return f
