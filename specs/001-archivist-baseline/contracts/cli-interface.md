# CLI Contract: `archivist`

**Feature**: 001-archivist-baseline | **Date**: 2026-07-30

The tool's only external interface is the `archivist` command-line program.
Global behavior contract, then per-command schemas.

## Global contract

- `--config <path>` on every command; defaults to `config.yaml` in the
  working directory.
- **Volume guard**: every command that can write, move, or delete first
  verifies both volumes are mounted, writable, and carry
  `.archivist-volume-id` sentinels; on failure it exits non-zero, names the
  failed check, and touches nothing (FR-013).
- **Dry-run default**: every mutating command prints a reviewable plan and
  exits without changes unless `--apply` is passed on that invocation
  (FR-014). `--apply` never survives across invocations.
- **Exit codes**: `0` success (including "plan printed, nothing applied");
  non-zero for guard failure, verification failure, expired cloud session,
  or any error. Mid-run volume disconnection halts the run with non-zero
  exit and a journal accounting for every completed action.
- **Sources are read-only**: no command modifies, moves, or deletes anything
  in a source location or cloud account (FR-011).

## Commands

### `archivist status`

Read-only. Reports: volume/guard health for both volumes, catalog inventory
counts (total, by confidence, by source), last-run outcomes, and the
low-confidence review-queue depth (FR-025).

### `archivist init-volumes`

Writes the `.archivist-volume-id` sentinel files to both configured volume
roots (one-time setup). Refuses to overwrite existing mismatched sentinels.

### `archivist scan-archive [--full]`

Read-only against the archive (writes only catalog + logs on the working
volume). Walks `archive_root`, excludes OS junk, records/updates one catalog
row per media file with identity, date + confidence, and comparison
metadata. Incremental by default via `size + mtime + partial-hash` fast path
(FR-004); `--full` forces re-processing.

### `archivist ingest <path> --source <key> [--apply]`

Files loose media from a read-only source path (FR-021).

- Plan (always printed): per-item planned destination
  `<Year>/<MMDDYYYY> - Unsorted/<Device Folder>`, resolved date + source +
  confidence, grouped companions, plus explicit listings of:
  archive duplicates (skipped, FR-022), within-batch duplicates (one copy
  filed, rest skipped), non-media files (skipped, listed — never silent),
  and suspect files (media extension, non-media content — never filed).
- Apply: copy → byte-verify → journal line before each step → catalog
  commit only after verification (FR-015, FR-016). Collisions get
  primary-hash suffixes; never overwrites (FR-010).
- Report: `filed / skipped-dup(archive) / skipped-dup(batch) /
  skipped-non-media / suspect / errored / flagged-for-review` counts
  (FR-026).

### `archivist ingest-drops [--apply]`

Runs the ingest contract over every configured `drop` source's inbox
directory (`<work_root>/TheArchivist/drops/<source>/`).

### `archivist cleanup [--no-junk] [--apply]`

Plans and applies archive cleanup (FR-017..FR-019).

- Plan: exact-duplicate groups (keeper chosen by best location; keeper
  immune from condemnation by any other group), corrupt files, junk types.
- Apply: move condemned files into `<archive_root>/_Quarantine/`,
  re-confirming full-content identity per duplicate immediately before its
  move; journal-first; symbolic links skipped, never followed.

### `archivist purge [--apply]`

Deletes quarantined files (FR-020). Verifies every kept counterpart exists
and is intact first; refuses (per-file) when a kept copy is missing; deletes
only inside `_Quarantine`.

### `archivist review [--apply]`  *(new — FR-027)*

Interactive queue of items filed on low/medium-confidence dates. For each
item (companion group presented as one unit): shows guessed date, date
source, current location; accepts a corrected date (re-file), accept-as-is
(clear flag), or skip. Re-filing follows the full filing contract:
plan/approve, copy + verify to the corrected date folder, journaled,
no overwrites, catalog updated, flag cleared.

### `archivist auth-icloud --source <key>`

One-time interactive sign-in for an `icloud` source (operator enters
password + 2FA in the terminal). Session persists in the system keyring
only; no credential ever appears in config files or logs (FR-023).

### `archivist pull-icloud --source <key> [--recent N | --since DATE] [--apply]`

Incremental download of an iCloud library into its persistent per-source
mirror on the working volume (original quality, Live Photo pairs), then the
standard ingest contract files new items (FR-023). Nothing is ever deleted
or altered in the cloud account. Expired session ⇒ stop immediately with a
clear instruction to re-run `auth-icloud` (FR-024).
