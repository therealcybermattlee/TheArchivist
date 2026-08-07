"""Media metadata extraction via exiftool (batch, read-only).

exiftool reads both photos and QuickTime/MP4 video tags in one pass, so we use it
as the primary extractor and avoid a hard ffprobe dependency. One exiftool process
handles many files at once — important when reading over SMB.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Tags we ask exiftool for. Order of date tags here is not the resolution order
# (that lives in dates.py) — we just collect whatever is present.
_TAGS = [
    "DateTimeOriginal",
    "CreateDate",
    "CreationDate",
    "MediaCreateDate",
    "TrackCreateDate",
    "ImageWidth",
    "ImageHeight",
    "Make",
    "Model",
    "MIMEType",
    "FileType",
    "Duration",
    # Capture location (photos: EXIF GPS; videos: QuickTime/vendor atoms).
    "GPSLatitude",
    "GPSLatitudeRef",
    "GPSLongitude",
    "GPSLongitudeRef",
    "GPSAltitude",
    "GPSAltitudeRef",
    "GPSCoordinates",
    "Location",
]


class ExiftoolError(Exception):
    pass


@dataclass
class Meta:
    source_file: Path
    raw: dict

    def get(self, key: str) -> str | None:
        val = self.raw.get(key)
        return str(val) if val is not None else None

    @property
    def mime_type(self) -> str | None:
        return self.get("MIMEType")

    @property
    def is_image(self) -> bool:
        mt = self.mime_type or ""
        return mt.startswith("image/")

    @property
    def is_video(self) -> bool:
        mt = self.mime_type or ""
        return mt.startswith("video/")

    @property
    def width(self) -> int | None:
        return _as_int(self.raw.get("ImageWidth"))

    @property
    def height(self) -> int | None:
        return _as_int(self.raw.get("ImageHeight"))

    @property
    def camera_make(self) -> str | None:
        return self.get("Make")

    @property
    def camera_model(self) -> str | None:
        return self.get("Model")


def _as_int(val) -> int | None:
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def exiftool_available() -> bool:
    return shutil.which("exiftool") is not None


def extract_batch(paths: list[Path], chunk: int = 200) -> dict[Path, Meta]:
    """Run exiftool over many files; return {path: Meta}. Read-only."""
    if not exiftool_available():
        raise ExiftoolError("exiftool not found on PATH")
    out: dict[Path, Meta] = {}
    for i in range(0, len(paths), chunk):
        batch = paths[i : i + chunk]
        cmd = ["exiftool", "-json", "-n"]  # -n: numeric (raw) values
        for t in _TAGS:
            cmd.append(f"-{t}")
        cmd += [str(p) for p in batch]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        # exiftool exits non-zero on minor warnings; only treat empty stdout as fatal.
        if not proc.stdout.strip():
            if proc.returncode != 0:
                raise ExiftoolError(proc.stderr.strip() or "exiftool produced no output")
            continue
        for entry in json.loads(proc.stdout):
            sf = Path(entry.get("SourceFile", ""))
            out[sf] = Meta(source_file=sf, raw=entry)
    return out


def extract_preview(path: Path) -> bytes | None:
    """Extract the embedded JPEG preview from a RAW file via exiftool.

    Camera RAW formats (CR3/DNG/NEF/...) virtually always embed a
    camera-generated JPEG. Tries the common preview tags in order and
    returns raw JPEG bytes, or None. Read-only; cross-platform.
    """
    if not exiftool_available():
        return None
    for tag in ("-JpgFromRaw", "-PreviewImage", "-ThumbnailImage"):
        proc = subprocess.run(
            ["exiftool", "-b", tag, str(path)],
            capture_output=True,
        )
        if proc.returncode == 0 and proc.stdout[:3] == b"\xff\xd8\xff":
            return proc.stdout
    return None


_FFPROBE_LOCATION_KEYS = ("location", "com.apple.quicktime.location.ISO6709")


def ffprobe_location(path: Path) -> str | None:
    """Fallback for videos whose exiftool output has no location tags.

    Returns the raw location string (usually ISO 6709) or None. Read-only.
    """
    if shutil.which("ffprobe") is None:
        return None
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format_tags=" + ",".join(_FFPROBE_LOCATION_KEYS), "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        tags = json.loads(proc.stdout).get("format", {}).get("tags", {})
    except json.JSONDecodeError:
        return None
    for key in _FFPROBE_LOCATION_KEYS:
        for k, v in tags.items():
            if k.lower() == key and str(v).strip():
                return str(v).strip()
    return None
