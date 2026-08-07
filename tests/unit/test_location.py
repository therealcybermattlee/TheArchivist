"""Unit tests for location parsing, plausibility rules, and group resolution."""

from pathlib import Path

from archivist.location import (
    ABSENT,
    PRESENT,
    REJECTED,
    LocationResult,
    from_evidence,
    parse_iso6709,
    resolve_group_location,
    validate,
)


class TestParseIso6709:
    def test_lat_lon_only(self):
        assert parse_iso6709("+42.9634-085.6681/") == (42.9634, -85.6681, None)

    def test_with_altitude(self):
        lat, lon, alt = parse_iso6709("+42.9634-085.6681+021.000/")
        assert (lat, lon, alt) == (42.9634, -85.6681, 21.0)

    def test_no_trailing_solidus(self):
        assert parse_iso6709("+42.96-085.66") == (42.96, -85.66, None)

    def test_southern_western(self):
        assert parse_iso6709("-33.8688+151.2093/") == (-33.8688, 151.2093, None)

    def test_garbage(self):
        assert parse_iso6709("not a location") is None
        assert parse_iso6709("") is None


class TestValidate:
    def test_accepts_normal(self):
        r = validate(42.9634, -85.6681, 200.0)
        assert r.status == PRESENT and r.lat == 42.9634 and r.alt == 200.0

    def test_rejects_out_of_range_lat(self):
        assert validate(95.0, 10.0, None).status == REJECTED

    def test_rejects_out_of_range_lon(self):
        assert validate(10.0, 185.0, None).status == REJECTED

    def test_rejects_null_island(self):
        r = validate(0.0, 0.0, None)
        assert r.status == REJECTED and "null-island" in r.reason
        assert r.lat is None and r.lon is None  # no coordinates stored

    def test_near_null_island_within_epsilon(self):
        assert validate(0.00005, -0.00005, None).status == REJECTED

    def test_zero_lat_real_lon_ok(self):
        # The equator itself is fine — only the (0,0) point is a placeholder.
        assert validate(0.0, -78.5, None).status == PRESENT

    def test_absurd_altitude_dropped_coords_kept(self):
        r = validate(42.9, -85.6, 99_999.0)
        assert r.status == PRESENT and r.alt is None
        r = validate(42.9, -85.6, -1000.0)
        assert r.status == PRESENT and r.alt is None

    def test_dead_sea_altitude_kept(self):
        assert validate(31.5, 35.5, -430.0).alt == -430.0


class TestFromEvidence:
    def test_exif_unsigned_with_refs(self):
        r = from_evidence({
            "GPSLatitude": 42.9634, "GPSLatitudeRef": "N",
            "GPSLongitude": 85.6681, "GPSLongitudeRef": "W",
            "GPSAltitude": 200.0, "GPSAltitudeRef": "0",
        })
        assert r.is_present and r.lat == 42.9634 and r.lon == -85.6681
        assert r.alt == 200.0 and r.source == "exif"

    def test_exif_signed_without_refs(self):
        r = from_evidence({"GPSLatitude": -33.8688, "GPSLongitude": 151.2093})
        assert r.is_present and r.lat == -33.8688 and r.lon == 151.2093

    def test_below_sea_level_ref(self):
        r = from_evidence({
            "GPSLatitude": 31.5, "GPSLatitudeRef": "N",
            "GPSLongitude": 35.5, "GPSLongitudeRef": "E",
            "GPSAltitude": 430.0, "GPSAltitudeRef": "1",
        })
        assert r.alt == -430.0

    def test_quicktime_space_separated(self):
        r = from_evidence({"GPSCoordinates": "42.9634 -85.6681 200"}, is_video=True)
        assert r.is_present and r.lon == -85.6681 and r.source == "video-meta"

    def test_iso6709_location_string(self):
        r = from_evidence({"Location": "+42.9634-085.6681/"}, is_video=True)
        assert r.is_present and r.lat == 42.9634 and r.source == "video-meta"

    def test_no_evidence_is_absent(self):
        r = from_evidence({"MIMEType": "image/jpeg"})
        assert r.status == ABSENT and r.lat is None

    def test_null_island_rejected(self):
        r = from_evidence({
            "GPSLatitude": 0.0, "GPSLatitudeRef": "N",
            "GPSLongitude": 0.0, "GPSLongitudeRef": "E",
        })
        assert r.status == REJECTED


class TestGroupResolution:
    heic = Path("/x/IMG_1.HEIC")
    mov = Path("/x/IMG_1.MOV")
    aae = Path("/x/IMG_1.AAE")

    def _loc(self, lat=42.9, lon=-85.6, status=PRESENT, source="exif"):
        if status != PRESENT:
            return LocationResult(status)
        return LocationResult(PRESENT, lat=lat, lon=lon, source=source)

    def test_primary_wins(self):
        out = resolve_group_location(
            {self.heic: self._loc(lat=1.0, lon=1.0),
             self.mov: self._loc(lat=2.0, lon=2.0, source="video-meta")},
            primary=self.heic,
        )
        assert out.lat == 1.0

    def test_photo_beats_video_when_primary_absent(self):
        out = resolve_group_location(
            {self.aae: self._loc(status=ABSENT),
             self.heic: self._loc(lat=3.0, lon=3.0),
             self.mov: self._loc(lat=4.0, lon=4.0, source="video-meta")},
            primary=self.aae,
        )
        assert out.lat == 3.0 and out.source == "exif"

    def test_video_supplies_when_still_unlocated(self):
        out = resolve_group_location(
            {self.heic: self._loc(status=ABSENT),
             self.mov: self._loc(lat=5.0, lon=5.0, source="video-meta")},
            primary=self.heic,
        )
        assert out.lat == 5.0 and out.source == "video-meta"

    def test_all_absent(self):
        out = resolve_group_location(
            {self.heic: self._loc(status=ABSENT), self.mov: self._loc(status=ABSENT)},
            primary=self.heic,
        )
        assert out.status == ABSENT

    def test_rejected_preserved_over_absent(self):
        out = resolve_group_location(
            {self.heic: self._loc(status=REJECTED), self.mov: self._loc(status=ABSENT)},
            primary=self.heic,
        )
        assert out.status == REJECTED
