"""Unit tests: grouping missing items by period (006 US2)."""

from archivist.audit import SCATTER_CUTOFF_MONTHS, compare, month_of
from archivist.icloud import Listing


def listing(paths):
    return Listing(paths=frozenset(paths), listed_lines=len(paths), complete=True)


def test_month_is_read_from_the_download_folder_structure():
    assert month_of("2026/10/IMG_1.HEIC") == "2026-10"
    assert month_of("loose.HEIC") is None
    assert month_of("notayear/10/IMG.HEIC") is None


def test_contiguous_span_groups_into_its_months():
    paths = [f"2026/09/IMG_{i}.HEIC" for i in range(5)] + \
            [f"2026/10/IMG_{i}.HEIC" for i in range(3)]
    report = compare("demo", listing(paths), set())
    assert report.by_month == {"2026-09": 5, "2026-10": 3}
    assert report.months_affected == 2
    assert not report.too_scattered


def test_scatter_is_flagged_past_the_cutoff():
    paths = [f"2026/{m:02d}/IMG.HEIC" for m in range(1, 13)]
    report = compare("demo", listing(paths), set())
    assert report.months_affected == 12
    assert report.too_scattered


def test_exactly_at_the_cutoff_is_not_scattered():
    paths = [f"2026/{m:02d}/IMG.HEIC" for m in range(1, SCATTER_CUTOFF_MONTHS + 1)]
    assert not compare("demo", listing(paths), set()).too_scattered


def test_month_lines_are_ordered():
    paths = ["2026/10/A.HEIC", "2025/01/B.HEIC", "2026/03/C.HEIC"]
    report = compare("demo", listing(paths), set())
    assert [m for m, _ in report.month_lines()] == ["2025-01", "2026-03", "2026-10"]
