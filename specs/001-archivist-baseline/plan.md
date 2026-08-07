# Implementation Plan: The Archivist — Family Media Archival Tool (Baseline)

**Branch**: `001-archivist-baseline` | **Date**: 2026-07-30 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-archivist-baseline/spec.md`

## Summary

The Archivist is a single-operator, on-demand CLI that inventories a
multi-terabyte family media archive, safely cleans up exact duplicates and
junk via a quarantine-then-verified-purge flow, ingests loose media into the
`Year / MMDDYYYY - Event / Device` archive convention, and pulls iCloud photo
libraries into a local mirror for standard ingest. The technical approach is
already established and partially delivered: a Python 3.12 `typer` CLI backed
by a rebuildable SQLite catalog, JSONL run manifests journaled before every
destructive step, sentinel-file volume guards, two-tier content identity
(quick hash → full SHA-256 confirmation), and `exiftool`/`ffprobe` metadata
extraction with a tiered date-confidence resolver. This plan covers the
baseline as specified, including the gaps between the delivered code and the
spec: the interactive review workflow (FR-027), non-media skip reporting
(FR-021/FR-026), within-batch duplicate handling (FR-022), and an automated
test suite proving the safety invariants.

## Technical Context

**Language/Version**: Python 3.12+ (managed with `uv`; hatchling build)

**Primary Dependencies**: `typer` (CLI), `pyyaml` (config), `pillow` (image
introspection/phash support), `tzdata` (timezone math); external executables:
`exiftool`, `ffprobe` (metadata), `icloudpd` (iCloud pull, session in system
keyring)

**Storage**: SQLite catalog at `<work_root>/TheArchivist/catalog/` (derived
index, rebuildable); JSONL run manifests at `<work_root>/TheArchivist/logs/`
(authoritative journal); archive on SMB NAS `/Volumes/VideoStorage`; working
volume `/Volumes/ExternalBaseUnit`

**Testing**: `pytest` (dev dependency present; suite not yet written — this
plan adds unit + integration coverage using tmp-dir fake volumes with
sentinel files)

**Target Platform**: macOS (archivist's workstation, Darwin), volumes mounted
by the operator

**Project Type**: Single-project CLI (`src/archivist/` package, console
script `archivist`)

**Performance Goals**: Full scan of ≈5,500 files / ≈3 TB over SMB in under
1 hour; repeat scans in minutes (SC-004) via `size + mtime + partial-hash`
fast path; full SHA-256 only on candidate collisions

**Constraints**: Sources strictly read-only (FR-011); writes only to archive
+ working volumes (FR-012); sentinel-guarded mounts before any state change
(FR-013); dry-run by default, `--apply` to execute (FR-014); byte-verified
copies before catalog commit (FR-015); journal-before-destructive-step
(FR-016, record-only — no automated rollback)

**Scale/Scope**: One operator, one machine; ≈3 TB / ≈5,500 files existing
archive; drops of a few hundred items per sitting (SC-008); two iCloud
accounts

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is an unratified template (placeholder
tokens only), so no constitutional gates can be derived from it. In its
place, the spec's own non-negotiable safety invariants (FR-011 through
FR-016) and the PLAN.md data-flow invariant ("source data is read-only,
always") serve as the governing gates for this feature:

| Gate | Status |
|------|--------|
| No code path writes to a source location | PASS — ingest/pull copy only; delivered code has no source-mutating path |
| Dry-run default; every mutation behind `--apply` | PASS — all mutating commands default to plan-only |
| Byte-verified copy before catalog record | PASS — SHA-256 verify precedes `upsert` |
| Journal written before each destructive step | PASS — JSONL manifest appended pre-action |
| Volume sentinel guard on every state-changing command | PASS — `guard.py` checks both volumes |
| Only deletion ever performed is inside `_Quarantine` (and own scratch) | PASS — purge is quarantine-scoped |

No violations; Complexity Tracking not required.

**Post-design re-check (after Phase 1)**: PASS — the design artifacts add
one module (`review.py`) that reuses the existing filing pipeline (inheriting
all invariants) and a test suite that operates only on tmp-dir fake volumes.
No new write targets, no new deletion paths, no source-touching code.

## Project Structure

### Documentation (this feature)

```text
specs/001-archivist-baseline/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   └── cli-interface.md
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/archivist/
├── __init__.py
├── __main__.py
├── cli.py          # typer app: status, init-volumes, scan-archive, ingest,
│                   #   ingest-drops, cleanup, purge, auth-icloud, pull-icloud
│                   #   (+ NEW: review — FR-027)
├── config.py       # config.yaml load/validate: roots, timezone, sources map
├── guard.py        # volume sentinel guard (FR-013)
├── catalog.py      # SQLite derived index (schema v2, rebuildable)
├── scanner.py      # archive walk, junk exclusion, incremental fast path
├── hashing.py      # quick_hash (size+head/tail) + streaming sha256
├── metadata.py     # exiftool/ffprobe extraction, comparison columns
├── dates.py        # tiered date resolver + confidence + sanity bounds
├── grouping.py     # asset groups: Live Photo, RAW+JPEG, sidecars
├── ingest.py       # plan → approve → copy → verify → journal → catalog
├── dedupe.py       # cleanup planner + quarantine mover + purge verifier
├── icloud.py       # icloudpd wrapper: auth + incremental mirror pull
└── review.py       # NEW: interactive low-confidence review + re-file (FR-027)

tests/
├── unit/           # NEW: dates, hashing, grouping, config, guard logic
└── integration/    # NEW: tmp-dir fake volumes w/ sentinels; end-to-end
                    #   scan/ingest/cleanup/purge/review against fixtures
```

**Structure Decision**: Keep the delivered single-package layout
(`src/archivist/`, one flat module per subsystem). The only structural
additions are `review.py` (the one undelivered FR) and the `tests/` tree.
No reorganization of delivered modules — they map one-to-one onto the spec's
capabilities and the baseline's job is to close gaps, not churn structure.

## Gap Analysis (delivered baseline vs. spec)

The spec documents the tool as designed; most of it is delivered. Planning
focuses on the delta:

| Spec item | Delivered? | Gap to close |
|-----------|-----------|--------------|
| FR-001..FR-010, FR-017..FR-020 (scan, identity, dates, filing, cleanup, purge) | Yes | Verified by new test suite only |
| FR-011..FR-016 safety invariants | Yes | Prove with integration tests (unmounted-volume, verify-before-record, journal-first) |
| FR-021 non-media skip **reporting** | Partial — junk filtered, but non-media files are not surfaced in plan/report | Add skipped-non-media listing to ingest plan + run report |
| FR-022 within-batch duplicates | Partial — catalog-dup skip exists; within-batch behavior unverified | Confirm/implement file-one-report-rest within a single ingest batch |
| FR-023/FR-024 iCloud pull + session expiry | Yes (built, awaiting first live run) | Live-run validation per quickstart |
| FR-025/FR-026 status + run outcome counts | Partial — counts exist; add non-media count (FR-026 as clarified) | Extend report counters |
| FR-027 interactive review workflow | **No** — no `review` command exists | New `review.py` + `archivist review` command |
| Automated tests (SC-001..SC-007 evidence) | No tests written | Unit + integration suite with fake volumes |
