"""Coverage watermarks: what the tool is willing to claim it archived.

A coverage watermark is the tool's assertion that a source is complete through
an instant. Before 005 that assertion was inferred from a process exit code
plus the absence of ingest failures, and a run that fetched nothing while
exiting cleanly advanced it just as happily as one that did the work. On
2026-09-26 that cost real coverage: two sources advanced to the present having
downloaded nothing, putting a month of media outside every future window.

So the advance is now a decision with evidence behind it, taken in one place
and recorded with what it claimed. `decide_advance` maps (mode, proof, ingest
outcome) to either an Advance carrying the interval claimed, or a Refuse
carrying the reason the operator will read. Everything about that mapping is
in contracts/coverage-proof.md §4; this module is its implementation.

Ordering matters: the journal entry is written BEFORE the catalog is updated
(constitution Principle IV). An interruption between the two leaves the journal
authoritative and the watermark stale, which re-covers ground on the next run
rather than losing it.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path

from .icloud import CoverageProof


class PullMode(str, Enum):
    """How a run was bounded — resolved once, then carried.

    Making the mode explicit is what keeps FR-004 structural rather than
    remembered: NARROW cannot advance a coverage watermark because the decision
    table has no path for it, not because a caller checked a flag.
    """

    ROUTINE_BOUNDED = "routine_bounded"
    RECONCILE = "reconcile"
    BOOTSTRAP_FULL = "bootstrap_full"
    EXPLICIT_SINCE = "explicit_since"
    NARROW = "narrow"
    INGEST_ONLY = "ingest_only"


#: Modes that sweep the whole library and so may also advance the
#: reconciliation watermark (contracts/coverage-proof.md §4.4).
UNBOUNDED_MODES = (PullMode.RECONCILE, PullMode.BOOTSTRAP_FULL)


def resolve_mode(*, no_download: bool, recent: int | None, until_found: int | None,
                 until: str | None, full: bool, since: str | None,
                 reconcile_due: bool) -> PullMode:
    """Resolve the run mode from the CLI arguments (data-model.md §4).

    Order matters. `--no-download` wins over everything (nothing was attempted);
    any count/end-date bound makes the run NARROW regardless of what else was
    asked for, because such a run cannot have covered the window.
    """
    if no_download:
        return PullMode.INGEST_ONLY
    if recent is not None or until_found is not None or until is not None:
        return PullMode.NARROW
    if full:
        return PullMode.BOOTSTRAP_FULL
    if since is not None:
        return PullMode.EXPLICIT_SINCE
    return PullMode.RECONCILE if reconcile_due else PullMode.ROUTINE_BOUNDED


@dataclass(frozen=True)
class IngestOutcome:
    """What the ingest stage did — or why it did nothing.

    `ran` False distinguishes "ingest never executed" from "ingest executed and
    copied nothing". The old code returned a bare None for both, and the
    advance guard short-circuited on it: that is the hole the 2026-09-26 loss
    went through.
    """

    ran: bool = False
    reason: str = ""          # when ran is False: "no-files" | "not-a-directory"
    copied: int = 0
    skipped: int = 0
    failed: int = 0
    copied_bytes: int = 0
    #: Archived files whose bytes disagreed with the catalog during planning.
    #: Non-zero means the archive needs assessing BEFORE anything is pruned.
    integrity_warnings: int = 0

    @property
    def found_files(self) -> bool:
        return self.ran and (self.copied + self.skipped) > 0


@dataclass(frozen=True)
class Advance:
    claimed_through: datetime

    decision = "advance"
    reason: str | None = None


@dataclass(frozen=True)
class Refuse:
    reason: str

    decision = "refuse"
    claimed_through: None = None


Decision = Advance | Refuse


def decide_advance(mode: PullMode, proof: CoverageProof, ingest: IngestOutcome, *,
                   applying: bool, run_started: datetime,
                   previous_watermark: datetime | None = None,
                   window_since: date | None = None,
                   scan_bound: int | None = None,
                   watermark_unreadable: str | None = None) -> Decision:
    """May this run's coverage watermark advance? See contracts §4.

    Universal preconditions first, in order — the first failure names the
    refusal. Then the per-mode requirement. Every refusal reason is operator-
    facing text (FR-008, FR-017).
    """
    # --- §4.1 universal preconditions ------------------------------------
    if not applying:
        return Refuse("dry-run — no state written")
    if mode is PullMode.INGEST_ONLY:
        return Refuse("--no-download: coverage not attempted")
    if mode is PullMode.NARROW:
        return Refuse("bounded by an explicit count or end date — "
                      "did not cover the window")
    if not proof.parser_confident:
        return Refuse(f"download step could not be confirmed: {proof.note_text()}")
    if not proof.enumeration_complete:
        return Refuse("enumeration did not complete")
    if ingest.failed:
        return Refuse(f"{ingest.failed} file(s) failed to copy")
    if watermark_unreadable is not None:
        # A watermark that exists but cannot be parsed is not the same as no
        # watermark. Treating it as absent would skip the FR-005 span check
        # below and let `--since <later date>` overwrite it, permanently hiding
        # whatever it was protecting.
        return Refuse(
            f"existing watermark {watermark_unreadable!r} is unreadable — "
            f"repair or clear it before advancing")

    # --- §4.2 per-mode requirements --------------------------------------
    if mode is PullMode.ROUTINE_BOUNDED and not proof.reached_before_cutoff:
        bound = scan_bound if scan_bound is not None else "?"
        return Refuse(
            f"scan bound ({bound}) reached without clearing the window — "
            f"raise scan_bound for this source")
    if mode is PullMode.EXPLICIT_SINCE and previous_watermark is not None:
        if window_since is not None and window_since > previous_watermark.date():
            return Refuse(
                f"--since {window_since.isoformat()} starts after the current "
                f"watermark {previous_watermark.date().isoformat()} — would "
                f"skip {previous_watermark.date().isoformat()}.."
                f"{window_since.isoformat()}")

    # --- §4.3 null ingest result -----------------------------------------
    # Not a refusal in itself: a genuinely quiet source downloads nothing and
    # has nothing to ingest. It is PROVEN empty (complete enumeration, nothing
    # downloaded, nothing in the mirror), never assumed empty. A run that
    # fetched nothing because it could not do its work has already been refused
    # above, by parser_confident or enumeration_complete.
    if not ingest.found_files and (proof.downloaded or ingest.failed):
        return Refuse("downloaded items never reached ingest")

    return Advance(claimed_through=run_started)


def may_advance_reconcile(mode: PullMode, decision: Decision,
                          ingest: IngestOutcome) -> bool:
    """§4.4 — only an unbounded sweep that actually covered may reconcile."""
    return (mode in UNBOUNDED_MODES
            and isinstance(decision, Advance)
            and ingest.failed == 0)


# ---------------------------------------------------------------------------
# Coverage record + journal
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CoverageRecord:
    """One source's outcome in one applying run (data-model.md §3)."""

    source: str
    run_id: str
    mode: str
    run_started: str
    run_finished: str
    window_since: str | None
    window_until: str | None
    scan_bound: int | None
    enumeration_complete: bool
    reached_before_cutoff: bool
    examined: int
    downloaded: int
    already_present: int
    ingest_copied: int
    ingest_skipped: int
    ingest_failed: int
    decision: str
    reason: str | None
    claimed_through: str | None

    def to_json(self) -> str:
        return json.dumps(asdict(self))


