"""Unit tests: the verdict table of contracts/gap-report.md §5 (006).

Three states, not a boolean. "nothing missing", "things missing" and "could not
tell" are operationally different; collapsing the third into either of the
others is exactly how coverage was lost in September 2026.
"""

from datetime import datetime

from archivist.audit import (GapReport, Incomplete, Reconciled, Unverified,
                             compare, decide_verdict, mirror_has_unfiled_files)
from archivist.icloud import Listing

NOW = datetime(2026, 10, 27, 12, 0, 0)


def listing(paths=(), *, complete=True, notes=()):
    return Listing(paths=frozenset(paths), listed_lines=len(paths),
                   complete=complete, notes=tuple(notes))


def test_clean_comparison_reconciles():
    lst = listing(["2026/10/A.HEIC"])
    report = compare("demo", lst, {"2026/10/A.HEIC"})
    v = decide_verdict(lst, report, checked_at=NOW)
    assert isinstance(v, Reconciled)
    assert v.verdict == "reconciled"


def test_missing_items_are_incomplete_not_unverified():
    lst = listing(["2026/10/A.HEIC"])
    report = compare("demo", lst, set())
    v = decide_verdict(lst, report, checked_at=NOW)
    assert isinstance(v, Incomplete)
    assert v.report.missing_count == 1


def test_incomplete_listing_can_never_reconcile():
    """Even with an empty difference — an unproven listing proves nothing."""
    lst = listing([], complete=False, notes=("listing ended mid-line",))
    report = compare("demo", lst, set())
    assert report.missing_count == 0
    v = decide_verdict(lst, report, checked_at=NOW)
    assert isinstance(v, Unverified)
    assert "mid-line" in v.reason


def test_unfiled_mirror_files_block_a_clean_verdict():
    """The only identified route to a FALSE reconciled.

    The listing omits items already in the mirror. An item downloaded but not
    yet filed is therefore absent from the listing AND from the catalog, so the
    difference reads empty while the archive genuinely lacks it.
    """
    lst = listing(["2026/10/A.HEIC"])
    report = compare("demo", lst, {"2026/10/A.HEIC"})
    v = decide_verdict(lst, report, checked_at=NOW, unfiled_in_mirror=3)
    assert isinstance(v, Unverified)
    assert "not yet" in v.reason and "3" in v.reason


def test_empty_library_reconciles_when_the_listing_completed():
    lst = listing([])
    v = decide_verdict(lst, compare("demo", lst, set()), checked_at=NOW)
    assert isinstance(v, Reconciled)
    assert v.listed == 0


def test_missing_comparison_is_unverified():
    v = decide_verdict(listing([]), None, checked_at=NOW)
    assert isinstance(v, Unverified)


# --- the mirror scan -------------------------------------------------------

def test_mirror_scan_counts_only_unrecorded_files(tmp_path):
    mirror = tmp_path / "m"
    (mirror / "2026" / "10").mkdir(parents=True)
    (mirror / "2026" / "10" / "A.HEIC").write_text("a")
    (mirror / "2026" / "10" / "B.HEIC").write_text("b")
    (mirror / ".DS_Store").write_text("noise")
    assert mirror_has_unfiled_files(mirror, {"2026/10/A.HEIC"}) == 1
    assert mirror_has_unfiled_files(mirror, {"2026/10/A.HEIC",
                                             "2026/10/B.HEIC"}) == 0


def test_absent_mirror_is_not_an_obstacle(tmp_path):
    assert mirror_has_unfiled_files(tmp_path / "nope", set()) == 0
