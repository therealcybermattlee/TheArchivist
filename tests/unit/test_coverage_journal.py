"""Unit tests: the coverage record and its journal (005, data-model.md §3)."""

import json
from datetime import date, datetime

from archivist.coverage import (Advance, IngestOutcome, PullMode, Refuse,
                                append_record, build_record)
from archivist.icloud import CoverageProof

STARTED = datetime(2026, 9, 27, 10, 0, 0)
FINISHED = datetime(2026, 9, 27, 10, 2, 30)
PROOF = CoverageProof(enumeration_complete=True, reached_before_cutoff=True,
                      examined=500, downloaded=15, already_present=3,
                      session_present_before=True, parser_confident=True)
ING = IngestOutcome(ran=True, copied=15, skipped=3, failed=0)


def record(decision, **kw):
    return build_record(source="peepaw-cell", run_id="20260927-100000",
                        mode=kw.pop("mode", PullMode.ROUTINE_BOUNDED),
                        run_started=STARTED, run_finished=FINISHED,
                        window_since=date(2026, 9, 20), window_until=None,
                        scan_bound=500, proof=PROOF, ingest=ING,
                        decision=decision, **kw)


def test_advance_record_claims_run_start():
    r = record(Advance(claimed_through=STARTED))
    assert r.decision == "advance"
    assert r.claimed_through == STARTED.isoformat()
    assert r.reason is None


def test_refusal_record_carries_a_reason_and_no_claim():
    r = record(Refuse("scan bound (500) reached without clearing the window"))
    assert r.decision == "refuse"
    assert r.claimed_through is None
    assert "scan bound" in r.reason


def test_record_round_trips_through_json():
    payload = json.loads(record(Advance(claimed_through=STARTED)).to_json())
    assert payload["source"] == "peepaw-cell"
    assert payload["mode"] == "routine_bounded"
    assert payload["window_since"] == "2026-09-20"
    assert payload["window_until"] is None
    assert payload["examined"] == 500
    assert payload["downloaded"] == 15
    assert payload["ingest_copied"] == 15


def test_journal_appends_one_line_per_record(tmp_path):
    path = tmp_path / "logs" / "pull-20260927-100000.jsonl"
    append_record(path, record(Advance(claimed_through=STARTED)))
    append_record(path, record(Refuse("dry-run — no state written")))
    lines = path.read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["decision"] == "advance"
    assert json.loads(lines[1])["decision"] == "refuse"


def test_journal_creates_its_directory(tmp_path):
    path = tmp_path / "deep" / "nested" / "pull-x.jsonl"
    append_record(path, record(Advance(claimed_through=STARTED)))
    assert path.is_file()


def test_incident_shape_is_legible_in_the_journal():
    """The 2026-09-26 loss, had the journal existed, would have been a query.

    Zero downloads against a month-wide window with an unconfirmed enumeration
    is exactly the row an audit would look for.
    """
    bad_proof = CoverageProof(enumeration_complete=False, examined=0,
                              downloaded=0, parser_confident=False,
                              notes=("no completion signal in icloudpd output",))
    r = build_record(source="matt-public", run_id="20260926-133440",
                     mode=PullMode.ROUTINE_BOUNDED, run_started=STARTED,
                     run_finished=FINISHED, window_since=date(2026, 8, 19),
                     window_until=None, scan_bound=500, proof=bad_proof,
                     ingest=IngestOutcome(ran=False, reason="no-files"),
                     decision=Refuse("enumeration did not complete"))
    assert r.downloaded == 0
    assert r.enumeration_complete is False
    assert r.window_since == "2026-08-19"
    assert r.decision == "refuse"
