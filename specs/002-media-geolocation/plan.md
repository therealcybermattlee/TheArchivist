# Implementation Plan: Media Geolocation Catalog

**Branch**: `002-media-geolocation` | **Date**: 2026-07-30 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-media-geolocation/spec.md`

## Summary

Extend the existing inventory so every media item records *where* it was
captured whenever embedded location evidence exists: backfill the
already-archived library in place (read-only), capture location on every
ingest pathway going forward, surface coverage in `status` and run reports,
and generate a Google Earth desktop export (clickable photo pins) as the
map preview. Technically this is a catalog schema extension (v2 → v3:
latitude/longitude/altitude + location source + location status), a GPS
extraction pass added to the existing `exiftool`/`ffprobe` metadata layer
(including ISO 6709 parsing for video location tags), an incremental
`scan-locations` backfill command, location-aware duplicate handling, and a
new KMZ export module with locally generated thumbnails. Nothing transmits
coordinates anywhere; all writes land in the catalog and the exports
directory on the working volume.

## Technical Context

**Language/Version**: Python 3.12+ (uv-managed; existing `src/archivist`
package)

**Primary Dependencies**: existing — `typer`, `pyyaml`, `pillow`, `tzdata`;
external executables `exiftool` (GPS EXIF + QuickTime location tags,
numeric mode), `ffprobe`/`ffmpeg` (video location tag fallback + video
frame-grab thumbnails), macOS `sips` (HEIC → JPEG thumbnails, avoids a new
Python dependency). No new Python dependencies.

**Storage**: SQLite catalog schema v2 → v3 migration (new columns:
`gps_lat`, `gps_lon`, `gps_alt`, `gps_source`, `gps_status`); KMZ exports +
thumbnails under `<work_root>/TheArchivist/exports/` (new directory);
JSONL run manifests unchanged

**Testing**: `pytest` — unit tests for coordinate parsing/validation
(EXIF rationals, ISO 6709 strings, rejection rules) and integration tests
using fixture media with GPS metadata written into tmp-dir fake volumes

**Target Platform**: macOS (archivist's workstation) — `sips` dependency is
deliberate and platform-consistent

**Project Type**: Single-project CLI (extends existing `archivist` command)

**Performance Goals**: Full location backfill of ≈5,500 files / ≈3 TB over
SMB in under 2 hours (SC-003) — achieved by batching exiftool invocations
(`-stay_open`/argfile batching) instead of one process per file; repeat
backfills in minutes via `gps_status`-driven incrementality (only rows with
no recorded location outcome are read)

**Constraints**: Archived files read in place, never modified (byte-for-byte
identical, SC-002); no coordinate ever transmitted off-machine by this
feature (FR-012); catalog remains a rebuildable derived index — location
columns must be reconstructable by re-running `scan-locations`; all existing
safety invariants (volume guards, read-only sources, plan-before-apply for
writes) apply unchanged

**Scale/Scope**: ≈5,500 existing items to backfill; coverage expected
partial (phone-era media mostly); exports up to the full located set —
thousands of pins with thumbnails in one KMZ

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` remains an unratified template, so the
baseline's governing gates (spec FR-011/FR-012 here; baseline FR-011..FR-016)
apply:

| Gate | Status |
|------|--------|
| No code path writes to a source or archived file | PASS — extraction is read-only; export/thumbnails write only to `exports/` on the working volume |
| Writes confined to archive + working volumes | PASS — catalog + exports both live on the working volume; archive untouched |
| Volume sentinel guard before any state-changing command | PASS — `scan-locations` and `export-map` run the existing guard (they write catalog/exports) |
| Catalog stays a rebuildable derived index | PASS — location columns fully reconstructable via `scan-locations` |
| No location leaves the machine | PASS — no network code anywhere in this feature |
| Dry-run/plan-before-apply for destructive actions | PASS trivially — this feature has no destructive actions (catalog updates and export generation are additive and re-runnable) |

No violations; Complexity Tracking not required.

**Post-design re-check (after Phase 1)**: PASS — design adds one extraction
module, one export module, a guarded additive schema migration, and CLI
surface; no new deletion paths, no source-touching code, no network use.

## Project Structure

### Documentation (this feature)

```text
specs/002-media-geolocation/
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
├── catalog.py      # MODIFY: schema v3 (gps_* columns), migration from v2,
│                   #   coverage queries, location-preserving upsert rules
├── metadata.py     # MODIFY: extract GPS fields in the existing
│                   #   exiftool/ffprobe pass; batched exiftool invocation
├── location.py     # NEW: coordinate parsing (EXIF numeric, ISO 6709),
│                   #   plausibility validation, group location resolution
├── scanner.py      # MODIFY: location backfill walk (gps_status-driven
│                   #   incrementality, resumable)
├── ingest.py       # MODIFY: record location on filing; retain location
│                   #   from located duplicate copies (FR-007)
├── mapexport.py    # NEW: KMZ generation — placemarks, balloon templates,
│                   #   thumbnail generation (Pillow / sips / ffmpeg)
└── cli.py          # MODIFY: new `scan-locations`, `export-map` commands;
                    #   location coverage in `status`; run-report counters

tests/
├── unit/           # location parsing, validation, rejection, group
│                   #   resolution, KML placemark rendering
└── integration/    # fixture media with GPS metadata in fake volumes:
                    #   backfill, ingest capture, duplicate retention,
                    #   export generation + archive-untouched verification
```

**Structure Decision**: Follow the baseline's one-module-per-subsystem
pattern: `location.py` mirrors `dates.py` (evidence parsing + validation +
group resolution), `mapexport.py` is a standalone product generator like
`dedupe.py` is for cleanup. All other work is surgical extension of
delivered modules — no reorganization.

## Dependencies on baseline (001-archivist-baseline)

- Requires the delivered scan/ingest pipeline and catalog (present).
- Independent of the baseline's open gaps (review workflow, test-suite
  build-out) — this feature can proceed in parallel, but shares the
  `tests/` scaffolding when both land.
- The future map viewer (feature 003, not yet specified) consumes this
  feature's catalog columns and is explicitly out of scope here.
