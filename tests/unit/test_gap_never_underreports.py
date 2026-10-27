"""The safety contract of feature 006: the comparison never under-reports.

    for every item genuinely absent from the archive, it MUST be reported
    missing; items that are in fact archived MAY be reported missing.

A false "missing" costs a redundant fetch the ingest hash check discards. A
false "present" lets a source be called reconciled while items are missing,
advancing a watermark past assets no future window will ever examine again —
which is the September 2026 loss arriving through a different door.

These are the tests whose failure means data loss rather than inconvenience.
contracts/gap-report.md §6 is the list they implement.
"""

import random

from archivist.audit import compare
from archivist.icloud import Listing

MIRROR = "/work/staging/icloud/demo"


def listing(paths, *, complete=True):
    return Listing(paths=frozenset(paths), listed_lines=len(paths),
                   complete=complete)


def synthetic_library(n, seed=0):
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        year = rnd.choice((2024, 2025, 2026))
        month = rnd.randint(1, 12)
        out.append(f"{year}/{month:02d}/ASSET_{i:05d}.HEIC")
    return out


# --- the property ----------------------------------------------------------

def test_every_unarchived_item_is_reported_missing():
    """Over many random splits, A (genuinely absent) must be a subset of M."""
    for seed in range(60):
        rnd = random.Random(seed)
        library = synthetic_library(200, seed)
        archived = set(rnd.sample(library, rnd.randint(0, len(library))))
        genuinely_absent = set(library) - archived

        report = compare("demo", listing(library), archived)

        assert genuinely_absent <= set(report.missing), (
            f"seed {seed}: under-reported "
            f"{sorted(genuinely_absent - set(report.missing))[:3]}")


def test_an_empty_archive_reports_the_whole_library_missing():
    library = synthetic_library(50)
    report = compare("demo", listing(library), set())
    assert report.missing_count == len(set(library))


def test_a_complete_archive_reports_nothing_missing():
    library = synthetic_library(50)
    report = compare("demo", listing(library), set(library))
    assert report.missing_count == 0


# --- isolation between accounts -------------------------------------------

def test_another_sources_rows_cannot_reduce_missing():
    """All accounts share one staging tree.

    The caller filters catalog rows by this source's mirror prefix. If that
    filter were ever dropped, a neighbour's identically-named item would mark
    this source's item present — the same defect class as a session check that
    asked whether *any* account had signed in.
    """
    library = ["2026/10/IMG_0001.HEIC", "2026/10/IMG_0002.HEIC"]
    # Same relative names, but they belong to another account and so must never
    # reach `archived` for this one.
    foreign = set()
    report = compare("demo", listing(library), foreign)
    assert report.missing_count == 2


def test_archived_set_must_already_be_relative():
    """Absolute paths in the archived set match nothing and so over-report.

    Fails safe: the entire library reads as missing rather than a silent
    partial match marking some items present.
    """
    library = ["2026/10/IMG_0001.HEIC"]
    absolute = {f"{MIRROR}/2026/10/IMG_0001.HEIC"}
    report = compare("demo", listing(library), absolute)
    assert report.missing_count == 1


# --- the one-way direction -------------------------------------------------

def test_items_the_archive_has_but_the_library_lacks_never_affect_the_verdict():
    """The archive keeps what a source deletes; that is Principle I, not a gap."""
    library = ["2026/10/IMG_0001.HEIC"]
    archived = {"2026/10/IMG_0001.HEIC", "2019/03/SCAN_0001.JPG"}
    report = compare("demo", listing(library), archived)
    assert report.missing_count == 0
    assert report.not_in_listing == 1      # reported as a diagnostic only


# --- counting integrity ----------------------------------------------------

def test_duplicate_listed_paths_are_counted_once():
    """Two distinct assets can map to one target path (measured: 13 in 6,100)."""
    dupes = ["2025/07/IMG_0691.HEIC", "2025/07/IMG_0691.HEIC"]
    report = compare("demo", listing(dupes), set())
    assert report.missing_count == 1


def test_month_buckets_and_undated_always_sum_to_missing():
    """An item whose period is unreadable is reported, never dropped."""
    library = ["2026/10/IMG_1.HEIC", "2026/09/IMG_2.HEIC", "loose-file.HEIC"]
    report = compare("demo", listing(library), set())
    assert sum(report.by_month.values()) + report.undated == report.missing_count
    assert report.undated == 1
