# PLAN.md — The Archivist

## Overview

The Archivist is a personal media archival tool for the Lee Family library. Its purpose is to safely ingest photos and videos from cloud providers, physical storage devices, and miscellaneous drop folders into a structured, TrueNAS-backed local archive.

The system operates under an aggressively defensive safety model:

* **Dry-run by default:** Every mutating command requires an explicit `--apply` flag.
* **Copy, never move:** Source media is never mutated or deleted automatically.
* **Hash-verified writes:** Every file copy is verified via byte-level hashing at the destination before catalog entry.
* **Idempotent processing:** Re-running an ingest over the same input results in a harmless no-op.
* **Deterministic grouping:** Sidecars, RAW files, and Live Photos travel and live together permanently.

### The Data-Flow Invariant (non-negotiable)

> **Source data is read-only, always.** Cloud (iCloud/Google) and physical-device originals are never moved, modified, or deleted by The Archivist. All media flows in one direction:
>
> ```
> [Source: iCloud / Google Takeout / Device / Drop]
>        └─(copy only)─> /Volumes/ExternalBaseUnit  (gather · stage · resolve · hash · DECIDE)
>                               └─(copy + verify)─> /Volumes/VideoStorage  (archive — ONLY write target)
>                                                          └─(user-owned NFS replication)─> secondary TrueNAS
> ```
>
> The archive copy is byte-verified before the catalog records it as done. The only deletion the tool ever performs is on its **own working-directory scratch** (and only when asked). `dedupe` cleanup suggestions target the **archive**, never a source. No code path may write to a source location. **Replication of `/Volumes/VideoStorage` to the secondary TrueNAS is handled entirely by the user via NFS and is out of scope for this tool** (see §8).

---

## 1. Archive Structure (The Target Layout)

The archive enforces a strict three-level deep layout:

```
<ARCHIVE_ROOT>/
  2023/
    07152023 - Beach Trip/          # "MMDDYYYY - Event Description"
      GoPro3/
      Insta Go3/
      Matt Personal Cell/
  2024/
    08122024 - Unsorted/            # Default fallback for new ingests
      Matt Personal Cell/
```

### Layout Rules:

* **Level 1 (Year):** `YYYY` derived strictly from the resolved media capture date.
* **Level 2 (Event):** `MMDDYYYY - Event Name`. The tool writes to `MMDDYYYY - Unsorted` by default. Curation (renaming `Unsorted` to a human description or merging folders) is strictly a manual downstream task.
* **Level 3 (Device/Source):** The clean, configured human name of the source device.
* **No quarantine track.** Every file is placed by its best-available date (see §4C). Low-confidence dates are not sidelined into a review folder; they are placed normally and **flagged in the catalog**, then surfaced via `archivist status` for optional later correction. (`mtime`/`ctime` always yields a usable fallback date, so nothing is ever stranded.)

---

## 2. Infrastructure & Storage Model

To keep high-churn I/O off the network and protect against connection drops, processing is divided between local scratch space and the network share.

### Storage Layout

* **Archive Storage (`/Volumes/VideoStorage`):** primary TrueNAS share and the tool's **only** write target. Already holds the existing `YYYY/...` library. The user replicates this to a secondary TrueNAS via NFS independently of the tool.
* **Working Storage (`/Volumes/ExternalBaseUnit`):** high-speed local external drive (the **mount**; sentinel/guard live at its root). All tool files live under a configurable subfolder — `work_subdir`, default `TheArchivist/` — so the tool never litters the drive root:
  * `TheArchivist/staging/` (transient cloud download dumps)
  * `TheArchivist/drops/` (inboxes for manual device dumps)
  * `TheArchivist/logs/` (run manifests and execution history)
  * `TheArchivist/catalog/` (the SQLite state database)

Cloud/device pulls land in `staging/` first, are date-resolved and hash-verified locally, and are then **copied** to `archive_root`. This keeps high-churn pull/scratch I/O off the NAS until files are finalized.

### Mount Protection Guard

Before *any* command execution, the tool verifies that both volumes are present, writable, and contain a unique sentinel file:

* `/Volumes/VideoStorage/.archivist-volume-id`
* `/Volumes/ExternalBaseUnit/.archivist-volume-id`

If either validation fails, the CLI aborts instantly. The sentinel check (not just a path-exists check) is what defends against the common SMB failure mode where an unmounted share leaves behind an empty but writable local mount-point directory — writing there would silently dump data onto the boot disk.

---

## 3. Configuration & Sources

Managed via `config.yaml`. Every ingest pathway must map explicitly to a target Level-3 device folder.

