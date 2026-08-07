# Quickstart: Validating the Media Geolocation Catalog

**Feature**: 002-media-geolocation | **Date**: 2026-07-30

Runnable scenarios proving the feature end-to-end. Command semantics:
[contracts/cli-interface.md](contracts/cli-interface.md); schema and states:
[data-model.md](data-model.md).

## Prerequisites

- Baseline tool working (see [001 quickstart](../001-archivist-baseline/quickstart.md)):
  volumes mounted with sentinels, catalog populated by `scan-archive`.
- `exiftool`, `ffprobe`/`ffmpeg` on PATH; macOS `sips` (built in).
- Google Earth desktop installed (for Scenario 4 acceptance).

```bash
uv sync
uv run archivist status   # catalog reachable; location section shows all items "unexamined"
```

## Scenario 1 — Backfill the existing archive (SC-001/002/003, Story 1)

```bash
# Optional timing trial first:
uv run archivist scan-locations --limit 200
# Full backfill:
time uv run archivist scan-locations
uv run archivist status
```

- **Expected**: full backfill completes in under 2 hours; `status` shows
  located/absent/rejected counts by year and source with zero unexamined
  items; spot-checked phone photos with known locations carry matching
  coordinates; old scans/GoPro footage shows `absent`, not errors.
- **Archive untouched (SC-002)**: record archive file hashes/mtimes for a
  sample directory before and after — byte-identical.
- **Incremental**: re-run `scan-locations` — completes in minutes, examines
  0 items. Interrupt a `--full` run mid-way (Ctrl-C), re-run — it resumes
  without re-reading completed batches.

## Scenario 2 — Location capture on ingest (SC-004, Story 2)

Fixture folder: located phone photos (JPEG + HEIC), a located video, a
Live Photo pair where only the HEIC has GPS, unlocated media, and a file
with (0,0) placeholder coordinates.

```bash
uv run archivist ingest /path/to/fixture --source peepaw-cell          # plan
uv run archivist ingest /path/to/fixture --source peepaw-cell --apply
```

- **Expected**: run report includes located / location-absent /
  location-rejected counts; filed items carry correct coordinates with no
  extra operator step; the Live Photo pair shares one location (from the
  HEIC) on both rows; the (0,0) file is recorded `rejected` with no
  coordinates stored.

## Scenario 3 — Duplicate never erases a location (FR-007)

1. Ingest a located photo; confirm its row is `present`.
2. Force its row's location fields to `absent` (test harness only), then
   re-ingest the same byte-identical file.
- **Expected**: the skip-as-duplicate path restores `present` with the
  correct coordinates; a second re-ingest of an *unlocated* duplicate of a
  located item leaves the location untouched.

## Scenario 4 — Google Earth export (SC-006, Story 3)

```bash
uv run archivist export-map
open "/Volumes/ExternalBaseUnit/TheArchivist/exports/"   # locate the .kmz
```

- **Expected**: double-clicking the `.kmz` opens Google Earth desktop;
  every located item appears as a pin, foldered by year in the sidebar;
  clicking a pin opens a balloon showing the photo thumbnail (HEIC and
  video items show generated JPEG thumbnails), capture date, source, and
  archive path. Filters work: `--year 2024` exports only that year.
- **Read-only**: catalog row counts and archive bytes identical before and
  after export.

## Scenario 5 — Guard rails still hold

With the archive volume unmounted (or sentinel removed):

```bash
uv run archivist scan-locations   # must refuse, name the failed check
uv run archivist export-map       # must refuse
```

- **Expected**: both refuse and touch nothing, consistent with the
  baseline's SC-007.

## Automated test suite

```bash
uv run pytest tests/unit/test_location.py tests/integration/ -k location
```

- **Expected**: unit tests (ISO 6709 parsing, range/null-island/altitude
  rejection, group resolution, placemark rendering) and integration tests
  (backfill incrementality, ingest capture, duplicate retention, valid KMZ
  with all thumbnails referenced, archive-unchanged assertions) all pass.
