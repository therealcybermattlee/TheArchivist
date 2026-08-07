# Quickstart: Validating The Archivist Baseline

**Feature**: 001-archivist-baseline | **Date**: 2026-07-30

Runnable scenarios proving the baseline end-to-end. Command semantics are
defined in [contracts/cli-interface.md](contracts/cli-interface.md); entities
and counters in [data-model.md](data-model.md).

## Prerequisites

- macOS workstation with `uv`, `exiftool`, `ffprobe` (ffmpeg), and
  `icloudpd` on PATH.
- Both volumes mounted by the operator: archive (`/Volumes/VideoStorage`)
  and working (`/Volumes/ExternalBaseUnit`), each carrying its
  `.archivist-volume-id` sentinel (`archivist init-volumes` once).
- `config.yaml` present (see `config.example.yaml`) with `archive_root`,
  `work_root`, `default_timezone`, and the `sources` map.

```bash
uv sync            # install package + dev deps
uv run archivist status   # sanity: guards pass, catalog reachable
```

## Scenario 1 — Guard rails (SC-007, User Story 5)

1. Unmount the archive volume (or temporarily rename its sentinel).
2. Run each state-changing command: `ingest`, `ingest-drops`, `cleanup`,
   `purge`, `review`, `pull-icloud` (with and without `--apply`).
3. **Expected**: every command refuses, names the failed volume check, exits
   non-zero, and no file anywhere is created, moved, or deleted.
4. Restore the mount/sentinel; `archivist status` reports healthy again.

## Scenario 2 — Inventory scan (SC-004, User Story 1)

```bash
time uv run archivist scan-archive
uv run archivist status
```

- **Expected**: full scan of the ≈5,500-file / ≈3 TB archive completes in
  under 1 hour; reported totals and per-year breakdown match reality;
  OS junk absent from the catalog; spot-checked files show correct capture
  dates + confidence.
- Re-run immediately: completes in minutes (incremental fast path, FR-004).

## Scenario 3 — Folder ingest dry-run → apply (SC-001/002/006/008, User Story 3)

Prepare a small fixture folder containing: dated media, a Live Photo pair,
a file with no embedded date, a byte-identical copy of an already-archived
file, two identical copies of a new file, and a PDF.

```bash
uv run archivist ingest /path/to/fixture --source peepaw-cell          # plan only
uv run archivist ingest /path/to/fixture --source peepaw-cell --apply  # execute
uv run archivist ingest /path/to/fixture --source peepaw-cell --apply  # idempotency
```

- **Plan** lists: destinations under `<Year>/<MMDDYYYY> - Unsorted/Peepaw
  Cell/`; the pair grouped to one folder; the archive duplicate skipped; one
  of the two identical new files filed and the other reported as a
  within-batch duplicate; the PDF listed as skipped non-media (not silent).
- **Apply**: every filed copy byte-verified before catalog commit; JSONL
  manifest written in `logs/`; run report shows all counters from
  [data-model.md](data-model.md#run-report-per-run-counters-fr-026).
- **Re-run**: zero new items filed (SC-006). Source folder byte-identical to
  before (SC-001) — verify with `diff -r` against a pre-made copy.

## Scenario 4 — Cleanup → quarantine → purge (SC-003, User Story 2)

```bash
uv run archivist cleanup            # plan: dup groups, corrupt, junk
uv run archivist cleanup --apply    # move condemned to _Quarantine
uv run archivist purge              # plan: verify kept counterparts
uv run archivist purge --apply      # delete inside _Quarantine only
```

- **Expected**: exactly one keeper per duplicate group (best-placed copy),
  keeper never condemned by another group; quarantined files recoverable
  before purge; purge refuses any file whose kept copy is missing (test by
  hiding one keeper first); deletions occur only under `_Quarantine/`.

## Scenario 5 — Interactive review (FR-027, clarification 2026-07-29)

```bash
uv run archivist review             # walk low-confidence queue, plan re-files
uv run archivist review --apply
```

- **Expected**: each flagged item (companion groups as one unit) presented
  with guessed date, date source, current location; approving a corrected
  date re-files the whole group into the corrected date folder with
  verification + journaling and clears the flag; `status` review-queue depth
  drops accordingly.

## Scenario 6 — iCloud pull (User Story 4)

```bash
uv run archivist auth-icloud --source matt-personal    # one-time, interactive
uv run archivist pull-icloud --source matt-personal --recent 25
uv run archivist pull-icloud --source matt-personal --recent 25 --apply
uv run archivist pull-icloud --source matt-personal --recent 25 --apply  # re-run
```

- **Expected**: no password in any config or log file (grep for it);
  25 recent items (with Live Photo pairs, original quality) land in the
  per-source mirror; ingest files them per Scenario 3 rules; re-run
  downloads and files nothing new; cloud library untouched. With an expired
  session, the pull stops immediately and instructs re-running
  `auth-icloud` (FR-024).

## Automated test suite

```bash
uv run pytest
```

- **Expected**: unit tests (date resolver tiers + sanity bounds, hashing,
  grouping, collision suffixes, config validation) and integration tests
  (fake tmp-dir volumes with sentinels; scan/ingest/cleanup/purge/review
  end-to-end; guard-refusal with sentinel removed) all pass. Tests never
  touch `/Volumes/*`.
