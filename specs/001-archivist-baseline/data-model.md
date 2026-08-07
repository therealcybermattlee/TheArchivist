# Data Model: The Archivist — Baseline

**Feature**: 001-archivist-baseline | **Date**: 2026-07-30

Two persistence layers plus config. The **files and run manifests are
authoritative**; the SQLite catalog is a derived index, fully rebuildable via
`scan-archive`.

## Entity: Media Item (`assets` table row, schema v2)

One row per physical media file known to the archive.

| Field | Type | Notes / validation |
|-------|------|--------------------|
| `id` | INTEGER PK | surrogate key |
| `quick_hash` | TEXT | size + head/tail digest; candidate-match tier only — never sufficient for skip/destructive decisions (FR-002) |
| `content_hash` | TEXT | full streaming SHA-256; computed lazily; REQUIRED before any duplicate skip, quarantine move, or purge decision |
| `source_label` | TEXT | configured source key (e.g. `peepaw-cell`) |
| `original_path` | TEXT | where the file came from (read-only source) |
| `archive_path` | TEXT | current location in archive; UNIQUE where not null — one row per archived file, no overwrites |
| `asset_group_id` | TEXT | joins companion files (nullable for singletons) |
| `ingested_at` | TEXT | ISO timestamp of catalog commit (post-verification only, FR-015) |
| `run_manifest_id` | TEXT | back-reference to the journal that filed it |
| `capture_dt` | TEXT | ISO, normalized to `default_timezone` |
| `date_source` | TEXT | enum: `exif` \| `sidecar` \| `filename` \| `mtime` |
| `confidence` | TEXT | enum: `high` \| `medium` \| `low` — anything below `high` enters the review queue (FR-027) |
| `phash` | TEXT | perceptual hash, captured for future near-dup tooling (matching out of baseline scope) |
| `width`, `height` | INTEGER | stills/video dimensions |
| `file_size` | INTEGER | bytes |
| `duration` | REAL | seconds, video only |
| `camera_make`, `camera_model` | TEXT | when recoverable |
| `mime_type` | TEXT | sniffed type; media-extension/non-media mismatch ⇒ suspect (FR-018) |

**Indexes**: `quick_hash`, `content_hash`, `phash`, `asset_group_id`;
unique partial index on `archive_path`.

**Validation rules** (from FRs):
- Capture dates before 1990 or in the future are invalid evidence (FR-007).
- A row's `ingested_at`/`archive_path` may only be written after byte-perfect
  verification of the archive copy (FR-015).
- OS junk (`.DS_Store`, `Thumbs.db`, `._*`) never gets a row (FR-003).

**State transitions** (per file):

```
discovered ──> planned ──> copied ──> verified ──> cataloged
                                (verify fail ⇒ errored, no catalog row)
cataloged ──(cleanup plan + approval)──> quarantined ──(verified purge)──> deleted
                       (kept-copy missing ⇒ purge refused, stays quarantined)
cataloged(low/medium confidence) ──(review + approval)──> re-filed (new archive_path, flag cleared)
```

## Entity: Asset Group

Companion files that travel together (Live Photo HEIC+MOV, RAW+JPEG,
image+AAE/XMP sidecar, video+telemetry). Represented by a shared
`asset_group_id`, not a separate table.

- **Primary member**: the still image (JPEG for RAW+JPEG pairs). Its
  resolved date and collision suffix govern the whole group (FR-009).
- **Invariants**: single unified date decision; single destination folder;
  identical collision suffix derived from the primary's hash; review re-files
  the whole group together (FR-027).

## Entity: Source (config.yaml `sources` map)

| Field | Type | Notes |
|-------|------|-------|
| key | string | CLI `--source` name, e.g. `matt-personal` |
| `type` | enum | `icloud` \| `takeout` \| `device` \| `drop` (takeout pathway out of delivered baseline) |
| `device_folder` | string | Level-3 archive folder name, e.g. `Matt Personal Cell` |

Every ingest pathway MUST map to exactly one `device_folder` (FR-008,
FR-021). `icloud` sources additionally imply a keyring session and a
persistent mirror directory on the working volume.

## Entity: Archive Location (path convention, not stored)

`<archive_root>/<YYYY>/<MMDDYYYY> - <Event>/<Device Folder>/` — the tool
creates only `<MMDDYYYY> - Unsorted` date folders; event naming is manual
and never performed by the tool. Collisions between different files get a
short primary-hash suffix (`IMG_1234__a1b2c3d4.JPG`); byte-identical files
are duplicates and are skipped, never suffixed (FR-010, FR-022).

## Entity: Cleanup Plan / Ingest Plan (in-memory, rendered for approval)

A reviewable list of intended actions; nothing executes without `--apply` on
that invocation (FR-014).

- **Ingest plan action**: `{original_path, group_id, resolved_date,
  date_source, confidence, planned_archive_path, action}` where action ∈
  `file` | `skip-duplicate (archive)` | `skip-duplicate (within batch)` |
  `skip-non-media` | `suspect`.
- **Cleanup plan action**: `{archive_path, reason (duplicate|corrupt|junk),
  kept_copy_path?, quarantine_path}` with per-plan survivor immunity: a kept
  copy may not be condemned by any other group (FR-017).

## Entity: Run Journal (JSONL manifest, `logs/manifest-<ts>.jsonl`)

Authoritative per-action ledger, independent of SQLite. One line per action,
appended **before** the action's destructive step (FR-016).

Line shape: `{run_id, source, original_path, resolved_date, confidence,
hash, planned_path, action, result}`.

- Basis for verification and **manual** recovery — no automated rollback
  (clarification 2026-07-30).
- Catalog state must be fully reconstructable from manifests + files alone.

## Entity: Quarantine (`<archive_root>/_Quarantine/`)

Holding area for condemned files between cleanup and purge.

- Only reachable via an approved cleanup plan; every move re-confirms
  full-content identity for duplicates immediately beforehand (FR-019).
- Purge deletes **only** inside `_Quarantine`, and only after verifying every
  kept counterpart exists; any missing counterpart ⇒ that file is refused
  deletion (FR-020) — it may be the last copy.

## Run Report (per-run counters, FR-026)

`{filed, skipped_duplicates_archive, skipped_duplicates_within_batch,
skipped_non_media, quarantined, errored, flagged_for_review}` — surfaced at
run end and via `archivist status` (last-run outcomes, volume health,
inventory counts, review-queue depth).
