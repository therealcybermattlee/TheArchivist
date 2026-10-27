"""Reconciliation by enumeration diff: asking instead of downloading.

A coverage watermark is a claim about CREATED time, but a cloud photo library is
mutable in created time. An asset created in 2019 and added to the library today
is filtered out by "skip items created before <watermark>" — and by every future
run, because the watermark only moves forward. Backdated additions are much of
the point of a family archive, so something has to re-examine ground already
claimed. That is what reconciliation is for.

Before 006 it did that by re-downloading the library, because the working mirror
is pruned and the downloader had nothing local to compare against: ~246 GB and
several hours across four accounts, paid unconditionally, to discover 19 new
files in September 2026. This module replaces the download with a question. The
library can be listed without transferring media, the catalog already records
the exact path it assigned every item it ever filed, and the difference between
those two sets IS the reconciliation answer.

THE ONE INVARIANT
-----------------
Everything here is arranged around a deliberate asymmetry:

    for every item genuinely absent from the archive, it MUST be reported
    missing; items that are in fact archived MAY be reported missing.

A false "missing" costs a redundant fetch that the ingest hash check throws
away — bandwidth, nothing worse. A false "present" lets a source be called
reconciled when it is not, advancing a watermark past items no future window
will ever look at again. That is the September 2026 failure wearing a new hat,
so every judgement call in this module resolves toward "missing".

Three measured causes of over-reporting are accepted as the price (see
contracts/gap-report.md §4); none of them can produce the opposite error,
because each arises from the archive holding an item under a name the listing
does not produce — which makes an item look absent, never look present.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from .icloud import Listing

#: Distinct months beyond which period-bounded repair stops being worthwhile and
#: starts approximating a full sweep. A starting value, revisable once measured.
SCATTER_CUTOFF_MONTHS = 8

#: A mirror-relative path begins with the download folder structure, {:%Y/%m}.
_RE_MONTH = re.compile(r"^(\d{4})/(\d{2})/")


def month_of(relative_path: str) -> str | None:
    """"2026/10/IMG_1.HEIC" -> "2026-10"; None when the path carries no month.

    None is reported rather than dropped: an item whose period cannot be read
    still has to be counted somewhere, or the totals stop adding up and a
    missing item hides in the discrepancy.
    """
    m = _RE_MONTH.match(relative_path)
    return f"{m.group(1)}-{m.group(2)}" if m else None


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GapReport:
    """One comparison's outcome. Deliberately an upper bound on what is missing."""

    source: str
    listed: int = 0
    archived: int = 0
    missing: tuple[str, ...] = ()
    by_month: dict[str, int] = field(default_factory=dict)
    undated: int = 0
    #: Archived items the library no longer lists. Diagnostic ONLY — the archive
    #: never deletes to match a source (Principle I), so this never affects a
    #: verdict. Reported because a sudden jump is worth an operator's attention.
    not_in_listing: int = 0

    @property
    def missing_count(self) -> int:
        return len(self.missing)

    @property
    def months_affected(self) -> int:
        return len(self.by_month)

    @property
    def too_scattered(self) -> bool:
        return self.months_affected > SCATTER_CUTOFF_MONTHS

    def month_lines(self) -> list[tuple[str, int]]:
        return sorted(self.by_month.items())


def compare(source: str, listing: Listing, archived: set[str]) -> GapReport:
    """Set-difference a listing against the archive's recorded paths.

    Both sides arrive already relative to the source's mirror root, so an
    absolute path change cannot masquerade as a missing item, and the caller
    has already restricted `archived` to this source's rows.
    """
    missing = sorted(listing.paths - archived)
    by_month: dict[str, int] = {}
    undated = 0
    for rel in missing:
        m = month_of(rel)
        if m is None:
            undated += 1
        else:
            by_month[m] = by_month.get(m, 0) + 1
    return GapReport(
        source=source,
        listed=len(listing.paths),
        archived=len(archived),
        missing=tuple(missing),
        by_month=by_month,
        undated=undated,
        not_in_listing=len(archived - listing.paths),
    )


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Reconciled:
    listed: int
    checked_at: datetime
    verdict = "reconciled"
    report: None = None
    reason: None = None


@dataclass(frozen=True)
class Incomplete:
    report: GapReport
    verdict = "incomplete"
    reason: None = None


@dataclass(frozen=True)
class Unverified:
    reason: str
    verdict = "unverified"
    report: None = None


Verdict = Reconciled | Incomplete | Unverified


