"""Unit tests: the reconciliation staleness predicate (005 FR-012/FR-016)."""

from datetime import datetime, timedelta

from archivist.icloud import DEFAULT_RECONCILE_INTERVAL_DAYS, is_reconcile_due

NOW = datetime(2026, 9, 27, 10, 0, 0)


def test_absent_watermark_is_due():
    """A source that has never been swept is exactly what reconciliation is for.

    This is also what makes the first run after deployment repair the existing
    2026-09-26 holes without the operator knowing they exist.
    """
    assert is_reconcile_due(None, NOW)
    assert is_reconcile_due("", NOW)


def test_fresh_watermark_is_not_due():
    assert not is_reconcile_due((NOW - timedelta(days=3)).isoformat(), NOW)


def test_stale_watermark_is_due():
    assert is_reconcile_due((NOW - timedelta(days=31)).isoformat(), NOW)


def test_boundary_is_strictly_greater_than_the_interval():
    exactly = (NOW - timedelta(days=DEFAULT_RECONCILE_INTERVAL_DAYS)).isoformat()
    assert not is_reconcile_due(exactly, NOW)
    just_over = (NOW - timedelta(days=30, seconds=1)).isoformat()
    assert is_reconcile_due(just_over, NOW)


def test_interval_is_configurable():
    ten_days_ago = (NOW - timedelta(days=10)).isoformat()
    assert not is_reconcile_due(ten_days_ago, NOW, interval_days=30)
    assert is_reconcile_due(ten_days_ago, NOW, interval_days=7)


def test_unparseable_watermark_is_due():
    """Junk is not evidence of freshness — fail toward doing the work."""
    assert is_reconcile_due("not-a-date", NOW)
