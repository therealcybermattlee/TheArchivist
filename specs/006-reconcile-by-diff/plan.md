# Implementation Plan: Reconciliation by Enumeration Diff

**Branch**: `006-reconcile-by-diff` | **Date**: 2026-10-27 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-reconcile-by-diff/spec.md`

## Summary

Reconciliation stops being a download and becomes a question.

`icloudpd --only-print-filenames` enumerates a library and prints the local path
it *would* write for every item, transferring no media. The catalog already
stores that exact path string in `assets.original_path`, permanently, surviving
the prune that empties the mirror. Set-differencing the two answers "is anything
in this library missing from the archive?" outright.

An empty difference, from a listing that provably completed, advances
`reconcile_state:<source>` with zero bytes moved. A non-empty difference becomes
a `GapReport` — count, the items themselves, and their clustering by month —
which either drives a date-range repair within a configured budget, or is
reported for the operator to act on.

The whole design turns on one asymmetry: **the comparison may over-report but
must never under-report.** Duplicate-path and collision-suffix effects inflate
the missing count, costing a redundant fetch that the ingest hash check throws
away. Under-reporting would mark a source reconciled while it is not, which is
the September failure in a new costume.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: typer (CLI), icloudpd 1.32.3 (external binary, enumeration + fetch), sqlite3 (stdlib), PyYAML

**Storage**: SQLite catalog (`assets`, `meta`) on the work volume; append-only JSONL journals; no new tables

**Testing**: pytest — unit for the comparison and verdict logic, integration for CLI behaviour, fixture streams for external output parsing

**Target Platform**: macOS 15+ and Debian-family Linux, identical behaviour (constitution: Development Workflow)

**Project Type**: Single-project CLI

**Performance Goals**: Enumerate 35,000 items in under 30 minutes with zero media transfer (SC-001/SC-002); comparison of 40,000 listed against 40,000 recorded paths in under 2 seconds

**Constraints**: No media transfer during an audit; no authentication attempt when credentials are unusable (SC-008); automatic repair bounded by a configured budget; `--apply` required before any stored state changes

**Scale/Scope**: 4 iCloud sources, 20,000–40,000 assets each, ~90,000 catalog rows total

## Constitution Check

*GATE: evaluated before Phase 0 and re-evaluated after Phase 1.*

| Principle | Assessment | Gate |
|---|---|---|
| **I. Source Data Is Sacred** | Enumeration is strictly read-only. The listing command is built by the same argument builder that 005's safety test already covers, extended to assert no iCloud-mutating flag (`--auto-delete`, `--delete-after-download`) can appear in an enumeration invocation either. No new deletion path. | PASS |
| **II. Plan Before Apply** | `archivist audit` reports by default; `--apply` is required before any watermark or journal write. Automatic repair within `pull all` inherits the `--apply` already given on that invocation and never carries approval across invocations. | PASS |
| **III. Verify Before Record** | The audit records a *reconciliation claim*, not an archive write; no file is filed or skipped on its evidence. Repairs flow through the existing verified ingest path unchanged. The gap report is explicitly an upper bound and is never used to justify a deletion or a skip. | PASS |
| **IV. Journal Before Destruction; Catalog Derived** | A reconciliation advance writes its journal record, fsynced, before the catalog write — reusing 005's ordering and `append_record`. The journal names what was compared and what was concluded, so the claim is auditable after the fact. | PASS |
| **V. Guarded Volumes** | `audit` is a state-changing command under `--apply` and goes through `_require(cfg)` like every other. It reads the catalog, which lives on the work volume; an unmounted work volume must refuse, not read an empty mount point. | PASS |
| **VI. Never Delete the Last Copy** | No deletion path is added or modified. | PASS |

**Scope & Boundaries — reviewed, not violated.** The constitution reserves
"scheduled/unattended operation" for its own feature and constitutional review.
Budgeted automatic repair runs *inside* an operator-invoked `pull all`, which is
the same shape as the existing `auto_reconcile` setting; it is automatic action
within an invoked command, not unattended operation. This feature makes every
branch bounded — a precondition for a future scheduling feature — and
deliberately stops there. Recorded in the spec's Out of Scope.

**Post-Phase-1 re-evaluation**: unchanged, all PASS. The design added no module
with write authority over the archive; `audit.py` is pure comparison over an
in-memory listing and a read-only catalog query, and every mutation it motivates
is executed by code that already carries its own gates.

## Project Structure

### Documentation (this feature)

```text
specs/006-reconcile-by-diff/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   ├── enumeration.md   # External listing output -> Listing
│   ├── gap-report.md    # Comparison rules and the no-under-report invariant
│   └── cli-audit.md     # Command surface, exit codes, summary vocabulary
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # /speckit-tasks output
```

### Source Code (repository root)

```text
src/archivist/
├── audit.py            # NEW - comparison, gap report, reconcile verdict, repair planning
├── icloud.py           # enumerate_library(); shared arg builder; session gate (reused)
├── coverage.py         # reconcile verdict feeds the existing advance machinery
├── catalog.py          # NEW query: recorded source paths for a source
├── config.py           # NEW settings: audit_interval_days, repair_budget_gb, auto_repair
└── cli.py              # NEW `audit` command; `pull all` integration; summary ranking

