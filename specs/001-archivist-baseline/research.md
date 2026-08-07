# Research: The Archivist — Baseline

**Feature**: 001-archivist-baseline | **Date**: 2026-07-30

No `NEEDS CLARIFICATION` markers remain in the Technical Context — the stack
is established and largely delivered. This document records the decisions
already embodied in the delivered code (so downstream phases treat them as
settled) plus the two design decisions needed for the remaining gaps
(review workflow, test harness).

## D1. CLI framework — `typer`

- **Decision**: Python 3.12 + `typer` subcommand CLI, console script
  `archivist`, dry-run by default with an explicit `--apply` flag on every
  mutating command.
- **Rationale**: Typed options and native subcommands make the
  plan-then-approve model (FR-014) idiomatic; `--apply` gating is a single
  boolean per command. Delivered and proven in real runs.
- **Alternatives considered**: `argparse` (more boilerplate for subcommand
  trees); `click` directly (typer wraps it with type hints); TUI framework
  (overkill for a single-operator tool).

## D2. Catalog — SQLite as a derived, rebuildable index

- **Decision**: One SQLite database (`assets` table, schema v2) as a derived
  index. Files + JSONL run manifests are authoritative; the entire catalog is
  rebuildable via `scan-archive`.
- **Rationale**: At ≈5,500 files, SQLite is far past sufficient; making it
  derived (not source of truth) means DB loss/corruption is a
  re-scan, not a disaster — consistent with the safety posture.
- **Alternatives considered**: JSON/CSV flat file (no indexed hash lookups);
  Postgres (a server dependency for a single-user desktop tool); making the
  DB authoritative (rejected: violates rebuildability principle).

## D3. Identity — two-tier hashing (quick_hash → SHA-256)

- **Decision**: `quick_hash` = file size + hashed head/tail bytes for
  candidate matching; streaming full-file SHA-256 confirms every match before
  any skip/destructive decision (FR-002). Cleanup re-confirms full-content
  identity immediately before each quarantine move (FR-019).
- **Rationale**: The archive is terabytes over SMB; full-hashing everything
  per scan would blow the SC-004 hour budget. The fast path prunes; SHA-256
  decides. SHA-256 (not MD5/xxhash) because collision resistance underwrites
  "never delete the last copy."
- **Alternatives considered**: full-hash everything (too slow over SMB);
  xxhash/BLAKE3 for the full tier (fine technically, but SHA-256 is stdlib
  and speed is dominated by network reads anyway).

## D4. Metadata extraction — external `exiftool` + `ffprobe`

- **Decision**: Shell out to `exiftool` (photos, sidecars) and `ffprobe`
  (video streams); capture comparison columns (`phash`, dimensions,
  duration, camera make/model, mime) at ingest time even though perceptual
  matching is out of baseline scope.
- **Rationale**: exiftool's format coverage is unmatched; capturing
  comparison metadata now avoids ever re-reading terabytes to backfill when
  near-duplicate review tooling arrives later.
- **Alternatives considered**: pure-Python EXIF readers (weak RAW/video
  coverage); deferring phash capture (rejected — cannot backfill without a
  full re-read).

## D5. Date resolution — tiered evidence with confidence + sanity bounds

- **Decision**: Priority order: embedded metadata (HIGH) → sidecar JSON
  (HIGH) → filename patterns incl. US MMDDYYYY forms (MEDIUM) → filesystem
  mtime/ctime (LOW). Video timestamps treated as UTC and normalized to the
  configured home timezone (`America/Detroit`); photo timestamps treated as
  local. Dates before 1990 or in the future are rejected as evidence and the
  resolver falls through (FR-005..FR-007).
- **Rationale**: QuickTime spec stores creation time in UTC while EXIF
  `DateTimeOriginal` is wall-clock local — treating them differently is what
  keeps late-night videos on the correct local calendar day. Sanity bounds
  stop epoch-zero and camera-default dates from minting absurd year folders.
- **Alternatives considered**: single-source dating (loses the long tail of
  undated media); quarantining undated files (rejected in design — every file
  is placed by best guess and flagged, so nothing is ever stranded).

## D6. Cloud pull — `icloudpd` into a persistent per-source mirror

- **Decision**: Wrap `icloudpd` (v1.32.x line) via subprocess. One-time
  interactive `auth-icloud` stores the session in the system keyring
  (password + 2FA typed by the operator, never persisted by the tool).
  Pulls download original-quality media incl. Live Photo pairs into a
  persistent per-source mirror on the working volume; repeat pulls are
  incremental; expired sessions abort with a re-auth instruction (FR-023,
  FR-024).
- **Rationale**: icloudpd is actively maintained, handles Live Photos/RAW
  and headless session reuse; the mirror decouples flaky cloud transfers
  from the verified ingest step.
- **Alternatives considered**: `pyicloud` direct API (fragile, weaker media
  coverage); Photos.app library export (manual, not incremental).

## D7. Google libraries — Takeout export bundles only (no live API)

