"""Capture-location evidence: parsing, plausibility, group resolution.

Mirrors dates.py in spirit: raw evidence in, a validated verdict out. Location
is read-only evidence about a file — nothing here ever touches the file, and
no location is ever inferred from anything but the item's own metadata.

Status semantics (catalog `gps_status`):
  present  — accepted coordinates recorded
  absent   — examined, no recoverable location (a normal state, not an error)
  rejected — evidence existed but was implausible (out of range / null island)
  NULL     — never examined (drives incremental backfill)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .grouping import IMAGE_EXTS, RAW_EXTS

PRESENT = "present"
ABSENT = "absent"
REJECTED = "rejected"

# Anything this close to (0, 0) is treated as the null-island placeholder some
# devices write when GPS is on but has no fix.
_NULL_ISLAND_EPS = 1e-4

# Altitude sanity bounds (meters): below the Dead Sea shore, above any aircraft
# a family camera rides in. Bad altitude drops silently; lat/lon are kept.
_ALT_MIN, _ALT_MAX = -500.0, 20_000.0

# ISO 6709 as found in QuickTime location atoms: "+42.9634-085.6681+021.000/"
_ISO6709_RE = re.compile(
    r"^\s*(?P<lat>[+-]\d+(?:\.\d+)?)(?P<lon>[+-]\d+(?:\.\d+)?)(?P<alt>[+-]\d+(?:\.\d+)?)?"
)


@dataclass(frozen=True)
class LocationResult:
    status: str                 # present | absent | rejected
    lat: float | None = None
    lon: float | None = None
    alt: float | None = None
    source: str | None = None   # exif | video-meta | sidecar
    reason: str | None = None   # set when rejected

    @property
    def is_present(self) -> bool:
        return self.status == PRESENT


def parse_iso6709(value: str) -> tuple[float, float, float | None] | None:
    """Parse an ISO 6709 point string; return (lat, lon, alt) or None."""
    m = _ISO6709_RE.match(value or "")
    if not m:
        return None
    lat = float(m.group("lat"))
    lon = float(m.group("lon"))
    alt = float(m.group("alt")) if m.group("alt") else None
    return lat, lon, alt


def _signed(value, ref: str | None) -> float | None:
    """Combine a coordinate value with its hemisphere ref (exiftool -n output).

    exiftool may emit either signed decimals or unsigned+ref; trust an explicit
    S/W ref, otherwise trust the value's own sign.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    ref = (ref or "").strip().upper()
    if ref in ("S", "W"):
        return -abs(v)
    if ref in ("N", "E"):
        return abs(v)
    return v


def validate(lat: float, lon: float, alt: float | None) -> LocationResult:
    """Apply plausibility rules to raw coordinates (source filled by caller)."""
    if abs(lat) > 90 or abs(lon) > 180:
        return LocationResult(REJECTED, reason=f"out of range ({lat}, {lon})")
    if abs(lat) <= _NULL_ISLAND_EPS and abs(lon) <= _NULL_ISLAND_EPS:
        return LocationResult(REJECTED, reason="null-island placeholder (0, 0)")
    if alt is not None and not (_ALT_MIN <= alt <= _ALT_MAX):
        alt = None
    return LocationResult(PRESENT, lat=lat, lon=lon, alt=alt)


def from_evidence(raw: dict, is_video: bool = False) -> LocationResult:
    """Resolve a file's location verdict from its exiftool tag dict."""
    source = "video-meta" if is_video else "exif"

    # EXIF numeric GPS tags (photos; also present on some videos).
    lat = _signed(raw.get("GPSLatitude"), raw.get("GPSLatitudeRef"))
    lon = _signed(raw.get("GPSLongitude"), raw.get("GPSLongitudeRef"))
    if lat is not None and lon is not None:
        alt = None
        try:
            alt = float(raw["GPSAltitude"])
            if str(raw.get("GPSAltitudeRef", "0")).strip() in ("1", "Below Sea Level"):
                alt = -abs(alt)
        except (KeyError, TypeError, ValueError):
            pass
        r = validate(lat, lon, alt)
        return LocationResult(r.status, r.lat, r.lon, r.alt, source, r.reason)

    # QuickTime / vendor location strings: "lat lon [alt]" or ISO 6709.
    coords = raw.get("GPSCoordinates") or raw.get("Location") or raw.get("LocationISO6709")
    if coords is not None:
        parsed = None
        text = str(coords).strip()
        parts = text.replace(",", " ").split()
        try:
            nums = [float(x) for x in parts[:3]]
            if len(nums) >= 2:
                parsed = (nums[0], nums[1], nums[2] if len(nums) > 2 else None)
        except ValueError:
            parsed = parse_iso6709(text)
        if parsed:
            r = validate(*parsed)
            return LocationResult(r.status, r.lat, r.lon, r.alt, "video-meta", r.reason)

    return LocationResult(ABSENT)


def _member_rank(path: Path, primary: Path) -> tuple[int, int, str]:
    """Order for choosing the group's contributing member: primary, then
    stills, then RAW, then everything else (photo beats video on ties)."""
    ext = path.suffix.lower()
    kind = 0 if ext in IMAGE_EXTS else 1 if ext in RAW_EXTS else 2
    return (0 if path == primary else 1, kind, path.name.lower())


def resolve_group_location(
    outcomes: dict[Path, LocationResult], primary: Path
) -> LocationResult:
    """One location per asset group: the best-located member governs.

    Preference: primary member first, then stills over video. If no member has
    an accepted location, the group is rejected if any member was rejected
    (preserving the audit trail), else absent.
    """
    ordered = sorted(outcomes, key=lambda p: _member_rank(p, primary))
    for p in ordered:
        if outcomes[p].is_present:
            return outcomes[p]
    for p in ordered:
        if outcomes[p].status == REJECTED:
            return outcomes[p]
    return LocationResult(ABSENT)
