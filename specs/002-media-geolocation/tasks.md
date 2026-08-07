# Tasks: Media Geolocation Catalog

**Input**: Design documents from `/specs/002-media-geolocation/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-interface.md, quickstart.md

**Tests**: Included — the plan explicitly designs the test harness (research.md D9) and the success criteria (SC-001..SC-006) are verified by it.

**Organization**: Tasks are grouped by user story so each story is an independently testable increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: [US1] backfill, [US2] ingest capture, [US3] coverage & export

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Test scaffolding and GPS fixture media every story's tests depend on

- [X] T001 Create pytest scaffolding: `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py`, and `tests/conftest.py` with fixtures for fake volumes (tmp-dir archive + working roots carrying `.archivist-volume-id` sentinels) and a `config.yaml` factory pointing at them
- [X] T002 [P] Create GPS fixture media builder in `tests/fixtures/build_fixtures.py`: uses `exiftool` to stamp real GPS tags onto tiny generated JPEGs (located, unlocated, null-island (0,0), out-of-range), a located HEIC+MOV Live-Photo-style pair (GPS on the still only), and a tiny located MP4 (ISO 6709 `com.apple.quicktime.location.ISO6709` tag via ffmpeg); expose as conftest fixtures

**Checkpoint**: `uv run pytest` collects (0 tests) with fixtures importable

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Location parsing/validation, schema v3, and GPS-aware metadata extraction — every story consumes these

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T003 Create `src/archivist/location.py`: `CaptureLocation` value object (`lat`, `lon`, `alt`, `source`) plus outcome type (`present`/`absent`/`rejected(reason)`); parse EXIF numeric GPS fields and ISO 6709 strings (`+42.3601-071.0589+021.000/` forms); plausibility validation per data-model.md (|lat|>90, |lon|>180, null island ±0.0001°, altitude kept only within −500…20,000 m); `resolve_group_location(members)` implementing best-located-member (primary first, photo over video on ties)
- [X] T004 Extend `src/archivist/catalog.py` to schema v3: add `gps_lat`, `gps_lon`, `gps_alt`, `gps_source`, `gps_status` columns + `idx_assets_gps_status` index; bump `SCHEMA_VERSION` to 3 with automatic additive migration when stored version < 3; add helpers `rows_missing_location()` (gps_status IS NULL), `set_location(conn, id, outcome)`, and location-preserving upsert rule (never downgrade `present`)
- [X] T005 Extend `src/archivist/metadata.py`: request GPS tags in the existing `exiftool -n` pass (GPSLatitude/GPSLongitude/GPSAltitude, Keys/QuickTime location tags) and return raw location evidence alongside existing fields; add `ffprobe` `location` tag fallback for videos; add `extract_batch(paths)` running exiftool once per argfile batch (several hundred paths, JSON output) for the backfill path
- [X] T006 [P] Unit tests in `tests/unit/test_location.py`: ISO 6709 parsing variants (lat/lon, with altitude, trailing solidus), EXIF numeric conversion, all rejection rules (range, null island, altitude bounds), group resolution (primary wins, photo-over-video tie, all-absent → absent)
- [X] T007 [P] Unit test in `tests/unit/test_catalog_migration.py`: v2 database with existing rows migrates to v3 in place (rows intact, new columns NULL, version stamped, migration idempotent); `set_location` never downgrades `present`

**Checkpoint**: Foundation ready — user story phases can proceed (in parallel if desired)

---

## Phase 3: User Story 1 - Backfill locations for the existing archive (Priority: P1) 🎯 MVP

**Goal**: `archivist scan-locations` populates locations for already-archived media by reading files in place — incremental, resumable, archive bytes untouched

**Independent Test**: quickstart.md Scenario 1 — backfill a fixture archive; located items gain coordinates, unlocated marked `absent`, re-run examines 0 items, interrupted run resumes, archive bytes identical

- [X] T008 [US1] Add location backfill engine in `src/archivist/scanner.py`: `backfill_locations(catalog, cfg, *, full, limit, progress)` — select target rows (`gps_status IS NULL`, or all when `full`), batch paths through `metadata.extract_batch`, resolve outcomes via `location.py` (including group stamping by `asset_group_id`), commit per batch for resumability, return report counts `{examined, located, location_absent, location_rejected}`
- [X] T009 [US1] Add `scan-locations` command in `src/archivist/cli.py` per contracts/cli-interface.md: `--full`, `--limit N`, volume guard before running, progress line, final report with elapsed time, non-zero exit on guard failure or mid-run volume loss
- [X] T010 [P] [US1] Integration test in `tests/integration/test_backfill_locations.py`: seed fake archive + v3 catalog from fixture media; assert located fixtures → `present` with correct coordinates (±0.0002°), unlocated → `absent`, null-island → `rejected` with no coordinates stored; re-run examines 0 rows; batch-interrupt simulation resumes without re-reading completed rows; SHA-256 of every archive file identical before/after (SC-002)
- [X] T011 [P] [US1] Guard-rail integration test in `tests/integration/test_location_guards.py`: with the archive sentinel removed, `scan-locations` refuses, names the failed check, exits non-zero, and writes nothing to the catalog

**Checkpoint**: Backfill delivers the location database on its own — MVP complete

---

## Phase 4: User Story 2 - Capture location during every new ingest (Priority: P2)

**Goal**: Every ingest pathway records location automatically; companion groups share one location; duplicates never erase a known location; run reports count location outcomes

**Independent Test**: quickstart.md Scenarios 2–3 — ingest the GPS fixture folder; filed rows carry correct `gps_*` values with no extra step; Live-Photo pair shares the still's location; duplicate re-ingest restores/never-downgrades location; report shows located/absent/rejected counts

- [X] T012 [US2] Extend `src/archivist/ingest.py`: resolve each item's location outcome from the existing per-file metadata extraction, stamp group location across `asset_group_id` members (via `location.resolve_group_location`), include `gps_*` fields in the catalog record, and add `located` / `location_absent` / `location_rejected` to the ingest result counters
- [X] T013 [US2] Implement duplicate location retention (FR-007) in `src/archivist/ingest.py`: on skip-as-duplicate, if the incoming copy yields an accepted location and the matched catalog row's `gps_status` ≠ `present`, update that row via `catalog.set_location`; never overwrite `present` with absent/rejected evidence
- [X] T014 [US2] Surface the new counters in `src/archivist/cli.py` run-report output for `ingest`, `ingest-drops`, and `pull-icloud` (per contracts/cli-interface.md Modified commands)
- [X] T015 [P] [US2] Integration test in `tests/integration/test_ingest_locations.py`: ingest fixture folder with `--apply`; assert per-fixture `gps_status`/coordinates, pair shares the still's location on both rows with correct `gps_source`, (0,0) fixture → `rejected`, report counters match; duplicate-retention cases: absent-row + located duplicate → `present`; located row + unlocated duplicate → unchanged

**Checkpoint**: New media never enters the archive without a location verdict

---

## Phase 5: User Story 3 - See and share location coverage (Priority: P3)

**Goal**: `status` shows location coverage (overall / by year / by source); `export-map` produces a KMZ that opens in Google Earth desktop with clickable photo pins

**Independent Test**: quickstart.md Scenario 4 — after backfill, `status` counts match fixtures; `export-map` KMZ is a valid zip whose KML plots every located item with balloon thumbnails; manual: open in Google Earth desktop, click a pin, see the photo

- [X] T016 [P] [US3] Add coverage queries to `src/archivist/catalog.py`: `location_coverage()` returning present/absent/rejected/unexamined counts overall, by capture year (from `capture_dt`), and by `source_label`
- [X] T017 [P] [US3] Create `src/archivist/mapexport.py`: thumbnail generation (Pillow for JPEG/PNG, `sips` subprocess for HEIC/RAW, `ffmpeg` single-frame grab for video; ~800 px JPEG, graceful per-item failure), KML document builder (Folders by year, Placemark per located item/group — primary member only — with balloon showing embedded thumbnail + capture date + source + archive path), and KMZ zip packaging to `<work_root>/TheArchivist/exports/map-<timestamp>.kmz`
- [X] T018 [US3] Add `export-map` command in `src/archivist/cli.py` per contracts/cli-interface.md: `--year`, `--source`, `--out` filters, volume guard, report (items exported, thumbnails generated/failed, output path + size)
- [X] T019 [US3] Add **Location coverage** section to the `status` command in `src/archivist/cli.py` using `catalog.location_coverage()` (no file reads)
- [X] T020 [P] [US3] Unit test in `tests/unit/test_mapexport.py`: placemark/balloon rendering (coordinate order lon,lat; XML escaping of paths/names), year-folder grouping, group → single placemark
- [X] T021 [P] [US3] Integration test in `tests/integration/test_export_map.py`: after fixture backfill, `export-map` produces a KMZ that unzips to well-formed KML (parse it), placemark count == located count (groups collapsed), every thumbnail referenced by the KML exists inside the KMZ zip, `--year` filter narrows output, catalog and archive untouched (row counts + file hashes identical); `status` coverage numbers match fixture expectations

**Checkpoint**: All three stories independently functional

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T022 [P] Update `README.md` and `config.example.yaml` notes: new commands (`scan-locations`, `export-map`), exports directory, location coverage in `status`, privacy posture (nothing transmitted; future viewer may use online maps)
- [ ] T023 (suite ✅ 49 passed 2026-07-30; real-volume quickstart runs pending operator) Run the full suite (`uv run pytest`) plus quickstart.md Scenarios 1–5 against real volumes; record backfill wall-clock vs. the 2-hour SC-003 budget in `specs/002-media-geolocation/quickstart.md` results notes
- [ ] T024 (pending operator: needs Google Earth desktop + real archive) Manual acceptance (SC-006): open the real-archive KMZ in Google Earth desktop, verify year folders, pin click → photo balloon; note any oversized-KMZ sluggishness as input for the future viewer spec (003)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none — start immediately
- **Foundational (Phase 2)**: needs Phase 1 (tests use fixtures); T003 → T004/T005 order-free (different files), T006/T007 after their targets
- **US1 (Phase 3)**: needs Phase 2 complete (location.py + catalog v3 + batched metadata)
- **US2 (Phase 4)**: needs Phase 2 complete; independent of US1
- **US3 (Phase 5)**: needs Phase 2 complete; its integration test (T021) is easiest after US1 exists to populate data, but `export-map`/`status` code is independent
- **Polish (Phase 6)**: after all desired stories

### Story Dependency Notes

- US1, US2, US3 share only Phase 2 modules — they touch disjoint code paths (`scanner.py` vs `ingest.py` vs `mapexport.py`/`status`) and can proceed in parallel, except both US2 (T014) and US3 (T018, T019) edit `cli.py` — serialize those three tasks or expect merge friction.

### Parallel Opportunities

```text
Phase 1: T001 ∥ T002
Phase 2: T003 first → then T004 ∥ T005 → T006 ∥ T007
Phase 3: T008 → T009 → T010 ∥ T011
Phase 4: T012 → T013 → T014 → T015
Phase 5: T016 ∥ T017 → T018 → T019 → T020 ∥ T021
```

---

## Implementation Strategy

**MVP first (US1 only)**: Phases 1–3 deliver the thing the user actually asked for — a database of where the media was taken, populated from the existing archive. Stop, run quickstart Scenario 1 against the real archive, and check the SC-003 timing.

**Incremental delivery**: add US2 (ingest capture) so coverage never decays, then US3 (status + Google Earth export) for the visible payoff. Each checkpoint is independently shippable; nothing in later phases reworks earlier ones.

**Solo-operator note**: this is a one-developer project — the parallel markers mainly indicate "no ordering constraint," useful for batching related edits in one sitting.
