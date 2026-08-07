# CLI Contract: Media Geolocation Catalog

**Feature**: 002-media-geolocation | **Date**: 2026-07-30

Extends the baseline CLI contract
([001 contracts/cli-interface.md](../../001-archivist-baseline/contracts/cli-interface.md)).
Global behavior (volume guard, `--config`, exit codes, read-only sources)
applies unchanged to the commands below.

## New commands

### `archivist scan-locations [--full] [--limit N]`

Backfills capture locations for cataloged items (FR-005).

- **Reads**: archived files in place (batched metadata extraction). Never
  modifies, moves, or re-copies any file.
- **Writes**: catalog rows only (`gps_*` columns), committed per batch —
  an interrupted run resumes where it left off.
- **Incremental**: examines only rows with `gps_status IS NULL`; `--full`
  re-examines everything; `--limit N` caps this run (useful for timing
  trials).
- **Guard**: runs the volume guard (it writes the catalog and reads the
  archive).
- **Report**: `examined / located / location_absent / location_rejected`
  counts and elapsed time.
- **Exit**: `0` on completion; non-zero on guard failure or mid-run volume
  loss (halt, batch-committed progress retained).

### `archivist export-map [--year YYYY] [--source KEY] [--out PATH]`

Generates the Google Earth preview export (FR-010).

- **Input**: catalog rows with `gps_status='present'` (optionally filtered
  by year/source). Companion groups export one placemark (primary member).
- **Output**: a single `.kmz` under `<work_root>/TheArchivist/exports/`
  (or `--out`), containing `doc.kml` + generated thumbnails. Read-only with
  respect to archive and catalog.
- **Acceptance**: the KMZ opens in Google Earth desktop; every located item
  plots as a pin; clicking a pin shows the item's photo thumbnail with its
  capture date, source, and archive path (SC-006).
- **Report**: items exported, thumbnails generated, thumbnail failures
  (item still exported, balloon notes the missing preview), output path +
  size.
- **Guard**: runs the volume guard (reads archive files for thumbnails,
  writes to the working volume).

## Modified commands

### `archivist status`

Adds a **Location coverage** section (FR-008): counts of located / absent /
rejected / unexamined items, overall and broken down by year and by source.
Purely catalog-driven; no file reads.

### `archivist ingest`, `ingest-drops`, `pull-icloud`

Location extraction becomes part of the standard metadata pass (FR-006) —
no new flags, no separate step:

- Every filed item's catalog row includes its `gps_*` outcome.
- Byte-identical duplicate skips: if the incoming copy yields an accepted
  location and the existing row's `gps_status` is not `present`, the
  existing row's location is updated (FR-007). Locations are never
  overwritten by absent/rejected evidence.
- Run report adds `located / location_absent / location_rejected` counters
  (FR-009).

### `archivist scan-archive`

New items discovered by archive scans get location extracted in the same
pass when metadata is read; previously scanned items are left to
`scan-locations` (keeps repeat scans fast).