```yaml
archive_root: "/Volumes/VideoStorage"   # primary TrueNAS share; ONLY write target. User replicates to 2nd NAS via NFS (out of scope)
work_root: "/Volumes/ExternalBaseUnit"
default_timezone: "America/Detroit"   # US Eastern; used to normalize UTC timestamps to local calendar day

sources:
  matt-personal:
    type: icloud
    device_folder: "Matt Personal Cell"
  matt-public:
    type: takeout
    device_folder: "Matt Public Cell"
  gopro3:
    type: device
    device_folder: "GoPro3"
  insta-go3:
    type: device
    device_folder: "Insta Go3"
  peepaw-cell:
    type: drop
    device_folder: "Peepaw Cell"
  peepaw-old-pics:
    type: drop
    device_folder: "Peepaw Old Pictures"
  kat-cell:
    type: drop
    device_folder: "Kat Cell"
  john-cell:
    type: drop
    device_folder: "John Cell"
  andrew-cell:
    type: drop
    device_folder: "Andrew Cell"
  misc:
    type: drop
    device_folder: "Misc"
```

### Source Types

* **`icloud`** — automated pull via `icloudpd` (v1.32.x, actively maintained: sync/move modes, Live Photos, RAW, headless session auth).
* **`takeout`** — ingest of an unzipped **Google Takeout** export. *Why Takeout and not a live API:* Google removed the `photoslibrary.readonly` scope on **2025-03-31**. The Library API now only returns media an app itself uploaded, and the replacement **Picker API** requires manual per-item selection — neither supports bulk archival. Tools relying on the old scope (`gphotos-sync`, `rclone` Google Photos) are broken for full-library sync. Takeout is the only reliable bulk path; **do not attempt to re-add live Google API sync — it cannot work.**
* **`device`** — mount an SD card / camera storage and point the tool at it.
* **`drop`** — a `drops/<source>/` inbox bound to a device-folder name. Copy/AirDrop/USB-dump files in, run `archivist ingest-drops`. `Misc` is the catch-all when a file's source can't be attributed. (Risk: files dropped into the wrong source folder get the wrong device label; `Misc` is the safety valve.)

---

## 4. Architectural Core Components

### A. Catalog Database (SQLite)

Tracks the state of the physical archive. One row per individual file.

* **Identity & state:** `id`, `content_hash` (exact bytes), `source_label`, `original_path`, `archive_path`, `asset_group_id`, `ingested_at`, `run_manifest_id`.
* **Date:** `capture_dt` (ISO string, normalized to `default_timezone`), `date_source` (exif|sidecar|filename|mtime), `confidence` (high|medium|low).
* **Comparison metadata (captured at ingest for similarity, not just exact match):** `phash` (perceptual hash), `width`, `height`, `file_size`, `duration` (video), `camera_make`, `camera_model`, `mime_type`. These let `dedupe` find the *same shot in different bytes* — e.g. an iCloud HEIC vs. a downscaled Google-Takeout JPEG — and choose the highest-quality copy to keep. They are cheap to record during the `exiftool` pass and cannot be backfilled without re-reading every file, so v1 captures them even though perceptual *matching* is enabled later.
* **Principle:** the catalog is a **derived index, not the source of truth.** Files + JSON run manifests (§5) are authoritative; the entire DB is rebuildable via `scan-archive`.
* **Exclusions:** the scanner and ingestion logic completely ignore OS-specific noise files (`.DS_Store`, `Thumbs.db`, Apple resource forks `._*`).

### B. Asset Grouping Engine

Files are grouped by base filename and proximity *before* processing to protect multi-file pairs from being separated.

* **Pairs bound:** Live Photos (`.HEIC` + `.MOV`), RAW+JPEG pairs (`.CR3`/`.DNG`/etc. + `.JPG`), and edit sidecars (`.JPG` + `.AAE` / `.XMP`).
* **Rule:** A group receives a single unified date-resolution decision and is placed in the exact same target directory.
* **Primary asset:** the still image (HEIC/JPEG; for RAW+JPEG, the JPEG) is the group's primary. Its date and its collision-hash suffix govern the whole group.

### C. Date Resolver & Confidence Policy

Evaluates metadata in a rigid priority sequence, outputting a timestamp and a confidence tier:

1. **HIGH:** EXIF `DateTimeOriginal` (photos) / QuickTime `CreationDate` or `CreateDate` (videos) via `exiftool`/`ffprobe`.
2. **HIGH:** Google Takeout sidecar JSON (`photoTakenTime.timestamp`). **Must normalize the UTC epoch to `default_timezone` before deriving the target folder date** (a late-night Eastern capture is the previous day in UTC).
3. **MEDIUM:** Filename parsing regex (`YYYYMMDD_*`, `IMG_YYYYMMDD_*`, GoPro/Insta standard date tokens).
4. **LOW:** Filesystem `mtime` / `ctime`.

#### Routing (all confidence tiers):

* Every file is placed into `<YEAR>/<MMDDYYYY> - Unsorted/<Device_Folder>/` based on its resolved date.
* `confidence` is recorded in the catalog. **LOW**-confidence items (and `Peepaw Old Pictures` scans, which will be predominantly LOW) are placed normally and listed in the `archivist status` review queue so you can correct dates/locations later. No file is quarantined.
* Sanity bounds: reject resolved dates earlier than 1990 or in the future, and fall back to the next tier (or `Misc`/current-date with a flag) rather than creating absurd year folders.

