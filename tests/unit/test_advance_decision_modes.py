"""Contract tests: per-mode advance requirements (005 §4.2, cases 15/16)."""

from datetime import date, datetime

from archivist.coverage import (Advance, IngestOutcome, PullMode, Refuse,
                                decide_advance, may_advance_reconcile)
from archivist.icloud import CoverageProof

STARTED = datetime(2026, 9, 27, 10, 0, 0)
WATERMARK = datetime(2026, 9, 20, 8, 0, 0)
COMPLETE = CoverageProof(enumeration_complete=True, parser_confident=True,
                         downloaded=1, session_present_before=True)
RAN = IngestOutcome(ran=True, copied=1)


def decide(mode, proof=COMPLETE, **kw):
    return decide_advance(mode, proof, kw.pop("ingest", RAN), applying=True,
                          run_started=STARTED, **kw)


# --- reconcile / bootstrap: completion is enough ---------------------------

def test_reconcile_advances_on_completion_alone():
    assert isinstance(decide(PullMode.RECONCILE), Advance)


def test_bootstrap_advances_on_completion_alone():
    assert isinstance(decide(PullMode.BOOTSTRAP_FULL), Advance)


def test_unbounded_modes_do_not_need_a_skip_line():
    """Only a BOUNDED scan needs proof it reached past the cutoff."""
    proof = CoverageProof(enumeration_complete=True, parser_confident=True,
                          reached_before_cutoff=False, downloaded=1)
    assert isinstance(decide(PullMode.RECONCILE, proof=proof), Advance)


# --- case 15/16: explicit --since ------------------------------------------

def test_since_at_or_before_the_watermark_advances():
    d = decide(PullMode.EXPLICIT_SINCE, previous_watermark=WATERMARK,
               window_since=date(2026, 8, 19))
    assert isinstance(d, Advance)


def test_since_after_the_watermark_refuses_and_names_the_span():
    d = decide(PullMode.EXPLICIT_SINCE, previous_watermark=WATERMARK,
               window_since=date(2026, 9, 25))
    assert isinstance(d, Refuse)
    assert "2026-09-20..2026-09-25" in d.reason


def test_since_with_no_previous_watermark_advances():
    d = decide(PullMode.EXPLICIT_SINCE, previous_watermark=None,
               window_since=date(2020, 1, 1))
    assert isinstance(d, Advance)


def test_since_exactly_at_the_watermark_advances():
    d = decide(PullMode.EXPLICIT_SINCE, previous_watermark=WATERMARK,
               window_since=WATERMARK.date())
    assert isinstance(d, Advance)


# --- §4.4 reconciliation watermark -----------------------------------------

def test_only_unbounded_modes_reconcile():
    adv = Advance(claimed_through=STARTED)
    assert may_advance_reconcile(PullMode.RECONCILE, adv, RAN)
    assert may_advance_reconcile(PullMode.BOOTSTRAP_FULL, adv, RAN)
    assert not may_advance_reconcile(PullMode.ROUTINE_BOUNDED, adv, RAN)
    assert not may_advance_reconcile(PullMode.EXPLICIT_SINCE, adv, RAN)


def test_a_refused_sweep_does_not_reconcile():
    assert not may_advance_reconcile(
        PullMode.RECONCILE, Refuse("enumeration did not complete"), RAN)


def test_a_sweep_with_ingest_failures_does_not_reconcile():
    assert not may_advance_reconcile(
        PullMode.RECONCILE, Advance(claimed_through=STARTED),
        IngestOutcome(ran=True, copied=5, failed=1))
