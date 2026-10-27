"""Contract tests: the window-cleared determination (005 cases 7/8, FR-022/023).

Under --recent the iterator is truncated, so the loop still ends normally and
the completion line still appears. Only a skip-before-cutoff line proves the
scan actually reached past the window — without it, a bounded run that hit its
ceiling is indistinguishable from one that cleared the window, and advancing
would reopen the very gap this feature exists to close.
"""

from datetime import datetime

from archivist.coverage import (Advance, IngestOutcome, PullMode, Refuse,
                                decide_advance)
from archivist.icloud import CoverageProof

STARTED = datetime(2026, 9, 27, 10, 0, 0)
RAN = IngestOutcome(ran=True, copied=1)


def decide(reached: bool, scan_bound=500):
    proof = CoverageProof(enumeration_complete=True, parser_confident=True,
                          reached_before_cutoff=reached, downloaded=1,
                          examined=scan_bound, session_present_before=True)
    return decide_advance(PullMode.ROUTINE_BOUNDED, proof, RAN, applying=True,
                          run_started=STARTED, scan_bound=scan_bound)


# --- case 7 ---------------------------------------------------------------

def test_window_cleared_advances():
    assert isinstance(decide(reached=True), Advance)


# --- case 8 ---------------------------------------------------------------

def test_window_not_cleared_refuses():
    d = decide(reached=False)
    assert isinstance(d, Refuse)
    assert "scan bound" in d.reason


def test_refusal_names_the_bound_and_the_setting_to_raise():
    """FR-023: the operator must be told what to change, not just that it failed."""
    d = decide(reached=False, scan_bound=250)
    assert "250" in d.reason
    assert "scan_bound" in d.reason
