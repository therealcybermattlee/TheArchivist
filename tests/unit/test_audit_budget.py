"""Unit tests: repair now, or hand it to the operator? (006 US3)

Every uncertain case must resolve toward handing it over. A repair that runs
when it should not have is an unbounded transfer inside a routine command —
the exact behaviour feature 006 exists to remove.
"""

from datetime import date

from archivist.audit import Repair, Report, RepairPlan, decide_budget

GB = 1024 ** 3


def plan(estimated, *, scattered=False, ranges=1):
    return RepairPlan(
        ranges=tuple((date(2026, 9, 1), date(2026, 9, 30)) for _ in range(ranges)),
        expected_items=100, expected_missing=10,
        estimated_bytes=estimated, too_scattered=scattered)


def test_within_budget_repairs():
    assert isinstance(decide_budget(plan(2 * GB), 5 * GB), Repair)


def test_over_budget_reports():
    d = decide_budget(plan(9 * GB), 5 * GB)
    assert isinstance(d, Report)
    assert "exceeds" in d.reason


def test_exactly_at_budget_repairs():
    assert isinstance(decide_budget(plan(5 * GB), 5 * GB), Repair)


def test_unknown_estimate_is_treated_as_over_budget():
    """FR-030. No basis for an estimate must not read as "free"."""
    d = decide_budget(plan(None), 5 * GB)
    assert isinstance(d, Report)
    assert "could not be estimated" in d.reason


def test_scattered_gaps_are_never_swept_automatically():
    d = decide_budget(plan(1 * GB, scattered=True), 5 * GB)
    assert isinstance(d, Report)
    assert "full sweep" in d.reason


def test_auto_repair_disabled_reports_everything():
    d = decide_budget(plan(1 * GB), 5 * GB, auto_repair=False)
    assert isinstance(d, Report)
    assert "disabled" in d.reason


def test_an_empty_plan_is_nothing_to_do():
    d = decide_budget(RepairPlan(), 5 * GB)
    assert isinstance(d, Report)
    assert "nothing to repair" in d.reason