def decide_verdict(listing: Listing, report: GapReport | None, *,
                   checked_at: datetime,
                   unfiled_in_mirror: int = 0) -> Verdict:
    """Map (listing, comparison) to a verdict. See contracts/gap-report.md §5.

    Three states rather than a boolean, because "nothing missing", "things
    missing" and "could not tell" are operationally different and collapsing
    the third into either of the others is precisely how coverage was lost.
    """
    if not listing.complete:
        return Unverified(f"listing did not complete: {listing.note_text()}")
    if unfiled_in_mirror:
        # The only identified route to a FALSE "reconciled". The listing omits
        # items already in the mirror, so an item downloaded but not yet filed
        # is absent from the listing AND from the catalog, and the difference
        # reads empty while the archive is genuinely missing it.
        return Unverified(
            f"{unfiled_in_mirror} file(s) in the working mirror are not yet "
            f"filed — ingest them first, then re-audit")
    if report is None:
        return Unverified("no comparison was made")
    if report.missing_count:
        return Incomplete(report)
    return Reconciled(listed=report.listed, checked_at=checked_at)


def mirror_has_unfiled_files(mirror: Path, archived: set[str]) -> int:
    """Count files sitting in the mirror that the catalog does not record.

    Cheap: the mirror is normally empty or nearly so, because pruning is what
    makes this whole feature necessary in the first place.
    """
    if not mirror.is_dir():
        return 0
    unfiled = 0
    for p in mirror.rglob("*"):
        if not p.is_file() or p.name.startswith("."):
            continue
        if str(p.relative_to(mirror)) not in archived:
            unfiled += 1
    return unfiled


def is_audit_due(audited_through: str | None, now: datetime,
                 interval_days: int) -> bool:
    """Never audited, an unreadable timestamp, or older than the interval."""
    if not audited_through:
        return True
    try:
        last = datetime.fromisoformat(audited_through)
    except ValueError:
        return True
    return (now - last) >= timedelta(days=interval_days)


# ---------------------------------------------------------------------------
# Repair planning
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepairPlan:
    ranges: tuple[tuple[date, date], ...] = ()
    expected_items: int = 0
    expected_missing: int = 0
    estimated_bytes: int | None = None
    too_scattered: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.ranges


def _month_bounds(month: str) -> tuple[date, date]:
    year, mon = (int(x) for x in month.split("-"))
    first = date(year, mon, 1)
    last = (date(year + (mon == 12), (mon % 12) + 1, 1) - timedelta(days=1))
    return first, last


def _merge_months(months: list[str]) -> list[tuple[date, date]]:
    """Collapse consecutive months into inclusive date spans."""
    spans: list[tuple[date, date]] = []
    for month in sorted(months):
        first, last = _month_bounds(month)
        if spans and (spans[-1][1] + timedelta(days=1)) == first:
            spans[-1] = (spans[-1][0], last)
        else:
            spans.append((first, last))
    return spans


def plan_repair(report: GapReport, *, median_size: int | None,
                archived_by_month: dict[str, int] | None = None,
                cutoff: int = SCATTER_CUTOFF_MONTHS) -> RepairPlan:
    """Which periods to re-fetch, and what that is expected to cost.

    The estimate covers EVERY item in the affected periods, not only the
    missing ones, because a date-bounded fetch cannot discriminate: the
    downloader takes date bounds, never an item list. Those extra items are
    recognized by hash on arrival and discarded, but they cross the wire, so
    pretending otherwise would understate the cost the budget exists to cap.
    """
    months = sorted(report.by_month)
    if not months:
        return RepairPlan()

    scattered = len(months) > cutoff
    spans = tuple(_merge_months(months))
    expected_missing = sum(report.by_month[m] for m in months)
    extra = sum((archived_by_month or {}).get(m, 0) for m in months)
    expected_items = expected_missing + extra

    # An unknown median means no basis for an estimate. Returning None (rather
    # than guessing, or defaulting to zero) is what lets decide_budget refuse:
    # an unestimatable repair must read as too large, never as free.
    estimated = None if median_size is None else expected_items * median_size

    return RepairPlan(
        ranges=spans,
        expected_items=expected_items,
        expected_missing=expected_missing,
        estimated_bytes=estimated,
        too_scattered=scattered,
    )


@dataclass(frozen=True)
class Repair:
    plan: RepairPlan
    decision = "repair"
    reason: None = None


@dataclass(frozen=True)
class Report:
    plan: RepairPlan
    reason: str
    decision = "report"


BudgetDecision = Repair | Report


def decide_budget(plan: RepairPlan, budget_bytes: int, *,
                  auto_repair: bool = True) -> BudgetDecision:
    """Fetch now, or hand it to the operator? Fails toward handing it over."""
    if plan.is_empty:
        return Report(plan, "nothing to repair")
    if not auto_repair:
        return Report(plan, "automatic repair is disabled")
    if plan.too_scattered:
        return Report(
            plan,
            f"missing items span {len(plan.ranges)} period(s) across more than "
            f"{SCATTER_CUTOFF_MONTHS} months — a full sweep is the remaining "
            f"option, and is not started automatically")
    if plan.estimated_bytes is None:
        return Report(plan, "transfer size could not be estimated — "
                            "treating as over budget")
    if plan.estimated_bytes > budget_bytes:
        return Report(
            plan,
            f"estimated {plan.estimated_bytes / 1024**3:.2f} GB exceeds the "
            f"{budget_bytes / 1024**3:.2f} GB repair budget")
    return Repair(plan)
