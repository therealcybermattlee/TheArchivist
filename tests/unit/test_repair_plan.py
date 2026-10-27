"""Unit tests: turning a gap into date-bounded ranges (006 US3)."""

from datetime import date

from archivist.audit import (GapReport, RepairPlan, SCATTER_CUTOFF_MONTHS,
                             plan_repair)

MEDIAN = 4 * 1024 * 1024      # 4 MB, close to the observed 3.8 MB/file


def report(by_month, undated=0):
    missing = tuple(f"{m.replace('-', '/')}/IMG_{i}.HEIC"
                    for m, n in by_month.items() for i in range(n))
    return GapReport(source="demo", listed=100, archived=90,
                     missing=missing, by_month=dict(by_month), undated=undated)


def test_single_month_becomes_one_inclusive_span():
    plan = plan_repair(report({"2026-09": 10}), median_size=MEDIAN)
    assert plan.ranges == ((date(2026, 9, 1), date(2026, 9, 30)),)
    assert plan.expected_missing == 10


def test_consecutive_months_merge_into_one_range():
    plan = plan_repair(report({"2026-09": 5, "2026-10": 5}), median_size=MEDIAN)
    assert plan.ranges == ((date(2026, 9, 1), date(2026, 10, 31)),)


def test_non_consecutive_months_stay_separate():
    plan = plan_repair(report({"2026-01": 1, "2026-09": 1}), median_size=MEDIAN)
    assert len(plan.ranges) == 2


def test_year_boundary_merges():
    plan = plan_repair(report({"2025-12": 1, "2026-01": 1}), median_size=MEDIAN)
    assert plan.ranges == ((date(2025, 12, 1), date(2026, 1, 31)),)


def test_estimate_covers_everything_in_the_range_not_just_the_missing():
    """A date-bounded fetch cannot discriminate: it takes dates, not items.

    Already-held items in those periods still cross the wire before being
    recognized and discarded, so the estimate must include them or it
    understates the very cost the budget exists to cap.
    """
    plan = plan_repair(report({"2026-09": 10}), median_size=MEDIAN,
                       archived_by_month={"2026-09": 90})
    assert plan.expected_missing == 10
    assert plan.expected_items == 100
    assert plan.estimated_bytes == 100 * MEDIAN


def test_unknown_median_yields_no_estimate():
    plan = plan_repair(report({"2026-09": 10}), median_size=None)
    assert plan.estimated_bytes is None


def test_scatter_is_carried_into_the_plan():
    by_month = {f"2026-{m:02d}": 1 for m in range(1, 13)}
    plan = plan_repair(report(by_month), median_size=MEDIAN)
    assert plan.too_scattered


def test_no_months_yields_an_empty_plan():
    plan = plan_repair(GapReport(source="demo"), median_size=MEDIAN)
    assert plan.is_empty
    assert plan.ranges == ()


def test_undated_items_do_not_create_a_range():
    """An item with no readable period cannot be fetched by date bound.

    It stays counted in the report so the totals hold, but it cannot drive a
    range — which is why a gap of only undated items plans nothing.
    """
    plan = plan_repair(report({}, undated=3), median_size=MEDIAN)
    assert plan.is_empty