- **Decision**: Google media arrives via manually requested Takeout export
  bundles; the export-ingest pathway is planned but explicitly outside the
  delivered baseline (spec Assumptions).
- **Rationale**: Google removed the `photoslibrary.readonly` scope on
  2025-03-31; the Library API now returns only app-uploaded media and the
  Picker API requires per-item manual selection. No live bulk path exists.
  **Do not re-attempt live Google API sync — it cannot work.**
- **Alternatives considered**: `gphotos-sync` / `rclone` Google Photos
  backends (both broken by the scope removal).

## D8. Cleanup safety — quarantine → verify → purge

- **Decision**: Cleanup never deletes directly. Condemned files (exact
  duplicates, corrupt media-extension files, configured junk) move to
  `<archive_root>/_Quarantine/`, with per-group survivor immunization (a
  kept copy can never be condemned by another group). Purge verifies every
  kept counterpart exists before deleting, refuses otherwise, and only ever
  deletes inside `_Quarantine` (FR-017..FR-020).
- **Rationale**: Two-phase delete with an intervening verification pass is
  what makes "cleanup can never remove the last copy" (SC-003) enforceable;
  real-world run verified 256/256 kept copies across ≈270 GB.
- **Distinction to keep straight**: quarantine is for *condemned files* in
  cleanup only. Low-confidence-*dated* files are never quarantined — they are
  filed normally and flagged for review (see D9).

## D9. Review workflow (FR-027) — interactive re-file loop *(new design)*

- **Decision**: New `archivist review` command backed by `review.py`.
  Queries the catalog for flagged items (`confidence` below high) grouped by
  `asset_group_id`, presents one group at a time with its evidence (guessed
  date, `date_source`, current `archive_path`), and accepts: corrected date
  (re-file), accept-as-is (clear flag), or skip. Re-filing reuses the ingest
  machinery's plan/copy/verify/journal path — move-within-archive as
  copy + verify + journaled removal of the old location, companion group
  travels together, collision suffixes apply, catalog updated to the new
  location. Dry-run by default; `--apply` executes, consistent with every
  other mutating command.
- **Rationale**: Reusing the filing pipeline means the review path inherits
  every safety invariant for free instead of re-implementing move logic; the
  per-clarification decision (Session 2026-07-29) requires interactive
  present-and-re-file, not just a report.
- **Alternatives considered**: report-only queue in `status` (delivered, but
  the clarification explicitly requires interactive correction); editing the
  catalog date without moving files (leaves files in wrong date folders —
  contradicts the archive convention).

## D10. Journaling — JSONL run manifests, record-only recovery

- **Decision**: Every applying run appends per-action JSONL entries to
  `logs/manifest-<timestamp>.jsonl` *before* each destructive step. The
  journal is a complete, human-usable record; recovery is manual (e.g.,
  moving files back from quarantine). No automated rollback command in the
  baseline (per clarification, Session 2026-07-30).
- **Rationale**: Journal-first ordering guarantees any interruption leaves a
  full account; JSONL is greppable and independent of the SQLite catalog, so
  catalog state is reconstructable from manifests + files alone.
- **Alternatives considered**: automated `undo <run-id>` command (explicitly
  deferred out of baseline scope); journaling into SQLite (couples the ledger
  to the thing it must survive).

## D11. Non-media & within-batch duplicate reporting *(gap closure)*

- **Decision**: Per clarifications (Session 2026-07-30): (a) legitimate
  non-media files in an ingest source are never filed but are listed in the
  ingest plan and run report as skipped non-media; (b) when one ingest batch
  contains multiple byte-identical copies, exactly one is filed and the rest
  are reported as within-batch duplicates. Run reports gain a
  `skipped_non_media` counter alongside filed/duplicate/errored/flagged.
- **Rationale**: Both close silent-behavior holes: the archivist must be
  able to trust that "ingest complete" accounts for every file that was in
  the source.
- **Alternatives considered**: silent skip (fails the accounting
  requirement); filing all within-batch copies with suffixes (creates
  instant cleanup debt).

## D12. Test harness — pytest with fake sentinel volumes *(new design)*

- **Decision**: `pytest` suite in `tests/unit/` (dates, hashing, grouping,
  config, guard, collision policy) and `tests/integration/` (tmp-dir fake
  archive + working volumes carrying `.archivist-volume-id` sentinels;
  end-to-end scan → ingest → cleanup → purge → review against small
  fixture media; unmounted-volume refusal tests by removing the sentinel).
- **Rationale**: The safety invariants (SC-001, SC-002, SC-003, SC-007) are
  claims about behavior under failure — only executable tests make them
  regression-proof. Fake volumes with sentinels let the guard path be tested
  without real mounts. Tests never touch `/Volumes/*`.
- **Alternatives considered**: manual test checklist only (delivered
  reality; doesn't survive refactoring); mocking the filesystem (real
  tmp-dir I/O is cheap and exercises the actual copy/verify code).
