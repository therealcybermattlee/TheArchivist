"""Unit tests: KML rendering rules (coordinate order, escaping, folders)."""

from archivist.mapexport import ExportItem, build_kml, placemark_kml


def _item(**kw) -> ExportItem:
    base = dict(asset_id=1, archive_path="/archive/2024/a.jpg",
                lat=42.9634, lon=-85.6681, alt=None,
                capture_dt="2024-06-15T14:00:00", source_label="Peepaw Cell")
    base.update(kw)
    return ExportItem(**base)


def test_coordinates_are_lon_lat_order():
    kml = placemark_kml(_item(), None)
    assert "<coordinates>-85.6681,42.9634</coordinates>" in kml


def test_altitude_appended_when_present():
    kml = placemark_kml(_item(alt=200.0), None)
    assert "<coordinates>-85.6681,42.9634,200.0</coordinates>" in kml


def test_balloon_embeds_thumbnail_and_facts():
    kml = placemark_kml(_item(), "thumbs/1.jpg")
    assert '<img src="thumbs/1.jpg"' in kml
    assert "Peepaw Cell" in kml and "2024-06-15" in kml
    assert "/archive/2024/a.jpg" in kml


def test_missing_thumbnail_noted_not_dropped():
    kml = placemark_kml(_item(), None)
    assert "no preview available" in kml and "<Placemark>" in kml


def test_xml_escaping_of_names_and_paths():
    kml = placemark_kml(
        _item(archive_path="/archive/2024/Beach & Sun <trip>/a.jpg"), None)
    assert "Beach &amp; Sun &lt;trip&gt;" in kml
    assert "& Sun <trip>" not in kml.replace("&amp;", "").replace("&lt;", "")


def test_folders_by_year_sorted():
    items = [
        _item(asset_id=1, capture_dt="2023-01-01T00:00:00"),
        _item(asset_id=2, capture_dt="2024-05-05T00:00:00"),
        _item(asset_id=3, capture_dt=None),
    ]
    kml = build_kml(items, {})
    assert kml.index("<name>2023</name>") < kml.index("<name>2024</name>")
    assert "<name>Undated</name>" in kml
    assert kml.count("<Placemark>") == 3
    assert kml.startswith('<?xml version="1.0"')