def build_record(*, source: str, run_id: str, mode: PullMode,
                 run_started: datetime, run_finished: datetime,
                 window_since: date | str | None, window_until: date | str | None,
                 scan_bound: int | None, proof: CoverageProof,
                 ingest: IngestOutcome, decision: Decision) -> CoverageRecord:
    def _d(v) -> str | None:
        if v is None:
            return None
        return v.isoformat() if isinstance(v, date) else str(v)

    return CoverageRecord(
        source=source,
        run_id=run_id,
        mode=mode.value,
        run_started=run_started.isoformat(),
        run_finished=run_finished.isoformat(),
        window_since=_d(window_since),
        window_until=_d(window_until),
        scan_bound=scan_bound,
        enumeration_complete=proof.enumeration_complete,
        reached_before_cutoff=proof.reached_before_cutoff,
        examined=proof.examined,
        downloaded=proof.downloaded,
        already_present=proof.already_present,
        ingest_copied=ingest.copied,
        ingest_skipped=ingest.skipped,
        ingest_failed=ingest.failed,
        decision=decision.decision,
        reason=decision.reason,
        claimed_through=(decision.claimed_through.isoformat()
                         if isinstance(decision, Advance) else None),
    )


def append_record(journal_path: Path, record: CoverageRecord) -> None:
    """Append one record durably. Called BEFORE any catalog write.

    fsync, not just flush: the catalog commit that follows is fsynced by SQLite,
    so a flush-only journal could lose its record to a power cut while the
    watermark survived — a watermark with no journal behind it, which is the
    inversion Principle IV exists to prevent.
    """
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    with journal_path.open("a", encoding="utf-8") as fh:
        fh.write(record.to_json() + "\n")
        fh.flush()
        os.fsync(fh.fileno())
