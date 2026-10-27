"""Contract tests: the null-ingest discrimination (005 §4.3, cases 13/14).

This is the crux. A run that fetched nothing and a run that COULD not fetch
look identical from the ingest side — both leave an empty mirror and a null
ingest result. Discriminating them is the whole feature:

  * proven empty  -> complete enumeration, nothing downloaded  -> advance
  * did nothing   -> no completion signal                      -> refuse

On 2026-09-26 the old guard short-circuited on the null result and advanced
both. Case 14 is that exact shape; if it ever passes, the tool has regressed.
"""

from datetime import datetime

from archivist.coverage import (Advance, IngestOutcome, PullMode, Refuse,
                                decide_advance)
from archivist.icloud import CoverageProof

STARTED = datetime(2026, 9, 27, 10, 0, 0)
NO_FILES = IngestOutcome(ran=False, reason="no-files")


def decide(proof, ingest=NO_FILES, mode=PullMode.RECONCILE):
    return decide_advance(mode, proof, ingest, applying=True,
                          run_started=STARTED, scan_bound=500)


# --- case 13: a genuinely quiet source -------------------------------------

def test_quiet_source_is_proven_empty_and_advances():
    proof = CoverageProof(enumeration_complete=True, parser_confident=True,
                          examined=412, downloaded=0, session_present_before=True)
    assert isinstance(decide(proof), Advance)


def test_quiet_bounded_source_still_needs_its_window_cleared():
    proof = CoverageProof(enumeration_complete=True, parser_confident=True,
                          reached_before_cutoff=True, downloaded=0)
    assert isinstance(decide(proof, mode=PullMode.ROUTINE_BOUNDED), Advance)


# --- case 14: THE INCIDENT -------------------------------------------------

def test_incident_shape_refuses():
    """2026-09-26: download reported nothing, mirror empty, zero ingest failures.

    The old condition at cli.py:828 passed on exactly this and advanced two
    sources a month past their real coverage.
    """
    proof = CoverageProof(enumeration_complete=False, parser_confident=False,
                          examined=0, downloaded=0,
                          notes=("no completion signal in icloudpd output",))
    d = decide(proof)
    assert isinstance(d, Refuse)
    assert "could not be confirmed" in d.reason


def test_incident_shape_refuses_even_when_the_exit_code_was_clean():
    """An exit code says the process ran, not that it covered anything."""
    proof = CoverageProof(enumeration_complete=False, parser_confident=True,
                          exit_code=0, downloaded=0)
    d = decide(proof)
    assert isinstance(d, Refuse)
    assert "enumeration did not complete" in d.reason


def test_dead_session_refuses_before_anything_else_happens():
    proof = CoverageProof(session_present_before=False, parser_confident=False,
                          notes=("no session artifact before the run",))
    d = decide(proof)
    assert isinstance(d, Refuse)
    assert "session artifact" in d.reason


# --- downloads that never reached ingest -----------------------------------

def test_downloads_that_vanished_before_ingest_refuse():
    """Items were fetched but ingest found nothing: something is wrong."""
    proof = CoverageProof(enumeration_complete=True, parser_confident=True,
                          downloaded=12)
    d = decide(proof, ingest=NO_FILES)
    assert isinstance(d, Refuse)
    assert "never reached ingest" in d.reason


def test_not_a_directory_is_treated_like_no_files():
    proof = CoverageProof(enumeration_complete=True, parser_confident=True,
                          downloaded=0)
    d = decide(proof, ingest=IngestOutcome(ran=False, reason="not-a-directory"))
    assert isinstance(d, Advance)
