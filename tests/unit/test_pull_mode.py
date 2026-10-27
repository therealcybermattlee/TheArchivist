"""Unit tests: PullMode resolution (005, data-model.md §4).

Making the mode explicit is what keeps FR-004 structural: a NARROW run cannot
advance a coverage watermark because the decision table has no path for it, not
because somebody remembered to check a flag.
"""

import pytest

from archivist.coverage import PullMode, resolve_mode

BASE = dict(no_download=False, recent=None, until_found=None, until=None,
            full=False, since=None, reconcile_due=False)


def mode(**kw) -> PullMode:
    return resolve_mode(**{**BASE, **kw})


def test_routine_bounded_is_the_default():
    assert mode() is PullMode.ROUTINE_BOUNDED


def test_reconcile_when_due():
    assert mode(reconcile_due=True) is PullMode.RECONCILE


def test_full_is_bootstrap():
    assert mode(full=True) is PullMode.BOOTSTRAP_FULL


def test_explicit_since():
    assert mode(since="2026-08-19") is PullMode.EXPLICIT_SINCE


@pytest.mark.parametrize("kw", [
    {"recent": 50},
    {"until_found": 10},
    {"until": "2026-01-01"},
])
def test_every_narrow_trigger(kw):
    assert mode(**kw) is PullMode.NARROW


def test_no_download_wins_over_everything():
    assert mode(no_download=True, full=True, recent=5) is PullMode.INGEST_ONLY


def test_narrow_wins_over_full_and_since():
    """A count bound makes the run narrow whatever else was asked for."""
    assert mode(recent=5, full=True) is PullMode.NARROW
    assert mode(until="2026-01-01", since="2020-01-01") is PullMode.NARROW


def test_narrow_wins_over_reconcile_due():
    assert mode(recent=5, reconcile_due=True) is PullMode.NARROW
