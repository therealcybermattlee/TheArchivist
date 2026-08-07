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
