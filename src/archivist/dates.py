"""Capture-date resolution with confidence tiers.

Priority (highest first):
  1. EXIF DateTimeOriginal / photo CreateDate        -> HIGH  (camera local wall-clock)
  2. QuickTime video CreationDate / CreateDate        -> HIGH  (UTC-normalized to local)
  3. Filename date tokens (YYYYMMDD, IMG_YYYYMMDD...)  -> MEDIUM
  4. Filesystem mtime                                 -> LOW

All results are normalized to `default_timezone` and returned as naive local
datetimes (the folder date is the local calendar day). Dates outside
[1990, now+1day] are rejected and the resolver falls through to the next tier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# exiftool date format: "YYYY:MM:DD HH:MM:SS" optionally followed by tz offset / 'Z'.
_DT_RE = re.compile(
    r"^(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})"
    r"(?:\.\d+)?"
    r"(Z|[+-]\d{2}:?\d{2})?"
)

# Filename date patterns -> we extract Y, M, D (and optional H, M, S).
_FNAME_PATTERNS = [
    re.compile(r"(?P<Y>\d{4})(?P<M>\d{2})(?P<D>\d{2})[_-](?P<h>\d{2})(?P<mi>\d{2})(?P<s>\d{2})"),
    re.compile(r"(?P<Y>\d{4})(?P<M>\d{2})(?P<D>\d{2})"),
    re.compile(r"(?P<Y>\d{4})[._-](?P<M>\d{2})[._-](?P<D>\d{2})"),
    # US MM-DD-YYYY / MM.DD.YYYY — the dominant format in this archive.
    re.compile(r"(?P<M>\d{2})[-.](?P<D>\d{2})[-.](?P<Y>\d{4})"),
]

# How a naive (offset-less) date in a given tag should be interpreted.
#   "local" -> already local wall-clock; "utc" -> stored in UTC, convert.
# The SAME tag name differs by media type: EXIF CreateDate (photo) is local,
# QuickTime CreateDate (video) is UTC. So we choose the tag list by file type.
_IMAGE_DATE_TAGS = (
    ("DateTimeOriginal", "local"),
    ("CreateDate", "local"),
    ("CreationDate", "local"),
)
_VIDEO_DATE_TAGS = (
    ("CreationDate", "local"),       # Apple: usually carries an offset; naive == local
    ("CreateDate", "utc"),           # QuickTime: stored in UTC
    ("MediaCreateDate", "utc"),
    ("TrackCreateDate", "utc"),
)

_MIN_DATE = datetime(1990, 1, 1)


@dataclass
class DateResult:
    dt: datetime          # naive, in local (default_timezone) wall-clock
    source: str           # exif | sidecar | filename | mtime
    confidence: str       # high | medium | low
    tag: str | None = None


def _parse_exif_dt(value: str) -> tuple[datetime, bool] | None:
    """Return (datetime, tz_aware). datetime is tz-aware if an offset was present."""
    m = _DT_RE.match(value.strip())
    if not m:
        return None
    y, mo, d, h, mi, s, tz = m.groups()
    try:
        base = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s))
    except ValueError:
        return None
    if tz:
        if tz == "Z":
            return base.replace(tzinfo=timezone.utc), True
        sign = 1 if tz[0] == "+" else -1
        tz = tz.replace(":", "")
        off = timedelta(hours=int(tz[1:3]), minutes=int(tz[3:5])) * sign
        return base.replace(tzinfo=timezone(off)), True
    return base, False


def _to_local_naive(dt: datetime, tz_aware: bool, assume_utc: bool, local: ZoneInfo) -> datetime:
    if tz_aware:
        return dt.astimezone(local).replace(tzinfo=None)
    if assume_utc:
        return dt.replace(tzinfo=timezone.utc).astimezone(local).replace(tzinfo=None)
    return dt  # already local wall-clock


def _sane(dt: datetime) -> bool:
    return _MIN_DATE <= dt <= datetime.now() + timedelta(days=1)


def resolve(path: Path, meta_raw: dict, tz_name: str, is_video: bool = False) -> DateResult:
    """Resolve the best capture date for one file.

    `is_video` selects the correct tag interpretation (QuickTime dates are UTC;
    EXIF photo dates are local).
    """
    local = ZoneInfo(tz_name)
    tags = _VIDEO_DATE_TAGS if is_video else _IMAGE_DATE_TAGS

    # 1 & 2: metadata date tags, in priority order (type-aware).
    for tag, interp in tags:
        val = meta_raw.get(tag)
        if not val:
            continue
        parsed = _parse_exif_dt(str(val))
        if not parsed:
            continue
        dt, tz_aware = parsed
        local_dt = _to_local_naive(dt, tz_aware, interp == "utc", local)
        if _sane(local_dt):
            return DateResult(local_dt, "exif", "high", tag)

    # 3: filename tokens.
    for pat in _FNAME_PATTERNS:
        m = pat.search(path.name)
        if not m:
            continue
        gd = m.groupdict()
        try:
            dt = datetime(
                int(gd["Y"]), int(gd["M"]), int(gd["D"]),
                int(gd.get("h") or 0), int(gd.get("mi") or 0), int(gd.get("s") or 0),
            )
        except (ValueError, TypeError):
            continue
        if _sane(dt):
            return DateResult(dt, "filename", "medium", None)

    # 4: filesystem mtime (always available -> nothing is ever stranded).
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).astimezone(local)
    return DateResult(mtime.replace(tzinfo=None), "mtime", "low", None)
