"""Unit tests: windowed pull state math (004 FR-015)."""

from archivist.icloud import WINDOW_OVERLAP_DAYS, pull_state_key, window_since


def test_state_key_shape():
    assert pull_state_key("matt-personal") == "pull_state:matt-personal"


def test_window_subtracts_overlap():
    assert WINDOW_OVERLAP_DAYS == 7
    assert window_since("2026-07-31T12:00:00") == "2026-07-24"


def test_window_crosses_month_boundary():
    assert window_since("2026-08-03T09:30:00") == "2026-07-27"


def test_window_output_is_date_only():
    # icloudpd --skip-created-before takes a date; time must be dropped.
    assert window_since("2026-07-31T23:59:59") == "2026-07-24"


# --- 005: the overlap must survive mode resolution (FR-009) ----------------

def test_overlap_constant_is_still_seven_days():
    """Guarded because 005 rewrote every caller of window_since()."""
    from archivist.icloud import WINDOW_OVERLAP_DAYS
    assert WINDOW_OVERLAP_DAYS == 7


def test_routine_and_reconcile_windows_both_carry_the_overlap():
    """No mode may bypass the overlap: it is what absorbs clock skew and
    late-arriving cloud items, and it is the only slack the watermark has."""
    from datetime import datetime, timedelta

    from archivist.icloud import WINDOW_OVERLAP_DAYS, window_since

    for stamp in ("2026-09-26T13:34:40", "2026-01-01T00:00:00",
                  "2026-03-08T02:30:00"):   # DST spring-forward in US Eastern
        expected = (datetime.fromisoformat(stamp)
                    - timedelta(days=WINDOW_OVERLAP_DAYS)).strftime("%Y-%m-%d")
        assert window_since(stamp) == expected


def test_window_since_crosses_a_year_boundary():
    assert window_since("2026-01-03T09:00:00") == "2025-12-27"


def test_window_since_handles_a_leap_day():
    assert window_since("2028-03-02T09:00:00") == "2028-02-24"
