# Data Model: Media Geolocation Catalog

**Feature**: 002-media-geolocation | **Date**: 2026-07-30

Extends the baseline data model ([001 data-model.md](../001-archivist-baseline/data-model.md)).
The catalog stays a derived, rebuildable index; location columns are fully
reconstructable by re-running `scan-locations`.

## Media Item — extended (`assets` table, schema v2 → v3)

New columns (additive migration, auto-run when `schema_version` < 3):

| Field | Type | Notes / validation |
|-------|------|--------------------|
| `gps_lat` | REAL | decimal degrees, −90 … 90; NULL unless `gps_status='present'` |
| `gps_lon` | REAL | decimal degrees, −180 … 180; NULL unless `gps_status='present'` |
| `gps_alt` | REAL | meters; optional — kept only with accepted lat/lon and within −500 … 20,000 |
| `gps_source` | TEXT | enum: `exif` \| `video-meta` \| `sidecar` — the evidence that supplied the accepted location |
| `gps_status` | TEXT | enum: `present` \| `absent` \| `rejected`; **NULL = not yet examined** (drives incremental backfill) |

**New index**: `idx_assets_gps_status ON assets(gps_status)`.

**Validation rules** (FR-001..FR-003):
- Accepted coordinates must be in range; (lat, lon) within ±0.0001° of
  (0, 0) is the null-island placeholder → `rejected`.
- `rejected` rows keep no coordinate values — only the status (audit trail
  for SC-005); the rejection is noted in the run report.
- `absent` is a normal state, never an error, never inferred away: no
  location is ever derived from folder names, event names, or nearby items
  (FR-002).
- Location capture never mutates the examined file (FR-011/SC-002).

**Location state transitions** (per item):

```
NULL (unexamined)
  ├─(evidence accepted)──────────> present {lat, lon, alt?, source}
  ├─(no recoverable evidence)────> absent
  └─(implausible evidence)───────> rejected
absent/rejected ──(located byte-identical duplicate seen, FR-007)──> present
present ──(never downgraded by absent/rejected evidence)──> present
any ──(scan-locations --full re-examination)──> re-resolved from scratch
```

## Asset Group — extended

One location per group, resolved in `location.py` (FR-004):

- Prefer the primary member's accepted location; else the first member with
  an accepted location (photo preferred over video on ties).
- The group location is stamped on **every** member row; `gps_source`
  records the contributing member's evidence type.
- Map export renders one placemark per group (the primary member).

## Capture Location (value object)

Not a table — the validated result passed through the pipeline:
`{lat: float, lon: float, alt: float|None, source: enum}` or the sentinel
outcomes `absent` / `rejected(reason)`. Produced by `location.py` from raw
evidence (EXIF numeric tags, ISO 6709 strings, future sidecar `geoData`).

## Location Export (KMZ product)

Generated file at `<work_root>/TheArchivist/exports/map-<YYYYMMDD-HHMMSS>.kmz`
— never written inside the archive; producing it alters neither archive nor
catalog (FR-010).

Structure:

| Component | Content |
|-----------|---------|
| `doc.kml` | KML document; Folders by capture year; one Placemark per located item/group |
| Placemark | coordinates (lon, lat[, alt]); name = capture date + primary filename |
| Balloon | embedded thumbnail, capture date, source label, archive path |
| `thumbs/<asset-id>.jpg` | ~800 px JPEG thumbnail (Pillow / `sips` for HEIC / `ffmpeg` frame for video) |

## Run Report — extended counters (FR-009)

Ingest and `scan-locations` reports add:
`{located, location_absent, location_rejected}`; existing counters
unchanged.

## Status view — location coverage (FR-008)

From the catalog only (no file reads):
- Overall: `present` / `absent` / `rejected` / unexamined counts.
- By year: derived from `capture_dt`.
- By source: `source_label`.
