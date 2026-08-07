# Research: Media Geolocation Catalog

**Feature**: 002-media-geolocation | **Date**: 2026-07-30

No `NEEDS CLARIFICATION` markers remain in the Technical Context. Decisions
below resolve the technical unknowns for location extraction, storage,
backfill performance, and the Google Earth export.

## D1. Location evidence sources & extraction

- **Decision**: Extract via the existing metadata layer: `exiftool -n`
  (numeric mode) for photo GPS tags (`GPSLatitude`, `GPSLongitude`,
  `GPSAltitude` with hemisphere refs resolved) and for video location tags
  (`Keys:GPSCoordinates` / `com.apple.quicktime.location.ISO6709`, plus
  vendor GPS atoms exiftool already normalizes); `ffprobe` `location` tag
  as a video fallback. Google Takeout sidecar `geoData` is recognized as an
  evidence source for the future takeout pathway (parser lives in
  `location.py`; wiring waits for that pathway). Evidence source recorded
  per item: `exif` | `video-meta` | `sidecar`.
- **Rationale**: exiftool already runs against every file in the pipeline —
  adding GPS tags to the same pass costs no extra file reads. `-n` avoids
  fragile DMS-string parsing; ISO 6709 strings (`+42.3601-071.0589+021.0/`)
  still need a small parser for QuickTime tags surfaced raw.
- **Alternatives considered**: Pillow EXIF GPS parsing (no video support,
  weaker RAW coverage); a dedicated GPS library (unnecessary dependency for
  two tag families).

## D2. Catalog schema — v3 additive migration

- **Decision**: Bump `SCHEMA_VERSION` to 3; `ALTER TABLE assets ADD COLUMN`
  for `gps_lat REAL`, `gps_lon REAL`, `gps_alt REAL`, `gps_source TEXT`,
  `gps_status TEXT` (`present` | `absent` | `rejected`; NULL = not yet
  examined). Migration runs automatically on first connect when
  `schema_version` < 3; purely additive, no row rewrites. Index on
  `gps_status` for backfill/coverage queries.
- **Rationale**: NULL-vs-`absent` distinction is what makes backfill
  incremental and resumable: NULL means "never examined", `absent` means
  "examined, no location" — repeat runs only touch NULLs. Additive ALTERs
  keep the migration trivially safe and the catalog rebuildable.
- **Alternatives considered**: separate `locations` table keyed by asset id
  (join cost and upsert complexity for five scalar fields — not warranted);
  full catalog rebuild instead of migration (forces a multi-hour re-scan for
  no benefit).

## D3. Plausibility validation

- **Decision**: Reject and record `gps_status='rejected'` when: |lat| > 90,
  |lon| > 180, or (lat, lon) within ±0.0001° of (0, 0) — the null-island
  placeholder. Altitude is kept only when lat/lon are accepted; absurd
  altitudes (< −500 m or > 20,000 m) are dropped while keeping the valid
  lat/lon.
- **Rationale**: Mirrors the baseline's implausible-date rule (FR-003 here,
  FR-007 there): bad evidence is recorded as rejected, never silently kept,
  and never poisons a future map with pins in the Gulf of Guinea.
- **Alternatives considered**: treating (0,0) as valid (it is a real ocean
  coordinate, but as camera output it is overwhelmingly a placeholder);
  dropping rejected items entirely (loses the audit trail SC-005 needs).

## D4. Group location resolution — best-located member

- **Decision**: In `location.py`, resolve one location per asset group:
  prefer the group's primary member's accepted location; otherwise the first
  member with an accepted location (photo over video when tied). The group
  location is stamped on every member's row, with `gps_source` reflecting
  the contributing member's evidence.
- **Rationale**: Matches the spec's "best-located member" rule (FR-004) and
  the established "best-dated member governs the group" pattern — a Live
  Photo pair must be one pin, not two.
- **Alternatives considered**: averaging member coordinates (false
  precision, meaningless for HEIC+MOV pairs seconds apart); leaving members
  independent (violates FR-004).

## D5. Backfill performance — batched exiftool

- **Decision**: `scan-locations` collects catalog rows with
  `gps_status IS NULL`, then runs exiftool in batches (argfile of several
  hundred paths per invocation, JSON output) rather than one process per
  file; results are committed per batch so interruption loses at most one
  batch. ffprobe fallback runs only for videos whose exiftool output has no
  location tags.