### D. Ingest Pipeline

```
[Source Path] ──> [Filter OS Noise] ──> [Group Assets] ──> [Resolve Dates]
                                                                 │
[Record Catalog] <── [Verify Hash] <── [Copy to NAS] <── [Hash Content & Dedup]
```

### E. Filename Collision Policy

The tool will never overwrite an existing file. If `IMG_1234.JPG` already exists in the target directory but has a *different* content hash, the new file is renamed with a short hash suffix: `IMG_1234__a1b2c3d4.JPG`. (If the existing file has the *same* hash, it's a duplicate → skip and log.)

* **Group constraint:** If an asset group collides, every component receives the *same* suffix, generated from the **primary asset's** hash, so the pair (`IMG_1234.HEIC` + `IMG_1234.MOV`) stays locked together.

---

## 5. Execution Journaling (Run Manifests)

Every execution generates a standalone log file: `logs/manifest-YYYYMMDD-HHMMSS.json`. This is a transaction ledger independent of the SQLite database — a per-action record of `{source, original_path, resolved_date, confidence, hash, planned_path, action, result}`. If the network drops mid-run or the database is lost/corrupted, the raw JSON manifests allow full reconstruction of catalog state.

---

## 6. Target CLI Framework

Built with Python + **`typer`** (native subcommands, typed options, clean `--apply`/dry-run switches).

```bash
# Read-only: index the existing archive to build the baseline tracking DB
# (no --apply; it never mutates the archive)
archivist scan-archive

# Ingest and sort an arbitrary directory of old or unorganized files
archivist ingest <path> --source <source-name> [--apply]

# Process files placed into local drop inboxes
archivist ingest-drops [--apply]

# Pull from iCloud down to staging, then pipe into the ingest pipeline
archivist pull icloud --source matt-personal [--apply]

# Process an unzipped Google Takeout hierarchy using its JSON sidecars
archivist pull google-takeout <path> --source matt-public [--apply]

# Identify duplicates and issue actionable, safe cleanup options
archivist dedupe [--apply]

# Print catalog statistics, volume status, and the low-confidence review queue
archivist status
```

> **Performance note (`scan-archive`):** the existing archive is large (terabytes of video over SMB). Indexing uses a `size + mtime + partial-hash` fast-path for identity and only computes a full content hash when the fast-path signals a possible collision, to avoid reading the entire archive over the network on every run.

---

## 7. Phased Implementation Strategy

```
Phase 0: Scaffold
  - CLI setup (typer), YAML config, Volume/Sentinel Guard, SQLite catalog schema
  - MILESTONE: `archivist status` runs, guards both mounts, reports an empty catalog

Phase 1: Engine Baseline & Scan  ◀── first "test with real data" milestone
  - exiftool/ffprobe metadata extraction (incl. phash + comparison columns)
  - Date resolver + confidence tiers; content hashing; dry-run reporting
  - scan-archive (read-only index of the existing library)
  - MILESTONE: dry-run `ingest <sample> --source <name>` prints a correct, verifiable
    placement plan against REAL sample data on the working drive (no archive writes)

Phase 2: Asset Grouping & Drops Ingest
  - Pair HEIC+MOV / RAW+JPEG / sidecars; collision policy; ingest --apply + ingest-drops
  - MILESTONE: real sample copied + hash-verified into archive; re-run is a clean no-op

Phase 3: External Integration (iCloud & Takeout)
  - Wrap icloudpd; parse Takeout JSON with UTC→America/Detroit normalization

Phase 4: Deduplication Maintenance
  - Exact-hash dedup (v1) + cross-source mapping + safe, archive-only cleanup suggestions
  - Perceptual matching turned on using phash captured since Phase 1 (no re-scan needed)
```

---

## 8. Explicit Non-Goals (V1)

* Automatic deletion of source media.
* Algorithmic event classification or semantic folder naming (e.g., guessing "Beach Trip").
* Facial/object recognition or GPS-to-location mapping.
* Bi-directional sync (writing back to iCloud/Google).
* Replication/backup of the archive to the secondary TrueNAS — handled by the user via NFS, outside the tool.
* Live Google Photos API sync (impossible since 2025-03-31 — see §3).
* Perceptual/near-duplicate *matching logic* in the first cut (v1 dedup acts on exact-content-hash). **Note:** the `phash` and comparison columns ARE captured from Phase 1 so this can be switched on later with no re-scan.

---

## 9. Open Items / Deferred

* **Date-range auto-match into existing named events** (drop a file straight into `07152023 - Beach Trip` if its date falls inside that event's span) — deferred; date-based, not semantic, so compatible with the non-goals, but not needed for v1.
* **RAW+JPEG primary-asset edge cases** (RAW-only with no JPEG sibling) — define concrete rules during Phase 2.
* **Timezone of historical media** captured outside Eastern — `default_timezone` is a global default; per-source overrides could be added later if needed.