tests/
├── unit/
│   ├── test_enumeration_parse.py      # listing output -> Listing, fail-closed
│   ├── test_gap_compare.py            # set logic, relative-path keying
│   ├── test_gap_never_underreports.py # the invariant, adversarially
│   ├── test_audit_verdict.py          # Reconciled / Incomplete / Unverified
│   ├── test_repair_plan.py            # period grouping, estimate, scatter cutoff
│   ├── test_audit_budget.py           # budget decision incl. unknown estimate
│   └── test_audit_config.py           # new settings, validation, defaults
├── integration/
│   ├── test_audit_cli.py              # report-only default, --apply, exit codes
│   ├── test_audit_unfiled_mirror.py   # FR-008 refusal
│   ├── test_audit_session_gate.py     # no auth attempt (SC-008)
│   ├── test_pull_all_audit.py         # interval behaviour, summary lines
│   └── test_pull_all_autorepair.py    # within budget / over budget
└── fixtures/icloudpd_streams/
    └── enumeration-*.log              # real listing output shapes
```

**Structure Decision**: Single-project CLI, matching features 001–005. One new
module, `audit.py`, holding the comparison and the verdict; it has no I/O of its
own beyond being handed a listing and a set of recorded paths, which is what
makes the no-under-report invariant cheap to test exhaustively.

## Design Notes

**Why a new module rather than extending `coverage.py`.** `coverage.py` answers
"may this run's *coverage* watermark advance, given what the downloader did".
The audit answers "does this library contain anything the archive lacks". They
meet only at the point where a verdict becomes an advance. Keeping them apart
preserves 005's decision table as the single place coverage advances are decided,
and keeps the comparison logic pure enough to fuzz.

**Comparison key.** Both sides are reduced to the path *relative to the source's
mirror root* before comparison, so a work-volume path change cannot masquerade as
a missing item. The catalog's rows are filtered by the mirror prefix for that
source only — one account's rows can never satisfy another's audit, which is the
same per-account discipline the session check needed.

**Why the estimate can be unknown.** Item sizes are not in the listing. The
estimate comes from the archive's own median size for that source, which is
absent for a source with no filed items. FR-030 makes an unknown estimate
*exceed* the budget rather than bypass it.

## Complexity Tracking

> No constitutional violations requiring justification.

| Consideration | Resolution |
|---|---|
| Budgeted auto-repair resembles unattended operation | Reviewed against Scope & Boundaries: runs inside an operator-invoked command, same shape as existing `auto_reconcile`. Not unattended operation; scheduling remains out of scope. |
| A second "staleness interval" alongside `reconcile_interval_days` | `audit_interval_days` (7) governs how often the cheap audit runs; `reconcile_interval_days` (30) continues to govern when an unbounded sweep is considered overdue. They answer different questions and are not merged, but the summary must not report both as "due" for the same source — resolved in the CLI contract. |
