"""Contract tests: universal preconditions of the advance decision (005 §4.1).

Cases 9-12 of contracts/coverage-proof.md §6. Order matters — the first
failing precondition names the refusal the operator reads.
"""

from datetime import datetime

import pytest

from archivist.coverage import (Advance, IngestOutcome, PullMode, Refuse,
                                decide_advance)
from archivist.icloud import CoverageProof

STARTED = datetime(2026, 9, 27, 10, 0, 0)
GOOD = CoverageProof(enumeration_complete=True, reached_before_cutoff=True,
                     examined=100, downloaded=5, session_present_before=True,
                     parser_confident=True)
RAN = IngestOutcome(ran=True, copied=5, skipped=0, failed=0)


def decide(mode=PullMode.ROUTINE_BOUNDED, proof=GOOD, ingest=RAN,
           applying=True, **kw):
    return decide_advance(mode, proof, ingest, applying=applying,
                          run_started=STARTED, scan_bound=500, **kw)


def test_the_happy_path_advances():
    d = decide()
    assert isinstance(d, Advance)
    assert d.claimed_through == STARTED


# --- case 11: dry-run ------------------------------------------------------

def test_dry_run_never_advances():
    d = decide(applying=False)
    assert isinstance(d, Refuse)
    assert "dry-run" in d.reason


# --- case 10: ingest-only --------------------------------------------------

def test_no_download_never_advances():
    d = decide(mode=PullMode.INGEST_ONLY)
    assert isinstance(d, Refuse)
    assert "--no-download" in d.reason


# --- case 9: narrow --------------------------------------------------------

def test_narrow_never_advances():
    d = decide(mode=PullMode.NARROW)
    assert isinstance(d, Refuse)
    assert "did not cover the window" in d.reason


def test_narrow_refuses_even_with_perfect_evidence():
    """A narrow pull can be flawless and still not have covered the window.

    This is the 2026-09-26 defect in its original form: the old guard let
    `--recent N --apply` move the watermark to the present.
    """
    d = decide(mode=PullMode.NARROW, proof=GOOD, ingest=RAN)
    assert isinstance(d, Refuse)


# --- unconfirmed download --------------------------------------------------

def test_unconfirmed_proof_refuses_and_quotes_the_notes():
    proof = CoverageProof(enumeration_complete=True, parser_confident=False,
                          notes=("icloudpd exited 1",))
    d = decide(proof=proof)
    assert isinstance(d, Refuse)
    assert "could not be confirmed" in d.reason
    assert "exited 1" in d.reason


def test_incomplete_enumeration_refuses():
    proof = CoverageProof(enumeration_complete=False, parser_confident=True)
    d = decide(proof=proof)
    assert isinstance(d, Refuse)
    assert "enumeration did not complete" in d.reason


# --- case 12: ingest failures ----------------------------------------------

def test_ingest_failures_refuse():
    d = decide(ingest=IngestOutcome(ran=True, copied=3, failed=2))
    assert isinstance(d, Refuse)
    assert "2 file(s) failed to copy" in d.reason


# --- precedence ------------------------------------------------------------

def test_dry_run_is_checked_before_everything_else():
    d = decide(applying=False, mode=PullMode.NARROW,
               proof=CoverageProof(parser_confident=False))
    assert "dry-run" in d.reason


@pytest.mark.parametrize("mode", list(PullMode))
def test_no_mode_can_advance_on_a_default_proof(mode):
    """A proof nobody filled in must never authorise a watermark move."""
    d = decide(mode=mode, proof=CoverageProof())
    assert isinstance(d, Refuse)