- **Rationale**: Per-file exiftool process spawn (~150 ms) × 5,500 files is
  ~15 minutes of pure overhead before any I/O; batching reads tags at
  network speed and comfortably meets the 2-hour SC-003 budget. Per-batch
  commits give resumability (acceptance scenario: interrupted runs resume
  without re-reading completed items).
- **Alternatives considered**: `exiftool -stay_open` daemon protocol
  (fastest, but more protocol code for marginal gain at 5,500 files);
  extending `scan-archive --full` instead of a dedicated command (forces
  users to re-run date/identity work just to get locations).

## D6. Ingest capture & duplicate location retention

- **Decision**: `metadata.py` returns GPS fields with the rest of the
  extraction, so every ingest pathway records location at filing time with
  no new pipeline stage (FR-006). Duplicate handling (FR-007): when an
  incoming item is skipped as byte-identical to a cataloged item whose
  `gps_status` is not `present`, and the incoming copy yields an accepted
  location, the existing row's location fields are updated — locations are
  only ever added or confirmed by duplicates, never overwritten by
  absent/rejected evidence.
- **Rationale**: Byte-identical copies necessarily carry identical embedded
  metadata *in the file*, but sidecar-derived evidence (future takeout) can
  differ — the retain-if-any-copy-knows rule costs nothing and closes the
  spec's dedup-never-erases-location requirement.
- **Alternatives considered**: ignoring skipped duplicates entirely
  (violates FR-007 once sidecar evidence exists).

## D7. Export format — KMZ with embedded thumbnails

- **Decision**: `export-map` writes a single `.kmz` (zip of `doc.kml` +
  `thumbs/…jpg`) to `<work_root>/TheArchivist/exports/`. Each located item
  is a KML Placemark at its coordinates; the balloon (pop-up) shows the
  embedded thumbnail, capture date, source, and archive path. Thumbnails
  (~800 px JPEG): Pillow for JPEG/PNG, macOS `sips` for HEIC/RAW, `ffmpeg`
  single-frame grab for videos. Items are grouped into KML Folders by year
  for navigable sidebar browsing. Companion groups export one placemark
  (the group's primary).
- **Rationale**: KMZ is Google Earth desktop's native bundle — one
  double-clickable file, thumbnails travel inside it (no fragile absolute
  file paths), balloons make pins clickable-to-photo per SC-006. HEIC and
  video can't render in balloons, which is exactly why thumbnails are
  generated; `sips`/`ffmpeg` avoid adding `pillow-heif`.
- **Alternatives considered**: KML with absolute local file paths (breaks
  if the archive volume isn't mounted; HEIC still won't render); GeoJSON
  (better for the future web viewer, but Google Earth balloon/photo support
  is what the acceptance criterion names — the viewer can read the catalog
  directly); embedding full-resolution photos (multi-GB KMZ, sluggish).

## D8. Coverage reporting

- **Decision**: `status` gains a location section: counts of
  `present` / `absent` / `rejected` / unexamined (NULL), overall plus
  breakdowns by year (from `capture_dt`) and by `source_label`. Ingest and
  scan-locations run reports gain `located` / `location_absent` /
  `location_rejected` counters.
- **Rationale**: Directly satisfies FR-008/FR-009 and gives the archivist
  the "is the database filling?" signal Story 3 asks for.
- **Alternatives considered**: separate `location-status` command (needless
  surface; `status` is already the health view).

## D9. Testing approach

- **Decision**: Unit: ISO 6709 parsing, rejection rules (range, null
  island, altitude bounds), group resolution, placemark/balloon rendering.
  Integration (fake tmp volumes with sentinels): fixture JPEGs with real
  GPS EXIF (written once by exiftool into committed fixtures), backfill
  populates v3 columns and is incremental on re-run; ingest captures
  location end-to-end; duplicate retention; KMZ opens as valid zip+KML and
  references every thumbnail; archive-bytes-unchanged assertion around
  backfill (SC-002).
- **Rationale**: Same harness pattern as the baseline plan (D12 there);
  fixture files with genuine embedded GPS keep tests honest without
  network or real volumes.
- **Alternatives considered**: mocking exiftool output (faster but stops
  testing the real tag surface — keep one mocked unit layer *and* real
  fixtures in integration).
